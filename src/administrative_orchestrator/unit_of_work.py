from __future__ import annotations

from .domain import AdministrativeCase, AdministrativeRequest, Decision
from .messaging import emit_outbox
from .persistence import (
    CaseRow,
    ConcurrencyConflict,
    DecisionRow,
    PolicyEvaluationRow,
    RequestRow,
    SqlStore,
    utcnow,
)
from .policy import PolicyEvaluation


class AdministrativeUnitOfWork:
    """Atomic persistence boundary for case creation and authority transitions.

    A policy/decision record, the current Case state, and the durable workflow
    wake-up event commit together. A crash after this transaction may delay
    orchestration, but cannot silently lose the fact that orchestration is due.
    """

    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def create_case(
        self,
        request: AdministrativeRequest,
        case: AdministrativeCase,
    ) -> None:
        """Create Request -> Case -> initial Audit in explicit FK order.

        PostgreSQL enforces these foreign keys immediately. The staged flushes
        make ordering part of the transaction contract instead of relying on
        ORM mapper ordering that SQLite may fail to expose.
        """
        if request.requester_principal_id != case.requester_principal_id:
            raise ValueError("request and case requester must match")
        with self.store.sessions.begin() as db:
            db.add(
                RequestRow(
                    request_id=request.request_id,
                    requester_principal_id=request.requester_principal_id,
                    channel=request.channel,
                    intent=request.intent,
                    received_at=request.received_at,
                    source_ref=request.source_ref,
                )
            )
            db.flush()
            db.add(self.store._case_row(case, request.request_id))
            db.flush()
            self.store._append_audit(
                db,
                case.case_id,
                "case.created",
                {
                    "request_id": str(request.request_id),
                    "case_kind": case.case_kind,
                    "case_version": case.version,
                    "authority_epoch": case.authority_epoch,
                    "fact_snapshot_id": (
                        str(case.fact_snapshot.snapshot_id) if case.fact_snapshot else None
                    ),
                },
            )

    def apply_policy_transition(
        self,
        before: AdministrativeCase,
        after: AdministrativeCase,
        evaluation: PolicyEvaluation,
    ) -> None:
        if before.case_id != after.case_id:
            raise ValueError("policy transition cannot change case identity")
        if after.version <= before.version:
            raise ValueError("policy transition must advance case version")
        if after.authority_epoch != before.authority_epoch + 1:
            raise ValueError("policy transition must advance authority epoch exactly once")
        if after.policy_ref != evaluation.policy_ref:
            raise ValueError("case policy must match persisted policy evaluation")

        with self.store.sessions.begin() as db:
            row = db.get(CaseRow, before.case_id)
            self._require_version(row, before)
            db.add(
                PolicyEvaluationRow(
                    case_id=after.case_id,
                    case_version=after.version,
                    authority_epoch=after.authority_epoch,
                    policy_json=evaluation.policy_ref.model_dump(mode="json"),
                    evaluation_json=evaluation.model_dump(mode="json"),
                    created_at=utcnow(),
                )
            )
            self.store._copy_case_into_row(row, after)
            self.store._append_audit(
                db,
                after.case_id,
                "policy.evaluated",
                {
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "policy_id": evaluation.policy_ref.policy_id,
                    "policy_version": evaluation.policy_ref.version,
                    "disposition": evaluation.disposition.value,
                },
            )
            self.store._append_audit(
                db,
                after.case_id,
                "case.policy_applied",
                {
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "policy_disposition": evaluation.disposition.value,
                },
            )
            emit_outbox(
                db,
                event_type="workflow.case_changed",
                aggregate_id=str(after.case_id),
                payload={
                    "case_id": str(after.case_id),
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "cause": "policy_evaluated",
                },
            )

    def apply_decision_transition(
        self,
        before: AdministrativeCase,
        after: AdministrativeCase,
        decision: Decision,
    ) -> None:
        if before.case_id != after.case_id or decision.case_id != before.case_id:
            raise ValueError("decision transition cannot change case identity")
        if decision.case_version != before.version:
            raise ValueError("decision must be bound to the pre-transition case version")
        if decision.authority_epoch != before.authority_epoch:
            raise ValueError("decision must be bound to the pre-transition authority epoch")
        if after.version != before.version + 1:
            raise ValueError("decision transition must advance case version exactly once")
        if before.policy_ref is None or decision.policy_ref != before.policy_ref:
            raise ValueError("decision must be bound to the current policy")

        with self.store.sessions.begin() as db:
            row = db.get(CaseRow, before.case_id)
            self._require_version(row, before)
            db.add(
                DecisionRow(
                    decision_id=decision.decision_id,
                    case_id=decision.case_id,
                    case_version=decision.case_version,
                    authority_epoch=decision.authority_epoch,
                    principal_id=decision.principal_id,
                    disposition=decision.disposition.value,
                    rationale=decision.rationale,
                    policy_json=decision.policy_ref.model_dump(mode="json"),
                    decided_at=decision.decided_at,
                )
            )
            self.store._copy_case_into_row(row, after)
            self.store._append_audit(
                db,
                decision.case_id,
                "decision.recorded",
                {
                    "decision_id": str(decision.decision_id),
                    "case_version": decision.case_version,
                    "authority_epoch": decision.authority_epoch,
                    "principal_id": decision.principal_id,
                    "disposition": decision.disposition.value,
                    "policy_id": decision.policy_ref.policy_id,
                    "policy_version": decision.policy_ref.version,
                },
            )
            self.store._append_audit(
                db,
                after.case_id,
                "case.decision_applied",
                {
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "decision_id": str(decision.decision_id),
                },
            )
            emit_outbox(
                db,
                event_type="workflow.case_changed",
                aggregate_id=str(after.case_id),
                payload={
                    "case_id": str(after.case_id),
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "cause": "decision_recorded",
                    "decision_id": str(decision.decision_id),
                },
            )

    @staticmethod
    def _require_version(row: CaseRow | None, expected: AdministrativeCase) -> None:
        if row is None:
            raise KeyError(f"case {expected.case_id} not found")
        if row.version != expected.version:
            raise ConcurrencyConflict(
                f"case {expected.case_id} version changed: expected "
                f"{expected.version}, found {row.version}"
            )
        if row.authority_epoch != expected.authority_epoch:
            raise ConcurrencyConflict(
                f"case {expected.case_id} authority epoch changed: expected "
                f"{expected.authority_epoch}, found {row.authority_epoch}"
            )


__all__ = ["AdministrativeUnitOfWork"]
