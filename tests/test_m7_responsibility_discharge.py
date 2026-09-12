from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from administrative_orchestrator.authority import AuthorityRepository
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    ConfirmedOutcome,
    EffectRealizationAssessment,
    EffectRecord,
    EffectReversibility,
    EffectStatus,
    EvidenceRef,
    ExecutionAuthorization,
    PolicyRef,
    RealizationDisposition,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.governance import GovernanceRepository
from administrative_orchestrator.integrations.kernel.client import (
    KernelResponsibilityAssessmentReceipt,
    KernelResponsibilityDischargeDecisionReceipt,
    KernelResponsibilityDischargeError,
    KernelResponsibilityLifecycleTransitionReceipt,
    KernelResponsibilityStatusView,
)
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
    KernelShadowProjection,
    KernelWorkAdmissionStatus,
)
from administrative_orchestrator.integrations.kernel.recovery import KernelRecoveryError
from administrative_orchestrator.obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationRepository,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.responsibility_discharge import (
    AdministrativeResponsibilityDischargeService,
    ResponsibilityDischargeStatus,
    ResponsibilityHandle,
)

NOW = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)


def _fixture(*, with_completion: bool = True):
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    policy = PolicyRef(
        policy_id="employee-offboarding",
        version="v1",
        owner="administrative-orchestrator",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="offboard employee:1",
        received_at=NOW,
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref="employee:1",
        status=CaseStatus.COMPLETED,
        version=4,
        authority_epoch=2,
        policy_ref=policy,
        updated_at=NOW,
    )
    store.create_case(request, case)

    governance_basis_id = uuid4()
    obligation = AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        kind="iam.identity.disable",
        subject_ref=case.subject_ref,
        target_system="iam",
        required_operation="identity.disable",
        expected_postcondition={"enabled": False},
        authority_class=AuthorityClass.PRIVILEGED_ACCESS,
    )
    obligation_set = AdministrativeObligationSet(
        requirement_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        obligations=(obligation,),
    )
    obligations = ObligationRepository(store)
    obligations.put(obligation_set)

    if with_completion:
        authorization = ExecutionAuthorization(
            case_id=case.case_id,
            case_version=case.version,
            authority_epoch=case.authority_epoch,
            approval_satisfaction_id=uuid4(),
            issuer_principal_id="service:administrative-orchestrator",
            target_system="iam",
            subject_ref=case.subject_ref,
            allowed_operations=("identity.disable",),
            authority_class=obligation.authority_class,
            policy_ref=policy,
            issued_at=NOW,
        )
        execution = ExecutionRepository(store)
        execution.put_authorization(authorization)
        effect = EffectRecord(
            case_id=case.case_id,
            case_version=case.version,
            authority_epoch=case.authority_epoch,
            authorization_id=authorization.authorization_id,
            obligation_id=obligation.obligation_id,
            governance_basis_id=governance_basis_id,
            target_system=obligation.target_system,
            operation=obligation.required_operation,
            subject_ref=obligation.subject_ref,
            reversibility=EffectReversibility.IRREVERSIBLE,
            authority_class=obligation.authority_class,
            status=EffectStatus.SUCCEEDED,
            created_at=NOW,
            updated_at=NOW,
        )
        execution.put_effect(effect)
        obligations.link_effect(effect, obligation)
        evidence = EvidenceRef(
            source="test-verifier",
            owner="test",
            observed_at=NOW,
            digest="digest:1",
        )
        realization = EffectRealizationAssessment(
            effect_id=effect.effect_id,
            disposition=RealizationDisposition.VERIFIED,
            evidence=[evidence],
            assessed_at=NOW,
        )
        execution.put_realization(realization, case_id=case.case_id)
        execution.put_outcome(
            ConfirmedOutcome(
                case_id=case.case_id,
                case_version=case.version,
                authority_epoch=case.authority_epoch,
                effect_id=effect.effect_id,
                realization_assessment_id=realization.assessment_id,
                outcome_kind="iam.identity.disable.verified",
                evidence=[evidence],
                confirmed_at=NOW,
            )
        )
    return store, case, obligation


def _projection(case, obligation_id, *, ref: str, epoch: int | None = None):
    return KernelShadowProjection(
        projection_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=epoch or case.authority_epoch,
        grant_id=uuid4(),
        intent_id=uuid4(),
        obligation_id=obligation_id,
        contract_catalog="portable-runtime-contracts-v1",
        runtime_protocol="2.0",
        persistent_responsibility_contract="persistent-responsibility-v1",
        responsibility_payload={"id": ref, "object_type": "StandingResponsibility"},
        admission_payload={"id": f"admission:{ref}", "responsibility_version": 1},
        assessment_payload={"id": f"assessment:{ref}"},
        work_proposal_payload={"id": f"proposal:{ref}"},
        status=KernelProjectionStatus.CUTOVER,
        kernel_responsibility_ref=ref,
        kernel_admission_ref=f"admission:{ref}",
        kernel_assessment_ref=f"assessment:{ref}",
        kernel_proposal_ref=f"proposal:{ref}",
        kernel_work_admission_status=KernelWorkAdmissionStatus.WORK_MATERIALIZED,
        kernel_admission_policy_ref="policy:admission",
        kernel_priority_judgment_ref=f"priority:{ref}",
        kernel_resource_pool_ref=f"pool:{ref}",
        kernel_portfolio_admission_ref=f"portfolio:{ref}",
        kernel_reservation_ref=f"reservation:{ref}",
        kernel_commitment_ref=f"commitment:{ref}",
        kernel_work_ref=f"work:{ref}",
        kernel_execution_status=KernelExecutionStatus.COMPLETED,
        kernel_execution_ref=f"execution:{ref}",
        kernel_run_ref=f"run:{ref}",
        kernel_request_ref=f"request:{ref}",
        kernel_authorization_ref=f"authorization:{ref}",
        kernel_provider_id="provider:kernel",
        kernel_action_ref=f"action:{ref}",
        kernel_outcome_ref=f"outcome:{ref}",
        kernel_evidence_ref=f"evidence:{ref}",
        kernel_execution_responsibility_ref=ref,
        kernel_execution_processed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


class _Client:
    def __init__(self, *, statuses: dict[str, str] | None = None, fail_ref: str | None = None):
        self.statuses = statuses or {}
        self.fail_ref = fail_ref
        self.assessment_calls: list[str] = []
        self.decision_calls: list[str] = []
        self.transition_calls: list[str] = []
        self.status_calls: list[str] = []

    def get_responsibility_status(self, responsibility_ref, *, expected_version):
        del expected_version
        self.status_calls.append(responsibility_ref)
        if responsibility_ref == self.fail_ref:
            raise KernelResponsibilityDischargeError("simulated unavailable status")
        return KernelResponsibilityStatusView(
            responsibility_ref=responsibility_ref,
            responsibility_version=1,
            current_status=self.statuses.get(responsibility_ref, "active"),
        )

    def record_assessment(self, **kwargs):
        ref = kwargs["responsibility_ref"]
        self.assessment_calls.append(ref)
        return KernelResponsibilityAssessmentReceipt(
            assessment_ref=kwargs["assessment_ref"],
            responsibility_ref=ref,
            responsibility_version=kwargs["responsibility_version"],
        )

    def record_discharge_decision(self, **kwargs):
        ref = kwargs["responsibility_ref"]
        self.decision_calls.append(ref)
        return KernelResponsibilityDischargeDecisionReceipt(
            decision_ref=kwargs["decision_ref"],
            responsibility_ref=ref,
            responsibility_version=kwargs["responsibility_version"],
            status_after_decision="active",
            assessment_ref=kwargs["assessment_ref"],
        )

    def apply_lifecycle_transition(self, **kwargs):
        ref = kwargs["responsibility_ref"]
        self.transition_calls.append(ref)
        self.statuses[ref] = "discharged"
        return KernelResponsibilityLifecycleTransitionReceipt(
            transition_ref=kwargs["transition_ref"],
            responsibility_ref=ref,
            responsibility_version=kwargs["responsibility_version"],
            current_status="discharged",
            decision_ref=kwargs["decision_ref"],
        )


class _Bridge:
    cutover = True

    def __init__(self, projections, client, recovery_client=None):
        self.repository = SimpleNamespace(
            list_projections_for_case=lambda case_id: projections
        )
        self._client = client
        self._recovery_client = recovery_client
        self.compatibility_calls = 0

    def compatibility(self):
        self.compatibility_calls += 1
        return object()

    def client(self):
        return self._client

    def recovery_client(self):
        if self._recovery_client is None:
            raise AssertionError("test bridge recovery client was not configured")
        return self._recovery_client


class _RecoveryClient:
    def __init__(
        self,
        *,
        responsibility_ref: str,
        status: str = "recovered-completed",
        error: Exception | None = None,
    ):
        self.responsibility_ref = responsibility_ref
        self.status = status
        self.error = error
        self.inspect_calls: list[tuple[str, str | None]] = []

    def inspect(self, execution_ref, *, expected_work_ref=None):
        self.inspect_calls.append((execution_ref, expected_work_ref))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            current_status=self.status,
            responsibility_ref=self.responsibility_ref,
        )


def test_completion_must_be_satisfied_before_kernel_discharge() -> None:
    store, case, obligation = _fixture(with_completion=False)
    client = _Client()
    bridge = _Bridge([_projection(case, obligation.obligation_id, ref="resp:1")], client)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "completion_assessment_not_satisfied"
    assert client.assessment_calls == []
    assert client.decision_calls == []
    assert client.transition_calls == []


def test_missing_projection_fails_closed_without_kernel_mutation() -> None:
    store, case, _obligation = _fixture()
    client = _Client()
    bridge = _Bridge([], client)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "missing_or_duplicate_current_kernel_projection"
    assert bridge.compatibility_calls == 0
    assert client.status_calls == []


def test_assessment_and_decision_keep_active_until_transition_then_discharge() -> None:
    store, case, obligation = _fixture()
    client = _Client()
    bridge = _Bridge([_projection(case, obligation.obligation_id, ref="resp:1")], client)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.DISCHARGED
    assert result.responsibility_refs == ("resp:1",)
    assert result.discharged_refs == ("resp:1",)
    assert client.assessment_calls == ["resp:1"]
    assert client.decision_calls == ["resp:1"]
    assert client.transition_calls == ["resp:1"]
    assert client.status_calls.count("resp:1") == 4


def test_recovered_unknown_execution_can_discharge_without_rewriting_projection() -> None:
    store, case, obligation = _fixture()
    projection = _projection(case, obligation.obligation_id, ref="resp:recovered").model_copy(
        update={
            "status": KernelProjectionStatus.ADMITTED,
            "kernel_execution_status": KernelExecutionStatus.EXECUTION_UNKNOWN,
            "kernel_execution_ref": "execution:recovered",
            "kernel_execution_responsibility_ref": None,
            "kernel_outcome_ref": None,
            "kernel_evidence_ref": None,
            "kernel_execution_processed_at": None,
        }
    )
    client = _Client()
    recovery = _RecoveryClient(responsibility_ref="resp:recovered")
    bridge = _Bridge([projection], client, recovery)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.DISCHARGED
    assert recovery.inspect_calls == [("execution:recovered", "work:resp:recovered")]
    assert projection.status is KernelProjectionStatus.ADMITTED
    assert projection.kernel_execution_status is KernelExecutionStatus.EXECUTION_UNKNOWN
    assert client.transition_calls == ["resp:recovered"]


def test_historical_recovered_unknown_execution_is_verified_before_discharge() -> None:
    store, case, obligation = _fixture()
    historical = _projection(case, uuid4(), ref="resp:old-unknown", epoch=1).model_copy(
        update={
            "status": KernelProjectionStatus.ADMITTED,
            "kernel_execution_status": KernelExecutionStatus.EXECUTION_UNKNOWN,
            "kernel_execution_ref": "execution:old-unknown",
            "kernel_execution_responsibility_ref": None,
            "kernel_outcome_ref": None,
            "kernel_evidence_ref": None,
            "kernel_execution_processed_at": None,
        }
    )
    current = _projection(case, obligation.obligation_id, ref="resp:new-completed")
    client = _Client()
    recovery = _RecoveryClient(responsibility_ref="resp:old-unknown")
    bridge = _Bridge([historical, current], client, recovery)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.DISCHARGED
    assert recovery.inspect_calls == [("execution:old-unknown", "work:resp:old-unknown")]
    assert client.transition_calls == ["resp:new-completed", "resp:old-unknown"]
    assert historical.status is KernelProjectionStatus.ADMITTED
    assert historical.kernel_execution_status is KernelExecutionStatus.EXECUTION_UNKNOWN


def _unknown_current_projection(case, obligation_id, *, ref: str):
    return _projection(case, obligation_id, ref=ref).model_copy(
        update={
            "status": KernelProjectionStatus.ADMITTED,
            "kernel_execution_status": KernelExecutionStatus.EXECUTION_UNKNOWN,
            "kernel_execution_ref": f"execution:{ref}",
            "kernel_execution_responsibility_ref": None,
            "kernel_outcome_ref": None,
            "kernel_evidence_ref": None,
            "kernel_execution_processed_at": None,
        }
    )


def test_recovery_pending_blocks_discharge_without_kernel_mutation() -> None:
    store, case, obligation = _fixture()
    projection = _unknown_current_projection(case, obligation.obligation_id, ref="resp:pending")
    client = _Client()
    recovery = _RecoveryClient(responsibility_ref="resp:pending", status="recovery-pending")
    bridge = _Bridge([projection], client, recovery)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "historical_external_responsibility_not_completed"
    assert recovery.inspect_calls == [("execution:resp:pending", "work:resp:pending")]
    assert client.transition_calls == []


def test_recovery_transport_error_blocks_discharge_without_kernel_mutation() -> None:
    store, case, obligation = _fixture()
    projection = _unknown_current_projection(case, obligation.obligation_id, ref="resp:error")
    client = _Client()
    recovery = _RecoveryClient(
        responsibility_ref="resp:error",
        error=KernelRecoveryError("simulated resolution outage"),
    )
    bridge = _Bridge([projection], client, recovery)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "kernel_recovery_resolution_unavailable:KernelRecoveryError"
    assert client.transition_calls == []


def test_recovery_responsibility_identity_mismatch_blocks_discharge() -> None:
    store, case, obligation = _fixture()
    projection = _unknown_current_projection(case, obligation.obligation_id, ref="resp:expected")
    client = _Client()
    recovery = _RecoveryClient(responsibility_ref="resp:other")
    bridge = _Bridge([projection], client, recovery)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "kernel_recovery_responsibility_identity_rebound"
    assert client.transition_calls == []


def test_noncompleted_admitted_projection_blocks_discharge() -> None:
    store, case, obligation = _fixture()
    projection = _projection(case, obligation.obligation_id, ref="resp:not-executed").model_copy(
        update={
            "status": KernelProjectionStatus.ADMITTED,
            "kernel_execution_status": None,
            "kernel_execution_ref": None,
            "kernel_execution_responsibility_ref": None,
            "kernel_outcome_ref": None,
            "kernel_evidence_ref": None,
            "kernel_execution_processed_at": None,
        }
    )
    client = _Client()
    bridge = _Bridge([projection], client)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "current_external_responsibility_not_completed"
    assert client.transition_calls == []


def test_historical_responsibility_is_not_ignored() -> None:
    store, case, obligation = _fixture()
    historical = _projection(case, uuid4(), ref="resp:old", epoch=1)
    current = _projection(case, obligation.obligation_id, ref="resp:new")
    client = _Client()
    bridge = _Bridge([historical, current], client)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.DISCHARGED
    assert result.responsibility_refs == ("resp:new", "resp:old")
    assert client.transition_calls == ["resp:new", "resp:old"]


def test_partial_restart_reuses_discharged_responsibility_without_duplicate_chain() -> None:
    store, case, obligation = _fixture()
    second_obligation_id = uuid4()
    projections = [
        _projection(case, obligation.obligation_id, ref="resp:one"),
        _projection(case, second_obligation_id, ref="resp:two", epoch=1),
    ]
    first_client = _Client(fail_ref="resp:two")
    first_bridge = _Bridge(projections, first_client)
    first = AdministrativeResponsibilityDischargeService(store, first_bridge).discharge(case)

    assert first.status is ResponsibilityDischargeStatus.PENDING
    assert first.discharged_refs == ("resp:one",)
    assert first_client.transition_calls == ["resp:one"]

    replay_client = _Client(statuses={"resp:one": "discharged"})
    replay_bridge = _Bridge(projections, replay_client)
    replay = AdministrativeResponsibilityDischargeService(store, replay_bridge).discharge(case)

    assert replay.status is ResponsibilityDischargeStatus.DISCHARGED
    assert replay.discharged_refs == ("resp:one", "resp:two")
    assert replay_client.assessment_calls == ["resp:two"]
    assert replay_client.decision_calls == ["resp:two"]
    assert replay_client.transition_calls == ["resp:two"]


def test_non_active_status_prevents_set_closure() -> None:
    store, case, obligation = _fixture()
    client = _Client(statuses={"resp:1": "suspended"})
    bridge = _Bridge([_projection(case, obligation.obligation_id, ref="resp:1")], client)

    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "responsibility_not_active"
    assert client.assessment_calls == []
    assert client.decision_calls == []
    assert client.transition_calls == []


def test_operations_detail_exposes_completion_and_read_only_lifecycle_state(monkeypatch) -> None:
    store, case, _obligation = _fixture()
    from administrative_orchestrator import operations_api

    actor = SimpleNamespace(principal_id="person:operations")
    monkeypatch.setattr(operations_api, "_store", store)
    monkeypatch.setattr(operations_api, "_authority", AuthorityRepository(store))
    monkeypatch.setattr(operations_api, "_governance", GovernanceRepository(store))
    monkeypatch.setattr(operations_api, "_obligations", ObligationRepository(store))
    monkeypatch.setattr(operations_api, "_execution", ExecutionRepository(store))
    monkeypatch.setattr(
        operations_api,
        "_settings",
        SimpleNamespace(kernel_bridge_mode="disabled"),
    )
    monkeypatch.setattr(operations_api, "_actor", lambda request: actor)
    monkeypatch.setattr(operations_api, "_require", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        operations_api,
        "_access",
        SimpleNamespace(allows=lambda *args, **kwargs: False),
    )

    detail = operations_api.case_detail(case.case_id, object())

    assert detail["completion_assessment"]["satisfied"] is True
    assert detail["termination"]["employment_episode_ref"] is None
    assert detail["authority"] == {
        "bindings": [],
        "role_assignments": [],
        "delegations": [],
    }
    assert detail["responsibility_discharge"]["status"] == "pending"
    assert detail["responsibility_discharge"]["blocker"] == "kernel_cutover_required"
    assert detail["kernel_projections"] == []
    assert "force_discharge" not in detail


def test_operations_responsibility_snapshot_observes_active_and_discharged(monkeypatch) -> None:
    store, case, obligation = _fixture()
    from administrative_orchestrator import operations_api

    obligation_set = ObligationRepository(store).get_current(
        case.case_id, case.authority_epoch
    )
    assert obligation_set is not None
    effects = ExecutionRepository(store).list_effects(case.case_id, case.authority_epoch)
    outcomes = ExecutionRepository(store).list_outcomes(case.case_id, case.authority_epoch)
    links = ObligationRepository(store).list_links(case.case_id, case.authority_epoch)
    completion = operations_api._case_completion_assessment(
        obligation_set,
        effects,
        outcomes,
        links=links,
        fulfillments=[],
    )
    handle = ResponsibilityHandle(
        responsibility_ref="resp:ops",
        responsibility_version=1,
        obligation_ids=(obligation.obligation_id,),
    )
    client = SimpleNamespace(
        get_responsibility_status=lambda responsibility_ref, *, expected_version: (
            KernelResponsibilityStatusView(
                responsibility_ref=responsibility_ref,
                responsibility_version=expected_version,
                current_status="active",
            )
        )
    )

    class _Bridge:
        cutover = True

        def client(self):
            return client

    class _Service:
        def __init__(self, store, bridge):
            del store, bridge

        def project_responsibility_set(self, case, obligation_set):
            del case, obligation_set
            return (handle,)

        def discharge_chain_refs(self, case, handle):
            del case, handle
            return ("assessment:ops", "decision:ops", "transition:ops")

    monkeypatch.setattr(operations_api, "_store", store)
    monkeypatch.setattr(
        operations_api,
        "_settings",
        SimpleNamespace(kernel_bridge_mode="cutover"),
    )
    monkeypatch.setattr(operations_api, "KernelExecutionBridge", lambda *args, **kwargs: _Bridge())
    monkeypatch.setattr(operations_api, "AdministrativeResponsibilityDischargeService", _Service)

    pending = operations_api._responsibility_snapshot(
        case, obligation_set, completion, []
    )
    assert pending["status"] == "pending"
    assert pending["responsibilities"][0]["current_status"] == "active"

    client.get_responsibility_status = lambda responsibility_ref, *, expected_version: (
        KernelResponsibilityStatusView(
            responsibility_ref=responsibility_ref,
            responsibility_version=expected_version,
            current_status="discharged",
        )
    )
    discharged = operations_api._responsibility_snapshot(
        case, obligation_set, completion, []
    )
    assert discharged["status"] == "discharged"
    assert discharged["blocker"] is None
