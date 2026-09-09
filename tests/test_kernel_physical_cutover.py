from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from administrative_orchestrator.domain import (
    AuthorityClass,
    EffectRecord,
    EffectReversibility,
)
from administrative_orchestrator.effect_provider import (
    ObservationAvailability,
    ObservationFreshness,
    ObservationPresence,
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
)
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)

NOW = datetime(2026, 9, 9, 2, 0, tzinfo=UTC)


class CountingLegacyProvider:
    def __init__(self) -> None:
        self.execute_calls: list[str] = []
        self.observe_calls: list[str] = []

    def execute(self, effect: EffectRecord, payload: dict) -> ProviderExecutionResult:
        del payload
        self.execute_calls.append(f"{effect.target_system}.{effect.operation}")
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref=f"legacy:{effect.target_system}",
        )

    def observe(self, effect: EffectRecord) -> RealityObservation:
        self.observe_calls.append(f"{effect.target_system}.{effect.operation}")
        return RealityObservation(
            availability=ObservationAvailability.AVAILABLE,
            presence=ObservationPresence.PRESENT,
            freshness=ObservationFreshness.CURRENT,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"legacy:{effect.target_system}",
            state={"active": True},
            observed_at=NOW,
        )


class FakeKernelRepository:
    def __init__(self, projection, intent) -> None:
        self.projection = projection
        self.intent = intent

    def get_projection_for_obligation(self, obligation_id):
        if self.projection is None or self.projection.obligation_id != obligation_id:
            return None
        return self.projection

    def get_intent(self, intent_id):
        if self.intent is None or self.intent.intent_id != intent_id:
            return None
        return self.intent


class FakeKernelBridge:
    cutover = True

    def __init__(self, projection, intent) -> None:
        self.repository = FakeKernelRepository(projection, intent)


def _effect(*, target: str, operation: str, obligation_id=None) -> EffectRecord:
    return EffectRecord(
        effect_id=uuid4(),
        case_id=uuid4(),
        case_version=3,
        authority_epoch=2,
        authorization_id=uuid4(),
        obligation_id=obligation_id or uuid4(),
        governance_basis_id=uuid4(),
        target_system=target,
        operation=operation,
        subject_ref="employee:new",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.EMPLOYMENT,
        created_at=NOW,
        updated_at=NOW,
    )


def test_hris_cutover_never_calls_legacy_execute_or_observe_but_iam_still_delegates() -> None:
    obligation_id = uuid4()
    intent_id = uuid4()
    expected = {
        "target_system": "hris",
        "operation": "employee.create",
        "subject_ref": "employee:new",
        "active": True,
        "payload": {
            "employee_ref": "employee:new",
            "department_ref": "department:engineering",
        },
    }
    projection = SimpleNamespace(
        obligation_id=obligation_id,
        intent_id=intent_id,
        status=KernelProjectionStatus.CUTOVER,
        kernel_execution_status=KernelExecutionStatus.COMPLETED,
        kernel_execution_ref="execution:hris:1",
        kernel_provider_id="provider:hris:kernel",
        kernel_execution_processed_at=NOW,
        kernel_evidence_ref="evidence:hris:kernel:1",
    )
    intent = SimpleNamespace(intent_id=intent_id, expected_postcondition=expected)
    legacy = CountingLegacyProvider()
    provider = KernelCutoverEffectProvider(legacy, FakeKernelBridge(projection, intent))

    hris = _effect(
        target="hris",
        operation="employee.create",
        obligation_id=obligation_id,
    )
    result = provider.execute(hris, expected["payload"])
    observation = provider.observe(hris)
    verification = verify_onboarding_observation(
        hris,
        observation,
        expected["payload"],
        expected_postcondition=expected,
    )

    assert result.status is ProviderExecutionStatus.SUCCEEDED
    assert result.provider_ref == "agent-kernel:provider:hris:kernel:execution:hris:1"
    assert verification.disposition is VerificationDisposition.VERIFIED
    assert legacy.execute_calls == []
    assert legacy.observe_calls == []

    iam = _effect(target="iam", operation="identity.create")
    assert provider.execute(iam, {}).status is ProviderExecutionStatus.SUCCEEDED
    assert provider.observe(iam).provider_ref == "legacy:iam"
    assert legacy.execute_calls == ["iam.identity.create"]
    assert legacy.observe_calls == ["iam.identity.create"]


def test_missing_kernel_receipt_fails_closed_without_local_fallback() -> None:
    legacy = CountingLegacyProvider()
    provider = KernelCutoverEffectProvider(legacy, FakeKernelBridge(None, None))
    hris = _effect(target="hris", operation="employee.create")

    result = provider.execute(hris, {"employee_ref": "employee:new"})
    observation = provider.observe(hris)

    assert result.status is ProviderExecutionStatus.OUTCOME_UNKNOWN
    assert result.retryable is False
    assert "local fallback forbidden" in (result.error or "")
    assert observation.availability is ObservationAvailability.UNKNOWN
    assert legacy.execute_calls == []
    assert legacy.observe_calls == []
