from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    Decision,
    DecisionDisposition,
    PolicyRef,
)
from .policy import OnboardingFacts, OnboardingPolicy, PolicyEvaluation
from .service import (
    TransitionError,
    apply_policy_evaluation,
    create_case,
    explicit_reopen,
    record_decision,
    start_policy_evaluation,
)

app = FastAPI(title="Administrative Orchestrator", version="0.1.0")

_cases: dict[UUID, AdministrativeCase] = {}
_evaluations: dict[UUID, PolicyEvaluation] = {}
_decisions: dict[UUID, Decision] = {}

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
    return {"status": "ready", "storage": "in-memory-m0", "external_effects": "disabled"}


@app.post("/v1/onboarding", response_model=OnboardingCaseResponse)
def create_onboarding(payload: CreateOnboardingCase) -> OnboardingCaseResponse:
    request = AdministrativeRequest(
        requester_principal_id=payload.requester_principal_id,
        channel=payload.channel,
        intent=f"onboard {payload.employee_ref}",
    )
    case = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref=payload.employee_ref,
    )
    case = start_policy_evaluation(case)
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
    case = apply_policy_evaluation(case, evaluation)
    _cases[case.case_id] = case
    _evaluations[case.case_id] = evaluation
    return OnboardingCaseResponse(case=case, policy_evaluation=evaluation)


@app.get("/v1/cases/{case_id}", response_model=AdministrativeCase)
def get_case(case_id: UUID) -> AdministrativeCase:
    case = _cases.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return case


@app.get("/v1/cases/{case_id}/policy", response_model=PolicyEvaluation)
def get_policy_evaluation(case_id: UUID) -> PolicyEvaluation:
    evaluation = _evaluations.get(case_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="policy evaluation not found")
    return evaluation


@app.post("/v1/cases/{case_id}/decisions", response_model=DecisionResponse)
def submit_decision(case_id: UUID, payload: RecordDecisionBody) -> DecisionResponse:
    case = _cases.get(case_id)
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
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _decisions[decision.decision_id] = decision
    _cases[case_id] = updated
    return DecisionResponse(decision=decision, case=updated)


@app.post("/v1/cases/{case_id}/reopen", response_model=AdministrativeCase)
def reopen_case(case_id: UUID) -> AdministrativeCase:
    case = _cases.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    try:
        updated = explicit_reopen(case)
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _cases[case_id] = updated
    return updated
