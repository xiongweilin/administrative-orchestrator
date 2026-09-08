from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    Decision,
    DecisionDisposition,
    PolicyRef,
)
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

app = FastAPI(title="Administrative Orchestrator", version="0.1.0")

_settings = get_settings()
_store = SqlStore(_settings.database_url)
_store.init_schema()
_uow = AdministrativeUnitOfWork(_store)

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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {
        "status": "ready",
        "storage": "sql-m1",
        "external_effects": "enabled" if _settings.external_effects_enabled else "disabled",
    }


@app.post("/v1/onboarding", response_model=OnboardingCaseResponse)
def create_onboarding(payload: CreateOnboardingCase) -> OnboardingCaseResponse:
    request = AdministrativeRequest(
        requester_principal_id=payload.requester_principal_id,
        channel=payload.channel,
        intent=f"onboard {payload.employee_ref}",
    )
    original = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref=payload.employee_ref,
    )
    _store.create_case(request, original)

    ready = start_policy_evaluation(original)
    evaluation = _ONBOARDING_POLICY.evaluate(
        OnboardingFacts(
            employee_ref=payload.employee_ref,
            department_ref=payload.department_ref,
            manager_principal_id=payload.manager_principal_id,
            start_date=payload.start_date,
            employment_type=payload.employment_type,
            requested_systems=payload.requested_systems,
            requires_privileged_access=payload.requires_privileged_access,
        )
    )
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


@app.get("/v1/cases/{case_id}/audit")
def get_case_audit(case_id: UUID) -> list[dict[str, Any]]:
    if _store.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _store.list_audit_events(case_id)


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
