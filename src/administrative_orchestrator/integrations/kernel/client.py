from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from .models import KernelProjectionStatus, KernelShadowProjection

EXPECTED_COMMAND_SCHEMA = "domain-responsibility-proposal-v1"
EXPECTED_RECEIPT_SCHEMA = "domain-responsibility-proposal-receipt-v1"
EXPECTED_WORK_ADMISSION_COMMAND_SCHEMA = "responsibility-work-admission-v1"
EXPECTED_WORK_ADMISSION_RECEIPT_SCHEMA = "responsibility-work-admission-receipt-v1"


class KernelSubmissionError(RuntimeError):
    pass


class KernelWorkAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KernelProposalReceipt:
    responsibility_ref: str
    admission_ref: str
    assessment_ref: str
    proposal_ref: str


@dataclass(frozen=True, slots=True)
class KernelWorkAdmissionReceipt:
    status: Literal["work-materialized", "priority-rejected", "portfolio-rejected"]
    proposal_ref: str
    policy_ref: str
    priority_judgment_ref: str
    resource_pool_ref: str | None = None
    portfolio_admission_ref: str | None = None
    reservation_ref: str | None = None
    commitment_ref: str | None = None
    work_ref: str | None = None


class KernelResponsibilityClient(Protocol):
    def submit(self, projection: KernelShadowProjection) -> KernelProposalReceipt: ...

    def admit(
        self,
        projection: KernelShadowProjection,
        *,
        expected_policy_ref: str,
    ) -> KernelWorkAdmissionReceipt: ...


class HttpKernelResponsibilityClient:
    """Submit responsibility prefixes and request Kernel-owned Work admission."""

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

    def admit(
        self,
        projection: KernelShadowProjection,
        *,
        expected_policy_ref: str,
    ) -> KernelWorkAdmissionReceipt:
        if projection.status is not KernelProjectionStatus.SUBMITTED:
            raise KernelWorkAdmissionError("kernel Work admission requires submitted projection")
        proposal_ref = projection.kernel_proposal_ref
        if not proposal_ref:
            raise KernelWorkAdmissionError("submitted projection lacks Kernel proposal ref")

        payload = {
            "schema": EXPECTED_WORK_ADMISSION_COMMAND_SCHEMA,
            "proposal_ref": proposal_ref,
            "expected_policy_ref": expected_policy_ref,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/responsibilities/work-admissions",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelWorkAdmissionError(
                f"agent-kernel Work admission failed: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise KernelWorkAdmissionError("agent-kernel Work admission receipt must be a JSON object")
        if raw.get("schema") != EXPECTED_WORK_ADMISSION_RECEIPT_SCHEMA:
            raise KernelWorkAdmissionError(
                "agent-kernel returned an incompatible Work admission receipt schema"
            )
        if raw.get("authority_bearing") is not False:
            raise KernelWorkAdmissionError(
                "agent-kernel Work admission receipt must be explicitly non-authoritative"
            )
        if raw.get("proposal_ref") != proposal_ref:
            raise KernelWorkAdmissionError("agent-kernel Work admission proposal identity mismatch")
        if raw.get("policy_ref") != expected_policy_ref:
            raise KernelWorkAdmissionError("agent-kernel Work admission policy identity mismatch")

        status = raw.get("status")
        if status not in {"work-materialized", "priority-rejected", "portfolio-rejected"}:
            raise KernelWorkAdmissionError("agent-kernel returned unknown Work admission status")
        priority_ref = raw.get("priority_judgment_ref")
        if not isinstance(priority_ref, str) or not priority_ref:
            raise KernelWorkAdmissionError("Work admission receipt lacks priority judgment ref")

        def optional_ref(name: str) -> str | None:
            value = raw.get(name)
            if value is None:
                return None
            if not isinstance(value, str) or not value:
                raise KernelWorkAdmissionError(f"invalid Work admission {name}")
            return value

        resource_pool_ref = optional_ref("resource_pool_ref")
        portfolio_admission_ref = optional_ref("portfolio_admission_ref")
        reservation_ref = optional_ref("reservation_ref")
        commitment_ref = optional_ref("commitment_ref")
        work_ref = optional_ref("work_ref")

        if status == "work-materialized":
            required = {
                "resource_pool_ref": resource_pool_ref,
                "portfolio_admission_ref": portfolio_admission_ref,
                "reservation_ref": reservation_ref,
                "commitment_ref": commitment_ref,
                "work_ref": work_ref,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise KernelWorkAdmissionError(
                    "materialized Work admission receipt lacks refs: " + ", ".join(missing)
                )
        elif status == "priority-rejected":
            if any(
                value is not None
                for value in (
                    resource_pool_ref,
                    portfolio_admission_ref,
                    reservation_ref,
                    commitment_ref,
                    work_ref,
                )
            ):
                raise KernelWorkAdmissionError(
                    "priority-rejected receipt must stop before resource and Work refs"
                )
        else:
            if not resource_pool_ref or not portfolio_admission_ref:
                raise KernelWorkAdmissionError(
                    "portfolio-rejected receipt requires pool and portfolio refs"
                )
            if any(value is not None for value in (reservation_ref, commitment_ref, work_ref)):
                raise KernelWorkAdmissionError(
                    "portfolio-rejected receipt must stop before reservation and Work refs"
                )

        return KernelWorkAdmissionReceipt(
            status=status,
            proposal_ref=proposal_ref,
            policy_ref=expected_policy_ref,
            priority_judgment_ref=priority_ref,
            resource_pool_ref=resource_pool_ref,
            portfolio_admission_ref=portfolio_admission_ref,
            reservation_ref=reservation_ref,
            commitment_ref=commitment_ref,
            work_ref=work_ref,
        )


__all__ = [
    "HttpKernelResponsibilityClient",
    "KernelProposalReceipt",
    "KernelResponsibilityClient",
    "KernelSubmissionError",
    "KernelWorkAdmissionError",
    "KernelWorkAdmissionReceipt",
]
