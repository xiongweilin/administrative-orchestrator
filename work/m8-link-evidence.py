from __future__ import annotations

import os
from uuid import UUID

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.financial import AdministrativeCaseEvidenceLink
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.transaction_repository import TransactionRepository


def main() -> None:
    raw_case = os.environ.get("M8_CASE_ID", "").strip()
    raw_artifact = os.environ.get("M8_ARTIFACT_ID", "").strip()
    raw_representation = os.environ.get("M8_REPRESENTATION_ID", "").strip()
    if not raw_case or not raw_artifact:
        raise RuntimeError("M8_CASE_ID and M8_ARTIFACT_ID are required")
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case = store.get_case(UUID(raw_case))
    if case is None:
        raise RuntimeError(f"case not found: {raw_case}")
    link = TransactionRepository(store).append_evidence_link(
        AdministrativeCaseEvidenceLink(
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            artifact_ref=UUID(raw_artifact),
            representation_ref=UUID(raw_representation) if raw_representation else None,
            declared_role=os.environ.get("M8_DOCUMENT_ROLE", "primary-document"),
            source="m8-local-preflight",
            linked_by=os.environ.get("M8_LINKED_BY", "person:m8-reviewer"),
        )
    )
    print(
        f"case={link.case_id} link={link.link_id} artifact={link.artifact_ref} "
        f"representation={link.representation_ref} role={link.declared_role}"
    )


if __name__ == "__main__":
    main()
