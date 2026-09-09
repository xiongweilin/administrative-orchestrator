from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import httpx

EXPECTED_RECOVERY_COMMAND_SCHEMA = "bounded-domain-effect-recovery-v1"
EXPECTED_RESOLUTION_SCHEMA = "bounded-domain-effect-resolution-v1"

KernelResolutionStatus = Literal[
    "authorization-rejected",
    "execution-failed",
    "execution-unknown",
    "verified-fail",
    "completed",
    "recovery-pending",
    "recovery-unavailable",
    "manual-resolution-required",
    "recovered-failed",
    "recovered-verified-fail",
    "recovered-completed",
]


class KernelRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KernelExecutionResolution:
    execution_ref: str
    original_status: str
    current_status: KernelResolutionStatus
    work_ref: str
    processed_at: datetime
    run_ref: str | None = None
    request_ref: str | None = None
    recovery_observation_ref: str | None = None
    recovery_disposition_ref: str | None = None
    recovery_application_ref: str | None = None
    outcome_ref: str | None = None
    evidence_ref: str | None = None
    responsibility_ref: str | None = None
    reason: str = ""


class KernelRecoveryClient(Protocol):
    def recover(
        self,
        execution_ref: str,
        *,
        expected_work_ref: str | None = None,
    ) -> KernelExecutionResolution: ...

    def inspect(
        self,
        execution_ref: str,
        *,
        expected_work_ref: str | None = None,
    ) -> KernelExecutionResolution | None: ...


class HttpKernelRecoveryClient:
    """Consume only Kernel's non-authoritative bounded recovery projection."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def recover(
        self,
        execution_ref: str,
        *,
        expected_work_ref: str | None = None,
    ) -> KernelExecutionResolution:
        if not execution_ref.strip():
            raise KernelRecoveryError("Kernel recovery requires execution_ref")
        try:
            response = httpx.post(
                f"{self.base_url}/v1/domain-effects/recoveries",
                json={
                    "schema": EXPECTED_RECOVERY_COMMAND_SCHEMA,
                    "execution_ref": execution_ref,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelRecoveryError(f"agent-kernel recovery request failed: {exc}") from exc
        return self._resolution(
            raw,
            expected_execution_ref=execution_ref,
            expected_work_ref=expected_work_ref,
        )

    def inspect(
        self,
        execution_ref: str,
        *,
        expected_work_ref: str | None = None,
    ) -> KernelExecutionResolution | None:
        if not execution_ref.strip():
            raise KernelRecoveryError("Kernel resolution inspection requires execution_ref")
        try:
            response = httpx.get(
                f"{self.base_url}/v1/domain-effects/executions/{execution_ref}/resolution",
                timeout=self.timeout_seconds,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelRecoveryError(f"agent-kernel resolution inspection failed: {exc}") from exc
        return self._resolution(
            raw,
            expected_execution_ref=execution_ref,
            expected_work_ref=expected_work_ref,
        )

    @staticmethod
    def _resolution(
        raw: object,
        *,
        expected_execution_ref: str,
        expected_work_ref: str | None,
    ) -> KernelExecutionResolution:
        if not isinstance(raw, dict):
            raise KernelRecoveryError("agent-kernel resolution must be a JSON object")
        if raw.get("schema") != EXPECTED_RESOLUTION_SCHEMA:
            raise KernelRecoveryError("agent-kernel returned incompatible resolution schema")
        if raw.get("authority_bearing") is not False:
            raise KernelRecoveryError("agent-kernel resolution must be explicitly non-authoritative")

        def required_ref(name: str) -> str:
            value = raw.get(name)
            if not isinstance(value, str) or not value:
                raise KernelRecoveryError(f"Kernel resolution lacks {name}")
            return value

        def optional_ref(name: str) -> str | None:
            value = raw.get(name)
            if value is None:
                return None
            if not isinstance(value, str) or not value:
                raise KernelRecoveryError(f"Kernel resolution has invalid {name}")
            return value

        execution_ref = required_ref("execution_ref")
        if execution_ref != expected_execution_ref:
            raise KernelRecoveryError("Kernel recovery execution identity rebound")
        work_ref = required_ref("work_ref")
        if expected_work_ref is not None and work_ref != expected_work_ref:
            raise KernelRecoveryError("Kernel recovery Work identity rebound")

        original_status = required_ref("original_status")
        status = raw.get("current_status")
        allowed = {
            "authorization-rejected",
            "execution-failed",
            "execution-unknown",
            "verified-fail",
            "completed",
            "recovery-pending",
            "recovery-unavailable",
            "manual-resolution-required",
            "recovered-failed",
            "recovered-verified-fail",
            "recovered-completed",
        }
        if status not in allowed:
            raise KernelRecoveryError("agent-kernel returned unknown recovery status")

        processed_raw = raw.get("processed_at")
        if not isinstance(processed_raw, str) or not processed_raw:
            raise KernelRecoveryError("Kernel resolution lacks processed_at")
        try:
            processed_at = datetime.fromisoformat(processed_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KernelRecoveryError("Kernel resolution processed_at is invalid") from exc

        refs = {
            "run_ref": optional_ref("run_ref"),
            "request_ref": optional_ref("request_ref"),
            "recovery_observation_ref": optional_ref("recovery_observation_ref"),
            "recovery_disposition_ref": optional_ref("recovery_disposition_ref"),
            "recovery_application_ref": optional_ref("recovery_application_ref"),
            "outcome_ref": optional_ref("outcome_ref"),
            "evidence_ref": optional_ref("evidence_ref"),
            "responsibility_ref": optional_ref("responsibility_ref"),
        }
        if status == "recovered-completed":
            required = (
                "run_ref",
                "request_ref",
                "recovery_observation_ref",
                "recovery_disposition_ref",
                "recovery_application_ref",
                "outcome_ref",
                "evidence_ref",
                "responsibility_ref",
            )
            missing = [name for name in required if not refs[name]]
            if missing:
                raise KernelRecoveryError(
                    "recovered-completed resolution lacks refs: " + ", ".join(missing)
                )

        reason = raw.get("reason")
        if not isinstance(reason, str):
            raise KernelRecoveryError("Kernel resolution reason must be a string")

        return KernelExecutionResolution(
            execution_ref=execution_ref,
            original_status=original_status,
            current_status=status,
            work_ref=work_ref,
            processed_at=processed_at,
            run_ref=refs["run_ref"],
            request_ref=refs["request_ref"],
            recovery_observation_ref=refs["recovery_observation_ref"],
            recovery_disposition_ref=refs["recovery_disposition_ref"],
            recovery_application_ref=refs["recovery_application_ref"],
            outcome_ref=refs["outcome_ref"],
            evidence_ref=refs["evidence_ref"],
            responsibility_ref=refs["responsibility_ref"],
            reason=reason,
        )


__all__ = [
    "EXPECTED_RECOVERY_COMMAND_SCHEMA",
    "EXPECTED_RESOLUTION_SCHEMA",
    "HttpKernelRecoveryClient",
    "KernelExecutionResolution",
    "KernelRecoveryClient",
    "KernelRecoveryError",
    "KernelResolutionStatus",
]
