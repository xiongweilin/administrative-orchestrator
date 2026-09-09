from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AuthorityClass,
    EffectRecord,
    EffectReversibility,
    FactAuthority,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import (
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.governance import GovernanceBasis
from administrative_orchestrator.integrations.kernel.bridge import KernelExecutionBridge
from administrative_orchestrator.integrations.kernel.effect_provider import KernelCutoverEffectProvider
from administrative_orchestrator.integrations.kernel.models import KernelProjectionStatus
from administrative_orchestrator.obligations import AdministrativeObligation
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)
from scripts.kernel_cutover_stack import sandbox_effect_id


class ForbiddenFallbackProvider:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.observe_calls = 0

    def execute(self, effect: EffectRecord, payload: dict[str, object]) -> ProviderExecutionResult:
        del effect, payload
        self.execute_calls += 1
        raise AssertionError("legacy Administrative execute fallback was invoked")

    def observe(self, effect: EffectRecord) -> RealityObservation:
        del effect
        self.observe_calls += 1
        raise AssertionError("legacy Administrative observe fallback was invoked")


def _inputs(now: datetime) -> tuple[AdministrativeCase, GovernanceBasis, AdministrativeObligation]:
    case_id = uuid4()
    governance_id = uuid4()
    approval_id = uuid4()
    policy = PolicyRef(
        policy_id="employee-onboarding",
        version="v1",
        owner="administrative-orchestrator",
        effective_from=now - timedelta(days=30),
    )
    facts = {
        "employee_ref": "employee:kernel-cross-repo-e2e",
        "department_ref": "department:engineering",
        "manager_principal_id": "person:e2e-manager",
        "start_date": (now + timedelta(days=7)).date().isoformat(),
        "employment_type": "full-time",
    }
    snapshot = FactSnapshot(
        source="cross-repo-e2e",
        owner="administrative-orchestrator",
        authority=FactAuthority.ATTESTED,
        observed_at=now,
        facts=facts,
    )
    case = AdministrativeCase(
        case_id=case_id,
        case_kind="employee-onboarding",
        requester_principal_id="person:e2e-requester",
        subject_ref=facts["employee_ref"],
        authority_epoch=1,
        policy_ref=policy,
        fact_snapshot=snapshot,
        created_at=now,
        updated_at=now,
    )
    governance = GovernanceBasis(
        basis_id=governance_id,
        case_id=case_id,
        case_version_at_basis=case.version,
        authority_epoch=case.authority_epoch,
        fact_snapshot_id=snapshot.snapshot_id,
        fact_digest="cross-repo-e2e-fact-digest",
        policy_ref=policy,
        policy_definition_digest="cross-repo-e2e-policy-digest",
        organization_scope="department:engineering",
        approval_satisfaction_id=approval_id,
        qualifications=(),
        authority_digest="cross-repo-e2e-authority-digest",
        basis_digest="cross-repo-e2e-basis-digest",
        created_at=now,
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


def main() -> None:
    kernel_base_url = os.getenv("ADMIN_KERNEL_BASE_URL", "http://127.0.0.1:8020").rstrip("/")
    sandbox_base_url = os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    now = datetime.now(UTC)
    case, governance, obligation = _inputs(now)

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    settings = Settings(
        kernel_bridge_mode="cutover",
        kernel_base_url=kernel_base_url,
        kernel_contract_timeout_seconds=10.0,
        external_effects_enabled=True,
    )
    bridge = KernelExecutionBridge(store, settings=settings)

    first = bridge.prepare(case, obligation, governance)
    second = bridge.prepare(case, obligation, governance)
    if first is None or second is None:
        raise AssertionError("Kernel cutover did not create a durable Administrative projection")
    if first.status is not KernelProjectionStatus.CUTOVER:
        raise AssertionError(f"expected CUTOVER projection, got {first.status.value}")
    if second != first:
        raise AssertionError("Kernel cutover replay changed the durable execution projection")
    if first.kernel_execution_status is None or first.kernel_execution_status.value != "completed":
        raise AssertionError("Kernel cutover did not persist completed bounded execution")
    required_refs = {
        "run": first.kernel_run_ref,
        "request": first.kernel_request_ref,
        "authorization": first.kernel_authorization_ref,
        "provider": first.kernel_provider_id,
        "action": first.kernel_action_ref,
        "outcome": first.kernel_outcome_ref,
        "evidence": first.kernel_evidence_ref,
        "responsibility": first.kernel_execution_responsibility_ref,
    }
    missing = [name for name, value in required_refs.items() if not value]
    if missing:
        raise AssertionError("Kernel completed receipt lacks lineage: " + ", ".join(missing))

    effect_id = sandbox_effect_id(
        "administrative.hris.employee.create.v1",
        obligation.subject_ref,
    )
    response = httpx.get(f"{sandbox_base_url}/v1/effects/{effect_id}", timeout=5.0)
    response.raise_for_status()
    observed = response.json()
    if observed.get("state") != obligation.expected_postcondition:
        raise AssertionError("authoritative sandbox reality does not match the frozen postcondition")

    trap = ForbiddenFallbackProvider()
    provider = KernelCutoverEffectProvider(trap, bridge)
    effect = EffectRecord(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=uuid4(),
        obligation_id=obligation.obligation_id,
        governance_basis_id=governance.basis_id,
        target_system=obligation.target_system,
        operation=obligation.required_operation,
        subject_ref=obligation.subject_ref,
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=obligation.authority_class,
        created_at=now,
        updated_at=now,
    )
    execution = provider.execute(effect, dict(case.fact_snapshot.facts))
    if execution.status is not ProviderExecutionStatus.SUCCEEDED:
        raise AssertionError(f"Admin Kernel projection did not surface success: {execution.status}")
    observation = provider.observe(effect)
    verification = verify_onboarding_observation(
        effect,
        observation,
        expected_postcondition=obligation.expected_postcondition,
    )
    if verification.disposition is not VerificationDisposition.VERIFIED:
        raise AssertionError(
            "Admin semantic verification rejected Kernel-confirmed outcome: "
            + verification.reason
        )
    if trap.execute_calls != 0 or trap.observe_calls != 0:
        raise AssertionError("Kernel-owned HRIS capability touched the legacy provider")

    print(
        "cross-repo HRIS cutover verified: "
        f"execution_ref={first.kernel_execution_ref} "
        f"provider={first.kernel_provider_id} "
        "legacy_execute=0 legacy_observe=0"
    )


if __name__ == "__main__":
    main()
