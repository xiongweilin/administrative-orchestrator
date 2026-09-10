from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..authority import AuthorityRepository
from ..conversation import (
    ConversationMessage,
    ConversationMessageResult,
    ConversationRef,
    ConversationService,
    ResolvedProviderIdentity,
)
from ..intake.artifacts import ArtifactStore
from ..intake.interpretation import (
    InterpretationClient,
    InterpretationProfile,
)
from ..intake.models import (
    CandidateAdministrativeRequest,
    EvidenceSpan,
    IntakeReceipt,
    IntakeVerificationStatus,
    InterpretationRecord,
    InterpretationStatus,
    SourceArtifact,
)
from ..intake.repository import (
    IntakeReceiptConflict,
    IntakeRepository,
)
from ..intake.service import CandidateProjectionService
from ..persistence import SqlStore, utcnow

FEISHU_SOURCE_SYSTEM = "feishu"
FEISHU_INTAKE_EVENT_TYPE = "intake.feishu.received"
_FEISHU_NAMESPACE = uuid5(NAMESPACE_URL, "https://administrative-orchestrator/providers/feishu")


class FeishuVerificationError(ValueError):
    """The provider event cannot be admitted as an authenticated delivery."""


class FeishuCanonicalFetchError(RuntimeError):
    """The provider's canonical message could not be read safely."""


class FeishuProcessingError(RuntimeError):
    """The durable Feishu job cannot advance without fabricating intake state."""


class FeishuChallenge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge: str = Field(min_length=1, max_length=2000)


class _FeishuEventHeader(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    event_id: str = Field(alias="event_id", min_length=1, max_length=512)
    event_type: str = Field(default="", alias="event_type", max_length=255)
    tenant_key: str = Field(alias="tenant_key", min_length=1, max_length=512)
    token: str | None = Field(default=None, max_length=2000)
    create_time: str | None = Field(default=None, alias="create_time", max_length=64)


class _FeishuSenderId(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    open_id: str | None = Field(default=None, alias="open_id", max_length=1000)


class _FeishuSender(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sender_id: _FeishuSenderId


class _FeishuMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    message_id: str = Field(alias="message_id", min_length=1, max_length=512)
    root_id: str | None = Field(default=None, alias="root_id", max_length=512)
    parent_id: str | None = Field(default=None, alias="parent_id", max_length=512)
    create_time: str | None = Field(default=None, alias="create_time", max_length=64)
    message_type: str = Field(default="text", alias="message_type", max_length=64)


class _FeishuEventBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sender: _FeishuSender
    message: _FeishuMessage


class _FeishuEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    header: _FeishuEventHeader
    event: _FeishuEventBody


class FeishuProviderEvent(BaseModel):
    """Transient, body-free metadata needed by the asynchronous intake job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(default=FEISHU_SOURCE_SYSTEM, min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=512)
    tenant_ref: str = Field(min_length=1, max_length=512)
    message_id: str = Field(min_length=1, max_length=512)
    thread_ref: str = Field(min_length=1, max_length=512)
    sender_external_subject: str = Field(min_length=1, max_length=1000)
    event_type: str = Field(default="im.message.receive_v1", max_length=255)
    occurred_at: datetime
    sequence: int = Field(ge=1)
    delivery_digest: str = Field(min_length=64, max_length=128)

    @model_validator(mode="after")
    def validate_identity(self) -> FeishuProviderEvent:
        for name in (
            "provider",
            "event_id",
            "tenant_ref",
            "message_id",
            "thread_ref",
            "sender_external_subject",
            "delivery_digest",
        ):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be blank")
            object.__setattr__(self, name, value)
        if self.provider != FEISHU_SOURCE_SYSTEM:
            raise ValueError("Feishu provider event has an unexpected provider")
        return self

    def job_payload(self) -> dict[str, Any]:
        """Return metadata only; the untrusted message body is never enqueued."""
        return self.model_dump(mode="json")


class FeishuCanonicalMessage(BaseModel):
    """Canonical provider representation returned after durable acceptance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(min_length=1, max_length=512)
    tenant_ref: str = Field(min_length=1, max_length=512)
    thread_ref: str = Field(min_length=1, max_length=512)
    sender_external_subject: str = Field(min_length=1, max_length=1000)
    displayed_sender: str | None = Field(default=None, max_length=1000)
    participant_external_subjects: tuple[str, ...] = ()
    occurred_at: datetime
    sequence: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=2_000_000)
    mime_type: str = Field(default="text/plain; charset=utf-8", max_length=255)
    source_revision: str = Field(default="provider-v1", min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_identity(self) -> FeishuCanonicalMessage:
        for name in (
            "message_id",
            "tenant_ref",
            "thread_ref",
            "sender_external_subject",
            "content",
            "mime_type",
            "source_revision",
        ):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be blank")
            object.__setattr__(self, name, value)
        participants = tuple(
            dict.fromkeys(
                value.strip()
                for value in self.participant_external_subjects
                if value.strip()
            )
        )
        if self.sender_external_subject not in participants:
            participants = (self.sender_external_subject, *participants)
        object.__setattr__(self, "participant_external_subjects", participants)
        return self


class FeishuCanonicalFetcher(Protocol):
    """Read one provider message after an authenticated event is accepted."""

    def fetch(self, event: FeishuProviderEvent) -> FeishuCanonicalMessage:
        """Return the provider's canonical message or fail closed."""


class FeishuAccessTokenProvider(Protocol):
    def __call__(self) -> str:
        """Return a current provider access token without exposing it to logs."""


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _epoch_millis(value: str | None, *, field_name: str) -> int:
    if value is None or not value.isascii() or not value.isdigit():
        raise FeishuVerificationError(f"invalid Feishu {field_name}")
    parsed = int(value)
    if parsed < 1:
        raise FeishuVerificationError(f"invalid Feishu {field_name}")
    if len(value) <= 10:
        parsed *= 1000
    return parsed


def _datetime_from_epoch_millis(value: int) -> datetime:
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise FeishuVerificationError("invalid Feishu event time") from exc


class FeishuEventVerifier:
    """Verify Feishu callback tokens and optional signed callback headers."""

    def __init__(
        self,
        verification_token: str,
        *,
        encrypt_key: str | None = None,
        max_age_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not verification_token.strip():
            raise ValueError("verification_token must not be blank")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self._verification_token = verification_token
        self._encrypt_key = encrypt_key
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    def verify(self, body: bytes, headers: Mapping[str, str]) -> FeishuChallenge | FeishuProviderEvent:
        if not isinstance(body, bytes) or not body:
            raise FeishuVerificationError("Feishu callback body is empty")
        self._verify_optional_signature(body, headers)
        try:
            decoded = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise FeishuVerificationError("Feishu callback body is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise FeishuVerificationError("Feishu callback body must be an object")

        if decoded.get("type") == "url_verification":
            token = decoded.get("token")
            challenge = decoded.get("challenge")
            if not isinstance(token, str) or not self._same_secret(token):
                raise FeishuVerificationError("Feishu callback token is invalid")
            if not isinstance(challenge, str) or not challenge.strip():
                raise FeishuVerificationError("Feishu verification challenge is invalid")
            return FeishuChallenge(challenge=challenge)

        try:
            envelope = _FeishuEnvelope.model_validate(decoded)
        except ValidationError as exc:
            raise FeishuVerificationError("Feishu callback envelope is invalid") from exc
        if envelope.header.token is None or not self._same_secret(envelope.header.token):
            raise FeishuVerificationError("Feishu callback token is invalid")
        sender = envelope.event.sender.sender_id.open_id
        if sender is None or not sender.strip():
            raise FeishuVerificationError("Feishu callback has no provider actor identity")
        message = envelope.event.message
        created_at = _epoch_millis(
            message.create_time or envelope.header.create_time,
            field_name="create_time",
        )
        digest = hashlib.sha256(body).hexdigest()
        return FeishuProviderEvent(
            event_id=envelope.header.event_id,
            tenant_ref=envelope.header.tenant_key,
            message_id=message.message_id,
            thread_ref=message.root_id or message.parent_id or message.message_id,
            sender_external_subject=sender,
            event_type=envelope.header.event_type or "im.message.receive_v1",
            occurred_at=_datetime_from_epoch_millis(created_at),
            sequence=created_at,
            delivery_digest=digest,
        )

    def _same_secret(self, value: str) -> bool:
        return hmac.compare_digest(value, self._verification_token)

    def _verify_optional_signature(self, body: bytes, headers: Mapping[str, str]) -> None:
        if self._encrypt_key is None:
            return
        timestamp = _header(headers, "X-Lark-Request-Timestamp")
        nonce = _header(headers, "X-Lark-Request-Nonce")
        signature = _header(headers, "X-Lark-Signature")
        if not timestamp or not nonce or not signature:
            raise FeishuVerificationError("Feishu callback signature headers are incomplete")
        if not timestamp.isascii() or not timestamp.isdigit():
            raise FeishuVerificationError("Feishu callback timestamp is invalid")
        if abs(int(self._clock()) - int(timestamp)) > self._max_age_seconds:
            raise FeishuVerificationError("Feishu callback timestamp is outside the accepted window")
        expected = hashlib.sha256(
            (timestamp + nonce + self._encrypt_key).encode("utf-8") + body
        ).hexdigest()
        if not _constant_time_equal(expected, signature):
            raise FeishuVerificationError("Feishu callback signature is invalid")


def _constant_time_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for left_byte, right_byte in zip(left.encode(), right.lower().encode(), strict=True):
        result |= left_byte ^ right_byte
    return result == 0


class HttpFeishuCanonicalFetcher:
    """Minimal canonical Feishu message reader for the asynchronous worker."""

    def __init__(
        self,
        base_url: str,
        access_token: FeishuAccessTokenProvider,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    def fetch(self, event: FeishuProviderEvent) -> FeishuCanonicalMessage:
        token = self._access_token()
        if not isinstance(token, str) or not token.strip():
            raise FeishuCanonicalFetchError("Feishu access token is unavailable")
        try:
            response = self._client.get(
                f"{self._base_url}/open-apis/im/v1/messages/{quote(event.message_id, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
                params={"user_id_type": "open_id"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FeishuCanonicalFetchError("Feishu canonical message fetch failed") from exc
        try:
            message = _message_payload(payload)
            return _canonical_message_from_payload(message, event)
        except (TypeError, ValueError, KeyError, ValidationError) as exc:
            raise FeishuCanonicalFetchError("Feishu canonical message response is invalid") from exc

    def close(self) -> None:
        self._client.close()


def _message_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("provider response must be an object")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TypeError("provider response has no data object")
    message = data.get("message")
    if isinstance(message, dict):
        return message
    items = data.get("items")
    if isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict):
        return items[0]
    raise ValueError("provider response has no unique message")


def _canonical_message_from_payload(
    message: dict[str, Any],
    event: FeishuProviderEvent,
) -> FeishuCanonicalMessage:
    message_id = _text(message.get("message_id"), "message_id")
    tenant_ref = _text(message.get("tenant_key") or message.get("tenant_ref") or event.tenant_ref, "tenant_ref")
    sender_payload = message.get("sender_id") or message.get("sender") or {}
    if not isinstance(sender_payload, dict):
        raise TypeError("sender payload must be an object")
    sender = _text(sender_payload.get("open_id"), "sender open_id")
    body = message.get("body")
    body_content = body.get("content") if isinstance(body, dict) else message.get("content")
    content = _text_content(body_content, message.get("msg_type") or message.get("message_type"))
    created_at = _epoch_millis(
        _optional_text(message.get("create_time") or message.get("created_at"))
        or str(event.sequence),
        field_name="message create_time",
    )
    participants = [sender]
    mentions = message.get("mentions")
    if isinstance(mentions, list):
        for mention in mentions:
            if isinstance(mention, dict):
                mention_id = mention.get("id")
                if isinstance(mention_id, dict):
                    mention_id = mention_id.get("open_id")
                if isinstance(mention_id, str):
                    participants.append(mention_id)
    thread_ref = _text(
        message.get("root_id") or message.get("parent_id") or event.thread_ref,
        "thread_ref",
    )
    return FeishuCanonicalMessage(
        message_id=message_id,
        tenant_ref=tenant_ref,
        thread_ref=thread_ref,
        sender_external_subject=sender,
        displayed_sender=(
            message.get("sender_name")
            if isinstance(message.get("sender_name"), str)
            else None
        ),
        participant_external_subjects=tuple(participants),
        occurred_at=_datetime_from_epoch_millis(created_at),
        sequence=created_at,
        content=content,
        mime_type="text/plain; charset=utf-8",
        source_revision=_optional_text(message.get("update_time")) or "provider-v1",
    )


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"provider {field_name} is blank")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text_content(value: Any, message_type: Any) -> str:
    if message_type not in (None, "text"):
        raise ValueError("only Feishu text messages are supported by the reference slice")
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return _text(value, "message content")
        if isinstance(decoded, dict) and isinstance(decoded.get("text"), str):
            return _text(decoded["text"], "message text")
        return _text(value, "message content")
    if isinstance(value, dict):
        return _text(value.get("text"), "message text")
    raise ValueError("provider message content is invalid")


@dataclass(frozen=True, slots=True)
class FeishuAcceptance:
    receipt: IntakeReceipt
    outbox_event_id: UUID
    created: bool


class FeishuWebhookBoundary:
    """Fast durable ingress boundary; it never calls canonical fetch or a model."""

    def __init__(self, repository: IntakeRepository, verifier: FeishuEventVerifier) -> None:
        self.repository = repository
        self.verifier = verifier

    def accept(
        self,
        body: bytes,
        headers: Mapping[str, str],
    ) -> FeishuChallenge | FeishuAcceptance:
        verified = self.verifier.verify(body, headers)
        if isinstance(verified, FeishuChallenge):
            return verified
        receipt = IntakeReceipt(
            source_system=FEISHU_SOURCE_SYSTEM,
            tenant_ref=verified.tenant_ref,
            source_event_id=verified.event_id,
            verification_status=IntakeVerificationStatus.VERIFIED,
            delivery_digest=verified.delivery_digest,
        )
        try:
            accepted = self.repository.persist_verified_receipt_and_enqueue(
                receipt,
                event_type=FEISHU_INTAKE_EVENT_TYPE,
                aggregate_id=str(receipt.receipt_id),
                payload=verified.job_payload(),
            )
        except IntakeReceiptConflict:
            raise
        return FeishuAcceptance(
            receipt=accepted.receipt,
            outbox_event_id=accepted.outbox_event_id,
            created=accepted.created,
        )


@dataclass(frozen=True, slots=True)
class FeishuProcessResult:
    receipt: IntakeReceipt
    artifact: SourceArtifact
    evidence_span: EvidenceSpan
    identity: ResolvedProviderIdentity
    interpretation: InterpretationRecord
    candidate: CandidateAdministrativeRequest | None
    conversation: ConversationMessageResult | None


class FeishuInboxPipeline:
    """Asynchronous Feishu source-to-candidate pipeline.

    The pipeline is intentionally separate from ``FeishuWebhookBoundary``.
    It may perform network and model work only after a verified receipt and
    outbox job already exist.
    """

    def __init__(
        self,
        store: SqlStore,
        *,
        repository: IntakeRepository,
        artifact_store: ArtifactStore,
        canonical_fetcher: FeishuCanonicalFetcher,
        interpretation_client: InterpretationClient,
        interpretation_profile: InterpretationProfile,
        conversation_service: ConversationService | None = None,
        projection_service: CandidateProjectionService | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.artifact_store = artifact_store
        self.canonical_fetcher = canonical_fetcher
        self.interpretation_client = interpretation_client
        self.interpretation_profile = interpretation_profile
        self.conversation_service = conversation_service or ConversationService(
            store,
            authority=AuthorityRepository(store),
            intake=repository,
        )
        self.projection_service = projection_service or CandidateProjectionService()

    def process_event(self, payload: FeishuProviderEvent | Mapping[str, Any]) -> FeishuProcessResult:
        event = (
            payload
            if isinstance(payload, FeishuProviderEvent)
            else FeishuProviderEvent.model_validate(payload)
        )
        receipt = self.repository.get_intake_receipt(
            source_system=FEISHU_SOURCE_SYSTEM,
            tenant_ref=event.tenant_ref,
            source_event_id=event.event_id,
        )
        if receipt is None:
            raise FeishuProcessingError("Feishu job has no durable intake receipt")
        if receipt.verification_status is not IntakeVerificationStatus.VERIFIED:
            raise FeishuProcessingError("Feishu job receipt is not verified")

        canonical = self.canonical_fetcher.fetch(event)
        self._validate_canonical_identity(event, canonical)
        artifact, span = self._persist_source(event, canonical)
        conversation_ref = ConversationRef(
            provider=FEISHU_SOURCE_SYSTEM,
            tenant_ref=canonical.tenant_ref,
            thread_ref=canonical.thread_ref,
        )
        identity = self.conversation_service.resolve_provider_identity(
            conversation_ref,
            external_subject=canonical.sender_external_subject,
            displayed_sender=canonical.displayed_sender,
            provider=FEISHU_SOURCE_SYSTEM,
            tenant_ref=canonical.tenant_ref,
            at=canonical.occurred_at,
        )
        interpretation = self._interpret(artifact, canonical.content, span)
        if interpretation.status is not InterpretationStatus.SUCCEEDED:
            return FeishuProcessResult(
                receipt=self.repository.get_intake_receipt(
                    source_system=FEISHU_SOURCE_SYSTEM,
                    tenant_ref=event.tenant_ref,
                    source_event_id=event.event_id,
                )
                or receipt,
                artifact=artifact,
                evidence_span=span,
                identity=identity,
                interpretation=interpretation,
                candidate=None,
                conversation=None,
            )

        projection = self.projection_service.project(
            interpretation,
            conversation_ref=conversation_ref.canonical_ref,
            candidate_requester=f"feishu:{canonical.sender_external_subject}",
            source_refs=(artifact.artifact_id,),
        )
        facts = tuple(
            fact.model_copy(
                update={
                    "candidate_fact_id": uuid5(
                        _FEISHU_NAMESPACE,
                        f"fact:{interpretation.interpretation_id}:{index}:{fact.fact_key}",
                    )
                }
            )
            for index, fact in enumerate(projection.facts)
        )
        for fact in facts:
            self.repository.append_candidate_fact(fact)
        candidate = projection.candidate.model_copy(
            update={
                "candidate_id": uuid5(
                    _FEISHU_NAMESPACE,
                    f"candidate:{interpretation.interpretation_id}",
                ),
                "candidate_fact_refs": tuple(fact.candidate_fact_id for fact in facts),
                "created_at": canonical.occurred_at,
            }
        )
        candidate = self.repository.append_candidate_request(candidate)
        message = ConversationMessage(
            message_id=uuid5(
                _FEISHU_NAMESPACE,
                f"message:{canonical.tenant_ref}:{canonical.message_id}",
            ),
            conversation_ref=conversation_ref,
            provider_message_id=canonical.message_id,
            source_event_id=event.event_id,
            sender_external_subject=canonical.sender_external_subject,
            displayed_sender=canonical.displayed_sender,
            participant_external_subjects=canonical.participant_external_subjects,
            sequence=canonical.sequence,
            occurred_at=canonical.occurred_at,
            provider_tenant_ref=canonical.tenant_ref,
            content_digest=artifact.content_digest,
            source_refs=(artifact.artifact_id,),
            interpretation_refs=(interpretation.interpretation_id,),
            candidate_fact_refs=tuple(fact.candidate_fact_id for fact in facts),
        )
        conversation = self.conversation_service.accept_message(
            message,
            provider=FEISHU_SOURCE_SYSTEM,
            tenant_ref=canonical.tenant_ref,
            candidate=candidate,
        )
        return FeishuProcessResult(
            receipt=self.repository.get_intake_receipt(
                source_system=FEISHU_SOURCE_SYSTEM,
                tenant_ref=event.tenant_ref,
                source_event_id=event.event_id,
            )
            or receipt,
            artifact=artifact,
            evidence_span=span,
            identity=identity,
            interpretation=interpretation,
            candidate=candidate,
            conversation=conversation,
        )

    def _persist_source(
        self,
        event: FeishuProviderEvent,
        canonical: FeishuCanonicalMessage,
    ) -> tuple[SourceArtifact, EvidenceSpan]:
        content = canonical.content.encode("utf-8")
        stored = self.artifact_store.put(content)
        artifact_id = uuid5(
            _FEISHU_NAMESPACE,
            f"artifact:{canonical.tenant_ref}:{canonical.message_id}:{canonical.source_revision}",
        )
        artifact = self.repository.append_source_artifact(
            SourceArtifact(
                artifact_id=artifact_id,
                source_kind="inbox_message",
                source_system=FEISHU_SOURCE_SYSTEM,
                tenant_ref=canonical.tenant_ref,
                canonical_source_ref=f"message:{canonical.message_id}",
                source_revision=canonical.source_revision,
                source_event_ref=event.event_id,
                actor_external_identity_ref=canonical.sender_external_subject,
                captured_at=utcnow(),
                source_timestamp=canonical.occurred_at,
                content_digest=stored.content_digest,
                storage_ref=stored.storage_ref,
                mime_type=canonical.mime_type,
                size=stored.size,
                authenticity_class="provider_verified_canonical_fetch",
                retention_class="inbox_business_record",
            )
        )
        receipt = self.repository.get_intake_receipt(
            source_system=FEISHU_SOURCE_SYSTEM,
            tenant_ref=event.tenant_ref,
            source_event_id=event.event_id,
        )
        if receipt is None:
            raise FeishuProcessingError("Feishu receipt disappeared during source persistence")
        self.repository.attach_artifact_to_receipt(receipt.receipt_id, artifact.artifact_id)
        span = self.repository.append_evidence_span(
            EvidenceSpan(
                evidence_span_id=uuid5(_FEISHU_NAMESPACE, f"span:{artifact.artifact_id}:body"),
                artifact_ref=artifact.artifact_id,
                representation_digest=artifact.content_digest,
                locator_kind="message_body",
                locator={
                    "provider_message_id": canonical.message_id,
                    "encoding": "utf-8",
                    "byte_start": 0,
                    "byte_end": len(canonical.content.encode("utf-8")),
                },
                extractor_ref="feishu-canonical-message-v1",
            )
        )
        return artifact, span

    def _interpret(
        self,
        artifact: SourceArtifact,
        content: str,
        span: EvidenceSpan,
    ) -> InterpretationRecord:
        existing = [
            item
            for item in self.repository.list_interpretations(artifact.artifact_id)
            if item.interpretation_profile_ref == self.interpretation_profile.profile_ref
        ]
        if existing:
            return sorted(existing, key=lambda item: item.interpreted_at)[-1]
        interpretation_id = uuid5(
            _FEISHU_NAMESPACE,
            f"interpretation:{artifact.artifact_id}:{self.interpretation_profile.profile_ref}",
        )
        interpretation = self.interpretation_client.interpret(
            artifact,
            content,
            self.interpretation_profile,
            (span,),
            interpretation_id=interpretation_id,
        )
        if self.interpretation_client.repository is None:
            interpretation = self.repository.append_interpretation(interpretation)
        return interpretation

    @staticmethod
    def _validate_canonical_identity(
        event: FeishuProviderEvent,
        canonical: FeishuCanonicalMessage,
    ) -> None:
        if canonical.message_id != event.message_id:
            raise FeishuProcessingError("canonical Feishu message identity does not match the event")
        if canonical.tenant_ref != event.tenant_ref:
            raise FeishuProcessingError("canonical Feishu tenant does not match the event")
        if canonical.sender_external_subject != event.sender_external_subject:
            raise FeishuProcessingError("canonical Feishu sender does not match the event")
        if event.thread_ref != event.message_id and canonical.thread_ref != event.thread_ref:
            raise FeishuProcessingError("canonical Feishu thread does not match the event")


__all__ = [
    "FEISHU_INTAKE_EVENT_TYPE",
    "FEISHU_SOURCE_SYSTEM",
    "FeishuAcceptance",
    "FeishuCanonicalFetchError",
    "FeishuCanonicalFetcher",
    "FeishuCanonicalMessage",
    "FeishuChallenge",
    "FeishuEventVerifier",
    "FeishuInboxPipeline",
    "FeishuProcessingError",
    "FeishuProcessResult",
    "FeishuProviderEvent",
    "FeishuVerificationError",
    "HttpFeishuCanonicalFetcher",
    "FeishuWebhookBoundary",
]
