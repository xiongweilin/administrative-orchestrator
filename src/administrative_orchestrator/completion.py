from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from .domain import ConfirmedOutcome, EffectRecord
from .obligations import EffectObligationLink, OnboardingObligationSet


class CompletionRequirement(BaseModel):
    requirement_id: str
    required_effect_ids: tuple[UUID, ...] = ()
    required_outcome_kinds: tuple[str, ...] = ()
    required_obligation_ids: tuple[UUID, ...] = ()
    governance_basis_id: UUID | None = None


class CompletionAssessment(BaseModel):
    requirement_id: str
    satisfied: bool
    missing_effect_ids: tuple[UUID, ...] = ()
    missing_outcome_kinds: tuple[str, ...] = ()
    missing_obligation_ids: tuple[UUID, ...] = ()
    uncovered_obligation_ids: tuple[UUID, ...] = ()
    governance_basis_id: UUID | None = None
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)


def onboarding_completion_requirement(effects: list[EffectRecord]) -> CompletionRequirement:
    """Legacy compatibility helper for historical callers.

    New execution code must use an independently derived OnboardingObligationSet
    rather than deriving the business completion contract from the effect plan.
    """
    return CompletionRequirement(
        requirement_id="employee-onboarding-v1-legacy",
        required_effect_ids=tuple(effect.effect_id for effect in effects),
        required_outcome_kinds=tuple(
            f"{effect.target_system}.{effect.operation}.verified" for effect in effects
        ),
    )


def assess_onboarding_completion(
    requirement_or_effects: OnboardingObligationSet | list[EffectRecord],
    effects_or_outcomes: list[EffectRecord] | list[ConfirmedOutcome],
    outcomes: list[ConfirmedOutcome] | None = None,
    *,
    links: list[EffectObligationLink] | None = None,
) -> CompletionAssessment:
    if isinstance(requirement_or_effects, list):
        # Keep historical unit tests and immutable records readable while new
        # writes use obligation-backed completion.
        legacy_effects = requirement_or_effects
        legacy_outcomes = effects_or_outcomes
        assert all(isinstance(item, ConfirmedOutcome) for item in legacy_outcomes)
        return _assess_legacy(legacy_effects, legacy_outcomes)  # type: ignore[arg-type]

    obligation_set = requirement_or_effects
    effects = effects_or_outcomes
    if outcomes is None:
        raise ValueError("obligation-backed completion requires confirmed outcomes")
    if not all(isinstance(item, EffectRecord) for item in effects):
        raise TypeError("obligation-backed completion requires effect records")
    return _assess_obligations(
        obligation_set,
        effects,  # type: ignore[arg-type]
        outcomes,
        links=links or [],
    )


def _assess_obligations(
    obligation_set: OnboardingObligationSet,
    effects: list[EffectRecord],
    outcomes: list[ConfirmedOutcome],
    *,
    links: list[EffectObligationLink],
) -> CompletionAssessment:
    required = {item.obligation_id: item for item in obligation_set.obligations if item.required}
    effect_by_id = {item.effect_id: item for item in effects}
    outcome_effect_ids = {item.effect_id for item in outcomes}
    outcome_kinds = {item.outcome_kind for item in outcomes}
    link_by_obligation = {item.obligation_id: item for item in links}

    uncovered: list[UUID] = []
    missing_confirmed: list[UUID] = []
    missing_kinds: list[str] = []
    for obligation_id, obligation in required.items():
        link = link_by_obligation.get(obligation_id)
        if link is None or link.effect_id not in effect_by_id:
            uncovered.append(obligation_id)
            continue
        effect = effect_by_id[link.effect_id]
        if (
            effect.target_system != obligation.target_system
            or effect.operation != obligation.required_operation
            or effect.subject_ref != obligation.subject_ref
            or effect.authority_class != obligation.authority_class
        ):
            uncovered.append(obligation_id)
            continue
        if effect.effect_id not in outcome_effect_ids:
            missing_confirmed.append(obligation_id)
        required_kind = f"{obligation.target_system}.{obligation.required_operation}.verified"
        if required_kind not in outcome_kinds:
            missing_kinds.append(required_kind)

    reasons: list[str] = []
    if uncovered:
        reasons.append("one or more required business obligations are not covered by an effect")
    if missing_confirmed:
        reasons.append("one or more required business obligations lack a confirmed outcome")
    if missing_kinds:
        reasons.append("one or more required business outcome kinds are not confirmed")

    return CompletionAssessment(
        requirement_id=str(obligation_set.requirement_id),
        satisfied=not reasons,
        missing_obligation_ids=tuple(missing_confirmed),
        uncovered_obligation_ids=tuple(uncovered),
        missing_outcome_kinds=tuple(missing_kinds),
        governance_basis_id=obligation_set.governance_basis_id,
        blocking_reasons=tuple(reasons),
    )


def _assess_legacy(
    effects: list[EffectRecord],
    outcomes: list[ConfirmedOutcome],
) -> CompletionAssessment:
    requirement = onboarding_completion_requirement(effects)
    outcome_effect_ids = {outcome.effect_id for outcome in outcomes}
    outcome_kinds = {outcome.outcome_kind for outcome in outcomes}
    missing_effect_ids = tuple(
        effect_id for effect_id in requirement.required_effect_ids if effect_id not in outcome_effect_ids
    )
    missing_outcome_kinds = tuple(
        kind for kind in requirement.required_outcome_kinds if kind not in outcome_kinds
    )
    reasons: list[str] = []
    if missing_effect_ids:
        reasons.append("one or more planned effects lack a confirmed outcome")
    if missing_outcome_kinds:
        reasons.append("one or more declared business outcomes are not confirmed")
    return CompletionAssessment(
        requirement_id=requirement.requirement_id,
        satisfied=not reasons,
        missing_effect_ids=missing_effect_ids,
        missing_outcome_kinds=missing_outcome_kinds,
        blocking_reasons=tuple(reasons),
    )


__all__ = [
    "CompletionAssessment",
    "CompletionRequirement",
    "assess_onboarding_completion",
    "onboarding_completion_requirement",
]
