from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

import httpx

EXPECTED_EVIDENCE_VIEW_SCHEMA = "domain-effect-verification-evidence-view-v1"


class KernelEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KernelEvidenceView:
    evidence_ref: str
    action_ref: str
    work_ref: str
    run_ref: str
    objective_result: Literal["pass", "fail"]
    observed_postcondition: dict[str, Any]
    expected_postcondition: dict[str, Any]
    verification_request_ref: str
    verification_attempt_ref: str
    verifier_provider_id: str
    verifier_provider_execution_binding_ref: str
    captured_at: datetime


class KernelEvidenceClient(Protocol):
    def inspect(self, evidence_ref: str) -> KernelEvidenceView | None: ...


class HttpKernelEvidenceClient:
    """Read Kernel verification evidence without importing or minting Kernel authority."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def inspect(self, evidence_ref: str) -> KernelEvidenceView | None:
        try:
            response = httpx.get(
                f"{self.base_url}/v1/domain-effects/evidence/{evidence_ref}",
                timeout=self.timeout_seconds,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelEvidenceError(f"agent-kernel evidence inspection failed: {exc}") from exc
        if not isinstance(raw, dict):
            raise KernelEvidenceError("agent-kernel evidence view must be a JSON object")
        if raw.get("schema") != EXPECTED_EVIDENCE_VIEW_SCHEMA:
            raise KernelEvidenceError("agent-kernel returned incompatible evidence view schema")
        if raw.get("authority_bearing") is not False:
            raise KernelEvidenceError("agent-kernel evidence view must be explicitly non-authoritative")
        if raw.get("evidence_ref") != evidence_ref:
            raise KernelEvidenceError("agent-kernel evidence identity rebound")

        objective_result = raw.get("objective_result")
        if objective_result not in {"pass", "fail"}:
            raise KernelEvidenceError("agent-kernel evidence view lacks closed objective result")
        observed = raw.get("observed_postcondition")
        expected = raw.get("expected_postcondition")
        if not isinstance(observed, dict) or not isinstance(expected, dict):
            raise KernelEvidenceError("agent-kernel evidence view lacks postcondition objects")

        def required_string(name: str) -> str:
            value = raw.get(name)
            if not isinstance(value, str) or not value:
                raise KernelEvidenceError(f"agent-kernel evidence view lacks {name}")
            return value

        captured_raw = raw.get("captured_at")
        if not isinstance(captured_raw, str) or not captured_raw:
            raise KernelEvidenceError("agent-kernel evidence view lacks captured_at")
        try:
            captured_at = datetime.fromisoformat(captured_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KernelEvidenceError("agent-kernel evidence captured_at is invalid") from exc

        return KernelEvidenceView(
            evidence_ref=evidence_ref,
            action_ref=required_string("action_ref"),
            work_ref=required_string("work_ref"),
            run_ref=required_string("run_ref"),
            objective_result=objective_result,
            observed_postcondition=dict(observed),
            expected_postcondition=dict(expected),
            verification_request_ref=required_string("verification_request_ref"),
            verification_attempt_ref=required_string("verification_attempt_ref"),
            verifier_provider_id=required_string("verifier_provider_id"),
            verifier_provider_execution_binding_ref=required_string(
                "verifier_provider_execution_binding_ref"
            ),
            captured_at=captured_at,
        )


__all__ = [
    "EXPECTED_EVIDENCE_VIEW_SCHEMA",
    "HttpKernelEvidenceClient",
    "KernelEvidenceClient",
    "KernelEvidenceError",
    "KernelEvidenceView",
]
