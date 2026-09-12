from __future__ import annotations

import os
from uuid import UUID

from administrative_orchestrator.authority import (
    AuthorityRepository,
    assess_approval_satisfaction,
    resolve_decision_role,
)
from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import Decision, DecisionDisposition
from administrative_orchestrator.inspection import list_decisions
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.service import record_decision
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork


def main() -> None:
    raw_case = os.environ.get("M8_CASE_ID", "").strip()
    if not raw_case:
        raise RuntimeError("M8_CASE_ID is required")
    case_id = UUID(raw_case)
    reviewer = os.environ.get("M8_REVIEWER", "person:m8-reviewer").strip()
    role = os.environ.get("M8_ROLE", "procurement_approver").strip()
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    authority = AuthorityRepository(store)
    case = store.get_case(case_id)
    if case is None or case.policy_ref is None:
        raise RuntimeError(f"case or policy not found: {case_id}")
    evaluation = store.get_latest_policy_evaluation(case_id)
    if evaluation is None or evaluation.policy_ref != case.policy_ref:
        raise RuntimeError("case does not have the current policy evaluation")
    facts = case.fact_snapshot.facts if case.fact_snapshot else {}
    scope = str(facts.get("cost_center") or "*")
    decision_role = resolve_decision_role(
        authority,
        principal_id=reviewer,
        evaluation=evaluation,
        organization_scope=scope,
        requested_role=role,
    )
    decision = Decision(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        principal_id=reviewer,
        decision_role=decision_role,
        disposition=DecisionDisposition.APPROVE,
        rationale="M8 local preflight procurement facts and bounded vendor identity reviewed.",
        policy_ref=case.policy_ref,
    )
    approval = assess_approval_satisfaction(
        authority,
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        policy_ref=case.policy_ref,
        evaluation=evaluation,
        decisions=[*list_decisions(store, case.case_id), decision],
        organization_scope=scope,
    )
    updated = record_decision(case, decision, approval_complete=approval.satisfied)
    AdministrativeUnitOfWork(store).apply_decision_transition(
        case,
        updated,
        decision,
        organization_scope=scope,
        approval_satisfaction=approval.satisfaction,
    )
    print(
        f"case={case_id} status={updated.status.value} decision={decision.decision_id} "
        f"approval_satisfied={approval.satisfied}"
    )


if __name__ == "__main__":
    main()
