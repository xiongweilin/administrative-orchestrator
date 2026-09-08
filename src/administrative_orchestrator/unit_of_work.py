from __future__ import annotations

from .domain import AdministrativeCase, Decision
from .persistence import (
    CaseRow,
    ConcurrencyConflict,
    DecisionRow,
    PolicyEvaluationRow,
    SqlStore,
    utcnow,
)
from .policy import PolicyEvaluation


class AdministrativeUnitOfWork:
    """Atomic persistence boundary for authority-relevant case transitions.

    A policy/decision record and the case state it justifies must commit together.
    Append-only historical records are valuable only when their relationship to
    current state cannot be torn apart by a concurrent write or process failure.
    """

    def __init__(self, store: SqlStore) -> None:
        self.store = store

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
        if after.policy_ref != evaluation.policy_ref:
            raise ValueError("case policy must match persisted policy evaluation")

        with self.store.sessions.begin() as db:
            row = db.get(CaseRow, before.case_id)
            self._require_version(row, before)
            db.add(
                PolicyEvaluationRow(
                    case_id=after.case_id,
                    case_version=after.version,
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
                    "status": after.status.value,
                    "policy_disposition": evaluation.disposition.value,
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
                    "status": after.status.value,
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


__all__ = ["AdministrativeUnitOfWork"]
