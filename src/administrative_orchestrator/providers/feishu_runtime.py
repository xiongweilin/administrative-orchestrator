from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..intake.artifacts import FilesystemArtifactStore
from ..intake.interpretation import (
    InterpretationClient,
    InterpretationProfile,
    ModelGatewayError,
    ModelProvenance,
    ModelProviderUnavailable,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
)
from ..intake.repository import IntakeRepository
from ..persistence import SqlStore
from .feishu import (
    FeishuEventVerifier,
    FeishuInboxPipeline,
    FeishuWebhookBoundary,
    HttpFeishuCanonicalFetcher,
)


class HttpJsonModelGateway:
    """Small transport adapter for a configured candidate-only model gateway.

    The endpoint contract is intentionally narrow: it receives the artifact
    reference, versioned interpretation profile, and source text; it returns
    either a JSON object containing ``raw_output`` or the candidate JSON
    object itself. The gateway never receives authority or execution APIs.
    """

    def __init__(
        self,
        endpoint: str,
        provenance: ModelProvenance,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not endpoint.strip():
            raise ValueError("model gateway endpoint must not be blank")
        self.endpoint = endpoint.rstrip("/")
        self._provenance = provenance
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._client = httpx.Client(timeout=httpx.Timeout(30.0), transport=transport)

    @property
    def provenance(self) -> ModelProvenance:
        return self._provenance

    def complete(self, request: ModelRequest, *, timeout_seconds: float) -> ModelResponse:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "artifact_ref": str(request.artifact_ref),
            "profile": request.profile.model_dump(mode="json"),
            "source_text": request.source_text,
        }
        try:
            response = self._client.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=httpx.Timeout(timeout_seconds),
            )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("model gateway timed out") from exc
        except httpx.RequestError as exc:
            raise ModelProviderUnavailable("model gateway is unavailable") from exc

        if response.status_code in {408, 504}:
            raise ModelTimeoutError("model gateway timed out")
        if response.status_code >= 400:
            raise ModelProviderUnavailable("model gateway rejected the request")
        try:
            decoded = response.json()
        except ValueError:
            raw_output = response.text
        else:
            raw_output = _raw_output(decoded)
        if not raw_output.strip():
            raise ModelGatewayError("model gateway returned an empty response")
        return ModelResponse(raw_output=raw_output, provenance=self.provenance)

    def close(self) -> None:
        self._client.close()


@dataclass(slots=True)
class FeishuRuntime:
    """Configured provider runtime shared by API ingress and the worker."""

    boundary: FeishuWebhookBoundary | None
    pipeline: FeishuInboxPipeline | None
    _closables: tuple[object, ...] = ()

    def process_event(self, payload: dict[str, Any]) -> object:
        if self.pipeline is None:
            raise RuntimeError("Feishu processing runtime is not configured")
        return self.pipeline.process_event(payload)

    def close(self) -> None:
        for closable in reversed(self._closables):
            close = getattr(closable, "close", None)
            if close is not None:
                close()


def build_feishu_webhook_boundary(
    store: SqlStore,
    settings: Settings,
) -> FeishuWebhookBoundary | None:
    token = _secret(settings.feishu_verification_token)
    if not token:
        return None
    encrypt_key = _secret(settings.feishu_encrypt_key)
    return FeishuWebhookBoundary(
        IntakeRepository(store),
        FeishuEventVerifier(token, encrypt_key=encrypt_key or None),
    )


def build_feishu_runtime(store: SqlStore, settings: Settings) -> FeishuRuntime | None:
    boundary = build_feishu_webhook_boundary(store, settings)
    access_token = _secret(settings.feishu_access_token)
    model_url = settings.intake_model_url.strip()
    if not settings.feishu_base_url.strip() or not access_token or not model_url:
        return FeishuRuntime(boundary=boundary, pipeline=None)

    repository = IntakeRepository(store)
    model_gateway = HttpJsonModelGateway(
        model_url,
        ModelProvenance(
            provider=settings.intake_model_provider,
            model_identity=settings.intake_model_identity,
            model_version=settings.intake_model_version,
        ),
        api_key=_secret(settings.intake_model_api_key) or None,
    )
    fetcher = HttpFeishuCanonicalFetcher(
        settings.feishu_base_url,
        lambda: access_token,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    pipeline = FeishuInboxPipeline(
        store,
        repository=repository,
        artifact_store=FilesystemArtifactStore(Path(settings.feishu_artifact_root)),
        canonical_fetcher=fetcher,
        interpretation_client=InterpretationClient(
            model_gateway,
            repository,
            timeout_seconds=settings.provider_timeout_seconds,
        ),
        interpretation_profile=InterpretationProfile(
            profile_ref=settings.intake_model_profile_ref,
            schema_ref=settings.intake_model_schema_ref,
            instruction=settings.intake_model_instruction,
        ),
    )
    return FeishuRuntime(
        boundary=boundary,
        pipeline=pipeline,
        _closables=(fetcher, model_gateway),
    )


def _secret(value: Any) -> str:
    if value is None:
        return ""
    get_secret_value = getattr(value, "get_secret_value", None)
    if get_secret_value is not None:
        value = get_secret_value()
    return value.strip() if isinstance(value, str) else ""


def _raw_output(decoded: Any) -> str:
    if isinstance(decoded, dict):
        raw = decoded.get("raw_output")
        if isinstance(raw, str):
            return raw
        output = decoded.get("output")
        if isinstance(output, str):
            return output
    if isinstance(decoded, (dict, list)):
        return json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))
    if isinstance(decoded, str):
        return decoded
    raise ModelGatewayError("model gateway response is not JSON or text")


__all__ = [
    "FeishuRuntime",
    "HttpJsonModelGateway",
    "build_feishu_runtime",
    "build_feishu_webhook_boundary",
]
