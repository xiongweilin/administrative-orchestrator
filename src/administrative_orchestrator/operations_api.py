from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .access_policy import AccessDenied, AdministrativeAccessPolicy, AdministrativePermission
from .admission import (
    AdmissionConflict,
    AdmissionRejected,
    IntakeAssessmentService,
    IntakePromotionService,
)
from .auth import AuthenticatedPrincipal, Authenticator
from .authority import AuthorityError, AuthorityRepository, IdentityBinding
from .authority_lifecycle import AuthorityLifecycleEvent, AuthorityLifecycleRepository
from .candidate_admission import CandidateAdministrativeAdmissionService
from .config import get_settings
from .conversation import ConversationMessageRow, ConversationRow
from .domain import AdministrativeCase, AdministrativeRequest, CaseStatus, utcnow
from .execution_repository import ExecutionRepository
from .fact_acquisition import (
    FactAcquisitionError,
    build_hris_source,
    merge_authoritative_offboarding_facts,
    merge_authoritative_onboarding_facts,
)
from .fact_transitions import replace_facts_for_reevaluation
from .governance import GovernanceRepository
from .intake.models import (
    CandidateAdministrativeRequest,
    CandidateStatus,
    IntakeAssessment,
    IntakeDisposition,
    PromotionRecord,
)
from .intake.repository import AssessmentConflict, IntakeRepository
from .obligations import ObligationRepository
from .offboarding_admission import CandidateOffboardingAdmissionService
from .onboarding_admission import (
    CandidateOnboardingAdmissionService,
    OnboardingAdmissionError,
)
from .persistence import CaseRow, ConcurrencyConflict, SqlStore
from .policy import OffboardingFacts, OnboardingFacts, PolicyEvaluation
from .policy_plane import (
    PolicyPlaneError,
    PolicyRepository,
    compile_offboarding_policy,
    compile_onboarding_policy,
)
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
_intake = IntakeRepository(_store)
_intake_assessments = IntakeAssessmentService(_intake)
_intake_promotions = IntakePromotionService(_store, _intake)
_CONVERSATION_SCHEMA = (ConversationRow, ConversationMessageRow)
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


class IntakeQueueItem(BaseModel):
    candidate_id: UUID
    conversation_ref: str
    candidate_requester: str
    candidate_intent: str
    status: CandidateStatus
    created_at: datetime
    latest_assessment: IntakeAssessment | None = None


class IntakeCandidateDetail(BaseModel):
    candidate: CandidateAdministrativeRequest
    assessments: list[IntakeAssessment]
    promotion: PromotionRecord | None = None


class IntakeAssessmentBody(BaseModel):
    disposition: IntakeDisposition
    basis: dict[str, Any] = Field(default_factory=dict)


class IntakePromotionBody(BaseModel):
    assessment_id: UUID
    source_system: str = Field(min_length=1, max_length=128)
    tenant_ref: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    requester_principal_id: str = Field(min_length=1, max_length=255)
    channel: str = Field(default="intake", min_length=1, max_length=64)
    case_kind: str = Field(default="intake", min_length=1, max_length=128)
    subject_ref: str | None = Field(default=None, max_length=512)
    bridge_to_m5: bool = False
    promotion_policy_ref: str = Field(
        default="m6-human-confirmed-v1", min_length=1, max_length=512
    )


class IntakePromotionResponse(BaseModel):
    promotion: PromotionRecord
    request: AdministrativeRequest
    case: AdministrativeCase
    created: bool
    policy_evaluation: PolicyEvaluation | None = None


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


def _require_intake_review(actor: AuthenticatedPrincipal) -> None:
    _require(actor, AdministrativePermission.INTAKE_REVIEW)


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
    status_filter: Annotated[list[CaseStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
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


@app.get("/v1/operations/intake/candidates", response_model=list[IntakeQueueItem])
def intake_candidate_queue(
    request: Request,
    status_filter: Annotated[CandidateStatus | None, Query(alias="status")] = CandidateStatus.ACTIVE,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[IntakeQueueItem]:
    actor = _actor(request)
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    candidates = _intake.list_candidates(status=status_filter, limit=limit)
    result: list[IntakeQueueItem] = []
    for candidate in candidates:
        assessments = _intake.list_assessments(candidate.candidate_id)
        result.append(
            IntakeQueueItem(
                candidate_id=candidate.candidate_id,
                conversation_ref=candidate.conversation_ref,
                candidate_requester=candidate.candidate_requester,
                candidate_intent=candidate.candidate_intent,
                status=candidate.status,
                created_at=candidate.created_at,
                latest_assessment=assessments[-1] if assessments else None,
            )
        )
    return result


@app.get(
    "/v1/operations/intake/candidates/{candidate_id}",
    response_model=IntakeCandidateDetail,
)
def intake_candidate_detail(candidate_id: UUID, request: Request) -> IntakeCandidateDetail:
    actor = _actor(request)
    candidate = _intake.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="intake candidate not found")
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    return IntakeCandidateDetail(
        candidate=candidate,
        assessments=_intake.list_assessments(candidate_id),
        promotion=_intake.get_promotion(candidate_id),
    )


@app.post(
    "/v1/operations/intake/candidates/{candidate_id}/assessments",
    response_model=IntakeAssessment,
)
def finalize_intake_assessment(
    candidate_id: UUID,
    payload: IntakeAssessmentBody,
    request: Request,
) -> IntakeAssessment:
    actor = _actor(request)
    _require_intake_review(actor)
    if _intake.get_candidate(candidate_id) is None:
        raise HTTPException(status_code=404, detail="intake candidate not found")
    try:
        return _intake_assessments.finalize_human(
            candidate_id,
            payload.disposition,
            reviewer_principal_id=actor.principal_id,
            basis=payload.basis,
        )
    except (AdmissionRejected, AssessmentConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _admission_bridge(case_kind: str) -> CandidateAdministrativeAdmissionService:
    """Select the typed candidate admission service for one case kind."""
    if case_kind == "employee-onboarding":
        return CandidateOnboardingAdmissionService(
            _store, _intake, _intake_promotions, policies=_policies, uow=_uow
        )
    if case_kind == "employee-offboarding":
        return CandidateOffboardingAdmissionService(
            _store, _intake, _intake_promotions, policies=_policies, uow=_uow
        )
    raise OnboardingAdmissionError(
        f"bridge_to_m5 does not support case_kind={case_kind!r}"
    )


@app.post(
    "/v1/operations/intake/candidates/{candidate_id}/promote",
    response_model=IntakePromotionResponse,
)
def promote_intake_candidate(
    candidate_id: UUID,
    payload: IntakePromotionBody,
    request: Request,
) -> IntakePromotionResponse:
    actor = _actor(request)
    _require_intake_review(actor)
    candidate = _intake.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="intake candidate not found")
    assessment = _intake.get_assessment(payload.assessment_id)
    if assessment is None or assessment.candidate_ref != candidate_id:
        raise HTTPException(status_code=404, detail="intake assessment not found")
    try:
        if payload.bridge_to_m5:
            if payload.subject_ref is None:
                raise OnboardingAdmissionError(
                    "bridge_to_m5 promotion requires subject_ref"
                )
            admission = _admission_bridge(payload.case_kind).promote_and_evaluate(
                candidate,
                assessment,
                source_system=payload.source_system,
                tenant_ref=payload.tenant_ref,
                source_event_id=payload.source_event_id,
                requester_principal_id=payload.requester_principal_id,
                subject_ref=payload.subject_ref,
                channel=payload.channel,
                promotion_policy_ref=payload.promotion_policy_ref,
            )
            result = admission.promotion
            promoted_case = admission.case
            policy_evaluation = admission.policy_evaluation
        else:
            result = _intake_promotions.promote(
                candidate,
                assessment,
                source_system=payload.source_system,
                tenant_ref=payload.tenant_ref,
                source_event_id=payload.source_event_id,
                requester_principal_id=payload.requester_principal_id,
                channel=payload.channel,
                case_kind=payload.case_kind,
                subject_ref=payload.subject_ref,
                promotion_policy_ref=payload.promotion_policy_ref,
            )
            promoted_case = result.case
            policy_evaluation = None
    except (AdmissionConflict, AdmissionRejected, OnboardingAdmissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IntakePromotionResponse(
        promotion=result.promotion,
        request=result.request,
        case=promoted_case,
        created=result.created,
        policy_evaluation=policy_evaluation,
    )


def _apply_authoritative_refresh(
    case: AdministrativeCase,
    record: object,
) -> AdministrativeCase:
    """Merge authoritative HR facts and re-evaluate the case-kind policy."""
    if case.case_kind == "employee-onboarding":
        snapshot = merge_authoritative_onboarding_facts(case, record)  # type: ignore[arg-type]
        policy_id = "employee-onboarding"
        facts_model = OnboardingFacts
        compile_policy = compile_onboarding_policy
    elif case.case_kind == "employee-offboarding":
        snapshot = merge_authoritative_offboarding_facts(case, record)  # type: ignore[arg-type]
        policy_id = "employee-offboarding"
        facts_model = OffboardingFacts
        compile_policy = compile_offboarding_policy
    else:
        raise FactAcquisitionError(
            f"authoritative refresh does not support case kind {case.case_kind!r}"
        )
    changed = replace_facts_for_reevaluation(case, snapshot)
    ready = start_policy_evaluation(changed)
    policy_record = _policies.resolve_current(policy_id)
    facts = facts_model.model_validate(snapshot.facts)
    evaluation = compile_policy(policy_record).evaluate(facts)
    updated = apply_policy_evaluation(ready, evaluation)
    _uow.replace_facts_and_apply_policy(case, updated, evaluation)
    return updated


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
    if case.case_kind not in {"employee-onboarding", "employee-offboarding"}:
        raise HTTPException(
            status_code=409, detail="authoritative refresh does not support this case kind"
        )
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
        updated = _apply_authoritative_refresh(case, record)
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
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[AuthorityLifecycleEvent]:
    actor = _actor(request)
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    return _lifecycle.list_events(limit=limit)
