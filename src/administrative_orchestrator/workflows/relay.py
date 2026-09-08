from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..messaging import OutboxEvent
from .protocol import CASE_CHANGED_TOPIC


@dataclass(frozen=True)
class WorkflowWakeAction:
    workflow_id: str
    topic: str
    message: dict[str, Any]
    idempotency_key: str


def plan_outbox_action(event: OutboxEvent) -> WorkflowWakeAction:
    """Map a business outbox event to one deterministic DBOS start+wake action."""
    if event.event_type != "workflow.case_changed":
        raise ValueError(f"no DBOS relay action for event type {event.event_type!r}")
    case_id = str(event.payload.get("case_id") or event.aggregate_id)
    if not case_id:
        raise ValueError("workflow.case_changed requires case_id")
    return WorkflowWakeAction(
        workflow_id=case_id,
        topic=CASE_CHANGED_TOPIC,
        message={
            **event.payload,
            "event_id": str(event.event_id),
        },
        idempotency_key=str(event.event_id),
    )


def execute_outbox_action(action: WorkflowWakeAction) -> None:
    """Ensure the deterministic workflow exists, then durably wake it.

    Replaying this sequence is safe: SetWorkflowID makes start idempotent and
    DBOS.send deduplicates the wake by the outbox event id.
    """
    from dbos import DBOS, SetWorkflowID

    from .definitions import onboarding_case_workflow

    with SetWorkflowID(action.workflow_id):
        DBOS.start_workflow(onboarding_case_workflow, case_id=action.workflow_id)
    DBOS.send(
        destination_id=action.workflow_id,
        topic=action.topic,
        message=action.message,
        idempotency_key=action.idempotency_key,
    )


def dispatch_outbox_event(event: OutboxEvent) -> None:
    execute_outbox_action(plan_outbox_action(event))


__all__ = [
    "WorkflowWakeAction",
    "dispatch_outbox_event",
    "execute_outbox_action",
    "plan_outbox_action",
]
