from __future__ import annotations

from enum import StrEnum

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


class PolicyEvaluation(BaseModel):
    policy_ref: PolicyRef
    disposition: PolicyDisposition
    reason: str
    missing_facts: tuple[str, ...] = ()
    required_decision_roles: tuple[str, ...] = ()
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
    """Initial deterministic policy for the first vertical slice.

    This is intentionally small. It demonstrates that routine facts and already-closed
    organizational rules should be evaluated deterministically instead of delegated to a
    language model. A later persisted Policy Plane may compile versioned policy records into
    equivalent evaluators.
    """

    REQUIRED_FACTS = (
        "department_ref",
        "manager_principal_id",
        "start_date",
        "employment_type",
    )

    def __init__(self, policy_ref: PolicyRef) -> None:
        self.policy_ref = policy_ref

    def evaluate(self, facts: OnboardingFacts) -> PolicyEvaluation:
        missing = tuple(name for name in self.REQUIRED_FACTS if getattr(facts, name) is None)
        if missing:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.NEED_MORE_FACTS,
                reason="required onboarding facts are missing",
                missing_facts=missing,
            )

        effects = [
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
        ]
        effects.extend(
            AuthorizedEffectTemplate(
                target_system=system,
                operation="account.provision",
                authority_class=AuthorityClass.NORMAL,
            )
            for system in facts.requested_systems
        )

        if facts.requires_privileged_access:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
                reason="privileged access requires an explicit current human decision",
                required_decision_roles=("manager", "access_approver"),
                allowed_effects=tuple(effects),
            )

        return PolicyEvaluation(
            policy_ref=self.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason="employment creation requires an explicit current HR decision",
            required_decision_roles=("hr_approver",),
            allowed_effects=tuple(effects),
        )
