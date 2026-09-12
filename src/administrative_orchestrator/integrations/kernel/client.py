from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from urllib.parse import quote

import httpx

from .models import (
    AdministrativeEffectIntent,
    AdministrativeExecutionGrant,
    KernelProjectionStatus,
    KernelShadowProjection,
)

EXPECTED_COMMAND_SCHEMA = "domain-responsibility-proposal-v1"
EXPECTED_RECEIPT_SCHEMA = "domain-responsibility-proposal-receipt-v1"
EXPECTED_WORK_ADMISSION_COMMAND_SCHEMA = "responsibility-work-admission-v1"
EXPECTED_WORK_ADMISSION_RECEIPT_SCHEMA = "responsibility-work-admission-receipt-v1"
EXPECTED_EXECUTION_COMMAND_SCHEMA = "bounded-domain-effect-execution-v1"
EXPECTED_EXECUTION_RECEIPT_SCHEMA = "bounded-domain-effect-execution-receipt-v1"
EXPECTED_RESPONSIBILITY_ASSESSMENT_COMMAND_SCHEMA = "responsibility-assessment-record-v1"
EXPECTED_RESPONSIBILITY_ASSESSMENT_RECEIPT_SCHEMA = "responsibility-assessment-receipt-v1"
EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_COMMAND_SCHEMA = (
    "responsibility-discharge-decision-record-v1"
)
EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_RECEIPT_SCHEMA = (
    "responsibility-discharge-decision-receipt-v1"
)
EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_COMMAND_SCHEMA = (
    "responsibility-lifecycle-transition-apply-v1"
)
EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_RECEIPT_SCHEMA = (
    "responsibility-lifecycle-transition-receipt-v1"
)
EXPECTED_RESPONSIBILITY_STATUS_SCHEMA = "responsibility-status-view-v1"


class KernelSubmissionError(RuntimeError):
    pass


class KernelWorkAdmissionError(RuntimeError):
    pass


class KernelExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class KernelResponsibilityDischargeError(RuntimeError):
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


KernelExecutionStatus = Literal[
    "authorization-rejected",
    "execution-failed",
    "execution-unknown",
    "verified-fail",
    "completed",
]


@dataclass(frozen=True, slots=True)
class KernelExecutionReceipt:
    status: KernelExecutionStatus
    execution_ref: str
    work_ref: str
    processed_at: datetime
    run_ref: str | None = None
    request_ref: str | None = None
    authorization_ref: str | None = None
    provider_id: str | None = None
    external_operation_ref: str | None = None
    action_ref: str | None = None
    outcome_ref: str | None = None
    evidence_ref: str | None = None
    responsibility_ref: str | None = None


@dataclass(frozen=True, slots=True)
class KernelResponsibilityAssessmentReceipt:
    assessment_ref: str
    responsibility_ref: str
    responsibility_version: int


@dataclass(frozen=True, slots=True)
class KernelResponsibilityDischargeDecisionReceipt:
    decision_ref: str
    responsibility_ref: str
    responsibility_version: int
    status_after_decision: Literal["active", "suspended", "discharged"]
    assessment_ref: str


@dataclass(frozen=True, slots=True)
class KernelResponsibilityLifecycleTransitionReceipt:
    transition_ref: str
    responsibility_ref: str
    responsibility_version: int
    current_status: Literal["active", "suspended", "discharged"]
    decision_ref: str


@dataclass(frozen=True, slots=True)
class KernelResponsibilityStatusView:
    responsibility_ref: str
    responsibility_version: int
    current_status: Literal["active", "suspended", "discharged"]


class KernelResponsibilityClient(Protocol):
    def submit(self, projection: KernelShadowProjection) -> KernelProposalReceipt: ...

    def admit(
        self,
        projection: KernelShadowProjection,
        *,
        expected_policy_ref: str,
    ) -> KernelWorkAdmissionReceipt: ...

    def execute(
        self,
        projection: KernelShadowProjection,
        grant: AdministrativeExecutionGrant,
        intent: AdministrativeEffectIntent,
    ) -> KernelExecutionReceipt: ...

    def inspect_execution(
        self,
        execution_ref: str,
        *,
        expected_work_ref: str | None = None,
    ) -> KernelExecutionReceipt | None: ...

    def record_assessment(
        self,
        *,
        assessment_ref: str,
        responsibility_ref: str,
        responsibility_version: int,
        subject_ref: str,
        assessment_kind: str,
        basis_refs: Sequence[str],
        assessed_at: datetime,
        fresh_until: datetime | None,
        rationale: str,
        created_at: datetime,
    ) -> KernelResponsibilityAssessmentReceipt: ...

    def record_discharge_decision(
        self,
        *,
        decision_ref: str,
        responsibility_ref: str,
        responsibility_version: int,
        assessment_ref: str,
        basis_refs: Sequence[str],
        policy_ref: str,
        decided_at: datetime,
        rationale: str,
        created_at: datetime,
    ) -> KernelResponsibilityDischargeDecisionReceipt: ...

    def apply_lifecycle_transition(
        self,
        *,
        transition_ref: str,
        responsibility_ref: str,
        responsibility_version: int,
        decision_ref: str,
        basis_refs: Sequence[str],
        applied_at: datetime,
        reason: str,
        created_at: datetime,
    ) -> KernelResponsibilityLifecycleTransitionReceipt: ...

    def get_responsibility_status(
        self,
        responsibility_ref: str,
        *,
        expected_version: int,
    ) -> KernelResponsibilityStatusView: ...


class HttpKernelResponsibilityClient:
    """Consume Agent Kernel's public responsibility and bounded-action contracts."""

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

    def execute(
        self,
        projection: KernelShadowProjection,
        grant: AdministrativeExecutionGrant,
        intent: AdministrativeEffectIntent,
    ) -> KernelExecutionReceipt:
        if projection.status is not KernelProjectionStatus.ADMITTED:
            raise KernelExecutionError("kernel execution requires admitted Work")
        work_ref = projection.kernel_work_ref
        if not work_ref:
            raise KernelExecutionError("admitted projection lacks Kernel Work ref")
        if projection.grant_id != grant.grant_id or projection.intent_id != intent.intent_id:
            raise KernelExecutionError("kernel execution inputs do not match persisted projection")
        if grant.grant_id != intent.grant_id or grant.obligation_id != intent.obligation_id:
            raise KernelExecutionError("kernel execution grant and intent identities rebound")

        payload = {
            "schema": EXPECTED_EXECUTION_COMMAND_SCHEMA,
            "work_ref": work_ref,
            "domain_intent_ref": str(intent.intent_id),
            "domain_grant_ref": str(grant.grant_id),
            "governance_basis_ref": str(grant.governance_basis_id),
            "approval_satisfaction_ref": str(grant.approval_satisfaction_id),
            "capability": intent.capability,
            "subject_ref": intent.subject_ref,
            "authority_epoch": intent.authority_epoch,
            "parameters": dict(intent.parameters),
            "expected_postcondition": dict(intent.expected_postcondition),
            "observed_at": intent.created_at.isoformat(),
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/domain-effects/executions",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            status_code = exc.response.status_code
            raise KernelExecutionError(
                "agent-kernel bounded execution failed: "
                f"HTTP {status_code}: {detail}",
                retryable=500 <= status_code < 600,
                status_code=status_code,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelExecutionError(
                f"agent-kernel bounded execution failed: {exc}",
                retryable=True,
            ) from exc
        return self._execution_receipt(raw, expected_work_ref=work_ref)

    def inspect_execution(
        self,
        execution_ref: str,
        *,
        expected_work_ref: str | None = None,
    ) -> KernelExecutionReceipt | None:
        try:
            response = httpx.get(
                f"{self.base_url}/v1/domain-effects/executions/{execution_ref}",
                timeout=self.timeout_seconds,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelExecutionError(f"agent-kernel execution inspection failed: {exc}") from exc
        receipt = self._execution_receipt(raw, expected_work_ref=expected_work_ref)
        if receipt.execution_ref != execution_ref:
            raise KernelExecutionError("agent-kernel execution inspection identity rebound")
        return receipt

    def record_assessment(
        self,
        *,
        assessment_ref: str,
        responsibility_ref: str,
        responsibility_version: int,
        subject_ref: str,
        assessment_kind: str,
        basis_refs: Sequence[str],
        assessed_at: datetime,
        fresh_until: datetime | None,
        rationale: str,
        created_at: datetime,
    ) -> KernelResponsibilityAssessmentReceipt:
        assessment: dict[str, Any] = {
            "id": assessment_ref,
            "object_type": "ResponsibilityAssessment",
            "responsibility_ref": responsibility_ref,
            "responsibility_version": responsibility_version,
            "subject_ref": subject_ref,
            "assessment_kind": assessment_kind,
            "basis_refs": list(basis_refs),
            "assessed_at": assessed_at.isoformat(),
            "rationale": rationale,
            "created_at": created_at.isoformat(),
        }
        if fresh_until is not None:
            assessment["fresh_until"] = fresh_until.isoformat()
        raw = self._post_discharge(
            "/v1/responsibilities/assessments",
            {
                "schema": EXPECTED_RESPONSIBILITY_ASSESSMENT_COMMAND_SCHEMA,
                "assessment": assessment,
            },
        )
        if raw.get("schema") != EXPECTED_RESPONSIBILITY_ASSESSMENT_RECEIPT_SCHEMA:
            raise KernelResponsibilityDischargeError(
                "agent-kernel returned an incompatible responsibility assessment receipt schema"
            )
        self._require_non_authoritative(raw)
        returned = self._validate_responsibility_object(
            raw.get("assessment"),
            object_type="ResponsibilityAssessment",
            responsibility_ref=responsibility_ref,
            responsibility_version=responsibility_version,
        )
        if returned.get("id") != assessment_ref:
            raise KernelResponsibilityDischargeError(
                "agent-kernel assessment receipt identity rebound"
            )
        return KernelResponsibilityAssessmentReceipt(
            assessment_ref=assessment_ref,
            responsibility_ref=responsibility_ref,
            responsibility_version=responsibility_version,
        )

    def record_discharge_decision(
        self,
        *,
        decision_ref: str,
        responsibility_ref: str,
        responsibility_version: int,
        assessment_ref: str,
        basis_refs: Sequence[str],
        policy_ref: str,
        decided_at: datetime,
        rationale: str,
        created_at: datetime,
    ) -> KernelResponsibilityDischargeDecisionReceipt:
        decision = {
            "id": decision_ref,
            "object_type": "ResponsibilityDischargeDecision",
            "responsibility_ref": responsibility_ref,
            "responsibility_version": responsibility_version,
            "status_at_decision": "active",
            "assessment_ref": assessment_ref,
            "disposition": "discharge",
            "basis_refs": list(basis_refs),
            "policy_ref": policy_ref,
            "decided_at": decided_at.isoformat(),
            "rationale": rationale,
            "created_at": created_at.isoformat(),
        }
        raw = self._post_discharge(
            "/v1/responsibilities/discharge-decisions",
            {
                "schema": EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_COMMAND_SCHEMA,
                "decision": decision,
            },
        )
        if raw.get("schema") != EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_RECEIPT_SCHEMA:
            raise KernelResponsibilityDischargeError(
                "agent-kernel returned an incompatible responsibility discharge decision receipt schema"
            )
        self._require_non_authoritative(raw)
        returned = self._validate_responsibility_object(
            raw.get("decision"),
            object_type="ResponsibilityDischargeDecision",
            responsibility_ref=responsibility_ref,
            responsibility_version=responsibility_version,
        )
        if returned.get("id") != decision_ref or returned.get("assessment_ref") != assessment_ref:
            raise KernelResponsibilityDischargeError(
                "agent-kernel discharge decision receipt identity rebound"
            )
        status = raw.get("status_after_decision")
        if status != "active":
            raise KernelResponsibilityDischargeError(
                "agent-kernel discharge decision must leave responsibility active"
            )
        return KernelResponsibilityDischargeDecisionReceipt(
            decision_ref=decision_ref,
            responsibility_ref=responsibility_ref,
            responsibility_version=responsibility_version,
            status_after_decision=status,
            assessment_ref=assessment_ref,
        )

    def apply_lifecycle_transition(
        self,
        *,
        transition_ref: str,
        responsibility_ref: str,
        responsibility_version: int,
        decision_ref: str,
        basis_refs: Sequence[str],
        applied_at: datetime,
        reason: str,
        created_at: datetime,
    ) -> KernelResponsibilityLifecycleTransitionReceipt:
        transition = {
            "id": transition_ref,
            "object_type": "ResponsibilityLifecycleTransition",
            "responsibility_ref": responsibility_ref,
            "responsibility_version": responsibility_version,
            "from_status": "active",
            "to_status": "discharged",
            "decision_ref": decision_ref,
            "basis_refs": list(basis_refs),
            "applied_at": applied_at.isoformat(),
            "reason": reason,
            "created_at": created_at.isoformat(),
        }
        raw = self._post_discharge(
            "/v1/responsibilities/lifecycle-transitions",
            {
                "schema": EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_COMMAND_SCHEMA,
                "transition": transition,
            },
        )
        if raw.get("schema") != EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_RECEIPT_SCHEMA:
            raise KernelResponsibilityDischargeError(
                "agent-kernel returned an incompatible responsibility lifecycle receipt schema"
            )
        self._require_non_authoritative(raw)
        returned = self._validate_responsibility_object(
            raw.get("transition"),
            object_type="ResponsibilityLifecycleTransition",
            responsibility_ref=responsibility_ref,
            responsibility_version=responsibility_version,
        )
        if returned.get("id") != transition_ref or returned.get("decision_ref") != decision_ref:
            raise KernelResponsibilityDischargeError(
                "agent-kernel lifecycle transition receipt identity rebound"
            )
        if returned.get("from_status") != "active" or returned.get("to_status") != "discharged":
            raise KernelResponsibilityDischargeError(
                "agent-kernel lifecycle transition status semantics rebound"
            )
        if raw.get("current_status") != "discharged":
            raise KernelResponsibilityDischargeError(
                "agent-kernel lifecycle transition did not confirm discharged status"
            )
        return KernelResponsibilityLifecycleTransitionReceipt(
            transition_ref=transition_ref,
            responsibility_ref=responsibility_ref,
            responsibility_version=responsibility_version,
            current_status="discharged",
            decision_ref=decision_ref,
        )

    def get_responsibility_status(
        self,
        responsibility_ref: str,
        *,
        expected_version: int,
    ) -> KernelResponsibilityStatusView:
        escaped_ref = quote(responsibility_ref, safe="")
        try:
            response = httpx.get(
                f"{self.base_url}/v1/responsibilities/{escaped_ref}/status",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelResponsibilityDischargeError(
                f"agent-kernel responsibility status inspection failed: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility status must be a JSON object"
            )
        if raw.get("schema") != EXPECTED_RESPONSIBILITY_STATUS_SCHEMA:
            raise KernelResponsibilityDischargeError(
                "agent-kernel returned an incompatible responsibility status schema"
            )
        self._require_non_authoritative(raw)
        if raw.get("responsibility_ref") != responsibility_ref:
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility status identity rebound"
            )
        version = raw.get("responsibility_version")
        if not isinstance(version, int) or isinstance(version, bool) or version != expected_version:
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility status version mismatch"
            )
        status = raw.get("current_status")
        if status not in {"active", "suspended", "discharged"}:
            raise KernelResponsibilityDischargeError(
                "agent-kernel returned unknown responsibility status"
            )
        return KernelResponsibilityStatusView(
            responsibility_ref=responsibility_ref,
            responsibility_version=version,
            current_status=status,
        )

    def _post_discharge(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelResponsibilityDischargeError(
                f"agent-kernel responsibility discharge request failed: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility discharge receipt must be a JSON object"
            )
        return raw

    @staticmethod
    def _require_non_authoritative(raw: dict[str, Any]) -> None:
        if raw.get("authority_bearing") is not False:
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility discharge receipt must be explicitly non-authoritative"
            )

    @staticmethod
    def _validate_responsibility_object(
        raw: object,
        *,
        object_type: str,
        responsibility_ref: str,
        responsibility_version: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility receipt object must be a JSON object"
            )
        if raw.get("object_type") != object_type:
            raise KernelResponsibilityDischargeError(
                f"agent-kernel responsibility receipt object must be {object_type}"
            )
        if raw.get("responsibility_ref") != responsibility_ref:
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility receipt responsibility identity rebound"
            )
        version = raw.get("responsibility_version")
        if not isinstance(version, int) or isinstance(version, bool) or version != responsibility_version:
            raise KernelResponsibilityDischargeError(
                "agent-kernel responsibility receipt version mismatch"
            )
        return raw

    @staticmethod
    def _execution_receipt(
        raw: object,
        *,
        expected_work_ref: str | None,
    ) -> KernelExecutionReceipt:
        if not isinstance(raw, dict):
            raise KernelExecutionError("agent-kernel execution receipt must be a JSON object")
        if raw.get("schema") != EXPECTED_EXECUTION_RECEIPT_SCHEMA:
            raise KernelExecutionError("agent-kernel returned incompatible execution receipt schema")
        if raw.get("authority_bearing") is not False:
            raise KernelExecutionError("agent-kernel execution receipt must be non-authoritative")

        status = raw.get("status")
        allowed = {
            "authorization-rejected",
            "execution-failed",
            "execution-unknown",
            "verified-fail",
            "completed",
        }
        if status not in allowed:
            raise KernelExecutionError("agent-kernel returned unknown execution status")

        def required_ref(name: str) -> str:
            value = raw.get(name)
            if not isinstance(value, str) or not value:
                raise KernelExecutionError(f"execution receipt lacks {name}")
            return value

        def optional_ref(name: str) -> str | None:
            value = raw.get(name)
            if value is None:
                return None
            if not isinstance(value, str) or not value:
                raise KernelExecutionError(f"execution receipt has invalid {name}")
            return value

        execution_ref = required_ref("execution_ref")
        work_ref = required_ref("work_ref")
        if expected_work_ref is not None and work_ref != expected_work_ref:
            raise KernelExecutionError("agent-kernel execution Work identity rebound")
        processed_raw = raw.get("processed_at")
        if not isinstance(processed_raw, str) or not processed_raw:
            raise KernelExecutionError("execution receipt lacks processed_at")
        try:
            processed_at = datetime.fromisoformat(processed_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KernelExecutionError("execution receipt processed_at is invalid") from exc

        refs = {
            "run_ref": optional_ref("run_ref"),
            "request_ref": optional_ref("request_ref"),
            "authorization_ref": optional_ref("authorization_ref"),
            "provider_id": optional_ref("provider_id"),
            "external_operation_ref": optional_ref("external_operation_ref"),
            "action_ref": optional_ref("action_ref"),
            "outcome_ref": optional_ref("outcome_ref"),
            "evidence_ref": optional_ref("evidence_ref"),
            "responsibility_ref": optional_ref("responsibility_ref"),
        }
        if status == "completed":
            required_refs = {
                name: value
                for name, value in refs.items()
                if name != "external_operation_ref"
            }
            missing = [name for name, value in required_refs.items() if not value]
            if missing:
                raise KernelExecutionError(
                    "completed execution receipt lacks refs: " + ", ".join(missing)
                )
        if status == "verified-fail":
            required_verified_fail = ("run_ref", "request_ref", "provider_id", "action_ref", "outcome_ref", "evidence_ref")
            missing = [name for name in required_verified_fail if not refs[name]]
            if missing:
                raise KernelExecutionError(
                    "verified-fail receipt lacks refs: " + ", ".join(missing)
                )

        return KernelExecutionReceipt(
            status=status,
            execution_ref=execution_ref,
            work_ref=work_ref,
            processed_at=processed_at,
            run_ref=refs["run_ref"],
            request_ref=refs["request_ref"],
            authorization_ref=refs["authorization_ref"],
            provider_id=refs["provider_id"],
            external_operation_ref=refs["external_operation_ref"],
            action_ref=refs["action_ref"],
            outcome_ref=refs["outcome_ref"],
            evidence_ref=refs["evidence_ref"],
            responsibility_ref=refs["responsibility_ref"],
        )


__all__ = [
    "EXPECTED_RESPONSIBILITY_ASSESSMENT_COMMAND_SCHEMA",
    "EXPECTED_RESPONSIBILITY_ASSESSMENT_RECEIPT_SCHEMA",
    "EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_COMMAND_SCHEMA",
    "EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_RECEIPT_SCHEMA",
    "EXPECTED_EXECUTION_COMMAND_SCHEMA",
    "EXPECTED_EXECUTION_RECEIPT_SCHEMA",
    "EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_COMMAND_SCHEMA",
    "EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_RECEIPT_SCHEMA",
    "EXPECTED_RESPONSIBILITY_STATUS_SCHEMA",
    "HttpKernelResponsibilityClient",
    "KernelExecutionError",
    "KernelExecutionReceipt",
    "KernelExecutionStatus",
    "KernelProposalReceipt",
    "KernelResponsibilityAssessmentReceipt",
    "KernelResponsibilityClient",
    "KernelResponsibilityDischargeError",
    "KernelResponsibilityDischargeDecisionReceipt",
    "KernelResponsibilityLifecycleTransitionReceipt",
    "KernelResponsibilityStatusView",
    "KernelSubmissionError",
    "KernelWorkAdmissionError",
    "KernelWorkAdmissionReceipt",
]
