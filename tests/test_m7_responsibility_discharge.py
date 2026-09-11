from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

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
from administrative_orchestrator.obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationRepository,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.responsibility_discharge import (
    AdministrativeResponsibilityDischargeService,
    ResponsibilityDischargeStatus,
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

    def __init__(self, projections, client):
        self.repository = SimpleNamespace(
            list_projections_for_case=lambda case_id: projections
        )
        self._client = client
        self.compatibility_calls = 0

    def compatibility(self):
        self.compatibility_calls += 1
        return object()

    def client(self):
        return self._client


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
