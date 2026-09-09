from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AuthorityClass,
    FactAuthority,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.governance import GovernanceBasis
from administrative_orchestrator.integrations.kernel.bridge import KernelExecutionBridge
from administrative_orchestrator.integrations.kernel.client import (
    KernelExecutionReceipt,
    KernelProposalReceipt,
    KernelSubmissionError,
    KernelWorkAdmissionError,
    KernelWorkAdmissionReceipt,
)
from administrative_orchestrator.integrations.kernel.compatibility import (
    KernelCompatibilityError,
    KernelContractIdentity,
    validate_kernel_catalog,
)
from administrative_orchestrator.integrations.kernel.mapper import (
    derive_effect_intent,
    derive_execution_grant,
    project_to_kernel,
)
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
    KernelWorkAdmissionStatus,
)
from administrative_orchestrator.integrations.kernel.repository import KernelBridgeRepository
from administrative_orchestrator.obligations import AdministrativeObligation
from administrative_orchestrator.persistence import SqlStore

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)


class FakeKernelClient:
    def __init__(
        self,
        *,
        fail_submit: bool = False,
        fail_admit: bool = False,
        admission_status: str = "work-materialized",
        execution_status: str = "completed",
    ) -> None:
        self.fail_submit = fail_submit
        self.fail_admit = fail_admit
        self.admission_status = admission_status
        self.execution_status = execution_status
        self.submit_calls = 0
        self.admit_calls = 0
        self.execute_calls = 0

    def submit(self, projection):
        self.submit_calls += 1
        if self.fail_submit:
            raise KernelSubmissionError("simulated lost acknowledgement")
        return KernelProposalReceipt(
            responsibility_ref=projection.responsibility_payload["id"],
            admission_ref=projection.admission_payload["id"],
            assessment_ref=projection.assessment_payload["id"],
            proposal_ref=projection.work_proposal_payload["id"],
        )

    def admit(self, projection, *, expected_policy_ref: str):
        self.admit_calls += 1
        if self.fail_admit:
            raise KernelWorkAdmissionError("simulated lost Work admission acknowledgement")
        proposal_ref = projection.kernel_proposal_ref
        assert proposal_ref is not None
        priority_ref = f"priority:{proposal_ref}"
        if self.admission_status == "priority-rejected":
            return KernelWorkAdmissionReceipt(
                status="priority-rejected",
                proposal_ref=proposal_ref,
                policy_ref=expected_policy_ref,
                priority_judgment_ref=priority_ref,
            )
        pool_ref = f"pool:{proposal_ref}"
        portfolio_ref = f"portfolio:{proposal_ref}"
        if self.admission_status == "portfolio-rejected":
            return KernelWorkAdmissionReceipt(
                status="portfolio-rejected",
                proposal_ref=proposal_ref,
                policy_ref=expected_policy_ref,
                priority_judgment_ref=priority_ref,
                resource_pool_ref=pool_ref,
                portfolio_admission_ref=portfolio_ref,
            )
        return KernelWorkAdmissionReceipt(
            status="work-materialized",
            proposal_ref=proposal_ref,
            policy_ref=expected_policy_ref,
            priority_judgment_ref=priority_ref,
            resource_pool_ref=pool_ref,
            portfolio_admission_ref=portfolio_ref,
            reservation_ref=f"reservation:{proposal_ref}",
            commitment_ref=f"commitment:{proposal_ref}",
            work_ref=f"work:{proposal_ref}",
        )

    def execute(self, projection, grant, intent):
        del grant, intent
        self.execute_calls += 1
        work_ref = projection.kernel_work_ref
        assert work_ref is not None
        execution_ref = f"execution:{work_ref}"
        if self.execution_status != "completed":
            return KernelExecutionReceipt(
                status=self.execution_status,
                execution_ref=execution_ref,
                work_ref=work_ref,
                processed_at=NOW,
                run_ref=f"run:{work_ref}",
                request_ref=f"request:{work_ref}",
                authorization_ref=f"authorization:{work_ref}",
                provider_id="provider:hris:kernel",
            )
        return KernelExecutionReceipt(
            status="completed",
            execution_ref=execution_ref,
            work_ref=work_ref,
            processed_at=NOW,
            run_ref=f"run:{work_ref}",
            request_ref=f"request:{work_ref}",
            authorization_ref=f"authorization:{work_ref}",
            provider_id="provider:hris:kernel",
            action_ref=f"action:{work_ref}",
            outcome_ref=f"outcome:{work_ref}",
            evidence_ref=f"evidence:{work_ref}",
            responsibility_ref=projection.kernel_responsibility_ref,
        )

    def inspect_execution(self, execution_ref: str, *, expected_work_ref: str | None = None):
        del execution_ref, expected_work_ref
        return None


def _compatibility(
    *,
    work_admission: bool = False,
    execution: bool = False,
    evidence: bool = False,
) -> KernelContractIdentity:
    return KernelContractIdentity(
        catalog_version="portable-runtime-contracts-v1",
        owner="portable-runtime/contracts",
        runtime_protocol="2.0",
        persistent_responsibility_contract="persistent-responsibility-v1",
        domain_responsibility_proposal_contract="domain-responsibility-proposal-v1",
        responsibility_work_admission_contract=(
            "responsibility-work-admission-v1" if work_admission else None
        ),
        bounded_domain_effect_execution_contract=(
            "bounded-domain-effect-execution-v1" if execution else None
        ),
        domain_effect_verification_evidence_view=(
            "domain-effect-verification-evidence-view-v1" if evidence else None
        ),
    )


def _policy() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v1",
        owner="administrative-orchestrator",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _projection_inputs():
    case_id = uuid4()
    governance_id = uuid4()
    approval_id = uuid4()
    policy = _policy()
    facts = {
        "employee_ref": "employee:new",
        "department_ref": "department:engineering",
        "manager_principal_id": "person:manager",
        "start_date": "2026-09-15",
        "employment_type": "full-time",
    }
    case = AdministrativeCase(
        case_id=case_id,
        case_kind="employee-onboarding",
        requester_principal_id="person:requester",
        subject_ref="employee:new",
        authority_epoch=2,
        policy_ref=policy,
        fact_snapshot=FactSnapshot(
            source="test",
            owner="test",
            authority=FactAuthority.ATTESTED,
            observed_at=NOW,
            facts=facts,
        ),
        updated_at=NOW,
    )
    governance = GovernanceBasis(
        basis_id=governance_id,
        case_id=case_id,
        case_version_at_basis=case.version,
        authority_epoch=case.authority_epoch,
        fact_snapshot_id=case.fact_snapshot.snapshot_id,
        fact_digest="facts-digest",
        policy_ref=policy,
        policy_definition_digest="policy-digest",
        organization_scope="department:engineering",
        approval_satisfaction_id=approval_id,
        qualifications=(),
        authority_digest="authority-digest",
        basis_digest="basis-digest",
        created_at=NOW,
    )
    obligation = AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_id,
        kind="hris.employee.create",
        subject_ref=case.subject_ref,
        target_system="hris",
        required_operation="employee.create",
        expected_postcondition={
            "target_system": "hris",
            "operation": "employee.create",
            "subject_ref": case.subject_ref,
            "active": True,
            "payload": facts,
        },
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    return case, governance, obligation


def _catalog(
    *,
    include_work_admission: bool = False,
    include_execution: bool = False,
    include_evidence: bool = False,
) -> dict[str, object]:
    contracts: dict[str, object] = {
        "persistent_responsibility": {"current": "persistent-responsibility-v1"},
        "domain_responsibility_proposal": {
            "current": "domain-responsibility-proposal-v1"
        },
    }
    if include_work_admission:
        contracts["responsibility_work_admission"] = {
            "current": "responsibility-work-admission-v1"
        }
    if include_execution:
        contracts["bounded_domain_effect_execution"] = {
            "current": "bounded-domain-effect-execution-v1"
        }
    raw: dict[str, object] = {
        "catalog_version": "portable-runtime-contracts-v1",
        "owner": "portable-runtime/contracts",
        "runtime_protocol": "2.0",
        "contracts": contracts,
    }
    if include_evidence:
        raw["views"] = {
            "domain_effect_verification_evidence": {
                "current": "domain-effect-verification-evidence-view-v1"
            }
        }
    return raw


def test_kernel_contract_gate_preserves_shadow_compatibility_and_gates_admission() -> None:
    raw = _catalog()
    assert validate_kernel_catalog(raw) == _compatibility()

    with pytest.raises(KernelCompatibilityError, match="required for admission mode"):
        validate_kernel_catalog(raw, require_work_admission=True)

    admission_raw = _catalog(include_work_admission=True)
    assert validate_kernel_catalog(
        admission_raw,
        require_work_admission=True,
    ) == _compatibility(work_admission=True)

    execution_raw = _catalog(include_work_admission=True, include_execution=True)
    with pytest.raises(KernelCompatibilityError, match="domain_effect_verification_evidence"):
        validate_kernel_catalog(
            execution_raw,
            require_work_admission=True,
            require_domain_effect_execution=True,
            require_domain_effect_evidence=True,
        )

    cutover_raw = _catalog(
        include_work_admission=True,
        include_execution=True,
        include_evidence=True,
    )
    assert validate_kernel_catalog(
        cutover_raw,
        require_work_admission=True,
        require_domain_effect_execution=True,
        require_domain_effect_evidence=True,
    ) == _compatibility(work_admission=True, execution=True, evidence=True)

    changed = {
        **admission_raw,
        "contracts": {
            **admission_raw["contracts"],
            "responsibility_work_admission": {
                "current": "responsibility-work-admission-v2"
            },
        },
    }
    with pytest.raises(KernelCompatibilityError, match="responsibility_work_admission"):
        validate_kernel_catalog(changed, require_work_admission=True)


def test_kernel_projection_is_deterministic_and_carries_no_runtime_authority() -> None:
    case, governance, obligation = _projection_inputs()
    grant = derive_execution_grant(case, obligation, governance)
    intent = derive_effect_intent(case, grant)
    first = project_to_kernel(grant, intent, _compatibility())
    second = project_to_kernel(grant, intent, _compatibility())

    assert first == second
    assert intent.capability == "administrative.hris.employee.create.v1"
    assert first.responsibility_payload["object_type"] == "StandingResponsibility"
    assert first.admission_payload["object_type"] == "ResponsibilityAdmission"
    assert first.assessment_payload["object_type"] == "ResponsibilityAssessment"
    assert first.work_proposal_payload["object_type"] == "WorkProposal"
    assert first.work_proposal_payload["effect_class"] == "external-effect"
    assert first.work_proposal_payload["requested_capabilities"] == [intent.capability]

    serialized = str(first.model_dump(mode="json"))
    for forbidden in (
        "AuthorizationGrant",
        "InvocationPermit",
        "PriorityJudgment",
        "PortfolioAdmissionDecision",
        "Commitment",
        "object_type': 'Work'",
        "object_type': 'Run'",
    ):
        assert forbidden not in serialized


def test_shadow_bridge_submits_once_and_stops_before_work_admission() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    client = FakeKernelClient()
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(kernel_bridge_mode="shadow"),
        compatibility=_compatibility(),
        client=client,
    )

    first = bridge.prepare(case, obligation, governance)
    second = bridge.prepare(case, obligation, governance)

    assert first is not None
    assert first == second
    assert first.status is KernelProjectionStatus.SUBMITTED
    assert first.kernel_responsibility_ref == first.responsibility_payload["id"]
    assert first.kernel_admission_ref == first.admission_payload["id"]
    assert first.kernel_assessment_ref == first.assessment_payload["id"]
    assert first.kernel_proposal_ref == first.work_proposal_payload["id"]
    assert first.kernel_work_ref is None
    assert first.kernel_run_ref is None
    assert client.submit_calls == 1
    assert client.admit_calls == 0
    assert client.execute_calls == 0


def test_admission_shadow_materializes_kernel_work_once_without_run_or_authority() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    client = FakeKernelClient()
    settings = Settings(
        kernel_bridge_mode="admission",
        kernel_responsibility_admission_policy_ref="responsibility-admission:admin@1",
    )
    bridge = KernelExecutionBridge(
        store,
        settings=settings,
        compatibility=_compatibility(work_admission=True),
        client=client,
    )

    first = bridge.prepare(case, obligation, governance)
    second = bridge.prepare(case, obligation, governance)

    assert first is not None
    assert first == second
    assert first.status is KernelProjectionStatus.ADMITTED
    assert first.kernel_work_admission_status is KernelWorkAdmissionStatus.WORK_MATERIALIZED
    assert first.kernel_admission_policy_ref == settings.kernel_responsibility_admission_policy_ref
    assert first.kernel_priority_judgment_ref
    assert first.kernel_resource_pool_ref
    assert first.kernel_portfolio_admission_ref
    assert first.kernel_reservation_ref
    assert first.kernel_commitment_ref
    assert first.kernel_work_ref
    assert first.kernel_run_ref is None
    assert client.submit_calls == 1
    assert client.admit_calls == 1
    assert client.execute_calls == 0


def test_admission_rejection_is_terminal_shadow_state_without_work() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    client = FakeKernelClient(admission_status="priority-rejected")
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(kernel_bridge_mode="admission"),
        compatibility=_compatibility(work_admission=True),
        client=client,
    )

    first = bridge.prepare(case, obligation, governance)
    second = bridge.prepare(case, obligation, governance)

    assert first is not None
    assert first == second
    assert first.status is KernelProjectionStatus.REJECTED
    assert first.kernel_work_admission_status is KernelWorkAdmissionStatus.PRIORITY_REJECTED
    assert first.kernel_priority_judgment_ref
    assert first.kernel_resource_pool_ref is None
    assert first.kernel_portfolio_admission_ref is None
    assert first.kernel_work_ref is None
    assert first.kernel_run_ref is None
    assert client.submit_calls == 1
    assert client.admit_calls == 1
    assert client.execute_calls == 0


def test_lost_proposal_ack_leaves_shadow_for_idempotent_replay() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    failed_client = FakeKernelClient(fail_submit=True)
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(kernel_bridge_mode="shadow"),
        compatibility=_compatibility(),
        client=failed_client,
    )

    with pytest.raises(KernelSubmissionError, match="lost acknowledgement"):
        bridge.prepare(case, obligation, governance)

    persisted = KernelBridgeRepository(store).get_projection_for_obligation(
        obligation.obligation_id
    )
    assert persisted is not None
    assert persisted.status is KernelProjectionStatus.SHADOW
    assert persisted.kernel_responsibility_ref is None

    replay_client = FakeKernelClient()
    replay = KernelExecutionBridge(
        store,
        settings=Settings(kernel_bridge_mode="shadow"),
        compatibility=_compatibility(),
        client=replay_client,
    ).prepare(case, obligation, governance)
    assert replay is not None
    assert replay.status is KernelProjectionStatus.SUBMITTED
    assert replay_client.submit_calls == 1


def test_lost_work_admission_ack_leaves_submitted_for_idempotent_replay() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    failed_client = FakeKernelClient(fail_admit=True)
    settings = Settings(kernel_bridge_mode="admission")
    bridge = KernelExecutionBridge(
        store,
        settings=settings,
        compatibility=_compatibility(work_admission=True),
        client=failed_client,
    )

    with pytest.raises(KernelWorkAdmissionError, match="lost Work admission"):
        bridge.prepare(case, obligation, governance)

    persisted = KernelBridgeRepository(store).get_projection_for_obligation(
        obligation.obligation_id
    )
    assert persisted is not None
    assert persisted.status is KernelProjectionStatus.SUBMITTED
    assert persisted.kernel_work_ref is None
    assert failed_client.submit_calls == 1
    assert failed_client.admit_calls == 1

    replay_client = FakeKernelClient()
    replay = KernelExecutionBridge(
        store,
        settings=settings,
        compatibility=_compatibility(work_admission=True),
        client=replay_client,
    ).prepare(case, obligation, governance)
    assert replay is not None
    assert replay.status is KernelProjectionStatus.ADMITTED
    assert replay_client.submit_calls == 0
    assert replay_client.admit_calls == 1


def test_cutover_without_authority_and_reality_boundary_fails_closed_before_persistence() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(kernel_bridge_mode="cutover"),
        compatibility=_compatibility(work_admission=True),
        client=FakeKernelClient(),
    )

    with pytest.raises(KernelCompatibilityError, match="cutover is fail-closed"):
        bridge.prepare(case, obligation, governance)

    assert KernelBridgeRepository(store).list_projections(case.case_id, case.authority_epoch) == []


def test_cutover_executes_owned_hris_once_and_persists_complete_kernel_lineage() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    client = FakeKernelClient()
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(
            kernel_bridge_mode="cutover",
            external_effects_enabled=True,
            kernel_responsibility_admission_policy_ref="responsibility-admission:admin@1",
        ),
        compatibility=_compatibility(work_admission=True, execution=True, evidence=True),
        client=client,
    )

    first = bridge.prepare(case, obligation, governance)
    second = bridge.prepare(case, obligation, governance)

    assert first is not None
    assert first == second
    assert first.status is KernelProjectionStatus.CUTOVER
    assert first.kernel_execution_status is KernelExecutionStatus.COMPLETED
    assert first.kernel_work_ref
    assert first.kernel_execution_ref
    assert first.kernel_run_ref
    assert first.kernel_request_ref
    assert first.kernel_authorization_ref
    assert first.kernel_provider_id == "provider:hris:kernel"
    assert first.kernel_action_ref
    assert first.kernel_outcome_ref
    assert first.kernel_evidence_ref
    assert first.kernel_execution_responsibility_ref == first.kernel_responsibility_ref
    assert first.kernel_execution_processed_at == NOW
    assert client.submit_calls == 1
    assert client.admit_calls == 1
    assert client.execute_calls == 1

    persisted = KernelBridgeRepository(store).get_projection_for_obligation(
        obligation.obligation_id
    )
    assert persisted == first


def test_cutover_global_effect_gate_stops_before_kernel_physical_execution() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    client = FakeKernelClient()
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(
            kernel_bridge_mode="cutover",
            external_effects_enabled=False,
        ),
        compatibility=_compatibility(work_admission=True, execution=True, evidence=True),
        client=client,
    )

    projection = bridge.prepare(case, obligation, governance)

    assert projection is not None
    assert projection.status is KernelProjectionStatus.ADMITTED
    assert projection.kernel_execution_status is None
    assert client.submit_calls == 1
    assert client.admit_calls == 1
    assert client.execute_calls == 0


def test_execution_grant_rejects_stale_or_cross_case_governance() -> None:
    case, governance, obligation = _projection_inputs()
    stale = case.model_copy(update={"authority_epoch": case.authority_epoch + 1})
    with pytest.raises(ValueError, match="stale administrative authority epoch"):
        derive_execution_grant(stale, obligation, governance)

    other_governance = governance.model_copy(update={"case_id": uuid4()})
    with pytest.raises(ValueError, match="different administrative cases"):
        derive_execution_grant(case, obligation, other_governance)
