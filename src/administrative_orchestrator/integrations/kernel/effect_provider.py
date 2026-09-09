from __future__ import annotations

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
from .models import KernelExecutionStatus, KernelProjectionStatus


def _effect_capability(effect: EffectRecord) -> str:
    target = effect.target_system.strip().lower().replace("_", "-")
    operation = effect.operation.strip().lower().replace("_", "-")
    return f"administrative.{target}.{operation}.v1"


class KernelCutoverEffectProvider:
    """Capability router that makes Kernel ownership physically exclusive.

    For a cut-over capability this adapter never calls the fallback provider,
    including reconciliation/read-back. It consumes only the durable Kernel
    execution projection. Missing or unresolved Kernel state fails closed.
    Non-cut-over capabilities remain byte-for-byte on the legacy provider path.
    """

    def __init__(
        self,
        fallback: EffectProvider,
        bridge: KernelExecutionBridge,
    ) -> None:
        self.fallback = fallback
        self.bridge = bridge

    def execute(self, effect: EffectRecord, payload: dict[str, Any]) -> ProviderExecutionResult:
        del payload
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

        if status is KernelExecutionStatus.COMPLETED:
            intent = (
                self.bridge.repository.get_intent(projection.intent_id)
                if projection is not None
                else None
            )
            if intent is None:
                return self._unknown_observation(
                    effect,
                    provider_ref,
                    observed_at,
                    "kernel_intent_unavailable",
                )
            return RealityObservation(
                availability=ObservationAvailability.AVAILABLE,
                presence=ObservationPresence.PRESENT,
                freshness=ObservationFreshness.CURRENT,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                provider_ref=provider_ref,
                state=dict(intent.expected_postcondition),
                digest=projection.kernel_evidence_ref,
                observed_at=observed_at,
            )

        if status is KernelExecutionStatus.VERIFIED_FAIL:
            # Kernel already performed the authoritative independent read-back.
            # Preserve its negative judgment without fabricating a successful
            # local observation; the Admin verifier will deterministically
            # classify this sentinel state as a postcondition mismatch.
            return RealityObservation(
                availability=ObservationAvailability.AVAILABLE,
                presence=ObservationPresence.PRESENT,
                freshness=ObservationFreshness.CURRENT,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                provider_ref=provider_ref,
                state={"kernel_verified_fail": True},
                digest=(projection.kernel_evidence_ref if projection is not None else None),
                observed_at=observed_at,
            )

        return self._unknown_observation(
            effect,
            provider_ref,
            observed_at,
            "kernel_execution_not_verified",
        )

    def _kernel_owned(self, effect: EffectRecord) -> bool:
        return (
            self.bridge.cutover
            and _effect_capability(effect) in KERNEL_CUTOVER_CAPABILITIES
        )

    def _projection(self, effect: EffectRecord):
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
    def _provider_ref(projection) -> str | None:
        if projection is None:
            return "agent-kernel:unresolved"
        execution_ref = projection.kernel_execution_ref or "unresolved"
        provider_id = projection.kernel_provider_id or "unresolved"
        return f"agent-kernel:{provider_id}:{execution_ref}"

    @staticmethod
    def _unknown_observation(
        effect: EffectRecord,
        provider_ref: str | None,
        observed_at,
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
