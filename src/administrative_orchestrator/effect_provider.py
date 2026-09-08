from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from .domain import EffectRecord, UtcModel, utcnow


class ProviderExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ProviderExecutionResult(UtcModel):
    status: ProviderExecutionStatus
    provider_ref: str | None = None
    error: str | None = None
    retryable: bool = False


class RealityObservation(UtcModel):
    found: bool
    target_system: str
    operation: str
    subject_ref: str
    provider_ref: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    digest: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)


class EffectProvider(Protocol):
    def execute(self, effect: EffectRecord, payload: dict[str, Any]) -> ProviderExecutionResult: ...

    def observe(self, effect: EffectRecord) -> RealityObservation: ...


class HttpEffectProvider:
    """Typed HTTP boundary to a distinct authoritative sandbox/service plane."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def execute(self, effect: EffectRecord, payload: dict[str, Any]) -> ProviderExecutionResult:
        try:
            response = httpx.put(
                f"{self.base_url}/v1/effects/{effect.effect_id}",
                json={
                    "target_system": effect.target_system,
                    "operation": effect.operation,
                    "subject_ref": effect.subject_ref,
                    "payload": payload,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.OUTCOME_UNKNOWN,
                error=str(exc),
                retryable=False,
            )
        except httpx.HTTPStatusError as exc:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.FAILED,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
                retryable=500 <= exc.response.status_code < 600,
            )

        data = response.json()
        return ProviderExecutionResult(
            status=ProviderExecutionStatus(data.get("status", "succeeded")),
            provider_ref=data.get("provider_ref"),
            error=data.get("error"),
            retryable=bool(data.get("retryable", False)),
        )

    def observe(self, effect: EffectRecord) -> RealityObservation:
        try:
            response = httpx.get(
                f"{self.base_url}/v1/effects/{effect.effect_id}",
                timeout=self.timeout_seconds,
            )
            if response.status_code == 404:
                return RealityObservation(
                    found=False,
                    target_system=effect.target_system,
                    operation=effect.operation,
                    subject_ref=effect.subject_ref,
                )
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
            return RealityObservation(
                found=False,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
            )
        return RealityObservation.model_validate(response.json())
