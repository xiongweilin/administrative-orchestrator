from __future__ import annotations

import os
from uuid import UUID

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.financial import (
    TransactionQualificationAssessment,
    TransactionQualificationResult,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.transaction_repository import TransactionRepository


def main() -> None:
    raw_case = os.environ.get("M8_CASE_ID", "").strip()
    if not raw_case:
        raise RuntimeError("M8_CASE_ID is required")
    case_id = UUID(raw_case)
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case = store.get_case(case_id)
    if case is None or case.fact_snapshot is None:
        raise RuntimeError(f"case or fact snapshot not found: {case_id}")
    vendor_ref = str(case.fact_snapshot.facts.get("vendor_ref") or "").strip()
    if not vendor_ref.startswith("odoo:res.partner:"):
        raise RuntimeError("case vendor_ref is not bounded")
    assessment = TransactionRepository(store).append_assessment(
        TransactionQualificationAssessment(
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            assessment_kind="vendor_qualification",
            input_refs=(vendor_ref, f"candidate-case:{case.case_id}"),
            rule_ref="m8-vendor-master-v1",
            result=TransactionQualificationResult.QUALIFIED,
        )
    )
    print(
        f"case={case.case_id} assessment={assessment.assessment_id} "
        f"kind={assessment.assessment_kind} result={assessment.result.value}"
    )


if __name__ == "__main__":
    main()
