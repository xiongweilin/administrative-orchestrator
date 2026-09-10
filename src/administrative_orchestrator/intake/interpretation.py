from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import (
    EvidenceSpan,
    InterpretationRecord,
    InterpretationStatus,
    SourceArtifact,
)
from .repository import IntakeRepository


class ModelGatewayError(RuntimeError):
    """Base error raised when the model gateway cannot produce a response."""


class ModelTimeoutError(ModelGatewayError):
    """The model gateway exceeded the configured timeout."""


class ModelProviderUnavailable(ModelGatewayError):
    """The model provider is unavailable or rejected the request."""


class InterpretationValidationError(ValueError):
    """The model response cannot be admitted as a candidate interpretation."""


class InterpretationProfile(BaseModel):
    """Versioned instructions and output schema for one interpretation lane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_ref: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(min_length=1, max_length=512)
    instruction: str = Field(min_length=1, max_length=4000)


class CandidateFactDraft(BaseModel):
    """The only fact shape a model may propose to the Intake plane."""

    model_config = ConfigDict(extra="forbid")

    fact_key: str = Field(min_length=1, max_length=512)
    value: Any
    evidence_span_refs: tuple[UUID, ...] = ()


class CandidateInterpretationPayload(BaseModel):
    """Closed candidate-only model output schema.

    Unknown fields are rejected rather than ignored. In particular, model
    output cannot smuggle authority, decisions, grants, tools, or delivery
    commands through an untyped JSON envelope.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_intent: str = Field(min_length=1, max_length=2000)
    candidate_facts: tuple[CandidateFactDraft, ...] = ()
    draft_response: str | None = Field(default=None, max_length=10000)
    evidence_span_refs: tuple[UUID, ...] = ()


class ModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=128)
    model_identity: str = Field(min_length=1, max_length=512)
    model_version: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    artifact_ref: UUID
    profile: InterpretationProfile
    source_text: str


@dataclass(frozen=True, slots=True)
class ModelResponse:
    raw_output: str
    provenance: ModelProvenance


@runtime_checkable
class ModelGateway(Protocol):
    @property
    def provenance(self) -> ModelProvenance:
        """Return provider/model metadata even when a request fails."""

    def complete(self, request: ModelRequest, *, timeout_seconds: float) -> ModelResponse:
        """Return one raw structured response without assigning authority."""


ModelOutput = str | ModelResponse
ModelOutputFactory = Callable[[ModelRequest], ModelOutput]


class StaticModelGateway:
    """Deterministic adapter for tests and local contract exercises."""

    def __init__(
        self,
        output: ModelOutput | ModelOutputFactory,
        *,
        provenance: ModelProvenance,
    ) -> None:
        self._output = output
        self._provenance = provenance

    @property
    def provenance(self) -> ModelProvenance:
        return self._provenance

    def complete(self, request: ModelRequest, *, timeout_seconds: float) -> ModelResponse:
        del timeout_seconds
        output = self._output(request) if callable(self._output) else self._output
        if isinstance(output, ModelResponse):
            return output
        return ModelResponse(raw_output=output, provenance=self._provenance)


class InterpretationClient:
    """Turn one model response into an append-only, candidate-only record."""

    def __init__(
        self,
        gateway: ModelGateway,
        repository: IntakeRepository | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.gateway = gateway
        self.repository = repository
        self.timeout_seconds = timeout_seconds

    def interpret(
        self,
        artifact: SourceArtifact,
        source_text: str,
        profile: InterpretationProfile,
        evidence_spans: Sequence[EvidenceSpan] = (),
        *,
        interpretation_id: UUID | None = None,
    ) -> InterpretationRecord:
        request = ModelRequest(
            artifact_ref=artifact.artifact_id,
            profile=profile,
            source_text=source_text,
        )
        try:
            response = self.gateway.complete(request, timeout_seconds=self.timeout_seconds)
        except ModelTimeoutError:
            return self._persist_failure(
                artifact, profile, "model_timeout", interpretation_id=interpretation_id
            )
        except ModelProviderUnavailable:
            return self._persist_failure(
                artifact, profile, "provider_unavailable", interpretation_id=interpretation_id
            )
        except ModelGatewayError:
            return self._persist_failure(
                artifact, profile, "provider_error", interpretation_id=interpretation_id
            )

        try:
            payload = self._parse_payload(response.raw_output)
            bound_evidence = self._bind_evidence(payload, artifact, evidence_spans)
        except (InterpretationValidationError, TypeError, ValueError):
            return self._persist_invalid(
                artifact, profile, response, interpretation_id=interpretation_id
            )

        record = InterpretationRecord(
            interpretation_id=interpretation_id or uuid4(),
            artifact_refs=(artifact.artifact_id,),
            interpretation_profile_ref=profile.profile_ref,
            model_provider=response.provenance.provider,
            model_identity=response.provenance.model_identity,
            model_version=response.provenance.model_version,
            schema_ref=profile.schema_ref,
            structured_output=payload.model_dump(mode="json"),
            evidence_span_refs=bound_evidence,
            response_digest=_sha256_text(response.raw_output),
            status=InterpretationStatus.SUCCEEDED,
        )
        return self._append(record)

    @staticmethod
    def _parse_payload(raw_output: str) -> CandidateInterpretationPayload:
        try:
            decoded = json.loads(raw_output)
        except (TypeError, ValueError) as exc:
            raise InterpretationValidationError("model response is not valid JSON") from exc
        try:
            return CandidateInterpretationPayload.model_validate(decoded)
        except ValidationError as exc:
            raise InterpretationValidationError("model response violates candidate schema") from exc

    @staticmethod
    def _bind_evidence(
        payload: CandidateInterpretationPayload,
        artifact: SourceArtifact,
        evidence_spans: Sequence[EvidenceSpan],
    ) -> tuple[UUID, ...]:
        spans_by_id: dict[UUID, EvidenceSpan] = {}
        for span in evidence_spans:
            if span.artifact_ref != artifact.artifact_id:
                raise InterpretationValidationError("EvidenceSpan belongs to another artifact")
            if span.evidence_span_id in spans_by_id:
                raise InterpretationValidationError("duplicate EvidenceSpan identity")
            spans_by_id[span.evidence_span_id] = span

        requested = set(payload.evidence_span_refs)
        for fact in payload.candidate_facts:
            requested.update(fact.evidence_span_refs)

        for evidence_ref in requested:
            if evidence_ref not in spans_by_id:
                raise InterpretationValidationError("model referenced an unbound EvidenceSpan")

        return tuple(sorted(requested, key=str))

    def _persist_invalid(
        self,
        artifact: SourceArtifact,
        profile: InterpretationProfile,
        response: ModelResponse,
        *,
        interpretation_id: UUID | None = None,
    ) -> InterpretationRecord:
        record = InterpretationRecord(
            interpretation_id=interpretation_id or uuid4(),
            artifact_refs=(artifact.artifact_id,),
            interpretation_profile_ref=profile.profile_ref,
            model_provider=response.provenance.provider,
            model_identity=response.provenance.model_identity,
            model_version=response.provenance.model_version,
            schema_ref=profile.schema_ref,
            structured_output={},
            evidence_span_refs=(),
            response_digest=_sha256_text(response.raw_output),
            status=InterpretationStatus.INVALID,
        )
        return self._append(record)

    def _persist_failure(
        self,
        artifact: SourceArtifact,
        profile: InterpretationProfile,
        failure_code: str,
        *,
        interpretation_id: UUID | None = None,
    ) -> InterpretationRecord:
        provenance = self.gateway.provenance
        record = InterpretationRecord(
            interpretation_id=interpretation_id or uuid4(),
            artifact_refs=(artifact.artifact_id,),
            interpretation_profile_ref=profile.profile_ref,
            model_provider=provenance.provider,
            model_identity=provenance.model_identity,
            model_version=provenance.model_version,
            schema_ref=profile.schema_ref,
            structured_output={},
            evidence_span_refs=(),
            response_digest=_sha256_text(failure_code),
            status=InterpretationStatus.FAILED,
        )
        return self._append(record)

    def _append(self, record: InterpretationRecord) -> InterpretationRecord:
        if self.repository is not None:
            return self.repository.append_interpretation(record)
        return record


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "CandidateFactDraft",
    "CandidateInterpretationPayload",
    "InterpretationClient",
    "InterpretationProfile",
    "InterpretationValidationError",
    "ModelGateway",
    "ModelGatewayError",
    "ModelOutput",
    "ModelProvenance",
    "ModelProviderUnavailable",
    "ModelRequest",
    "ModelResponse",
    "ModelTimeoutError",
    "StaticModelGateway",
]
