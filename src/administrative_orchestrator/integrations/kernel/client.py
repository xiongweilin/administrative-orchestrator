from __future__ import annotations

from dataclasses import dataclass

import httpx

from .models import KernelShadowProjection

EXPECTED_COMMAND_SCHEMA = "domain-responsibility-proposal-v1"
EXPECTED_RECEIPT_SCHEMA = "domain-responsibility-proposal-receipt-v1"


class KernelSubmissionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KernelProposalReceipt:
    responsibility_ref: str
    admission_ref: str
    assessment_ref: str
    proposal_ref: str


class HttpKernelResponsibilityClient:
    """Submit a shadow proposal prefix without requesting Work or authority."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def submit(self, projection: KernelShadowProjection) -> KernelProposalReceipt:
        payload = {
            "schema": EXPECTED_COMMAND_SCHEMA,
            "responsibility": projection.responsibility_payload,
            "admission": projection.admission_payload,
            "assessment": projection.assessment_payload,
            "proposal": projection.work_proposal_payload,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/responsibilities/domain-proposals",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelSubmissionError(f"agent-kernel proposal submission failed: {exc}") from exc
        if not isinstance(raw, dict):
            raise KernelSubmissionError("agent-kernel proposal receipt must be a JSON object")
        if raw.get("schema") != EXPECTED_RECEIPT_SCHEMA:
            raise KernelSubmissionError("agent-kernel returned an incompatible proposal receipt schema")
        if raw.get("status") != "proposal-recorded":
            raise KernelSubmissionError("agent-kernel did not confirm proposal recording")
        if raw.get("authority_bearing") is not False:
            raise KernelSubmissionError("agent-kernel proposal receipt must be explicitly non-authoritative")

        expected = {
            "responsibility_ref": projection.responsibility_payload.get("id"),
            "admission_ref": projection.admission_payload.get("id"),
            "assessment_ref": projection.assessment_payload.get("id"),
            "proposal_ref": projection.work_proposal_payload.get("id"),
        }
        actual: dict[str, str] = {}
        for key, expected_value in expected.items():
            value = raw.get(key)
            if not isinstance(expected_value, str) or not expected_value:
                raise KernelSubmissionError(f"shadow projection lacks canonical {key}")
            if value != expected_value:
                raise KernelSubmissionError(
                    f"agent-kernel receipt {key} does not match submitted canonical identity"
                )
            actual[key] = value
        return KernelProposalReceipt(**actual)


__all__ = [
    "HttpKernelResponsibilityClient",
    "KernelProposalReceipt",
    "KernelSubmissionError",
]
