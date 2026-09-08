from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, model_validator

from .domain import AuthorityClass, PolicyRef, ReopenReason


class PolicyDisposition(StrEnum):
    AUTO_CLOSABLE = "auto_closable"
    HUMAN_DECISION_REQUIRED = "human_decision_required"
    NEED_MORE_FACTS = "need_more_facts"
    REOPEN_REQUIRED = "reopen_required"
    DENIED = "denied"


class AuthorizedEffectTemplate(BaseModel):
    target_system: str
    operation: str
    authority_class: AuthorityClass = AuthorityClass.NORMAL


class ApprovalRule(BaseModel):
    roles: tuple[str, ...]
    require_distinct_principals: bool = False

    @model_validator(mode="after")
    def validate_rule(self) -> ApprovalRule:
        if not self.roles:
            raise ValueError("approval rule requires at least one role")
        if self.require_distinct_principals and len(self.roles) < 2:
            raise ValueError("distinct approval requires at least two roles")
        return self


class OnboardingPolicyDefinition(BaseModel):
    required_facts: tuple[str, ...]
    standard_approval: ApprovalRule
    privileged_approval: ApprovalRule
    base_effects: tuple[AuthorizedEffectTemplate, ...]


class PolicyEvaluation(BaseModel):
    policy_ref: PolicyRef
    disposition: PolicyDisposition
    reason: str
    missing_facts: tuple[str, ...] = ()
    required_decision_roles: tuple[str, ...] = ()
    require_distinct_decision_principals: bool = False
    allowed_effects: tuple[AuthorizedEffectTemplate, ...] = ()
    reopen_reason: ReopenReason | None = None

    @model_validator(mode="after")
    def validate_disposition(self) -> PolicyEvaluation:
        if self.disposition == PolicyDisposition.NEED_MORE_FACTS and not self.missing_facts:
            raise ValueError("need_more_facts requires missing_facts")
        if (
            self.disposition == PolicyDisposition.HUMAN_DECISION_REQUIRED
            and not self.required_decision_roles
        ):
            raise ValueError("human_decision_required requires decision roles")
        if self.require_distinct_decision_principals and len(self.required_decision_roles) < 2:
            raise ValueError("distinct decision principals requires at least two required roles")
        if self.disposition == PolicyDisposition.AUTO_CLOSABLE:
            if self.required_decision_roles:
                raise ValueError("auto_closable cannot require human decisions")
            if self.allowed_effects:
                raise ValueError(
                    "auto_closable is policy-only closure and cannot authorize external effects"
                )
        if self.disposition == PolicyDisposition.REOPEN_REQUIRED and self.reopen_reason is None:
            raise ValueError("reopen_required policy evaluation requires reopen_reason")
        if self.disposition != PolicyDisposition.REOPEN_REQUIRED and self.reopen_reason is not None:
            raise ValueError("reopen_reason is only valid for reopen_required")
        return self


class OnboardingFacts(BaseModel):
    employee_ref: str
    department_ref: str | None = None
    manager_principal_id: str | None = None
    start_date: str | None = None
    employment_type: str | None = None
    requested_systems: tuple[str, ...] = ()
    requires_privileged_access: bool = False


class OnboardingPolicy:
    """Deterministic evaluator compiled from one persisted policy definition."""

    def __init__(
        self,
        policy_ref: PolicyRef,
        *,
        definition: dict[str, Any] | OnboardingPolicyDefinition | None = None,
    ) -> None:
        self.policy_ref = policy_ref
        self.definition = (
            definition
            if isinstance(definition, OnboardingPolicyDefinition)
            else OnboardingPolicyDefinition.model_validate(definition or self.default_definition())
        )

    @staticmethod
    def default_definition() -> dict[str, Any]:
        return OnboardingPolicyDefinition(
            required_facts=(
                "department_ref",
                "manager_principal_id",
                "start_date",
                "employment_type",
            ),
            standard_approval=ApprovalRule(roles=("hr_approver",)),
            privileged_approval=ApprovalRule(
                roles=("manager", "access_approver"),
                require_distinct_principals=True,
            ),
            base_effects=(
                AuthorizedEffectTemplate(
                    target_system="hris",
                    operation="employee.create",
                    authority_class=AuthorityClass.EMPLOYMENT,
                ),
                AuthorizedEffectTemplate(
                    target_system="iam",
                    operation="identity.create",
                    authority_class=AuthorityClass.PRIVILEGED_ACCESS,
                ),
            ),
        ).model_dump(mode="json")

    def evaluate(self, facts: OnboardingFacts) -> PolicyEvaluation:
        missing = tuple(
            name for name in self.definition.required_facts if getattr(facts, name) is None
        )
        if missing:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.NEED_MORE_FACTS,
                reason="required onboarding facts are missing",
                missing_facts=missing,
            )

        effects = list(self.definition.base_effects)
        effects.extend(
            AuthorizedEffectTemplate(
                target_system=system,
                operation="account.provision",
                authority_class=AuthorityClass.NORMAL,
            )
            for system in facts.requested_systems
        )

        rule = (
            self.definition.privileged_approval
            if facts.requires_privileged_access
            else self.definition.standard_approval
        )
        reason = (
            "privileged access requires the configured multi-party approval rule"
            if facts.requires_privileged_access
            else "employment creation requires the configured current approval rule"
        )
        return PolicyEvaluation(
            policy_ref=self.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason=reason,
            required_decision_roles=rule.roles,
            require_distinct_decision_principals=rule.require_distinct_principals,
            allowed_effects=tuple(effects),
        )


__all__ = [
    "ApprovalRule",
    "AuthorizedEffectTemplate",
    "OnboardingFacts",
    "OnboardingPolicy",
    "OnboardingPolicyDefinition",
    "PolicyDisposition",
    "PolicyEvaluation",
]
