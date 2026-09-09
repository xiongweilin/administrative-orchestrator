from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .access_policy import AccessDenied, AdministrativeAccessPolicy, AdministrativePermission
from .auth import AuthenticatedPrincipal, Authenticator
from .authority import AuthorityError, AuthorityRepository, IdentityBinding
from .authority_lifecycle import AuthorityLifecycleEvent, AuthorityLifecycleRepository
from .config import get_settings
from .domain import AdministrativeCase, CaseStatus, utcnow
from .execution_repository import ExecutionRepository
from .fact_acquisition import (
    FactAcquisitionError,
    build_hris_source,
    merge_authoritative_onboarding_facts,
)
from .fact_transitions import replace_facts_for_reevaluation
from .governance import GovernanceRepository
from .obligations import ObligationRepository
from .persistence import CaseRow, ConcurrencyConflict, SqlStore
from .policy import OnboardingFacts
from .policy_plane import PolicyPlaneError, PolicyRepository, compile_onboarding_policy
from .service import TransitionError, apply_policy_evaluation, start_policy_evaluation
from .unit_of_work import AdministrativeUnitOfWork

app = FastAPI(title="Administrative Operations API", version="0.3.0")

_settings = get_settings()
_store = SqlStore(_settings.database_url)
_authority = AuthorityRepository(_store)
_access = AdministrativeAccessPolicy(_authority)
_authenticator = Authenticator(_store, _settings)
_lifecycle = AuthorityLifecycleRepository(_store)
_execution = ExecutionRepository(_store)
_governance = GovernanceRepository(_store)
_obligations = ObligationRepository(_store)
_policies = PolicyRepository(_store)
_uow = AdministrativeUnitOfWork(_store)
if _settings.auto_create_schema:
    _store.init_schema()


class QueueItem(BaseModel):
    case_id: UUID
    case_kind: str
    status: CaseStatus
    subject_ref: str
    requester_principal_id: str
    version: int
    authority_epoch: int
    updated_at: datetime


class RefreshFactsResponse(BaseModel):
    case: AdministrativeCase
    source: str
    source_ref: str
    source_version: str
    source_digest: str


class BindIdentityBody(BaseModel):
    provider: str = Field(min_length=1, max_length=255)
    external_subject: str = Field(min_length=1, max_length=512)
    principal_id: str = Field(min_length=1, max_length=255)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _actor(request: Request) -> AuthenticatedPrincipal:
    return _authenticator.authenticate(request)


def _require(
    actor: AuthenticatedPrincipal,
    permission: AdministrativePermission,
    *,
    case: AdministrativeCase | None = None,
) -> None:
    try:
        _access.require(
            actor.principal_id,
            permission,
            case=case,
            organization_scope="*" if case is None else None,
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {
        "status": "ready",
        "auth_mode": _settings.auth_mode,
        "runtime_profile": _settings.runtime_profile,
        "hris_source": _settings.hris_source_kind,
        "iam_source": _settings.iam_source_kind,
        "authority_mutation_shortcuts": "forbidden",
    }


@app.get("/v1/operations/cases", response_model=list[QueueItem])
def case_queue(
    request: Request,
    status_filter: list[CaseStatus] | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[QueueItem]:
    actor = _actor(request)
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    with _store.sessions() as db:
        statement = select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(limit)
        if status_filter:
            statement = statement.where(CaseRow.status.in_([item.value for item in status_filter]))
        rows = db.execute(statement).scalars().all()
    return [
        QueueItem(
            case_id=row.case_id,
            case_kind=row.case_kind,
            status=CaseStatus(row.status),
            subject_ref=row.subject_ref,
            requester_principal_id=row.requester_principal_id,
            version=row.version,
            authority_epoch=row.authority_epoch,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@app.get("/v1/operations/cases/{case_id}")
def case_detail(case_id: UUID, request: Request) -> dict:
    actor = _actor(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    audit = None
    if _access.allows(actor.principal_id, AdministrativePermission.AUDIT_READ, case=case):
        audit = _store.list_audit_events(case.case_id)
    return {
        "case": case.model_dump(mode="json"),
        "policy": (
            evaluation.model_dump(mode="json")
            if (evaluation := _store.get_latest_policy_evaluation(case.case_id)) is not None
            else None
        ),
        "governance": (
            basis.model_dump(mode="json")
            if (basis := _governance.get_current_for_case(case.case_id, case.authority_epoch))
            is not None
            else None
        ),
        "obligations": (
            obligations.model_dump(mode="json")
            if (obligations := _obligations.get_current(case.case_id, case.authority_epoch))
            is not None
            else None
        ),
        "effects": [
            item.model_dump(mode="json")
            for item in _execution.list_effects(case.case_id, case.authority_epoch)
        ],
        "outcomes": [
            item.model_dump(mode="json")
            for item in _execution.list_outcomes(case.case_id, case.authority_epoch)
        ],
        "audit": audit,
    }


@app.post(
    "/v1/operations/cases/{case_id}/authoritative-facts/refresh",
    response_model=RefreshFactsResponse,
)
def refresh_authoritative_facts(case_id: UUID, request: Request) -> RefreshFactsResponse:
    actor = _actor(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _require(actor, AdministrativePermission.FACTS_REFRESH_AUTHORITATIVE, case=case)
    if case.case_kind != "employee-onboarding":
        raise HTTPException(status_code=409, detail="authoritative refresh currently supports onboarding")
    source = build_hris_source(_settings)
    if source is None:
        raise HTTPException(status_code=503, detail="authoritative HRIS source is not configured")
    try:
        record = source.read_employee(case.subject_ref)
        if not record.is_fresh_at(
            utcnow(),
            max_age_seconds=_settings.authoritative_fact_max_age_seconds,
        ):
            raise FactAcquisitionError("authoritative HRIS observation is stale")
        snapshot = merge_authoritative_onboarding_facts(case, record)
        changed = replace_facts_for_reevaluation(case, snapshot)
        ready = start_policy_evaluation(changed)
        policy_record = _policies.resolve_current("employee-onboarding")
        policy = compile_onboarding_policy(policy_record)
        facts = OnboardingFacts.model_validate(snapshot.facts)
        evaluation = policy.evaluate(facts)
        updated = apply_policy_evaluation(ready, evaluation)
        _uow.replace_facts_and_apply_policy(case, updated, evaluation)
    except (
        FactAcquisitionError,
        PolicyPlaneError,
        TransitionError,
        ConcurrencyConflict,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RefreshFactsResponse(
        case=updated,
        source=record.source,
        source_ref=record.source_ref,
        source_version=record.source_version,
        source_digest=record.digest,
    )


@app.post("/v1/operations/identities/bind", response_model=AuthorityLifecycleEvent)
def bind_identity(payload: BindIdentityBody, request: Request) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    valid_from = payload.valid_from or utcnow()
    try:
        binding = IdentityBinding(
            provider=payload.provider.rstrip("/"),
            external_subject=payload.external_subject,
            principal_id=payload.principal_id,
            valid_from=valid_from,
            valid_until=payload.valid_until,
        )
        return _lifecycle.bind_identity(
            binding,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
        )
    except (AuthorityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/operations/identities/{binding_id}/revoke",
    response_model=AuthorityLifecycleEvent,
)
def revoke_identity(
    binding_id: UUID,
    payload: ReasonBody,
    request: Request,
) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    try:
        return _lifecycle.expire_identity_binding(
            binding_id,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
        )
    except AuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/operations/principals/{principal_id}/deactivate",
    response_model=AuthorityLifecycleEvent,
)
def deactivate_principal(
    principal_id: str,
    payload: ReasonBody,
    request: Request,
) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    try:
        return _lifecycle.deactivate_principal(
            principal_id,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
        )
    except AuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/operations/authority-events", response_model=list[AuthorityLifecycleEvent])
def authority_events(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[AuthorityLifecycleEvent]:
    actor = _actor(request)
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    return _lifecycle.list_events(limit=limit)
