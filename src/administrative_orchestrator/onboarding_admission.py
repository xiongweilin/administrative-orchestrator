from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .admission import IntakePromotionService, PromotionResult
from .domain import (
    AdministrativeCase,
    FactAssertion,
    FactAuthority,
    FactSnapshot,
)
from .intake.models import CandidateAdministrativeRequest, IntakeAssessment
from .intake.repository import IntakeRepository
from .persistence import ConcurrencyConflict, SqlStore
from .policy import OnboardingFacts, PolicyEvaluation
from .policy_plane import PolicyRepository, compile_onboarding_policy
from .service import (
    TransitionError,
    apply_policy_evaluation,
    replace_fact_snapshot,
    start_policy_evaluation,
)
from .unit_of_work import AdministrativeUnitOfWork


class OnboardingAdmissionError(ValueError):
    """Candidate data cannot safely enter the existing onboarding path."""


@dataclass(frozen=True, slots=True)
class OnboardingAdmissionResult:
    promotion: PromotionResult
    case: AdministrativeCase
    policy_evaluation: PolicyEvaluation
    created: bool


class CandidateOnboardingAdmissionService:
    """Bridge an admitted candidate into the existing M5 onboarding semantics.

    This bridge keeps candidate claims as ``FactAuthority.CLAIM``. Human
    admission authorizes the request/case transition; it does not turn an
    inbox interpretation into an authoritative system-of-record fact.
    """

    _FACT_KEYS = frozenset(
        {
            "employee_ref",
            "department_ref",
            "manager_principal_id",
            "start_date",
            "employment_type",
            "requested_systems",
            "requires_privileged_access",
        }
    )

    def __init__(
        self,
        store: SqlStore,
        repository: IntakeRepository,
        promotions: IntakePromotionService | None = None,
        *,
        policies: PolicyRepository | None = None,
        uow: AdministrativeUnitOfWork | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.promotions = promotions or IntakePromotionService(store, repository)
        self.policies = policies or PolicyRepository(store)
        self.uow = uow or AdministrativeUnitOfWork(store)

    def promote_and_evaluate(
        self,
        candidate: CandidateAdministrativeRequest,
        assessment: IntakeAssessment,
        *,
        source_system: str,
        tenant_ref: str,
        source_event_id: str,
        requester_principal_id: str,
        subject_ref: str,
        channel: str = "intake",
        promotion_policy_ref: str = "m6-human-confirmed-v1",
    ) -> OnboardingAdmissionResult:
        subject_ref = subject_ref.strip()
        if not subject_ref:
            raise OnboardingAdmissionError(
                "employee-onboarding promotion requires a non-blank subject_ref"
            )

        promotion = self.promotions.promote(
            candidate,
            assessment,
            source_system=source_system,
            tenant_ref=tenant_ref,
            source_event_id=source_event_id,
            requester_principal_id=requester_principal_id,
            channel=channel,
            case_kind="employee-onboarding",
            subject_ref=subject_ref,
            promotion_policy_ref=promotion_policy_ref,
        )

        current = self.store.get_case(promotion.case.case_id)
        if current is None:
            raise OnboardingAdmissionError("promotion created a case that cannot be reloaded")
        existing_evaluation = self.store.get_latest_policy_evaluation(current.case_id)
        if existing_evaluation is not None:
            return OnboardingAdmissionResult(
                promotion=promotion,
                case=current,
                policy_evaluation=existing_evaluation,
                created=promotion.created,
            )

        facts = self._candidate_facts(
            candidate,
            subject_ref=subject_ref,
        )
        snapshot = self._fact_snapshot(
            candidate,
            assessment,
            facts,
            source_system=source_system,
            source_event_id=source_event_id,
        )
        changed = replace_fact_snapshot(current, snapshot)
        ready = start_policy_evaluation(changed)
        policy_record = self.policies.resolve_current("employee-onboarding")
        evaluation = compile_onboarding_policy(policy_record).evaluate(facts)
        updated = apply_policy_evaluation(ready, evaluation)
        try:
            self.uow.replace_facts_and_apply_policy(current, updated, evaluation)
        except (ConcurrencyConflict, TransitionError, ValueError) as exc:
            replayed = self.store.get_latest_policy_evaluation(current.case_id)
            if replayed is None:
                raise
            stored = self.store.get_case(current.case_id)
            if stored is None:
                raise OnboardingAdmissionError(
                    "onboarding policy transition committed without a readable case"
                ) from exc
            return OnboardingAdmissionResult(
                promotion=promotion,
                case=stored,
                policy_evaluation=replayed,
                created=promotion.created,
            )
        return OnboardingAdmissionResult(
            promotion=promotion,
            case=updated,
            policy_evaluation=evaluation,
            created=promotion.created,
        )

    def _candidate_facts(
        self,
        candidate: CandidateAdministrativeRequest,
        *,
        subject_ref: str,
    ) -> OnboardingFacts:
        assertions = self.repository.list_candidate_facts(candidate.candidate_id)
        values: dict[str, Any] = {}
        for assertion in assertions:
            if assertion.fact_key not in self._FACT_KEYS:
                raise OnboardingAdmissionError(
                    f"candidate fact {assertion.fact_key!r} is not allowed for onboarding"
                )
            if assertion.fact_key in values:
                raise OnboardingAdmissionError(
                    f"candidate contains duplicate onboarding fact {assertion.fact_key!r}"
                )
            values[assertion.fact_key] = assertion.value

        supplied_employee = values.get("employee_ref")
        if supplied_employee is not None and str(supplied_employee).strip() != subject_ref:
            raise OnboardingAdmissionError(
                "candidate employee_ref does not match the human-selected subject_ref"
            )
        values["employee_ref"] = subject_ref
        try:
            return OnboardingFacts.model_validate(values)
        except ValueError as exc:
            raise OnboardingAdmissionError(
                "admitted candidate facts do not satisfy the onboarding fact contract"
            ) from exc

    def _fact_snapshot(
        self,
        candidate: CandidateAdministrativeRequest,
        assessment: IntakeAssessment,
        facts: OnboardingFacts,
        *,
        source_system: str,
        source_event_id: str,
    ) -> FactSnapshot:
        source = f"intake:{source_system}"
        source_ref = f"intake:{source_system}/{source_event_id}"
        owner = assessment.reviewer_principal_id or "service:administrative-orchestrator"
        candidate_assertions = {
            assertion.fact_key: assertion
            for assertion in self.repository.list_candidate_facts(candidate.candidate_id)
        }
        flattened = facts.model_dump(mode="json")
        assertions: dict[str, FactAssertion] = {}
        for key, value in flattened.items():
            candidate_assertion = candidate_assertions.get(key)
            assertions[key] = FactAssertion(
                value=value,
                authority=FactAuthority.CLAIM,
                source=source,
                owner=owner,
                source_ref=(
                    f"candidate-fact:{candidate_assertion.candidate_fact_id}"
                    if candidate_assertion is not None
                    else source_ref
                ),
                source_version=(
                    str(candidate_assertion.interpretation_ref)
                    if candidate_assertion is not None
                    and candidate_assertion.interpretation_ref is not None
                    else "m6-human-confirmed-v1"
                ),
                observed_at=assessment.created_at,
                digest=_value_digest(value),
            )
        return FactSnapshot(
            source=source,
            owner=owner,
            authority=FactAuthority.CLAIM,
            source_ref=source_ref,
            source_version="m6-human-confirmed-v1",
            observed_at=assessment.created_at,
            facts=flattened,
            assertions=assertions,
            digest=_snapshot_digest(flattened, assertions),
        )


def _value_digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _snapshot_digest(facts: dict[str, Any], assertions: dict[str, FactAssertion]) -> str:
    payload = {
        "facts": facts,
        "assertions": {
            key: assertion.model_dump(mode="json") for key, assertion in sorted(assertions.items())
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "CandidateOnboardingAdmissionService",
    "OnboardingAdmissionError",
    "OnboardingAdmissionResult",
]
