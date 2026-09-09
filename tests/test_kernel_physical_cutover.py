from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

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
from administrative_orchestrator.integrations.kernel.evidence import KernelEvidenceView
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
    def __init__(self, projections, intents) -> None:
        self.projections = {item.obligation_id: item for item in projections}
        self.intents = {item.intent_id: item for item in intents}

    def get_projection_for_obligation(self, obligation_id: UUID):
        return self.projections.get(obligation_id)

    def get_intent(self, intent_id: UUID):
        return self.intents.get(intent_id)


class FakeEvidenceClient:
    def __init__(self, evidence=()) -> None:
        self.evidence = {item.evidence_ref: item for item in evidence}

    def inspect(self, evidence_ref: str):
        return self.evidence.get(evidence_ref)


class FakeKernelBridge:
    cutover = True

    def __init__(self, projections=(), intents=(), evidence=()) -> None:
        self.repository = FakeKernelRepository(projections, intents)
        self._evidence_client = FakeEvidenceClient(evidence)

    def evidence_client(self):
        return self._evidence_client


def _effect(
    *,
    target: str,
    operation: str,
    obligation_id: UUID | None = None,
    authority_class: AuthorityClass = AuthorityClass.EMPLOYMENT,
) -> EffectRecord:
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
        authority_class=authority_class,
        created_at=NOW,
        updated_at=NOW,
    )


def _completed_projection(*, obligation_id: UUID, target: str, operation: str):
    intent_id = uuid4()
    expected = {
        "target_system": target,
        "operation": operation,
        "subject_ref": "employee:new",
        "active": True,
        "payload": {
            "employee_ref": "employee:new",
            "department_ref": "department:engineering",
        },
    }
    work_ref = f"work:{target}:1"
    run_ref = f"run:{target}:1"
    action_ref = f"action:{target}:1"
    evidence_ref = f"evidence:{target}:kernel:1"
    projection = SimpleNamespace(
        obligation_id=obligation_id,
        intent_id=intent_id,
        status=KernelProjectionStatus.CUTOVER,
        kernel_execution_status=KernelExecutionStatus.COMPLETED,
        kernel_execution_ref=f"execution:{target}:1",
        kernel_provider_id=f"provider:{target}:kernel",
        kernel_execution_processed_at=NOW,
        kernel_work_ref=work_ref,
        kernel_run_ref=run_ref,
        kernel_action_ref=action_ref,
        kernel_evidence_ref=evidence_ref,
    )
    intent = SimpleNamespace(intent_id=intent_id, expected_postcondition=expected)
    evidence = KernelEvidenceView(
        evidence_ref=evidence_ref,
        action_ref=action_ref,
        work_ref=work_ref,
        run_ref=run_ref,
        objective_result="pass",
        observed_postcondition=dict(expected),
        expected_postcondition=dict(expected),
        verification_request_ref=f"verification-request:{target}:1",
        verification_attempt_ref=f"verification-attempt:{target}:1",
        verifier_provider_id=f"verifier:{target}:readback",
        verifier_provider_execution_binding_ref=f"binding:{target}:readback:1",
        captured_at=NOW,
    )
    return projection, intent, evidence, expected


def test_hris_and_iam_cutover_never_call_legacy_execute_or_observe() -> None:
    hris_obligation_id = uuid4()
    iam_obligation_id = uuid4()
    hris_projection, hris_intent, hris_evidence, hris_expected = _completed_projection(
        obligation_id=hris_obligation_id,
        target="hris",
        operation="employee.create",
    )
    iam_projection, iam_intent, iam_evidence, iam_expected = _completed_projection(
        obligation_id=iam_obligation_id,
        target="iam",
        operation="identity.create",
    )
    legacy = CountingLegacyProvider()
    provider = KernelCutoverEffectProvider(
        legacy,
        FakeKernelBridge(
            projections=(hris_projection, iam_projection),
            intents=(hris_intent, iam_intent),
            evidence=(hris_evidence, iam_evidence),
        ),
    )

    cases = (
        (
            _effect(
                target="hris",
                operation="employee.create",
                obligation_id=hris_obligation_id,
            ),
            hris_expected,
            "agent-kernel:provider:hris:kernel:execution:hris:1",
        ),
        (
            _effect(
                target="iam",
                operation="identity.create",
                obligation_id=iam_obligation_id,
                authority_class=AuthorityClass.PRIVILEGED_ACCESS,
            ),
            iam_expected,
            "agent-kernel:provider:iam:kernel:execution:iam:1",
        ),
    )

    for effect, expected, provider_ref in cases:
        result = provider.execute(effect, expected["payload"])
        observation = provider.observe(effect)
        verification = verify_onboarding_observation(
            effect,
            observation,
            expected["payload"],
            expected_postcondition=expected,
        )

        assert result.status is ProviderExecutionStatus.SUCCEEDED
        assert result.provider_ref == provider_ref
        assert observation.digest is not None
        assert observation.provider_ref is not None
        assert observation.provider_ref.startswith("agent-kernel-verifier:")
        assert observation.state == expected
        assert verification.disposition is VerificationDisposition.VERIFIED

    assert legacy.execute_calls == []
    assert legacy.observe_calls == []


def test_kernel_completed_does_not_override_admin_business_mismatch() -> None:
    obligation_id = uuid4()
    projection, intent, evidence, kernel_expected = _completed_projection(
        obligation_id=obligation_id,
        target="hris",
        operation="employee.create",
    )
    admin_expected = {
        **kernel_expected,
        "payload": {
            **kernel_expected["payload"],
            "department_ref": "department:finance",
        },
    }
    legacy = CountingLegacyProvider()
    provider = KernelCutoverEffectProvider(
        legacy,
        FakeKernelBridge(
            projections=(projection,),
            intents=(intent,),
            evidence=(evidence,),
        ),
    )
    effect = _effect(
        target="hris",
        operation="employee.create",
        obligation_id=obligation_id,
    )

    execution = provider.execute(effect, dict(kernel_expected["payload"]))
    observation = provider.observe(effect)
    verification = verify_onboarding_observation(
        effect,
        observation,
        expected_postcondition=admin_expected,
    )

    assert execution.status is ProviderExecutionStatus.SUCCEEDED
    assert observation.state == kernel_expected
    assert verification.disposition is VerificationDisposition.MISMATCH
    assert verification.differences["payload.department_ref"] == {
        "expected": "department:finance",
        "actual": "department:engineering",
    }
    assert legacy.execute_calls == []
    assert legacy.observe_calls == []


def test_rebound_or_missing_kernel_evidence_fails_closed_without_legacy_fallback() -> None:
    obligation_id = uuid4()
    projection, intent, evidence, expected = _completed_projection(
        obligation_id=obligation_id,
        target="hris",
        operation="employee.create",
    )
    effect = _effect(
        target="hris",
        operation="employee.create",
        obligation_id=obligation_id,
    )
    legacy = CountingLegacyProvider()

    missing_provider = KernelCutoverEffectProvider(
        legacy,
        FakeKernelBridge(projections=(projection,), intents=(intent,)),
    )
    missing = missing_provider.observe(effect)
    assert missing.availability is ObservationAvailability.UNKNOWN
    assert missing.error_class == "kernel_evidence_unavailable"

    rebound = replace(evidence, work_ref="work:rebound")
    rebound_provider = KernelCutoverEffectProvider(
        legacy,
        FakeKernelBridge(
            projections=(projection,),
            intents=(intent,),
            evidence=(rebound,),
        ),
    )
    rebound_observation = rebound_provider.observe(effect)
    assert rebound_observation.availability is ObservationAvailability.UNKNOWN
    assert rebound_observation.error_class == "kernel_evidence_work_identity_rebound"
    assert legacy.execute_calls == []
    assert legacy.observe_calls == []
    assert expected["active"] is True


def test_missing_kernel_receipt_fails_closed_for_both_cutover_capabilities() -> None:
    legacy = CountingLegacyProvider()
    provider = KernelCutoverEffectProvider(legacy, FakeKernelBridge())

    effects = (
        _effect(target="hris", operation="employee.create"),
        _effect(
            target="iam",
            operation="identity.create",
            authority_class=AuthorityClass.PRIVILEGED_ACCESS,
        ),
    )
    for effect in effects:
        result = provider.execute(effect, {"employee_ref": "employee:new"})
        observation = provider.observe(effect)

        assert result.status is ProviderExecutionStatus.OUTCOME_UNKNOWN
        assert result.retryable is False
        assert "local fallback forbidden" in (result.error or "")
        assert observation.availability is ObservationAvailability.UNKNOWN

    assert legacy.execute_calls == []
    assert legacy.observe_calls == []
