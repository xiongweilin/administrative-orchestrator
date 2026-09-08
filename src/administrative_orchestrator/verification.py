from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .domain import EffectRecord
from .effect_provider import RealityObservation


class VerificationDisposition(StrEnum):
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    MISMATCH = "mismatch"


class SemanticVerificationResult(BaseModel):
    disposition: VerificationDisposition
    reason: str
    differences: dict[str, Any] = Field(default_factory=dict)


def verify_onboarding_observation(
    effect: EffectRecord,
    observation: RealityObservation,
    facts: dict[str, Any],
) -> SemanticVerificationResult:
    """Verify that observed reality satisfies the onboarding effect postcondition.

    Provider lookup identity is necessary but not sufficient.  The verifier also
    checks the business state that this onboarding slice promises to create.
    Real connectors may specialize this contract, but they must preserve the
    distinction between provider success and verified business state.
    """
    if not observation.found:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.NOT_FOUND,
            reason="effect realization was not found in authoritative reality",
        )

    differences: dict[str, Any] = {}
    for field in ("target_system", "operation", "subject_ref"):
        expected = getattr(effect, field)
        actual = getattr(observation, field)
        if actual != expected:
            differences[field] = {"expected": expected, "actual": actual}

    state = observation.state
    if state.get("active") is not True:
        differences["active"] = {"expected": True, "actual": state.get("active")}

    payload = state.get("payload")
    if not isinstance(payload, dict):
        differences["payload"] = {"expected": "mapping", "actual": type(payload).__name__}
    else:
        # These facts define the minimum realized employee identity for the
        # current onboarding slice.  Optional fields are checked only when the
        # current authoritative snapshot contains them.
        for field in (
            "employee_ref",
            "department_ref",
            "manager_principal_id",
            "start_date",
            "employment_type",
        ):
            if field in facts and facts[field] is not None and payload.get(field) != facts[field]:
                differences[f"payload.{field}"] = {
                    "expected": facts[field],
                    "actual": payload.get(field),
                }

        if payload.get("employee_ref") != effect.subject_ref:
            differences["payload.employee_ref"] = {
                "expected": effect.subject_ref,
                "actual": payload.get("employee_ref"),
            }

        if effect.operation == "account.provision":
            requested = tuple(facts.get("requested_systems") or ())
            if effect.target_system not in requested:
                differences["requested_systems"] = {
                    "expected_contains": effect.target_system,
                    "actual": list(requested),
                }

    if differences:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.MISMATCH,
            reason="authoritative reality does not satisfy the expected onboarding postcondition",
            differences=differences,
        )

    return SemanticVerificationResult(
        disposition=VerificationDisposition.VERIFIED,
        reason="authoritative reality satisfies the expected onboarding postcondition",
    )


__all__ = [
    "SemanticVerificationResult",
    "VerificationDisposition",
    "verify_onboarding_observation",
]
