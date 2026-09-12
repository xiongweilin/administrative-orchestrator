from __future__ import annotations

import os
from uuid import UUID

from administrative_orchestrator.admission import IntakeAssessmentService
from administrative_orchestrator.config import get_settings
from administrative_orchestrator.financial_admission import CandidateProcurementAdmissionService
from administrative_orchestrator.intake.models import IntakeDisposition
from administrative_orchestrator.intake.repository import IntakeRepository, SourceArtifactRow
from administrative_orchestrator.persistence import SqlStore


def main() -> None:
    raw_candidate = os.environ.get("M8_CANDIDATE_ID", "").strip()
    if not raw_candidate:
        raise RuntimeError("M8_CANDIDATE_ID is required")
    candidate_id = UUID(raw_candidate)
    reviewer = os.environ.get("M8_REVIEWER", "person:m8-reviewer").strip()
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    repository = IntakeRepository(store)
    candidate = repository.get_candidate(candidate_id)
    if candidate is None:
        raise RuntimeError(f"candidate not found: {candidate_id}")
    facts = {item.fact_key: item.value for item in repository.list_candidate_facts(candidate_id)}
    vendor_ref = str(facts.get("vendor_ref") or "").strip()
    if not vendor_ref.startswith("odoo:res.partner:"):
        raise RuntimeError("procurement candidate vendor_ref is not bounded")
    with store.sessions() as db:
        artifact = db.get(SourceArtifactRow, candidate.source_refs[0])
        if artifact is None:
            raise RuntimeError("procurement source artifact not found")

    assessment = IntakeAssessmentService(repository).finalize_human(
        candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id=reviewer,
        basis={
            "review_basis": "M8 local preflight; bounded procurement facts and vendor identity reviewed",
            "promotion_policy_ref": "m8-human-confirmed-v1",
        },
    )
    result = CandidateProcurementAdmissionService(store, repository).promote_and_evaluate(
        candidate,
        assessment,
        source_system=artifact.source_system,
        tenant_ref=artifact.tenant_ref,
        source_event_id=artifact.source_event_ref,
        requester_principal_id=reviewer,
        subject_ref=f"transaction:{candidate_id}",
        channel="feishu",
        promotion_policy_ref="m8-human-confirmed-v1",
    )
    print(
        f"candidate={candidate_id} assessment={assessment.assessment_id} "
        f"promotion={result.promotion.promotion.promotion_id} "
        f"request={result.promotion.request.request_id} "
        f"case={result.case.case_id} status={result.case.status.value}"
    )


if __name__ == "__main__":
    main()
