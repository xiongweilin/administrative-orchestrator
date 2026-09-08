from uuid import uuid4

from administrative_orchestrator.messaging import OutboxEvent
from administrative_orchestrator.workflows.definitions import CASE_CHANGED_TOPIC
from administrative_orchestrator.workflows.relay import plan_outbox_action


def test_case_changed_maps_to_deterministic_start_and_wake() -> None:
    event_id = uuid4()
    case_id = uuid4()
    event = OutboxEvent(
        event_id=event_id,
        event_type="workflow.case_changed",
        aggregate_id=str(case_id),
        payload={
            "case_id": str(case_id),
            "case_version": 4,
            "authority_epoch": 2,
            "status": "authorized",
            "cause": "decision_recorded",
        },
        attempts=0,
    )

    action = plan_outbox_action(event)

    assert action.workflow_id == str(case_id)
    assert action.topic == CASE_CHANGED_TOPIC
    assert action.idempotency_key == str(event_id)
    assert action.message["event_id"] == str(event_id)
    assert action.message["authority_epoch"] == 2


def test_unknown_outbox_event_fails_closed() -> None:
    event = OutboxEvent(
        event_id=uuid4(),
        event_type="unknown.event",
        aggregate_id="x",
        payload={},
        attempts=0,
    )

    try:
        plan_outbox_action(event)
    except ValueError as exc:
        assert "no DBOS relay action" in str(exc)
    else:
        raise AssertionError("unknown outbox event must fail closed")
