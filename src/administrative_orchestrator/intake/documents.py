from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from ..domain import UtcModel, utcnow
from .artifacts import ArtifactStore
from .models import CandidateAuthority, CandidateFactAssertion, EvidenceSpan, SourceArtifact
from .repository import IntakeRepository

_DOCUMENT_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://administrative-orchestrator/intake/document-attachments",
)
_RESERVED_LOCATOR_KEYS = frozenset(
    {"representation_kind", "char_start", "char_end", "text_sha256"}
)


class DocumentProcessingStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentParseError(RuntimeError):
    """The parser/OCR boundary could not produce a trusted representation."""


class DocumentLineageError(DocumentParseError):
    """The parser output cannot be bound to exact EvidenceSpan lineage."""


class MessageAttachment(UtcModel):
    """Provider-neutral attachment input for the document intake boundary.

    The raw bytes are deliberately carried only across this transient boundary.
    Durable source metadata points to the content-addressed object returned by
    ``ArtifactStore`` rather than copying the binary into PostgreSQL.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    attachment_ref: str = Field(
        min_length=1,
        max_length=1000,
        validation_alias=AliasChoices("attachment_ref", "attachment_id"),
        serialization_alias="attachment_ref",
    )
    message_ref: str = Field(min_length=1, max_length=1000)
    source_system: str = Field(min_length=1, max_length=128)
    tenant_ref: str = Field(min_length=1, max_length=512)
    source_event_ref: str = Field(min_length=1, max_length=512)
    filename: str = Field(min_length=1, max_length=1000)
    mime_type: str = Field(min_length=1, max_length=255)
    content: bytes
    source_revision: str = Field(default="initial", min_length=1, max_length=256)
    actor_external_identity_ref: str | None = Field(default=None, max_length=1000)
    captured_at: datetime = Field(default_factory=utcnow)
    source_timestamp: datetime | None = None
    declared_content_digest: str | None = Field(default=None, min_length=64, max_length=64)
    authenticity_class: str = Field(
        default="provider_verified_attachment", min_length=1, max_length=128
    )
    retention_class: str = Field(default="inbox_business_record", min_length=1, max_length=128)

    @property
    def attachment_id(self) -> str:
        """Compatibility alias for callers that use an id rather than a ref."""

        return self.attachment_ref

    @model_validator(mode="after")
    def validate_identity(self) -> MessageAttachment:
        for name in (
            "attachment_ref",
            "message_ref",
            "source_system",
            "tenant_ref",
            "source_event_ref",
            "filename",
            "mime_type",
            "source_revision",
            "authenticity_class",
            "retention_class",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")
        return self


class DocumentEvidenceDraft(UtcModel):
    """One exact range in a parser/OCR text representation.

    ``text`` must equal ``representation[char_start:char_end]``. Additional
    locator fields are retained in the resulting EvidenceSpan, but cannot
    override the service-owned range or digest fields.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    locator_kind: str = Field(default="document_text", min_length=1, max_length=128)
    locator: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self) -> DocumentEvidenceDraft:
        if self.char_end <= self.char_start:
            raise ValueError("document evidence range must be non-empty")
        if _RESERVED_LOCATOR_KEYS.intersection(self.locator):
            raise ValueError("document evidence locator contains reserved lineage fields")
        return self


class DocumentFactDraft(UtcModel):
    """A candidate-only fact emitted by a parser/OCR adapter.

    A fact must name one or more exact evidence draft indexes. The processor
    refuses to turn an unbound parser claim into a CandidateFactAssertion.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_key: str = Field(min_length=1, max_length=512)
    value: Any
    evidence_indexes: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fact_key(self) -> DocumentFactDraft:
        if not self.fact_key.strip():
            raise ValueError("fact_key must not be blank")
        if len(set(self.evidence_indexes)) != len(self.evidence_indexes):
            raise ValueError("document fact evidence_indexes must be unique")
        return self


class DocumentExtraction(UtcModel):
    """Validated parser/OCR output over one textual representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    representation: str = Field(min_length=1)
    representation_kind: str = Field(default="utf-8-text", min_length=1, max_length=128)
    extractor_ref: str = Field(min_length=1, max_length=512)
    evidence: tuple[DocumentEvidenceDraft, ...] = ()
    facts: tuple[DocumentFactDraft, ...] = ()


@runtime_checkable
class DocumentParser(Protocol):
    """Parser/OCR port; implementations have no authority to persist facts."""

    def parse(self, attachment: MessageAttachment, content: bytes) -> DocumentExtraction:
        """Extract a representation and explicitly lineaged candidate drafts."""


class PlainTextDocumentParser:
    """Small deterministic parser useful for text attachments and tests."""

    def parse(self, attachment: MessageAttachment, content: bytes) -> DocumentExtraction:
        del attachment
        try:
            representation = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("text attachment is not valid UTF-8") from exc
        if not representation.strip():
            raise DocumentParseError("text attachment has no extractable content")
        return DocumentExtraction(
            representation=representation,
            extractor_ref="plain-text-parser-v1",
            evidence=(
                DocumentEvidenceDraft(
                    text=representation,
                    char_start=0,
                    char_end=len(representation),
                ),
            ),
        )


class DocumentAttachmentResult(UtcModel):
    """Auditable result, including the raw artifact on parser failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DocumentProcessingStatus
    artifact: SourceArtifact
    evidence_spans: tuple[EvidenceSpan, ...] = ()
    facts: tuple[CandidateFactAssertion, ...] = ()
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_result(self) -> DocumentAttachmentResult:
        if self.status is DocumentProcessingStatus.SUCCEEDED:
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("successful document processing cannot carry an error")
        elif not self.error_code:
            raise ValueError("failed document processing requires error_code")
        return self


class DocumentAttachmentProcessor:
    """Build raw artifact, parser spans, and candidate facts in that order."""

    def __init__(
        self,
        artifact_store: ArtifactStore,
        parser: DocumentParser,
        repository: IntakeRepository | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.parser = parser
        self.repository = repository

    def process(self, attachment: MessageAttachment) -> DocumentAttachmentResult:
        stored = self.artifact_store.put(
            attachment.content,
            expected_digest=attachment.declared_content_digest,
        )
        artifact = self._source_artifact(attachment, stored)
        if self.repository is not None:
            artifact = self.repository.append_source_artifact(artifact)

        try:
            raw_content = self.artifact_store.get(
                stored.storage_ref,
                expected_digest=stored.content_digest,
            )
            extraction = self.parser.parse(attachment, raw_content)
            spans, facts = self._bind_extraction(artifact, extraction)
        except Exception as exc:
            return DocumentAttachmentResult(
                status=DocumentProcessingStatus.FAILED,
                artifact=artifact,
                error_code=self._error_code(exc),
                error_message=str(exc)[:2000] or exc.__class__.__name__,
            )

        if self.repository is not None:
            spans = tuple(self.repository.append_evidence_span(span) for span in spans)
            facts = tuple(self.repository.append_candidate_fact(fact) for fact in facts)
        return DocumentAttachmentResult(
            status=DocumentProcessingStatus.SUCCEEDED,
            artifact=artifact,
            evidence_spans=spans,
            facts=facts,
        )

    @staticmethod
    def _source_artifact(attachment: MessageAttachment, stored: Any) -> SourceArtifact:
        artifact_id = uuid5(
            _DOCUMENT_NAMESPACE,
            f"artifact:{attachment.source_system}:{attachment.tenant_ref}:"
            f"{attachment.message_ref}:{attachment.attachment_ref}:{attachment.source_revision}",
        )
        return SourceArtifact(
            artifact_id=artifact_id,
            source_kind="message_attachment",
            source_system=attachment.source_system,
            tenant_ref=attachment.tenant_ref,
            canonical_source_ref=(
                f"message:{attachment.message_ref}/attachment:{attachment.attachment_ref}"
            ),
            source_revision=attachment.source_revision,
            source_event_ref=attachment.source_event_ref,
            actor_external_identity_ref=attachment.actor_external_identity_ref,
            captured_at=attachment.captured_at,
            source_timestamp=attachment.source_timestamp,
            content_digest=stored.content_digest,
            storage_ref=stored.storage_ref,
            mime_type=attachment.mime_type,
            size=stored.size,
            authenticity_class=attachment.authenticity_class,
            retention_class=attachment.retention_class,
        )

    @staticmethod
    def _bind_extraction(
        artifact: SourceArtifact,
        extraction: DocumentExtraction,
    ) -> tuple[tuple[EvidenceSpan, ...], tuple[CandidateFactAssertion, ...]]:
        representation_bytes = extraction.representation.encode("utf-8")
        representation_digest = hashlib.sha256(representation_bytes).hexdigest()
        spans: list[EvidenceSpan] = []
        for index, draft in enumerate(extraction.evidence):
            if draft.char_end > len(extraction.representation):
                raise DocumentLineageError("document evidence range exceeds representation")
            actual_text = extraction.representation[draft.char_start : draft.char_end]
            if actual_text != draft.text:
                raise DocumentLineageError("document evidence text does not match its range")
            locator = {
                "representation_kind": extraction.representation_kind,
                "char_start": draft.char_start,
                "char_end": draft.char_end,
                "text_sha256": _sha256_text(draft.text),
                **draft.locator,
            }
            spans.append(
                EvidenceSpan(
                    evidence_span_id=uuid5(
                        _DOCUMENT_NAMESPACE,
                        f"span:{artifact.artifact_id}:{representation_digest}:{index}",
                    ),
                    artifact_ref=artifact.artifact_id,
                    representation_digest=representation_digest,
                    locator_kind=draft.locator_kind,
                    locator=locator,
                    extractor_ref=extraction.extractor_ref,
                )
            )

        facts: list[CandidateFactAssertion] = []
        for index, draft in enumerate(extraction.facts):
            if any(evidence_index >= len(spans) for evidence_index in draft.evidence_indexes):
                raise DocumentLineageError("document fact references an unbound evidence span")
            evidence_refs = tuple(spans[evidence_index].evidence_span_id for evidence_index in draft.evidence_indexes)
            facts.append(
                CandidateFactAssertion(
                    candidate_fact_id=uuid5(
                        _DOCUMENT_NAMESPACE,
                        f"fact:{artifact.artifact_id}:{extraction.extractor_ref}:{index}",
                    ),
                    fact_key=draft.fact_key,
                    value=draft.value,
                    authority=CandidateAuthority.CLAIM,
                    source_refs=(artifact.artifact_id,),
                    evidence_span_refs=evidence_refs,
                    extractor_ref=extraction.extractor_ref,
                )
            )
        return tuple(spans), tuple(facts)

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, DocumentLineageError):
            return "lineage_validation_failed"
        if isinstance(error, DocumentParseError):
            return "parser_failed"
        if isinstance(error, ValueError):
            return "parser_output_invalid"
        return "parser_error"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Short aliases keep the boundary easy to discover without duplicating models.
ParsedDocument = DocumentExtraction
EvidenceDraft = DocumentEvidenceDraft
FactDraft = DocumentFactDraft
DocumentAttachmentIntake = DocumentAttachmentProcessor


__all__ = [
    "DocumentAttachmentIntake",
    "DocumentAttachmentProcessor",
    "DocumentAttachmentResult",
    "DocumentEvidenceDraft",
    "DocumentExtraction",
    "DocumentFactDraft",
    "DocumentLineageError",
    "DocumentParseError",
    "DocumentParser",
    "DocumentProcessingStatus",
    "EvidenceDraft",
    "FactDraft",
    "MessageAttachment",
    "ParsedDocument",
    "PlainTextDocumentParser",
]
