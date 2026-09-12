from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.intake.document_repository import DocumentRepository
from administrative_orchestrator.intake.models import (
    AssessmentAuthority,
    CandidateAdministrativeRequest,
    CandidateAuthority,
    CandidateFactAssertion,
    DocumentRepresentation,
    EvidenceSpan,
    IntakeReceipt,
    IntakeVerificationStatus,
    InterpretationRecord,
    SourceArtifact,
)
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.persistence import SqlStore

SEED_NAMESPACE = UUID("4b9cfcb4-cb13-5da7-8cb5-d3e0fcb95a43")
SEED_TIME = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)


def stable(label: str, *, suffix: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"{suffix}:{label}")


def main() -> None:
    suffix = os.environ.get("M8_SEED_SUFFIX", "001").strip() or "001"
    seed_event = f"m8-local-preflight-procurement-{suffix}"
    settings = get_settings()
    store = SqlStore(settings.database_url)
    intake = IntakeRepository(store)
    documents = DocumentRepository(store)
    artifact_store = FilesystemArtifactStore(Path(settings.feishu_artifact_root))

    raw_content = (
        f"M8 synthetic procurement request ({seed_event})\n".encode()
        + b"Description: ergonomic office chairs\n"
        b"Quantity: 2\n"
        b"Estimated amount: USD 120.00\n"
        b"Vendor: M8 Acme Office Supplies\n"
        b"Cost center: CC-STAGING\n"
    )
    raw = artifact_store.put(raw_content)
    representation_content = raw_content + b"\nDerived representation: text/plain page=1\n"
    representation_raw = artifact_store.put(representation_content)

    artifact = intake.append_source_artifact(
        SourceArtifact(
            artifact_id=stable("artifact", suffix=suffix),
            source_kind="feishu-canonical-message",
        source_system="feishu",
        tenant_ref="tenant:m8-staging",
        canonical_source_ref=f"feishu://m8-staging/message/{seed_event}",
        source_revision="initial",
        source_event_ref=seed_event,
            actor_external_identity_ref="m8-reviewer",
            captured_at=SEED_TIME,
            source_timestamp=SEED_TIME,
            content_digest=raw.digest,
            storage_ref=raw.storage_ref,
            mime_type="text/plain",
            size=raw.size,
            authenticity_class="provider-canonical-read-local-preflight",
            retention_class="financial-document-staging",
        )
    )
    intake.persist_intake_receipt(
        IntakeReceipt(
            receipt_id=stable("receipt", suffix=suffix),
            source_system="feishu",
            tenant_ref="tenant:m8-staging",
            source_event_id=seed_event,
            received_at=SEED_TIME,
            verification_status=IntakeVerificationStatus.VERIFIED,
            artifact_ref=artifact.artifact_id,
            delivery_digest=raw.digest,
        )
    )
    representation = documents.append_representation(
        DocumentRepresentation(
            representation_id=stable("representation", suffix=suffix),
            source_artifact_ref=artifact.artifact_id,
            representation_kind="text",
            extractor_ref="m8-local-seed",
            extractor_version="1",
            content_digest=representation_raw.digest,
            storage_ref=representation_raw.storage_ref,
            size=representation_raw.size,
            created_at=SEED_TIME,
            page_count=1,
            metadata={"mime_type": "text/plain", "lineage": "local-preflight"},
        )
    )
    span = intake.append_evidence_span(
        EvidenceSpan(
            evidence_span_id=stable("evidence-span", suffix=suffix),
            artifact_ref=artifact.artifact_id,
            representation_ref=representation.representation_id,
            representation_digest=representation.content_digest,
            locator_kind="line",
            locator={"page": 1, "start_line": 1, "end_line": 6},
            extractor_ref="m8-local-seed",
        )
    )
    interpretation = intake.append_interpretation(
        InterpretationRecord(
            interpretation_id=stable("interpretation", suffix=suffix),
            artifact_refs=(artifact.artifact_id,),
            interpretation_profile_ref="procurement-request-v1",
            model_provider="local-preflight",
            model_identity="deterministic-seed",
            model_version="1",
            schema_ref="m8.procurement.facts.v1",
            interpreted_at=SEED_TIME,
            structured_output={
                "description": "ergonomic office chairs",
                "requested_quantity": "2",
                "estimated_amount": {"amount": "120.00", "currency": "USD"},
                "candidate_vendor": "M8 Acme Office Supplies",
                "vendor_ref": "odoo:res.partner:11",
                "cost_center": "CC-STAGING",
            },
            evidence_span_refs=(span.evidence_span_id,),
            response_digest=representation.content_digest,
        )
    )

    fact_values = {
        "description": "ergonomic office chairs",
        "requested_quantity": "2",
        "estimated_amount": {"amount": "120.00", "currency": "USD"},
        "candidate_vendor": "M8 Acme Office Supplies",
        "vendor_ref": "odoo:res.partner:11",
        "cost_center": "CC-STAGING",
        "needed_by": "2026-10-01",
        "quote_ref": f"m8-synthetic-quote-{suffix}",
    }
    fact_refs: list[UUID] = []
    for key, value in fact_values.items():
        fact = intake.append_candidate_fact(
            CandidateFactAssertion(
            candidate_fact_id=stable(f"fact:{key}", suffix=suffix),
                fact_key=key,
                value=value,
                authority=CandidateAuthority.CLAIM,
                interpretation_ref=interpretation.interpretation_id,
                source_refs=(artifact.artifact_id,),
                evidence_span_refs=(span.evidence_span_id,),
                extractor_ref="m8-local-seed",
                created_at=SEED_TIME,
            )
        )
        fact_refs.append(fact.candidate_fact_id)

    candidate = intake.append_candidate_request(
        CandidateAdministrativeRequest(
            candidate_id=stable("candidate", suffix=suffix),
            conversation_ref=f"feishu/tenant:m8-staging/thread:{seed_event}",
            interpretation_refs=(interpretation.interpretation_id,),
            candidate_requester="m8-synthetic-requester",
            candidate_intent="Prepare a bounded procurement request for staging.",
            candidate_fact_refs=tuple(fact_refs),
            source_refs=(artifact.artifact_id,),
            created_at=SEED_TIME,
        )
    )
    print(
        f"candidate_id={candidate.candidate_id} artifact_id={artifact.artifact_id} "
        f"representation_id={representation.representation_id} "
        f"interpretation_id={interpretation.interpretation_id} "
        f"source_event_id={seed_event} authority={AssessmentAuthority.MODEL_SUGGESTION.value}"
    )


if __name__ == "__main__":
    main()
