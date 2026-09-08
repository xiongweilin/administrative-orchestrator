from datetime import UTC, datetime

import pytest

from administrative_orchestrator.domain import (
    AdministrativeRequest,
    Decision,
    DecisionDisposition,
    PolicyRef,
)
from administrative_orchestrator.persistence import ConcurrencyConflict, SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)


def _policy_ref() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v0.1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _facts() -> OnboardingFacts:
    return OnboardingFacts(
        employee_ref="employee:new",
        department_ref="department:engineering",
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
    )


def test_case_policy_decision_and_audit_survive_store_roundtrip() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()

    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
    )
    case = create_case(request, case_kind="employee-onboarding", subject_ref="employee:new")
    store.create_case(request, case)

    ready = start_policy_evaluation(case)
    evaluation = OnboardingPolicy(_policy_ref()).evaluate(_facts())
    awaiting = apply_policy_evaluation(ready, evaluation)
    store.update_case(
        awaiting,
        expected_previous_version=case.version,
        event_type="case.policy_applied",
    )
    store.append_policy_evaluation(awaiting.case_id, awaiting.version, evaluation)

    restored = store.get_case(awaiting.case_id)
    assert restored == awaiting
    assert store.get_latest_policy_evaluation(awaiting.case_id) == evaluation

    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=_policy_ref(),
    )
    authorized = record_decision(awaiting, decision)
    store.append_decision(decision)
    store.update_case(
        authorized,
        expected_previous_version=awaiting.version,
        event_type="case.decision_applied",
        payload={"decision_id": str(decision.decision_id)},
    )

    assert store.get_decision(decision.decision_id) == decision
    assert store.get_case(authorized.case_id) == authorized

    events = store.list_audit_events(authorized.case_id)
    assert [event["event_type"] for event in events] == [
        "case.created",
        "case.policy_applied",
        "policy.evaluated",
        "decision.recorded",
        "case.decision_applied",
    ]


def test_optimistic_version_conflict_fails_closed() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
    )
    case = create_case(request, case_kind="employee-onboarding", subject_ref="employee:new")
    store.create_case(request, case)

    ready = start_policy_evaluation(case)
    store.update_case(
        ready,
        expected_previous_version=case.version,
        event_type="case.ready_for_policy",
    )

    with pytest.raises(ConcurrencyConflict):
        store.update_case(
            ready,
            expected_previous_version=case.version,
            event_type="case.stale_write",
        )
