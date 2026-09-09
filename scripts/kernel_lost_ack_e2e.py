from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

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
from administrative_orchestrator.integrations.kernel.client import (
    HttpKernelResponsibilityClient,
    KernelExecutionReceipt,
)
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.models import KernelProjectionStatus
from administrative_orchestrator.obligations import AdministrativeObligation
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)
from kernel_cutover_stack import sandbox_effect_id

FIXED_TIME = datetime(2026, 9, 9, 6, 15, tzinfo=UTC)
CASE_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7001")
SNAPSHOT_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7002")
GOVERNANCE_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7003")
APPROVAL_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7004")
OBLIGATION_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7005")
AUTHORIZATION_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7006")
EFFECT_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7007")
SUBJECT_REF = "employee:kernel-lost-ack"
CAPABILITY = "administrative.hris.employee.create.v1"


class LostAckAfterKernelCompletion(RuntimeError):
    """Fault injection after Kernel commits reality but before Admin stores receipt."""


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


class LoseExecutionAckClient:
    """Delegate through real Kernel, then lose the response before bridge persistence."""

    def __init__(self, delegate: HttpKernelResponsibilityClient, receipt_path: Path) -> None:
        self.delegate = delegate
        self.receipt_path = receipt_path

    def submit(self, projection):
        return self.delegate.submit(projection)

    def admit(self, projection, *, expected_policy_ref: str):
        return self.delegate.admit(projection, expected_policy_ref=expected_policy_ref)

    def execute(self, projection, grant, intent):
        receipt = self.delegate.execute(projection, grant, intent)
        self.receipt_path.write_text(
            json.dumps(_receipt_dict(receipt), sort_keys=True),
            encoding="utf-8",
        )
        raise LostAckAfterKernelCompletion(
            "fault injection: Kernel completed but Administrative receipt persistence did not run"
        )

    def inspect_execution(self, execution_ref: str, *, expected_work_ref: str | None = None):
        return self.delegate.inspect_execution(
            execution_ref,
            expected_work_ref=expected_work_ref,
        )


def _receipt_dict(receipt: KernelExecutionReceipt) -> dict[str, object]:
    return {
        "status": receipt.status,
        "execution_ref": receipt.execution_ref,
        "work_ref": receipt.work_ref,
        "run_ref": receipt.run_ref,
        "request_ref": receipt.request_ref,
        "authorization_ref": receipt.authorization_ref,
        "provider_id": receipt.provider_id,
        "action_ref": receipt.action_ref,
        "outcome_ref": receipt.outcome_ref,
        "evidence_ref": receipt.evidence_ref,
        "responsibility_ref": receipt.responsibility_ref,
    }


def _inputs() -> tuple[AdministrativeCase, GovernanceBasis, AdministrativeObligation]:
    facts = {
        "employee_ref": SUBJECT_REF,
        "department_ref": "department:engineering",
        "manager_principal_id": "person:lost-ack-manager",
        "start_date": "2026-09-16",
        "employment_type": "full-time",
    }
    policy = PolicyRef(
        policy_id="employee-onboarding",
        version="v1",
        owner="administrative-orchestrator",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    snapshot = FactSnapshot(
        snapshot_id=SNAPSHOT_ID,
        source="cross-repo-lost-ack-e2e",
        owner="administrative-orchestrator",
        authority=FactAuthority.ATTESTED,
        observed_at=FIXED_TIME,
        facts=facts,
    )
    case = AdministrativeCase(
        case_id=CASE_ID,
        case_kind="employee-onboarding",
        requester_principal_id="person:lost-ack-requester",
        subject_ref=SUBJECT_REF,
        authority_epoch=1,
        fact_snapshot=snapshot,
        policy_ref=policy,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    governance = GovernanceBasis(
        basis_id=GOVERNANCE_ID,
        case_id=CASE_ID,
        case_version_at_basis=case.version,
        authority_epoch=case.authority_epoch,
        fact_snapshot_id=SNAPSHOT_ID,
        fact_digest="lost-ack-fact-digest",
        policy_ref=policy,
        policy_definition_digest="lost-ack-policy-digest",
        organization_scope="department:engineering",
        approval_satisfaction_id=APPROVAL_ID,
        qualifications=(),
        authority_digest="lost-ack-authority-digest",
        basis_digest="lost-ack-basis-digest",
        created_at=FIXED_TIME,
    )
    obligation = AdministrativeObligation(
        obligation_id=OBLIGATION_ID,
        case_id=CASE_ID,
        authority_epoch=case.authority_epoch,
        governance_basis_id=GOVERNANCE_ID,
        kind="hris.employee.create",
        subject_ref=SUBJECT_REF,
        target_system="hris",
        required_operation="employee.create",
        expected_postcondition={
            "target_system": "hris",
            "operation": "employee.create",
            "subject_ref": SUBJECT_REF,
            "active": True,
            "payload": facts,
        },
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    return case, governance, obligation


def _paths() -> tuple[Path, Path]:
    return (
        Path(os.environ["ADMIN_LOST_ACK_DB_PATH"]).resolve(),
        Path(os.environ["ADMIN_LOST_ACK_RECEIPT_PATH"]).resolve(),
    )


def _settings() -> Settings:
    return Settings(
        kernel_bridge_mode="cutover",
        kernel_base_url=os.getenv("ADMIN_KERNEL_BASE_URL", "http://127.0.0.1:8020"),
        kernel_contract_timeout_seconds=10.0,
        external_effects_enabled=True,
    )


def _store(database_path: Path) -> SqlStore:
    store = SqlStore(f"sqlite+pysqlite:///{database_path}")
    store.init_schema()
    return store


def _sandbox_observation() -> dict[str, Any]:
    base_url = os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    effect_id = sandbox_effect_id(CAPABILITY, SUBJECT_REF)
    response = httpx.get(f"{base_url}/v1/effects/{effect_id}", timeout=5.0)
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, dict):
        raise AssertionError("sandbox observation must be a JSON object")
    return raw


def _phase1() -> None:
    database_path, receipt_path = _paths()
    database_path.unlink(missing_ok=True)
    receipt_path.unlink(missing_ok=True)
    case, governance, obligation = _inputs()
    store = _store(database_path)
    settings = _settings()
    client = LoseExecutionAckClient(
        HttpKernelResponsibilityClient(
            settings.kernel_base_url,
            timeout_seconds=settings.kernel_contract_timeout_seconds,
        ),
        receipt_path,
    )
    bridge = KernelExecutionBridge(store, settings=settings, client=client)
    bridge.prepare(case, obligation, governance)
    raise AssertionError("phase 1 must terminate at the injected lost-ack boundary")


def _phase2() -> None:
    database_path, receipt_path = _paths()
    case, governance, obligation = _inputs()
    store = _store(database_path)
    settings = _settings()
    bridge = KernelExecutionBridge(store, settings=settings)

    before = bridge.repository.get_projection_for_obligation(OBLIGATION_ID)
    if before is None:
        raise AssertionError("recovery did not reload the durable Administrative projection")
    if before.status is not KernelProjectionStatus.ADMITTED:
        raise AssertionError(f"lost-ack projection should be ADMITTED, got {before.status.value}")
    if any(
        value is not None
        for value in (
            before.kernel_execution_status,
            before.kernel_execution_ref,
            before.kernel_run_ref,
            before.kernel_action_ref,
            before.kernel_evidence_ref,
        )
    ):
        raise AssertionError("Administrative DB persisted completion despite injected lost ACK")

    first_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    recovered = bridge.prepare(case, obligation, governance)
    if recovered is None or recovered.status is not KernelProjectionStatus.CUTOVER:
        raise AssertionError("Kernel replay did not recover a completed cutover projection")
    recovered_receipt = {
        "status": recovered.kernel_execution_status.value if recovered.kernel_execution_status else None,
        "execution_ref": recovered.kernel_execution_ref,
        "work_ref": recovered.kernel_work_ref,
        "run_ref": recovered.kernel_run_ref,
        "request_ref": recovered.kernel_request_ref,
        "authorization_ref": recovered.kernel_authorization_ref,
        "provider_id": recovered.kernel_provider_id,
        "action_ref": recovered.kernel_action_ref,
        "outcome_ref": recovered.kernel_outcome_ref,
        "evidence_ref": recovered.kernel_evidence_ref,
        "responsibility_ref": recovered.kernel_execution_responsibility_ref,
    }
    for name, value in recovered_receipt.items():
        if first_receipt.get(name) != value:
            raise AssertionError(
                f"Kernel replay changed {name}: first={first_receipt.get(name)!r} recovered={value!r}"
            )

    trap = ForbiddenFallbackProvider()
    provider = KernelCutoverEffectProvider(trap, bridge)
    effect = EffectRecord(
        effect_id=EFFECT_ID,
        case_id=CASE_ID,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=AUTHORIZATION_ID,
        obligation_id=OBLIGATION_ID,
        governance_basis_id=GOVERNANCE_ID,
        target_system="hris",
        operation="employee.create",
        subject_ref=SUBJECT_REF,
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.EMPLOYMENT,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    execution = provider.execute(effect, dict(case.fact_snapshot.facts))
    observation = provider.observe(effect)
    verification = verify_onboarding_observation(
        effect,
        observation,
        expected_postcondition=obligation.expected_postcondition,
    )
    if execution.status is not ProviderExecutionStatus.SUCCEEDED:
        raise AssertionError("recovered Kernel execution did not surface success")
    if verification.disposition is not VerificationDisposition.VERIFIED:
        raise AssertionError(
            "recovered Kernel evidence did not satisfy Admin obligation: " + verification.reason
        )
    if trap.execute_calls != 0 or trap.observe_calls != 0:
        raise AssertionError("lost-ack recovery touched the legacy Administrative provider")

    sandbox = _sandbox_observation()
    if sandbox.get("state") != obligation.expected_postcondition:
        raise AssertionError("lost-ack recovery changed sandbox reality")
    if sandbox.get("apply_attempts") != 1:
        raise AssertionError(
            "Kernel replay crossed the provider boundary more than once: "
            f"apply_attempts={sandbox.get('apply_attempts')!r}"
        )
    print(
        "distributed lost-ack recovery verified: "
        f"execution_ref={recovered.kernel_execution_ref} "
        f"evidence_ref={recovered.kernel_evidence_ref} "
        "sandbox_apply_attempts=1 legacy_execute=0 legacy_observe=0"
    )


def _verify_phase1_boundary() -> None:
    database_path, receipt_path = _paths()
    if not database_path.exists() or not receipt_path.exists():
        raise AssertionError("phase 1 did not leave the expected durable/test harness state")
    store = _store(database_path)
    projection = store and KernelExecutionBridge(store, settings=_settings()).repository.get_projection_for_obligation(
        OBLIGATION_ID
    )
    if projection is None or projection.status is not KernelProjectionStatus.ADMITTED:
        raise AssertionError("phase 1 did not persist the pre-execution ADMITTED projection")
    if projection.kernel_execution_status is not None:
        raise AssertionError("phase 1 unexpectedly persisted Kernel completion")
    sandbox = _sandbox_observation()
    if sandbox.get("apply_attempts") != 1:
        raise AssertionError(
            f"phase 1 physical provider attempts={sandbox.get('apply_attempts')!r}, expected 1"
        )
    print("lost-ack boundary verified: admin_execution_receipt=absent sandbox_apply_attempts=1")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if phase == "phase1":
        _phase1()
    elif phase == "phase2":
        _phase2()
    elif phase == "verify":
        _verify_phase1_boundary()
    else:
        raise SystemExit(f"unknown phase: {phase}")
