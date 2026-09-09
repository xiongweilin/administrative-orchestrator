from __future__ import annotations

from types import SimpleNamespace

from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
)
from administrative_orchestrator.integrations.kernel.recovery import KernelExecutionResolution
from administrative_orchestrator.onboarding_execution import OnboardingExecutionEngine
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.domain import CaseStatus
from tests.test_kernel_obligation_completion import (
    FIXED_TIME,
    MutableKernelBridge,
    MutableKernelRepository,
    TrackingLegacyProvider,
    _authorized_case,
)


class RecoveringKernelRepository(MutableKernelRepository):
    def get_projection_for_obligation(self, obligation_id):
        projection = super().get_projection_for_obligation(obligation_id)
        obligation = self._obligation(obligation_id)
        if projection is None or obligation is None or obligation.target_system != "hris":
            return projection
        # Historical Administrative projection remains the original ambiguous
        # Kernel execution fact even after current Kernel resolution succeeds.
        return SimpleNamespace(
            **{
                **vars(projection),
                "status": KernelProjectionStatus.ADMITTED,
                "kernel_execution_status": KernelExecutionStatus.EXECUTION_UNKNOWN,
                "kernel_evidence_ref": None,
            }
        )


class RecoveryClient:
    def __init__(self, repository: RecoveringKernelRepository) -> None:
        self.repository = repository
        self.recover_calls = 0
        self.inspect_calls = 0

    def _resolution(self, execution_ref: str, expected_work_ref: str | None):
        self.recover_calls += 0
        if not execution_ref.startswith("execution:hris:"):
            return None
        refs = self.repository._refs("hris")
        assert expected_work_ref == refs["work"]
        return KernelExecutionResolution(
            execution_ref=execution_ref,
            original_status="execution-unknown",
            current_status="recovered-completed",
            work_ref=refs["work"],
            run_ref=refs["run"],
            request_ref="request:hris:ambiguous",
            recovery_observation_ref="recovery-observation:hris",
            recovery_disposition_ref="recovery-disposition:hris",
            recovery_application_ref="recovery-application:hris",
            outcome_ref="outcome:hris:recovered",
            evidence_ref=refs["evidence"],
            responsibility_ref="responsibility:hris:recovered",
            reason="test exact-authority recovery",
            processed_at=FIXED_TIME,
        )

    def recover(self, execution_ref: str, *, expected_work_ref: str | None = None):
        self.recover_calls += 1
        resolution = self._resolution(execution_ref, expected_work_ref)
        assert resolution is not None
        return resolution

    def inspect(self, execution_ref: str, *, expected_work_ref: str | None = None):
        self.inspect_calls += 1
        return self._resolution(execution_ref, expected_work_ref)


class RecoveringKernelBridge(MutableKernelBridge):
    def __init__(self, repository: RecoveringKernelRepository) -> None:
        super().__init__(repository)
        self._recovery_client = RecoveryClient(repository)

    def recovery_client(self):
        return self._recovery_client


def test_recovered_kernel_unknown_creates_admin_outcome_and_completes_case() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authorized = _authorized_case(store)
    repository = RecoveringKernelRepository(
        store,
        case_id=authorized.case_id,
        authority_epoch=authorized.authority_epoch,
    )
    repository.completed_targets.update({"hris", "iam"})
    bridge = RecoveringKernelBridge(repository)
    legacy = TrackingLegacyProvider()
    provider = KernelCutoverEffectProvider(legacy, bridge)

    completed = OnboardingExecutionEngine(store, provider).run(authorized.case_id)

    assert completed.status is CaseStatus.COMPLETED
    outcomes = ExecutionRepository(store).list_outcomes(
        completed.case_id,
        completed.authority_epoch,
    )
    outcome_kinds = {outcome.outcome_kind for outcome in outcomes}
    assert {
        "hris.employee.create.verified",
        "iam.identity.create.verified",
        "github.account.provision.verified",
    }.issubset(outcome_kinds)

    obligation_set = repository._obligation_set()
    assert obligation_set is not None
    hris = next(item for item in obligation_set.obligations if item.target_system == "hris")
    historical = repository.get_projection_for_obligation(hris.obligation_id)
    assert historical is not None
    assert historical.status is KernelProjectionStatus.ADMITTED
    assert historical.kernel_execution_status is KernelExecutionStatus.EXECUTION_UNKNOWN
    assert historical.kernel_evidence_ref is None

    assert bridge._recovery_client.recover_calls == 1
    assert bridge._recovery_client.inspect_calls >= 1
    assert "hris" not in legacy.execute_targets
    assert "iam" not in legacy.execute_targets
    assert "hris" not in legacy.observe_targets
    assert "iam" not in legacy.observe_targets
    assert legacy.execute_targets == ["github"]
