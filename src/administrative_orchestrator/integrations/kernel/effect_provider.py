from __future__ import annotations

from datetime import datetime
from typing import Any

from ...domain import EffectRecord
from ...effect_provider import (
    EffectProvider,
    ObservationAvailability,
    ObservationFreshness,
    ObservationPresence,
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from .bridge import KERNEL_CUTOVER_CAPABILITIES, KernelExecutionBridge
from .evidence import KernelEvidenceError
from .models import KernelExecutionStatus, KernelProjectionStatus, KernelShadowProjection


def _effect_capability(effect: EffectRecord) -> str:
    target = effect.target_system.strip().lower().replace("_", "-")
    operation = effect.operation.strip().lower().replace("_", "-")
    return f"administrative.{target}.{operation}.v1"


class KernelCutoverEffectProvider:
    """Capability router that makes Kernel ownership physically exclusive.

    For a cut-over capability this adapter never calls the fallback provider,
    including reconciliation/read-back. It consumes durable Kernel execution
    lineage and the canonical non-authoritative verification evidence view.
    Missing, rebound, or unresolved Kernel evidence fails closed. Non-cut-over
    capabilities remain byte-for-byte on the legacy provider path.
    """

    def __init__(
        self,
        fallback: EffectProvider,
        bridge: KernelExecutionBridge,
    ) -> None:
        self.fallback = fallback
        self.bridge = bridge

    def execute(self, effect: EffectRecord, payload: dict[str, Any]) -> ProviderExecutionResult:
        if not self._kernel_owned(effect):
            return self.fallback.execute(effect, payload)
        projection = self._projection(effect)
        status = projection.kernel_execution_status if projection is not None else None
        provider_ref = self._provider_ref(projection)
        if status is KernelExecutionStatus.COMPLETED:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.SUCCEEDED,
                provider_ref=provider_ref,
            )
        if status is KernelExecutionStatus.EXECUTION_UNKNOWN:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.OUTCOME_UNKNOWN,
                provider_ref=provider_ref,
                error="Kernel execution outcome is unknown; local fallback forbidden",
                retryable=False,
            )
        if status is KernelExecutionStatus.VERIFIED_FAIL:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.OUTCOME_UNKNOWN,
                provider_ref=provider_ref,
                error="Kernel independent verification failed; local fallback forbidden",
                retryable=False,
            )
        if status in {
            KernelExecutionStatus.AUTHORIZATION_REJECTED,
            KernelExecutionStatus.EXECUTION_FAILED,
        }:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.FAILED,
                provider_ref=provider_ref,
                error=f"Kernel bounded execution terminated as {status.value}",
                retryable=False,
            )
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.OUTCOME_UNKNOWN,
            provider_ref=provider_ref,
            error="Kernel-owned capability lacks a durable execution receipt; local fallback forbidden",
            retryable=False,
        )

    def observe(self, effect: EffectRecord) -> RealityObservation:
        if not self._kernel_owned(effect):
            return self.fallback.observe(effect)
        projection = self._projection(effect)
        status = projection.kernel_execution_status if projection is not None else None
        provider_ref = self._provider_ref(projection)
        observed_at = (
            projection.kernel_execution_processed_at
            if projection is not None and projection.kernel_execution_processed_at is not None
            else effect.updated_at
        )

        if status not in {
            KernelExecutionStatus.COMPLETED,
            KernelExecutionStatus.VERIFIED_FAIL,
        }:
            return self._unknown_observation(
                effect,
                provider_ref,
                observed_at,
                "kernel_execution_not_verified",
            )
        if projection is None or not projection.kernel_evidence_ref:
            return self._unknown_observation(
                effect,
                provider_ref,
                observed_at,
                "kernel_evidence_ref_unavailable",
            )

        try:
            evidence = self.bridge.evidence_client().inspect(projection.kernel_evidence_ref)
        except KernelEvidenceError:
            return self._unknown_observation(
                effect,
                provider_ref,
                observed_at,
                "kernel_evidence_read_error",
            )
        if evidence is None:
            return self._unknown_observation(
                effect,
                provider_ref,
                observed_at,
                "kernel_evidence_unavailable",
            )

        intent = self.bridge.repository.get_intent(projection.intent_id)
        if intent is None:
            return self._unknown_observation(
                effect,
                provider_ref,
                evidence.captured_at,
                "kernel_intent_unavailable",
            )
        if evidence.expected_postcondition != dict(intent.expected_postcondition):
            return self._unknown_observation(
                effect,
                provider_ref,
                evidence.captured_at,
                "kernel_evidence_expected_postcondition_rebound",
            )

        lineage = {
            "work": (evidence.work_ref, getattr(projection, "kernel_work_ref", None)),
            "run": (evidence.run_ref, getattr(projection, "kernel_run_ref", None)),
            "action": (evidence.action_ref, getattr(projection, "kernel_action_ref", None)),
        }
        for name, (actual, expected) in lineage.items():
            if not expected or actual != expected:
                return self._unknown_observation(
                    effect,
                    provider_ref,
                    evidence.captured_at,
                    f"kernel_evidence_{name}_identity_rebound",
                )

        expected_objective_result = (
            "pass" if status is KernelExecutionStatus.COMPLETED else "fail"
        )
        if evidence.objective_result != expected_objective_result:
            return self._unknown_observation(
                effect,
                provider_ref,
                evidence.captured_at,
                "kernel_evidence_objective_result_mismatch",
            )

        evidence_provider_ref = (
            "agent-kernel-verifier:"
            f"{evidence.verifier_provider_id}:"
            f"{evidence.verifier_provider_execution_binding_ref}"
        )
        return RealityObservation(
            availability=ObservationAvailability.AVAILABLE,
            presence=ObservationPresence.PRESENT,
            freshness=ObservationFreshness.CURRENT,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=evidence_provider_ref,
            state=dict(evidence.observed_postcondition),
            digest=evidence.evidence_ref,
            observed_at=evidence.captured_at,
        )

    def _kernel_owned(self, effect: EffectRecord) -> bool:
        return (
            self.bridge.cutover
            and _effect_capability(effect) in KERNEL_CUTOVER_CAPABILITIES
        )

    def _projection(self, effect: EffectRecord) -> KernelShadowProjection | None:
        if effect.obligation_id is None:
            return None
        projection = self.bridge.repository.get_projection_for_obligation(effect.obligation_id)
        if projection is None:
            return None
        if projection.status not in {
            KernelProjectionStatus.ADMITTED,
            KernelProjectionStatus.CUTOVER,
        }:
            return projection
        return projection

    @staticmethod
    def _provider_ref(projection: KernelShadowProjection | None) -> str:
        if projection is None:
            return "agent-kernel:unresolved"
        execution_ref = projection.kernel_execution_ref or "unresolved"
        provider_id = projection.kernel_provider_id or "unresolved"
        return f"agent-kernel:{provider_id}:{execution_ref}"

    @staticmethod
    def _unknown_observation(
        effect: EffectRecord,
        provider_ref: str,
        observed_at: datetime,
        error_class: str,
    ) -> RealityObservation:
        return RealityObservation(
            availability=ObservationAvailability.UNKNOWN,
            presence=ObservationPresence.UNKNOWN,
            freshness=ObservationFreshness.UNKNOWN,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=provider_ref,
            observed_at=observed_at,
            error_class=error_class,
        )


__all__ = ["KernelCutoverEffectProvider"]
