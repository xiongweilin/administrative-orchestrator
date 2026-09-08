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
from administrative_orchestrator.integrations.kernel.repository import KernelBridgeRepository
from administrative_orchestrator.obligations import AdministrativeObligation
from administrative_orchestrator.persistence import SqlStore

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)


def _compatibility() -> KernelContractIdentity:
    return KernelContractIdentity(
        catalog_version="portable-runtime-contracts-v1",
        owner="portable-runtime/contracts",
        runtime_protocol="2.0",
        persistent_responsibility_contract="persistent-responsibility-v1",
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


def test_kernel_contract_gate_accepts_only_expected_canonical_identity() -> None:
    raw = {
        "catalog_version": "portable-runtime-contracts-v1",
        "owner": "portable-runtime/contracts",
        "runtime_protocol": "2.0",
        "contracts": {
            "persistent_responsibility": {"current": "persistent-responsibility-v1"}
        },
    }
    assert validate_kernel_catalog(raw) == _compatibility()

    for key, incompatible in (
        ("catalog_version", "portable-runtime-contracts-v2"),
        ("owner", "administrative-orchestrator"),
        ("runtime_protocol", "3.0"),
    ):
        changed = {**raw, key: incompatible}
        with pytest.raises(KernelCompatibilityError, match="incompatible"):
            validate_kernel_catalog(changed)

    changed = {
        **raw,
        "contracts": {
            "persistent_responsibility": {"current": "persistent-responsibility-v2"}
        },
    }
    with pytest.raises(KernelCompatibilityError, match="persistent_responsibility"):
        validate_kernel_catalog(changed)


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


def test_shadow_bridge_persists_append_only_business_and_kernel_lineage() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(kernel_bridge_mode="shadow"),
        compatibility=_compatibility(),
    )

    first = bridge.prepare(case, obligation, governance)
    second = bridge.prepare(case, obligation, governance)

    assert first is not None
    assert first == second
    assert first.kernel_work_ref is None
    assert first.kernel_run_ref is None
    rows = KernelBridgeRepository(store).list_projections(case.case_id, case.authority_epoch)
    assert rows == [first]


def test_cutover_without_kernel_command_surface_fails_closed_before_persistence() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case, governance, obligation = _projection_inputs()
    bridge = KernelExecutionBridge(
        store,
        settings=Settings(kernel_bridge_mode="cutover"),
        compatibility=_compatibility(),
    )

    with pytest.raises(KernelCompatibilityError, match="cutover is fail-closed"):
        bridge.prepare(case, obligation, governance)

    assert KernelBridgeRepository(store).list_projections(case.case_id, case.authority_epoch) == []


def test_execution_grant_rejects_stale_or_cross_case_governance() -> None:
    case, governance, obligation = _projection_inputs()
    stale = case.model_copy(update={"authority_epoch": case.authority_epoch + 1})
    with pytest.raises(ValueError, match="stale administrative authority epoch"):
        derive_execution_grant(stale, obligation, governance)

    other_governance = governance.model_copy(update={"case_id": uuid4()})
    with pytest.raises(ValueError, match="different administrative cases"):
        derive_execution_grant(case, obligation, other_governance)
