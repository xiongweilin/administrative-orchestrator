from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from ...domain import AuthorityClass, PolicyRef, UtcModel, utcnow


class KernelProjectionStatus(StrEnum):
    SHADOW = "shadow"
    SUBMITTED = "submitted"
    ADMITTED = "admitted"
    CUTOVER = "cutover"
    REJECTED = "rejected"


class KernelWorkAdmissionStatus(StrEnum):
    WORK_MATERIALIZED = "work-materialized"
    PRIORITY_REJECTED = "priority-rejected"
    PORTFOLIO_REJECTED = "portfolio-rejected"


class AdministrativeExecutionGrant(UtcModel):
    """Business permission to discharge exactly one administrative obligation.

    This object is intentionally not an Agent Kernel AuthorizationGrant or
    InvocationPermit. It is administrative-domain authority evidence that a
    later Kernel admission/authorization path may consume as provenance.
    """

    grant_id: UUID
    case_id: UUID
    authority_epoch: int
    obligation_id: UUID
    governance_basis_id: UUID
    approval_satisfaction_id: UUID
    policy_ref: PolicyRef
    subject_ref: str
    target_system: str
    operation: str
    authority_class: AuthorityClass
    expected_postcondition: dict[str, Any] = Field(default_factory=dict)
    issued_by: str = "service:administrative-orchestrator"
    issued_at: datetime = Field(default_factory=utcnow)


class AdministrativeEffectIntent(UtcModel):
    """Administrative request for one future physical capability invocation.

    The intent carries business meaning and frozen parameters but no runtime
    execution authority. Physical dispatch remains illegal until Agent Kernel
    admits Work and separately authorizes the invocation.
    """

    intent_id: UUID
    grant_id: UUID
    case_id: UUID
    authority_epoch: int
    obligation_id: UUID
    capability: str
    subject_ref: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_postcondition: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class KernelShadowProjection(UtcModel):
    projection_id: UUID
    case_id: UUID
    authority_epoch: int
    grant_id: UUID
    intent_id: UUID
    obligation_id: UUID
    contract_catalog: str
    runtime_protocol: str
    persistent_responsibility_contract: str
    responsibility_payload: dict[str, Any]
    admission_payload: dict[str, Any]
    assessment_payload: dict[str, Any]
    work_proposal_payload: dict[str, Any]
    status: KernelProjectionStatus = KernelProjectionStatus.SHADOW
    kernel_responsibility_ref: str | None = None
    kernel_admission_ref: str | None = None
    kernel_assessment_ref: str | None = None
    kernel_proposal_ref: str | None = None
    kernel_work_admission_status: KernelWorkAdmissionStatus | None = None
    kernel_admission_policy_ref: str | None = None
    kernel_priority_judgment_ref: str | None = None
    kernel_resource_pool_ref: str | None = None
    kernel_portfolio_admission_ref: str | None = None
    kernel_reservation_ref: str | None = None
    kernel_commitment_ref: str | None = None
    kernel_work_ref: str | None = None
    kernel_run_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def refs_match_status(self) -> KernelShadowProjection:
        if self.status in {
            KernelProjectionStatus.SUBMITTED,
            KernelProjectionStatus.ADMITTED,
            KernelProjectionStatus.REJECTED,
            KernelProjectionStatus.CUTOVER,
        }:
            required_prefix_refs = (
                self.kernel_responsibility_ref,
                self.kernel_admission_ref,
                self.kernel_assessment_ref,
                self.kernel_proposal_ref,
            )
            if any(not value for value in required_prefix_refs):
                raise ValueError("submitted kernel projection requires full proposal-prefix refs")

        if self.status in {
            KernelProjectionStatus.ADMITTED,
            KernelProjectionStatus.REJECTED,
            KernelProjectionStatus.CUTOVER,
        }:
            if self.kernel_work_admission_status is None:
                raise ValueError("post-admission projection requires Work admission status")
            if not self.kernel_admission_policy_ref or not self.kernel_priority_judgment_ref:
                raise ValueError("post-admission projection requires policy and priority refs")

        if self.status in {KernelProjectionStatus.ADMITTED, KernelProjectionStatus.CUTOVER}:
            if self.kernel_work_admission_status is not KernelWorkAdmissionStatus.WORK_MATERIALIZED:
                raise ValueError("admitted kernel projection requires materialized Work status")
            required_work_refs = (
                self.kernel_resource_pool_ref,
                self.kernel_portfolio_admission_ref,
                self.kernel_reservation_ref,
                self.kernel_commitment_ref,
                self.kernel_work_ref,
            )
            if any(not value for value in required_work_refs):
                raise ValueError("admitted kernel projection requires complete Work admission refs")

        if self.status is KernelProjectionStatus.REJECTED:
            if self.kernel_work_admission_status is KernelWorkAdmissionStatus.WORK_MATERIALIZED:
                raise ValueError("rejected kernel projection cannot reference materialized Work")
            if self.kernel_work_ref or self.kernel_reservation_ref or self.kernel_commitment_ref:
                raise ValueError("rejected kernel projection cannot carry reservation or Work refs")
            if (
                self.kernel_work_admission_status
                is KernelWorkAdmissionStatus.PORTFOLIO_REJECTED
                and (
                    not self.kernel_resource_pool_ref
                    or not self.kernel_portfolio_admission_ref
                )
            ):
                raise ValueError("portfolio rejection requires pool and portfolio refs")
            if (
                self.kernel_work_admission_status
                is KernelWorkAdmissionStatus.PRIORITY_REJECTED
                and (self.kernel_resource_pool_ref or self.kernel_portfolio_admission_ref)
            ):
                raise ValueError("priority rejection must stop before resource admission refs")

        return self


__all__ = [
    "AdministrativeEffectIntent",
    "AdministrativeExecutionGrant",
    "KernelProjectionStatus",
    "KernelShadowProjection",
    "KernelWorkAdmissionStatus",
]
