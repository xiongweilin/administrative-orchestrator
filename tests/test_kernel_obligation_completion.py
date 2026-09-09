from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from administrative_orchestrator.domain import (
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import (
    ObservationAvailability,
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.evidence import KernelEvidenceView
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
)
from administrative_orchestrator.obligations import ObligationRepository
from administrative_orchestrator.onboarding_execution import OnboardingExecutionEngine
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)

FIXED_TIME = datetime(2026, 9, 9, 3, 45, tzinfo=UTC)


def _policy_ref() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v0.1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _authorized_case(store: SqlStore):
    uow = AdministrativeUnitOfWork(store)
    facts = OnboardingFacts(
        employee_ref="employee:kernel-completion",
        department_ref="department:engineering",
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
        requested_systems=("github",),
    )
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:kernel-completion",
    )
    original = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref=facts.employee_ref,
        fact_snapshot=FactSnapshot(
            source="ingress:test",
            owner="administrative-orchestrator",
            observed_at=FIXED_TIME,
            facts=facts.model_dump(mode="json"),
        ),
    )
    store.create_case(request, original)
    ready = start_policy_evaluation(original)
    evaluation = OnboardingPolicy(_policy_ref()).evaluate(facts)
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)
    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        authority_epoch=awaiting.authority_epoch,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=_policy_ref(),
        decided_at=FIXED_TIME,
    )
    authorized = record_decision(awaiting, decision)
    uow.apply_decision_transition(awaiting, authorized, decision)
    return authorized


class TrackingLegacyProvider:
    def __init__(self) -> None:
        self.execute_targets: list[str] = []
        self.observe_targets: list[str] = []
        self.observations: dict[str, RealityObservation] = {}

    def execute(self, effect, payload):
        self.execute_targets.append(effect.target_system)
        observation = RealityObservation(
            found=True,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"legacy:{effect.target_system}:{effect.effect_id}",
            state={"payload": dict(payload), "active": True},
            digest=f"legacy-digest:{effect.effect_id}",
            observed_at=FIXED_TIME,
        )
        self.observations[str(effect.effect_id)] = observation
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref=observation.provider_ref,
        )

    def observe(self, effect):
        self.observe_targets.append(effect.target_system)
        return self.observations.get(
            str(effect.effect_id),
            RealityObservation(
                found=False,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                observed_at=FIXED_TIME,
            ),
        )


class MutableKernelRepository:
    def __init__(self, store: SqlStore, *, case_id: UUID, authority_epoch: int) -> None:
        self.store = store
        self.case_id = case_id
        self.authority_epoch = authority_epoch
        self.completed_targets = {"hris"}
        self.kernel_observed_overrides: dict[str, dict[str, object]] = {}

    def _obligation_set(self):
        return ObligationRepository(self.store).get_current(
            self.case_id,
            self.authority_epoch,
        )

    def _obligation(self, obligation_id: UUID):
        obligation_set = self._obligation_set()
        if obligation_set is None:
            return None
        return next(
            (item for item in obligation_set.obligations if item.obligation_id == obligation_id),
            None,
        )

    @staticmethod
    def _intent_id(obligation_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"kernel-completion:intent:{obligation_id}")

    def _observed(self, obligation) -> dict[str, object]:
        override = self.kernel_observed_overrides.get(obligation.target_system)
        if override is not None:
            return dict(override)
        return dict(obligation.expected_postcondition)

    @staticmethod
    def _refs(target: str) -> dict[str, str]:
        return {
            "work": f"work:{target}:completed",
            "run": f"run:{target}:completed",
            "action": f"action:{target}:completed",
            "evidence": f"evidence:{target}:completed",
        }

    def get_projection_for_obligation(self, obligation_id: UUID):
        obligation = self._obligation(obligation_id)
        if obligation is None or obligation.target_system not in {"hris", "iam"}:
            return None
        if obligation.target_system not in self.completed_targets:
            return None
        target = obligation.target_system
        refs = self._refs(target)
        return SimpleNamespace(
            obligation_id=obligation_id,
            intent_id=self._intent_id(obligation_id),
            status=KernelProjectionStatus.CUTOVER,
            kernel_execution_status=KernelExecutionStatus.COMPLETED,
            kernel_execution_ref=f"execution:{target}:completed",
            kernel_provider_id=f"provider:{target}:kernel",
            kernel_execution_processed_at=FIXED_TIME,
            kernel_work_ref=refs["work"],
            kernel_run_ref=refs["run"],
            kernel_action_ref=refs["action"],
            kernel_evidence_ref=refs["evidence"],
        )

    def get_intent(self, intent_id: UUID):
        obligation_set = self._obligation_set()
        if obligation_set is None:
            return None
        for obligation in obligation_set.obligations:
            if self._intent_id(obligation.obligation_id) == intent_id:
                return SimpleNamespace(
                    intent_id=intent_id,
                    expected_postcondition=dict(obligation.expected_postcondition),
                )
        return None

    def evidence(self, evidence_ref: str) -> KernelEvidenceView | None:
        obligation_set = self._obligation_set()
        if obligation_set is None:
            return None
        for obligation in obligation_set.obligations:
            target = obligation.target_system
            if target not in self.completed_targets or target not in {"hris", "iam"}:
                continue
            refs = self._refs(target)
            if refs["evidence"] != evidence_ref:
                continue
            expected = dict(obligation.expected_postcondition)
            observed = self._observed(obligation)
            return KernelEvidenceView(
                evidence_ref=evidence_ref,
                action_ref=refs["action"],
                work_ref=refs["work"],
                run_ref=refs["run"],
                objective_result="pass",
                observed_postcondition=observed,
                expected_postcondition=expected,
                verification_request_ref=f"verification-request:{target}:completed",
                verification_attempt_ref=f"verification-attempt:{target}:completed",
                verifier_provider_id=f"verifier:{target}:readback",
                verifier_provider_execution_binding_ref=f"binding:{target}:readback",
                captured_at=FIXED_TIME,
            )
        return None


class MutableKernelEvidenceClient:
    def __init__(self, repository: MutableKernelRepository) -> None:
        self.repository = repository

    def inspect(self, evidence_ref: str):
        return self.repository.evidence(evidence_ref)


class MutableKernelBridge:
    cutover = True

    def __init__(self, repository: MutableKernelRepository) -> None:
        self.repository = repository
        self._evidence_client = MutableKernelEvidenceClient(repository)

    def evidence_client(self):
        return self._evidence_client


def _provider(store: SqlStore, authorized):
    kernel_repository = MutableKernelRepository(
        store,
        case_id=authorized.case_id,
        authority_epoch=authorized.authority_epoch,
    )
    legacy = TrackingLegacyProvider()
    provider = KernelCutoverEffectProvider(
        legacy,
        MutableKernelBridge(kernel_repository),
    )
    return kernel_repository, legacy, provider


def test_kernel_hris_completion_cannot_discharge_case_before_iam_is_confirmed() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authorized = _authorized_case(store)
    kernel_repository, legacy, provider = _provider(store, authorized)
    engine = OnboardingExecutionEngine(store, provider)

    partial = engine.run(authorized.case_id)

    assert partial.status is CaseStatus.RECONCILING
    execution_repository = ExecutionRepository(store)
    effects = execution_repository.list_effects(partial.case_id, partial.authority_epoch)
    obligation_set = ObligationRepository(store).get_current(
        partial.case_id,
        partial.authority_epoch,
    )
    assert obligation_set is not None
    hris_effect = next(item for item in effects if item.target_system == "hris")
    hris_obligation = next(
        item for item in obligation_set.obligations if item.target_system == "hris"
    )
    iam_effect = next(item for item in effects if item.target_system == "iam")
    iam_obligation = next(
        item for item in obligation_set.obligations if item.target_system == "iam"
    )
    assert hris_effect.obligation_id == hris_obligation.obligation_id
    assert hris_effect.governance_basis_id == hris_obligation.governance_basis_id
    assert iam_effect.obligation_id == iam_obligation.obligation_id
    assert iam_effect.governance_basis_id == iam_obligation.governance_basis_id

    hris_observation = provider.observe(hris_effect)
    hris_verification = verify_onboarding_observation(
        hris_effect,
        hris_observation,
        partial.fact_snapshot.facts if partial.fact_snapshot else {},
        expected_postcondition=hris_obligation.expected_postcondition,
    )
    assert hris_observation.availability is ObservationAvailability.AVAILABLE, (
        hris_observation.model_dump(mode="json")
    )
    assert hris_verification.disposition is VerificationDisposition.VERIFIED, (
        hris_verification.model_dump(mode="json")
    )

    outcomes = execution_repository.list_outcomes(
        partial.case_id,
        partial.authority_epoch,
    )
    outcome_kinds = {item.outcome_kind for item in outcomes}
    assert "hris.employee.create.verified" in outcome_kinds
    assert "iam.identity.create.verified" not in outcome_kinds
    assert "github.account.provision.verified" in outcome_kinds
    assert "hris" not in legacy.execute_targets
    assert "iam" not in legacy.execute_targets
    assert "hris" not in legacy.observe_targets
    assert "iam" not in legacy.observe_targets
    assert legacy.execute_targets == ["github"]

    kernel_repository.completed_targets.add("iam")
    completed = engine.run(authorized.case_id)

    assert completed.status is CaseStatus.COMPLETED
    completed_outcomes = execution_repository.list_outcomes(
        completed.case_id,
        completed.authority_epoch,
    )
    completed_kinds = {item.outcome_kind for item in completed_outcomes}
    assert {
        "hris.employee.create.verified",
        "iam.identity.create.verified",
        "github.account.provision.verified",
    }.issubset(completed_kinds)
    assert "hris" not in legacy.execute_targets
    assert "iam" not in legacy.execute_targets
    assert "hris" not in legacy.observe_targets
    assert "iam" not in legacy.observe_targets
    assert legacy.execute_targets == ["github"]


def test_kernel_completed_with_different_reality_cannot_discharge_admin_obligation() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authorized = _authorized_case(store)
    kernel_repository, legacy, provider = _provider(store, authorized)
    engine = OnboardingExecutionEngine(store, provider)

    # First drive materializes the governed obligation/effect set while Kernel
    # reports no completed execution. This gives us the frozen Administrative
    # postcondition before introducing a different independent reality readback.
    kernel_repository.completed_targets.clear()
    partial = engine.run(authorized.case_id)
    assert partial.status is CaseStatus.RECONCILING

    obligation_set = ObligationRepository(store).get_current(
        partial.case_id,
        partial.authority_epoch,
    )
    assert obligation_set is not None
    hris_obligation = next(
        item for item in obligation_set.obligations if item.target_system == "hris"
    )
    observed = dict(hris_obligation.expected_postcondition)
    payload = dict(observed["payload"])
    payload["department_ref"] = "department:finance"
    observed["payload"] = payload
    kernel_repository.kernel_observed_overrides["hris"] = observed
    kernel_repository.completed_targets.update({"hris", "iam"})

    result = engine.run(authorized.case_id)

    assert result.status is CaseStatus.RECONCILING
    outcomes = ExecutionRepository(store).list_outcomes(
        result.case_id,
        result.authority_epoch,
    )
    outcome_kinds = {item.outcome_kind for item in outcomes}
    assert "hris.employee.create.verified" not in outcome_kinds
    assert "iam.identity.create.verified" in outcome_kinds
    assert "github.account.provision.verified" in outcome_kinds
    assert "hris" not in legacy.execute_targets
    assert "iam" not in legacy.execute_targets
    assert "hris" not in legacy.observe_targets
    assert "iam" not in legacy.observe_targets
