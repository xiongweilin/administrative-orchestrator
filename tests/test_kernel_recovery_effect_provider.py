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
    ProviderExecutionStatus,
)
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.evidence import KernelEvidenceView
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
)
from administrative_orchestrator.integrations.kernel.recovery import KernelExecutionResolution

NOW = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)
EXPECTED = {
    "target_system": "hris",
    "operation": "employee.create",
    "subject_ref": "employee:ambiguous-recovery",
    "active": True,
    "payload": {
        "employee_ref": "employee:ambiguous-recovery",
        "department_ref": "department:engineering",
    },
}


class ForbiddenLegacyProvider:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.observe_calls = 0

    def execute(self, effect, payload):
        del effect, payload
        self.execute_calls += 1
        raise AssertionError("legacy execute fallback must remain forbidden")

    def observe(self, effect):
        del effect
        self.observe_calls += 1
        raise AssertionError("legacy observe fallback must remain forbidden")


class FakeRecoveryClient:
    def __init__(self, resolution: KernelExecutionResolution | None) -> None:
        self.resolution = resolution
        self.recover_calls = 0
        self.inspect_calls = 0

    def recover(self, execution_ref: str, *, expected_work_ref: str | None = None):
        self.recover_calls += 1
        assert execution_ref == "execution:ambiguous"
        assert expected_work_ref == "work:ambiguous"
        assert self.resolution is not None
        return self.resolution

    def inspect(self, execution_ref: str, *, expected_work_ref: str | None = None):
        self.inspect_calls += 1
        assert execution_ref == "execution:ambiguous"
        assert expected_work_ref == "work:ambiguous"
        return self.resolution


class FakeEvidenceClient:
    def __init__(self, evidence: KernelEvidenceView) -> None:
        self.evidence = evidence
        self.calls = 0

    def inspect(self, evidence_ref: str):
        self.calls += 1
        assert evidence_ref == self.evidence.evidence_ref
        return self.evidence


class FakeRepository:
    def __init__(self, projection, intent) -> None:
        self.projection = projection
        self.intent = intent

    def get_projection_for_obligation(self, obligation_id):
        assert obligation_id == self.projection.obligation_id
        return self.projection

    def get_intent(self, intent_id):
        assert intent_id == self.projection.intent_id
        return self.intent


class FakeBridge:
    cutover = True

    def __init__(self, projection, resolution: KernelExecutionResolution) -> None:
        self.repository = FakeRepository(
            projection,
            SimpleNamespace(expected_postcondition=dict(EXPECTED)),
        )
        self._recovery = FakeRecoveryClient(resolution)
        self._evidence = FakeEvidenceClient(
            KernelEvidenceView(
                evidence_ref="evidence:ambiguous",
                action_ref="action:ambiguous",
                work_ref="work:ambiguous",
                run_ref="run:ambiguous",
                objective_result="pass",
                observed_postcondition=dict(EXPECTED),
                expected_postcondition=dict(EXPECTED),
                verification_request_ref="verification-request:ambiguous",
                verification_attempt_ref="verification-attempt:ambiguous",
                verifier_provider_id="provider:hris:readback",
                verifier_provider_execution_binding_ref="binding:hris:readback",
                captured_at=NOW,
            )
        )

    def recovery_client(self):
        return self._recovery

    def evidence_client(self):
        return self._evidence


def _projection():
    obligation_id = uuid4()
    intent_id = uuid4()
    return SimpleNamespace(
        obligation_id=obligation_id,
        intent_id=intent_id,
        status=KernelProjectionStatus.ADMITTED,
        kernel_execution_status=KernelExecutionStatus.EXECUTION_UNKNOWN,
        kernel_execution_ref="execution:ambiguous",
        kernel_execution_processed_at=NOW,
        kernel_provider_id="provider:hris:kernel",
        kernel_work_ref="work:ambiguous",
        kernel_run_ref="run:ambiguous",
        kernel_request_ref="request:ambiguous",
        kernel_action_ref="action:ambiguous",
        kernel_evidence_ref=None,
    )


def _resolution(status: str = "recovered-completed") -> KernelExecutionResolution:
    return KernelExecutionResolution(
        execution_ref="execution:ambiguous",
        original_status="execution-unknown",
        current_status=status,
        work_ref="work:ambiguous",
        run_ref="run:ambiguous",
        request_ref="request:ambiguous",
        recovery_observation_ref="recovery-observation:ambiguous",
        recovery_disposition_ref="recovery-disposition:ambiguous",
        recovery_application_ref="recovery-application:ambiguous",
        outcome_ref="outcome:ambiguous",
        evidence_ref="evidence:ambiguous" if status == "recovered-completed" else None,
        responsibility_ref="responsibility:ambiguous",
        reason="test recovery",
        processed_at=NOW,
    )


def _effect(projection) -> EffectRecord:
    return EffectRecord(
        effect_id=uuid4(),
        case_id=uuid4(),
        case_version=1,
        authority_epoch=1,
        authorization_id=uuid4(),
        obligation_id=projection.obligation_id,
        governance_basis_id=uuid4(),
        target_system="hris",
        operation="employee.create",
        subject_ref="employee:ambiguous-recovery",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.EMPLOYMENT,
        created_at=NOW,
        updated_at=NOW,
    )


def test_unknown_execution_consumes_kernel_recovery_and_evidence_without_mutating_history() -> None:
    projection = _projection()
    bridge = FakeBridge(projection, _resolution())
    legacy = ForbiddenLegacyProvider()
    provider = KernelCutoverEffectProvider(legacy, bridge)
    effect = _effect(projection)

    execution = provider.execute(effect, dict(EXPECTED["payload"]))
    observation = provider.observe(effect)

    assert execution.status is ProviderExecutionStatus.SUCCEEDED
    assert observation.availability is ObservationAvailability.AVAILABLE
    assert observation.state == EXPECTED
    assert projection.kernel_execution_status is KernelExecutionStatus.EXECUTION_UNKNOWN
    assert projection.kernel_evidence_ref is None
    assert bridge._recovery.recover_calls == 1
    assert bridge._recovery.inspect_calls == 1
    assert bridge._evidence.calls == 1
    assert legacy.execute_calls == 0
    assert legacy.observe_calls == 0


def test_recovery_that_does_not_establish_success_stays_nonretryable_and_never_falls_back() -> None:
    projection = _projection()
    bridge = FakeBridge(projection, _resolution("recovered-failed"))
    legacy = ForbiddenLegacyProvider()
    provider = KernelCutoverEffectProvider(legacy, bridge)

    execution = provider.execute(_effect(projection), {})

    assert execution.status is ProviderExecutionStatus.FAILED
    assert execution.retryable is False
    assert bridge._recovery.recover_calls == 1
    assert legacy.execute_calls == 0


def test_rejected_work_admission_is_definitive_failure_and_never_falls_back() -> None:
    projection = _projection()
    projection.status = KernelProjectionStatus.REJECTED
    projection.kernel_work_admission_status = "portfolio-rejected"
    projection.kernel_execution_status = None
    projection.kernel_execution_ref = None
    bridge = FakeBridge(projection, _resolution())
    legacy = ForbiddenLegacyProvider()
    provider = KernelCutoverEffectProvider(legacy, bridge)

    execution = provider.execute(_effect(projection), {})

    assert execution.status is ProviderExecutionStatus.FAILED
    assert execution.retryable is False
    assert "portfolio-rejected" in (execution.error or "")
    assert legacy.execute_calls == 0
