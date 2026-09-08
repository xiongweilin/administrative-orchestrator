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
    kernel_proposal_ref: str | None = None
    kernel_work_ref: str | None = None
    kernel_run_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def refs_match_status(self) -> KernelShadowProjection:
        if self.status in {
            KernelProjectionStatus.SUBMITTED,
            KernelProjectionStatus.ADMITTED,
            KernelProjectionStatus.CUTOVER,
        } and not self.kernel_responsibility_ref:
            raise ValueError("submitted kernel projection requires responsibility ref")
        if (
            self.status in {KernelProjectionStatus.ADMITTED, KernelProjectionStatus.CUTOVER}
            and not self.kernel_proposal_ref
        ):
            raise ValueError("admitted kernel projection requires proposal ref")
        if self.status is KernelProjectionStatus.CUTOVER and not self.kernel_work_ref:
            raise ValueError("cutover kernel projection requires Work ref")
        return self


__all__ = [
    "AdministrativeEffectIntent",
    "AdministrativeExecutionGrant",
    "KernelProjectionStatus",
    "KernelShadowProjection",
]
