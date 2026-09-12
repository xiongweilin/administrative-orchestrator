from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.intake.document_repository import DocumentRepository
from administrative_orchestrator.intake.models import (
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
    kind = os.environ.get("M8_FINANCIAL_KIND", "invoice").strip().lower()
    if kind not in {"invoice", "expense"}:
        raise RuntimeError("M8_FINANCIAL_KIND must be invoice or expense")
    raw_suffix = os.environ.get("M8_SEED_SUFFIX", "001").strip() or "001"
    suffix = f"{kind}-{raw_suffix}"
    seed_event = f"m8-local-preflight-{kind}-{raw_suffix}"

    if kind == "invoice":
        invoice_number = os.environ.get("M8_INVOICE_NUMBER", f"M8-INV-{raw_suffix}").strip()
        if not invoice_number:
            raise RuntimeError("M8_INVOICE_NUMBER must not be empty")
        facts = {
            "vendor_name": "M8 Acme Office Supplies",
            "vendor_ref": "odoo:res.partner:11",
            "invoice_number": invoice_number,
            "invoice_date": "2026-09-12",
            "total": {"amount": "120.00", "currency": "USD"},
            "po_number": f"M8-PO-{raw_suffix}",
            "line_items": [
                {
                    "description": "ergonomic office chairs",
                    "quantity": "2",
                    "unit_price": {"amount": "60.00", "currency": "USD"},
                }
            ],
            "document_revision": "v1",
        }
        document_title = "M8 synthetic invoice/AP preparation"
        declared_role = "invoice"
    else:
        facts = {
            "employee_ref": "odoo:hr.employee:2",
            "merchant": "M8 Acme Office Supplies",
            "expense_date": "2026-09-12",
            "amount": {"amount": "42.00", "currency": "USD"},
            "category": "office-supplies",
            "business_purpose": "M8 staging office supplies",
            "receipt_ref": f"m8-expense-receipt-{raw_suffix}",
        }
        document_title = "M8 synthetic expense receipt"
        declared_role = "expense-receipt"

    settings = get_settings()
    store = SqlStore(settings.database_url)
    intake = IntakeRepository(store)
    documents = DocumentRepository(store)
    artifact_store = FilesystemArtifactStore(Path(settings.feishu_artifact_root))
    raw_content = (
        f"{document_title} ({seed_event})\n".encode()
        + json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    raw = artifact_store.put(raw_content)
    representation_raw = artifact_store.put(
        raw_content + b"Derived representation: text/plain page=1\n"
    )

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
            metadata={"mime_type": "text/plain", "lineage": "local-preflight", "kind": kind},
        )
    )
    span = intake.append_evidence_span(
        EvidenceSpan(
            evidence_span_id=stable("evidence-span", suffix=suffix),
            artifact_ref=artifact.artifact_id,
            representation_ref=representation.representation_id,
            representation_digest=representation.content_digest,
            locator_kind="line",
            locator={"page": 1, "start_line": 1, "end_line": 3},
            extractor_ref="m8-local-seed",
        )
    )
    interpretation = intake.append_interpretation(
        InterpretationRecord(
            interpretation_id=stable("interpretation", suffix=suffix),
            artifact_refs=(artifact.artifact_id,),
            interpretation_profile_ref=f"m8.{kind}.facts.v1",
            model_provider="local-preflight",
            model_identity="deterministic-seed",
            model_version="1",
            schema_ref=f"m8.{kind}.facts.v1",
            interpreted_at=SEED_TIME,
            structured_output=facts,
            evidence_span_refs=(span.evidence_span_id,),
            response_digest=representation.content_digest,
        )
    )
    if kind == "invoice":
        facts["document_digest"] = raw.digest
    fact_refs: list[UUID] = []
    for key, value in facts.items():
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
            candidate_intent=f"Prepare bounded M8 {kind} staging.",
            candidate_fact_refs=tuple(fact_refs),
            source_refs=(artifact.artifact_id,),
            created_at=SEED_TIME,
        )
    )
    print(
        f"kind={kind} candidate_id={candidate.candidate_id} artifact_id={artifact.artifact_id} "
        f"representation_id={representation.representation_id} "
        f"interpretation_id={interpretation.interpretation_id} "
        f"source_event_id={seed_event} declared_role={declared_role}"
    )


if __name__ == "__main__":
    main()
