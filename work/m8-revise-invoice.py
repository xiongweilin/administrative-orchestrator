from __future__ import annotations

import os
from decimal import Decimal
from uuid import UUID

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import FactAuthority, FactSnapshot
from administrative_orchestrator.fact_transitions import replace_facts_for_reevaluation
from administrative_orchestrator.financial import InvoiceFacts, has_material_financial_revision
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    compile_invoice_ap_policy,
)
from administrative_orchestrator.service import apply_policy_evaluation, start_policy_evaluation
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
        raise RuntimeError(f"invoice case or fact snapshot not found: {case_id}")
    if case.case_kind != "invoice-ap-preparation":
        raise RuntimeError(f"case is not an invoice case: {case.case_kind}")

    invoice = InvoiceFacts.model_validate(case.fact_snapshot.facts)
    if invoice.total is None:
        raise RuntimeError("invoice facts have no total")
    revised_amount = invoice.total.amount + Decimal(
        os.environ.get("M8_REVISION_DELTA", "5.00")
    )
    revised = invoice.model_copy(
        update={
            "total": invoice.total.model_copy(update={"amount": revised_amount}),
            "document_revision": os.environ.get("M8_DOCUMENT_REVISION", "v2"),
            "document_digest": os.environ.get("M8_DOCUMENT_DIGEST", "b" * 64),
        }
    )
    revised_facts = revised.model_dump(mode="json")
    if not has_material_financial_revision(
        case.case_kind,
        case.fact_snapshot.facts,
        revised_facts,
    ):
        raise RuntimeError("revision was not material")

    owner = os.environ.get("M8_REVIEWER", "person:m8-reviewer").strip()
    source_ref = os.environ.get("M8_REVISION_SOURCE_REF", "m8-local-document-revision")
    source_version = os.environ.get("M8_REVISION_SOURCE_VERSION", "v2")
    snapshot = FactSnapshot(
        source=f"document-revision:{owner}",
        owner=owner,
        authority=FactAuthority.CLAIM,
        source_ref=source_ref,
        source_version=source_version,
        facts=revised_facts,
    )
    changed = replace_facts_for_reevaluation(case, snapshot)
    policy_record = PolicyRepository(store).resolve_current("invoice-ap-preparation")
    evaluation = compile_invoice_ap_policy(policy_record).evaluate(revised)
    ready = start_policy_evaluation(changed)
    updated = apply_policy_evaluation(ready, evaluation)
    AdministrativeUnitOfWork(store).replace_facts_and_apply_policy(case, updated, evaluation)
    print(
        f"case={case_id} previous_version={case.version} new_version={updated.version} "
        f"previous_epoch={case.authority_epoch} new_epoch={updated.authority_epoch} "
        f"status={updated.status.value} policy_result={evaluation.disposition.value}"
    )


if __name__ == "__main__":
    main()
