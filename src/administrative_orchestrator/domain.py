from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class PrincipalKind(StrEnum):
    PERSON = "person"
    SERVICE = "service"
    AGENT = "agent"


class CaseStatus(StrEnum):
    RECEIVED = "received"
    GATHERING_FACTS = "gathering_facts"
    READY_FOR_POLICY = "ready_for_policy"
    AWAITING_DECISION = "awaiting_decision"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECONCILING = "reconciling"
    REOPEN_REQUIRED = "reopen_required"
    WAITING = "waiting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ReopenReason(StrEnum):
    NO_APPLICABLE_POLICY = "no_applicable_policy"
    POLICY_CONFLICT = "policy_conflict"
    MISSING_REQUIRED_FACT = "missing_required_fact"
    AUTHORITY_UNRESOLVED = "authority_unresolved"
    SUBJECT_CHANGED = "subject_changed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    REALITY_MISMATCH = "reality_mismatch"
    SCOPE_EXPANSION = "scope_expansion"
    UNKNOWN_RISK_DIMENSION = "unknown_risk_dimension"


class DecisionDisposition(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    ESCALATE = "escalate"


class EffectReversibility(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    CORRECTABLE = "correctable"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class AuthorityClass(StrEnum):
    NORMAL = "normal"
    PII = "pii"
    FINANCIAL = "financial"
    PRIVILEGED_ACCESS = "privileged_access"
    EMPLOYMENT = "employment"
    LEGAL = "legal"
    REGULATED = "regulated"


class EffectStatus(StrEnum):
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class RealizationDisposition(StrEnum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class Principal(BaseModel):
    principal_id: str
    kind: PrincipalKind = PrincipalKind.PERSON
    display_name: str


class RoleAssignment(BaseModel):
    assignment_id: UUID = Field(default_factory=uuid4)
    principal_id: str
    role: str
    organization_scope: str
    valid_from: datetime = Field(default_factory=utcnow)
    valid_until: datetime | None = None

    def is_current_at(self, at: datetime) -> bool:
        return self.valid_from <= at and (self.valid_until is None or at < self.valid_until)


class Delegation(BaseModel):
    delegation_id: UUID = Field(default_factory=uuid4)
    from_principal_id: str
    to_principal_id: str
    role: str
    organization_scope: str
    valid_from: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def validate_window(self) -> Delegation:
        if self.valid_until <= self.valid_from:
            raise ValueError("delegation valid_until must be after valid_from")
        return self


class PolicyRef(BaseModel):
    policy_id: str
    version: str
    owner: str
    effective_from: datetime
    effective_until: datetime | None = None

    def is_current_at(self, at: datetime) -> bool:
        return self.effective_from <= at and (
            self.effective_until is None or at < self.effective_until
        )


class EvidenceRef(BaseModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    source: str
    owner: str
    observed_at: datetime
    version: str | None = None
    digest: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdministrativeRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    requester_principal_id: str
    channel: str
    intent: str
    received_at: datetime = Field(default_factory=utcnow)
    source_ref: str | None = None


class AdministrativeCase(BaseModel):
    case_id: UUID = Field(default_factory=uuid4)
    case_kind: str
    requester_principal_id: str
    subject_ref: str
    status: CaseStatus = CaseStatus.RECEIVED
    version: int = 1
    policy_ref: PolicyRef | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    reopen_reason: ReopenReason | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def reopen_reason_matches_status(self) -> AdministrativeCase:
        if self.status == CaseStatus.REOPEN_REQUIRED and self.reopen_reason is None:
            raise ValueError("reopen_required case must record a reopen_reason")
        if self.status != CaseStatus.REOPEN_REQUIRED and self.reopen_reason is not None:
            raise ValueError("reopen_reason is only valid while case is reopen_required")
        return self


class Decision(BaseModel):
    decision_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    case_version: int
    principal_id: str
    disposition: DecisionDisposition
    rationale: str
    policy_ref: PolicyRef
    decided_at: datetime = Field(default_factory=utcnow)


class ExecutionAuthorization(BaseModel):
    authorization_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    case_version: int
    decision_id: UUID
    issuer_principal_id: str
    target_system: str
    subject_ref: str
    allowed_operations: tuple[str, ...]
    authority_class: AuthorityClass
    policy_ref: PolicyRef
    issued_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def validate_operations(self) -> ExecutionAuthorization:
        if not self.allowed_operations:
            raise ValueError("authorization must allow at least one operation")
        return self

    def is_current_at(self, at: datetime) -> bool:
        if self.revoked_at is not None and self.revoked_at <= at:
            return False
        return self.expires_at is None or at < self.expires_at


class EffectRecord(BaseModel):
    effect_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    case_version: int
    authorization_id: UUID
    target_system: str
    operation: str
    subject_ref: str
    reversibility: EffectReversibility
    authority_class: AuthorityClass
    status: EffectStatus = EffectStatus.PLANNED
    provider_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EffectRealizationAssessment(BaseModel):
    assessment_id: UUID = Field(default_factory=uuid4)
    effect_id: UUID
    disposition: RealizationDisposition
    evidence: list[EvidenceRef]
    assessed_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def verified_requires_evidence(self) -> EffectRealizationAssessment:
        if self.disposition == RealizationDisposition.VERIFIED and not self.evidence:
            raise ValueError("verified realization requires evidence")
        return self


class ConfirmedOutcome(BaseModel):
    outcome_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    case_version: int
    effect_id: UUID
    realization_assessment_id: UUID
    outcome_kind: str
    evidence: list[EvidenceRef]
    confirmed_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def outcome_requires_evidence(self) -> ConfirmedOutcome:
        if not self.evidence:
            raise ValueError("confirmed outcome requires evidence")
        return self
