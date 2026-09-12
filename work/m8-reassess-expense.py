from __future__ import annotations

import os
from uuid import UUID

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import FactAuthority, FactSnapshot
from administrative_orchestrator.fact_transitions import replace_facts_for_reevaluation
from administrative_orchestrator.financial import ExpenseFacts
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy_plane import PolicyRepository, compile_expense_policy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    explicit_reopen,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork


def main() -> None:
    raw_case = os.environ.get("M8_CASE_ID", "").strip()
    if not raw_case:
        raise RuntimeError("M8_CASE_ID is required")
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case_id = UUID(raw_case)
    case = store.get_case(case_id)
    if case is None or case.fact_snapshot is None:
        raise RuntimeError(f"expense case or fact snapshot not found: {case_id}")
    if case.case_kind != "expense-reimbursement":
        raise RuntimeError(f"case is not an expense case: {case.case_kind}")
    if case.status.value != "reopen_required":
        raise RuntimeError(f"expense case is not awaiting explicit reopen: {case.status.value}")

    reopened = explicit_reopen(case)
    store.update_case(
        reopened,
        expected_previous_version=case.version,
        event_type="case.reassessed",
    )

    owner = os.environ.get("M8_REVIEWER", "person:m8-reviewer").strip()
    facts = ExpenseFacts.model_validate(reopened.fact_snapshot.facts)
    snapshot = FactSnapshot(
        source=f"m8-reassessment:{owner}",
        owner=owner,
        authority=FactAuthority.CLAIM,
        source_ref=os.environ.get(
            "M8_REASSESSMENT_SOURCE_REF",
            "m8-real-expense-reassessment-after-connector-fix",
        ),
        source_version="m8-expense-connector-fix-v1",
        facts=facts.model_dump(mode="json"),
    )
    changed = replace_facts_for_reevaluation(reopened, snapshot)
    policy_record = PolicyRepository(store).resolve_current("expense-reimbursement")
    evaluation = compile_expense_policy(policy_record).evaluate(facts)
    ready = start_policy_evaluation(changed)
    updated = apply_policy_evaluation(ready, evaluation)
    AdministrativeUnitOfWork(store).replace_facts_and_apply_policy(
        reopened,
        updated,
        evaluation,
    )
    print(
        f"case={case_id} previous_epoch={case.authority_epoch} "
        f"new_epoch={updated.authority_epoch} status={updated.status.value} "
        f"policy_result={evaluation.disposition.value}"
    )


if __name__ == "__main__":
    main()
