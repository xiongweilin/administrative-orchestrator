from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from .completion import CompletionAssessment, assess_onboarding_completion
from .config import get_settings
from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    ConfirmedOutcome,
    Decision,
    DecisionDisposition,
    EffectRealizationAssessment,
    EffectRecord,
    ExecutionAuthorization,
    FactSnapshot,
    PolicyRef,
)
from .execution_repository import ExecutionRepository
from .fact_history import list_fact_snapshots
from .fact_transitions import replace_facts_for_reevaluation
from .ingress import DuplicateIngressEvent, get_ingress_receipt
from .inspection import list_authorizations, list_decisions, list_realizations
from .messaging import FailedOutboxEvent, list_failed_outbox
from .persistence import ConcurrencyConflict, SqlStore
from .policy import OnboardingFacts, OnboardingPolicy, PolicyEvaluation
from .service import (
    TransitionError,
    apply_policy_evaluation,
    create_case,
    explicit_reopen,
    record_decision,
    start_policy_evaluation,
)
from .unit_of_work import AdministrativeUnitOfWork

app = FastAPI(title="Administrative Orchestrator", version="0.2.0")

_settings = get_settings()
_store = SqlStore(_settings.database_url)
if _settings.auto_create_schema:
    _store.init_schema()
_uow = AdministrativeUnitOfWork(_store)
_execution = ExecutionRepository(_store)

_ONBOARDING_POLICY_REF = PolicyRef(
    policy_id="employee-onboarding",
    version="v0.1",
    owner="administrative-orchestrator",
    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
)
_ONBOARDING_POLICY = OnboardingPolicy(_ONBOARDING_POLICY_REF)


class CreateOnboardingCase(BaseModel):
    requester_principal_id: str
    employee_ref: str
    department_ref: str | None = None
    manager_principal_id: str | None = None
    start_date: str | None = None
    employment_type: str | None = None
    requested_systems: tuple[str, ...] = ()
    requires_privileged_access: bool = False
    channel: str = "api"
    source_event_id: str | None = Field(default=None, min_length=1, max_length=512)


class ReplaceOnboardingFacts(BaseModel):
    employee_ref: str
    department_ref: str | None = None
    manager_principal_id: str | None = None
    start_date: str | None = None
    employment_type: str | None = None
    requested_systems: tuple[str, ...] = ()
    requires_privileged_access: bool = False
    source: str = "operator"


class OnboardingCaseResponse(BaseModel):
    case: AdministrativeCase
    policy_evaluation: PolicyEvaluation


class RecordDecisionBody(BaseModel):
    principal_id: str
    disposition: DecisionDisposition
    rationale: str = Field(min_length=1)


class DecisionResponse(BaseModel):
    decision: Decision
    case: AdministrativeCase


def _existing_onboarding_response(source_event_id: str) -> OnboardingCaseResponse | None:
    receipt = get_ingress_receipt(_store, source_event_id)
    if receipt is None:
        return None
    case = _store.get_case(receipt.case_id)
    if case is None:
        raise HTTPException(status_code=500, detail="ingress receipt points to missing case")
    evaluation = _store.get_latest_policy_evaluation(case.case_id)
    if evaluation is None:
        raise HTTPException(
            status_code=409,
            detail="source event already created a case that has not completed policy evaluation",
        )
    return OnboardingCaseResponse(case=case, policy_evaluation=evaluation)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {
        "status": "ready",
        "storage": "sql-m1",
        "schema": "auto-create" if _settings.auto_create_schema else "managed-migration",
        "external_effects": "enabled" if _settings.external_effects_enabled else "disabled",
    }


@app.post("/v1/onboarding", response_model=OnboardingCaseResponse)
def create_onboarding(payload: CreateOnboardingCase) -> OnboardingCaseResponse:
    if payload.source_event_id is not None:
        existing = _existing_onboarding_response(payload.source_event_id)
        if existing is not None:
            return existing

    request = AdministrativeRequest(
        requester_principal_id=payload.requester_principal_id,
        channel=payload.channel,
        intent=f"onboard {payload.employee_ref}",
        source_ref=payload.source_event_id,
    )
    facts = OnboardingFacts(
        employee_ref=payload.employee_ref,
        department_ref=payload.department_ref,
        manager_principal_id=payload.manager_principal_id,
        start_date=payload.start_date,
        employment_type=payload.employment_type,
        requested_systems=payload.requested_systems,
        requires_privileged_access=payload.requires_privileged_access,
    )
    fact_snapshot = FactSnapshot(
        source=f"ingress:{payload.channel}",
        owner="administrative-orchestrator",
        facts=facts.model_dump(mode="json"),
    )
    original = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref=payload.employee_ref,
        fact_snapshot=fact_snapshot,
    )
    try:
        _uow.create_case(request, original, source_event_id=payload.source_event_id)
    except DuplicateIngressEvent as exc:
        existing = _existing_onboarding_response(exc.receipt.source_event_id)
        if existing is not None:
            return existing
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        if payload.source_event_id is not None:
            existing = _existing_onboarding_response(payload.source_event_id)
            if existing is not None:
                return existing
        raise HTTPException(status_code=409, detail="duplicate ingress event") from exc

    ready = start_policy_evaluation(original)
    evaluation = _ONBOARDING_POLICY.evaluate(facts)
    case = apply_policy_evaluation(ready, evaluation)
    try:
        _uow.apply_policy_transition(original, case, evaluation)
    except (ConcurrencyConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OnboardingCaseResponse(case=case, policy_evaluation=evaluation)


@app.get("/v1/cases/{case_id}", response_model=AdministrativeCase)
def get_case(case_id: UUID) -> AdministrativeCase:
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return case


@app.get("/v1/cases/{case_id}/policy", response_model=PolicyEvaluation)
def get_policy_evaluation(case_id: UUID) -> PolicyEvaluation:
    evaluation = _store.get_latest_policy_evaluation(case_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="policy evaluation not found")
    return evaluation


@app.get("/v1/cases/{case_id}/facts", response_model=list[FactSnapshot])
def get_case_fact_history(case_id: UUID) -> list[FactSnapshot]:
    if _store.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")
    return list_fact_snapshots(_store, case_id)


@app.post("/v1/cases/{case_id}/facts", response_model=OnboardingCaseResponse)
def replace_onboarding_facts(
    case_id: UUID,
    payload: ReplaceOnboardingFacts,
) -> OnboardingCaseResponse:
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if case.case_kind != "employee-onboarding":
        raise HTTPException(status_code=409, detail="facts endpoint supports onboarding cases only")
    if payload.employee_ref != case.subject_ref:
        raise HTTPException(status_code=409, detail="employee_ref cannot change case subject")

    facts = OnboardingFacts(
        employee_ref=payload.employee_ref,
        department_ref=payload.department_ref,
        manager_principal_id=payload.manager_principal_id,
        start_date=payload.start_date,
        employment_type=payload.employment_type,
        requested_systems=payload.requested_systems,
        requires_privileged_access=payload.requires_privileged_access,
    )
    snapshot = FactSnapshot(
        source=payload.source,
        owner="administrative-orchestrator",
        facts=facts.model_dump(mode="json"),
    )
    changed = replace_facts_for_reevaluation(case, snapshot)
    ready = start_policy_evaluation(changed)
    evaluation = _ONBOARDING_POLICY.evaluate(facts)
    updated = apply_policy_evaluation(ready, evaluation)
    try:
        _uow.replace_facts_and_apply_policy(case, updated, evaluation)
    except (TransitionError, ConcurrencyConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OnboardingCaseResponse(case=updated, policy_evaluation=evaluation)


@app.get("/v1/cases/{case_id}/decisions", response_model=list[Decision])
def get_case_decisions(case_id: UUID) -> list[Decision]:
    if _store.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")
    return list_decisions(_store, case_id)


@app.get(
    "/v1/cases/{case_id}/authorizations",
    response_model=list[ExecutionAuthorization],
)
def get_case_authorizations(case_id: UUID) -> list[ExecutionAuthorization]:
    if _store.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")
    return list_authorizations(_store, case_id)


@app.get("/v1/cases/{case_id}/effects", response_model=list[EffectRecord])
def get_case_effects(case_id: UUID) -> list[EffectRecord]:
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _execution.list_effects(case_id, case.authority_epoch)


@app.get(
    "/v1/cases/{case_id}/realizations",
    response_model=list[EffectRealizationAssessment],
)
def get_case_realizations(case_id: UUID) -> list[EffectRealizationAssessment]:
    if _store.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")
    return list_realizations(_store, case_id)


@app.get("/v1/cases/{case_id}/outcomes", response_model=list[ConfirmedOutcome])
def get_case_outcomes(case_id: UUID) -> list[ConfirmedOutcome]:
    if _store.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _execution.list_outcomes(case_id)


@app.get("/v1/cases/{case_id}/completion", response_model=CompletionAssessment)
def get_case_completion(case_id: UUID) -> CompletionAssessment:
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    effects = _execution.list_effects(case.case_id, case.authority_epoch)
    outcomes = _execution.list_outcomes(case.case_id, case.authority_epoch)
    return assess_onboarding_completion(effects, outcomes)


@app.get("/v1/cases/{case_id}/audit")
def get_case_audit(case_id: UUID) -> list[dict[str, Any]]:
    if _store.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _store.list_audit_events(case_id)


@app.get("/v1/outbox/dead-letter", response_model=list[FailedOutboxEvent])
def get_dead_letter_outbox(limit: int = Query(default=100, ge=1, le=1000)) -> list[FailedOutboxEvent]:
    return list_failed_outbox(_store, limit=limit)


@app.post("/v1/cases/{case_id}/decisions", response_model=DecisionResponse)
def submit_decision(case_id: UUID, payload: RecordDecisionBody) -> DecisionResponse:
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if case.policy_ref is None:
        raise HTTPException(status_code=409, detail="case has no current policy")

    decision = Decision(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        principal_id=payload.principal_id,
        disposition=payload.disposition,
        rationale=payload.rationale,
        policy_ref=case.policy_ref,
    )
    try:
        updated = record_decision(case, decision)
        _uow.apply_decision_transition(case, updated, decision)
    except (TransitionError, ConcurrencyConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return DecisionResponse(decision=decision, case=updated)


@app.post("/v1/cases/{case_id}/reopen", response_model=AdministrativeCase)
def reopen_case(case_id: UUID) -> AdministrativeCase:
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    try:
        updated = explicit_reopen(case)
        _store.update_case(
            updated,
            expected_previous_version=case.version,
            event_type="case.reopened",
        )
    except (TransitionError, ConcurrencyConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return updated
