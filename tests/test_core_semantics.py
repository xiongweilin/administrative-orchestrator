from datetime import UTC, datetime

import pytest

from administrative_orchestrator.domain import (
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    Decision,
    DecisionDisposition,
    EffectReversibility,
    EvidenceRef,
    PolicyRef,
    ReopenReason,
)
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy, PolicyDisposition
from administrative_orchestrator.service import (
    TransitionError,
    add_evidence,
    apply_policy_evaluation,
    create_case,
    explicit_reopen,
    mint_execution_authorization,
    plan_effect,
    record_decision,
    require_reopen,
    start_policy_evaluation,
)


@pytest.fixture
def policy_ref() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v0.1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _request() -> AdministrativeRequest:
    return AdministrativeRequest(
        requester_principal_id="employee:requester",
        channel="test",
        intent="onboard employee:new",
    )


def _complete_facts() -> OnboardingFacts:
    return OnboardingFacts(
        employee_ref="employee:new",
        department_ref="department:engineering",
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
        requested_systems=("github", "feishu"),
    )


def _awaiting_decision_case(policy_ref: PolicyRef):
    case = create_case(_request(), case_kind="employee-onboarding", subject_ref="employee:new")
    case = start_policy_evaluation(case)
    evaluation = OnboardingPolicy(policy_ref).evaluate(_complete_facts())
    return apply_policy_evaluation(case, evaluation)


def test_missing_facts_do_not_force_reopen(policy_ref: PolicyRef) -> None:
    case = create_case(_request(), case_kind="employee-onboarding", subject_ref="employee:new")
    case = start_policy_evaluation(case)
    evaluation = OnboardingPolicy(policy_ref).evaluate(
        OnboardingFacts(employee_ref="employee:new")
    )

    assert evaluation.disposition == PolicyDisposition.NEED_MORE_FACTS
    updated = apply_policy_evaluation(case, evaluation)
    assert updated.status == CaseStatus.GATHERING_FACTS
    assert updated.reopen_reason is None


def test_complete_onboarding_requires_explicit_decision(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    assert case.status == CaseStatus.AWAITING_DECISION
    assert case.policy_ref == policy_ref


def test_approve_then_mint_exact_authorization(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = Decision(
        case_id=case.case_id,
        case_version=case.version,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="current onboarding policy requirements satisfied",
        policy_ref=policy_ref,
    )
    case = record_decision(case, decision)

    authorization = mint_execution_authorization(
        case,
        decision,
        issuer_principal_id="service:admin-orchestrator",
        target_system="hris",
        allowed_operations=("employee.create",),
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    effect = plan_effect(
        case,
        authorization,
        operation="employee.create",
        reversibility=EffectReversibility.CORRECTABLE,
    )

    assert case.status == CaseStatus.AUTHORIZED
    assert authorization.subject_ref == case.subject_ref
    assert effect.authorization_id == authorization.authorization_id


def test_effect_cannot_exceed_authorization(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = Decision(
        case_id=case.case_id,
        case_version=case.version,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=policy_ref,
    )
    case = record_decision(case, decision)
    authorization = mint_execution_authorization(
        case,
        decision,
        issuer_principal_id="service:admin-orchestrator",
        target_system="hris",
        allowed_operations=("employee.create",),
        authority_class=AuthorityClass.EMPLOYMENT,
    )

    with pytest.raises(TransitionError, match="outside the authorization scope"):
        plan_effect(
            case,
            authorization,
            operation="employee.terminate",
            reversibility=EffectReversibility.IRREVERSIBLE,
        )


def test_current_case_change_invalidates_old_decision_for_new_authority(
    policy_ref: PolicyRef,
) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = Decision(
        case_id=case.case_id,
        case_version=case.version,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=policy_ref,
    )
    case = record_decision(case, decision)
    case = add_evidence(
        case,
        EvidenceRef(
            source="hris",
            owner="hris",
            observed_at=datetime.now(UTC),
            version="employee-v2",
        ),
    )

    with pytest.raises(TransitionError, match="stale"):
        mint_execution_authorization(
            case,
            decision,
            issuer_principal_id="service:admin-orchestrator",
            target_system="hris",
            allowed_operations=("employee.create",),
            authority_class=AuthorityClass.EMPLOYMENT,
        )


def test_reopen_is_explicit(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    case = require_reopen(case, ReopenReason.UNKNOWN_RISK_DIMENSION)
    assert case.status == CaseStatus.REOPEN_REQUIRED

    reopened = explicit_reopen(case)
    assert reopened.status == CaseStatus.GATHERING_FACTS
    assert reopened.reopen_reason is None
