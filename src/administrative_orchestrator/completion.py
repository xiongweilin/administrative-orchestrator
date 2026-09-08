from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from .domain import ConfirmedOutcome, EffectRecord


class CompletionRequirement(BaseModel):
    requirement_id: str
    required_effect_ids: tuple[UUID, ...]
    required_outcome_kinds: tuple[str, ...]


class CompletionAssessment(BaseModel):
    requirement_id: str
    satisfied: bool
    missing_effect_ids: tuple[UUID, ...] = ()
    missing_outcome_kinds: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)


def onboarding_completion_requirement(effects: list[EffectRecord]) -> CompletionRequirement:
    return CompletionRequirement(
        requirement_id="employee-onboarding-v1",
        required_effect_ids=tuple(effect.effect_id for effect in effects),
        required_outcome_kinds=tuple(
            f"{effect.target_system}.{effect.operation}.verified" for effect in effects
        ),
    )


def assess_onboarding_completion(
    effects: list[EffectRecord],
    outcomes: list[ConfirmedOutcome],
) -> CompletionAssessment:
    """Evaluate the declared completion scope for the current onboarding slice.

    This intentionally models completion as a finite contract rather than
    equating workflow termination or effect count with responsibility discharge.
    Future onboarding obligations can extend this requirement without changing
    the meaning of Effect/Outcome.
    """
    requirement = onboarding_completion_requirement(effects)
    outcome_effect_ids = {outcome.effect_id for outcome in outcomes}
    outcome_kinds = {outcome.outcome_kind for outcome in outcomes}

    missing_effect_ids = tuple(
        effect_id
        for effect_id in requirement.required_effect_ids
        if effect_id not in outcome_effect_ids
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
