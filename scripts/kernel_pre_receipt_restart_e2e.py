from __future__ import annotations

import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from kernel_cutover_stack import sandbox_effect_id

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
    KernelExecutionError,
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

FIXED_TIME = datetime(2026, 9, 9, 6, 30, tzinfo=UTC)
CASE_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7101")
SNAPSHOT_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7102")
GOVERNANCE_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7103")
APPROVAL_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7104")
OBLIGATION_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7105")
AUTHORIZATION_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7106")
EFFECT_ID = UUID("4e8ba42e-75ab-58ae-8e53-11abecce7107")
SUBJECT_REF = "employee:kernel-pre-receipt-crash"
CAPABILITY = "administrative.hris.employee.create.v1"


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


def _inputs() -> tuple[AdministrativeCase, GovernanceBasis, AdministrativeObligation]:
    facts = {
        "employee_ref": SUBJECT_REF,
        "department_ref": "department:engineering",
        "manager_principal_id": "person:pre-receipt-manager",
        "start_date": "2026-09-17",
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
        source="cross-repo-pre-receipt-e2e",
        owner="administrative-orchestrator",
        authority=FactAuthority.ATTESTED,
        observed_at=FIXED_TIME,
        facts=facts,
    )
    case = AdministrativeCase(
        case_id=CASE_ID,
        case_kind="employee-onboarding",
        requester_principal_id="person:pre-receipt-requester",
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
        fact_digest="pre-receipt-fact-digest",
        policy_ref=policy,
        policy_definition_digest="pre-receipt-policy-digest",
        organization_scope="department:engineering",
        approval_satisfaction_id=APPROVAL_ID,
        qualifications=(),
        authority_digest="pre-receipt-authority-digest",
        basis_digest="pre-receipt-basis-digest",
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
            "payload": {**facts, "subject_ref": SUBJECT_REF},
        },
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    return case, governance, obligation


def _database_path() -> Path:
    return Path(os.environ["ADMIN_PRE_RECEIPT_DB_PATH"]).resolve()


def _fault_marker_path() -> Path:
    return Path(os.environ["PORTABLE_RUNTIME_ADMIN_E2E_PRE_RECEIPT_FAIL_ONCE_PATH"]).resolve()


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


def _sandbox_observation() -> dict[str, object]:
    base_url = os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    effect_id = sandbox_effect_id(CAPABILITY, SUBJECT_REF)
    response = httpx.get(f"{base_url}/v1/effects/{effect_id}", timeout=5.0)
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, dict):
        raise AssertionError("sandbox observation must be a JSON object")
    return raw


def _execution_ref(projection) -> str:
    if not projection.kernel_work_ref:
        raise AssertionError("pre-receipt projection lacks Kernel Work ref")
    parts = (
        projection.kernel_work_ref,
        str(projection.intent_id),
        str(projection.grant_id),
        CAPABILITY,
        SUBJECT_REF,
        1,
    )
    digest = hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"execution_bounded_domain_effect_{digest[:32]}"


def _assert_admin_pre_receipt_state(bridge: KernelExecutionBridge):
    projection = bridge.repository.get_projection_for_obligation(OBLIGATION_ID)
    if projection is None:
        raise AssertionError("pre-receipt crash did not persist the Administrative projection")
    if projection.status is not KernelProjectionStatus.ADMITTED:
        raise AssertionError(
            f"pre-receipt crash should leave ADMITTED projection, got {projection.status.value}"
        )
    if any(
        value is not None
        for value in (
            projection.kernel_execution_status,
            projection.kernel_execution_ref,
            projection.kernel_run_ref,
            projection.kernel_action_ref,
            projection.kernel_evidence_ref,
        )
    ):
        raise AssertionError("Administrative DB persisted a bounded receipt before fault injection")
    return projection


def _phase1() -> None:
    database_path = _database_path()
    database_path.unlink(missing_ok=True)
    case, governance, obligation = _inputs()
    bridge = KernelExecutionBridge(_store(database_path), settings=_settings())
    try:
        bridge.prepare(case, obligation, governance)
    except KernelExecutionError:
        raise
    raise AssertionError("phase 1 expected Kernel pre-receipt fault but execution returned")


def _verify_phase1_boundary() -> None:
    database_path = _database_path()
    if not database_path.exists():
        raise AssertionError("phase 1 did not persist Administrative pre-execution state")
    bridge = KernelExecutionBridge(_store(database_path), settings=_settings())
    projection = _assert_admin_pre_receipt_state(bridge)
    marker = _fault_marker_path()
    if not marker.exists():
        raise AssertionError("Kernel pre-receipt fault marker was not written")

    sandbox = _sandbox_observation()
    if sandbox.get("apply_attempts") != 1:
        raise AssertionError(
            "phase 1 did not cross the physical provider boundary exactly once: "
            f"apply_attempts={sandbox.get('apply_attempts')!r}"
        )
    expected_state = _inputs()[2].expected_postcondition
    if sandbox.get("state") != expected_state:
        raise AssertionError("phase 1 physical reality does not match frozen postcondition")

    execution_ref = _execution_ref(projection)
    client = HttpKernelResponsibilityClient(
        _settings().kernel_base_url,
        timeout_seconds=_settings().kernel_contract_timeout_seconds,
    )
    if client.inspect_execution(
        execution_ref,
        expected_work_ref=projection.kernel_work_ref,
    ) is not None:
        raise AssertionError("Kernel persisted bounded execution receipt before injected crash")
    print(
        "pre-receipt crash boundary verified: "
        f"execution_ref={execution_ref} kernel_receipt=absent sandbox_apply_attempts=1"
    )


def _phase2() -> None:
    database_path = _database_path()
    case, governance, obligation = _inputs()
    bridge = KernelExecutionBridge(_store(database_path), settings=_settings())
    before = _assert_admin_pre_receipt_state(bridge)
    expected_execution_ref = _execution_ref(before)

    recovered = bridge.prepare(case, obligation, governance)
    if recovered is None or recovered.status is not KernelProjectionStatus.CUTOVER:
        raise AssertionError("Kernel restart did not resume the pre-receipt execution")
    if recovered.kernel_execution_status is None or recovered.kernel_execution_status.value != "completed":
        raise AssertionError("Kernel restart did not complete the resumed bounded execution")
    if recovered.kernel_execution_ref != expected_execution_ref:
        raise AssertionError("Kernel restart changed deterministic bounded execution identity")
    required = {
        "run_ref": recovered.kernel_run_ref,
        "request_ref": recovered.kernel_request_ref,
        "authorization_ref": recovered.kernel_authorization_ref,
        "provider_id": recovered.kernel_provider_id,
        "action_ref": recovered.kernel_action_ref,
        "outcome_ref": recovered.kernel_outcome_ref,
        "evidence_ref": recovered.kernel_evidence_ref,
        "responsibility_ref": recovered.kernel_execution_responsibility_ref,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise AssertionError("resumed Kernel receipt lacks lineage: " + ", ".join(missing))

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
        raise AssertionError("resumed Kernel execution did not surface success")
    if verification.disposition is not VerificationDisposition.VERIFIED:
        raise AssertionError(
            "resumed Kernel evidence did not satisfy Admin obligation: " + verification.reason
        )
    if trap.execute_calls != 0 or trap.observe_calls != 0:
        raise AssertionError("pre-receipt recovery touched the legacy Administrative provider")

    sandbox = _sandbox_observation()
    if sandbox.get("state") != obligation.expected_postcondition:
        raise AssertionError("pre-receipt recovery changed sandbox reality")
    if sandbox.get("apply_attempts") != 1:
        raise AssertionError(
            "Kernel resumed by redispatching the physical provider: "
            f"apply_attempts={sandbox.get('apply_attempts')!r}"
        )
    print(
        "pre-receipt Kernel restart recovery verified: "
        f"execution_ref={recovered.kernel_execution_ref} "
        f"evidence_ref={recovered.kernel_evidence_ref} "
        "sandbox_apply_attempts=1 legacy_execute=0 legacy_observe=0"
    )


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if phase == "phase1":
        _phase1()
    elif phase == "verify":
        _verify_phase1_boundary()
    elif phase == "phase2":
        _phase2()
    else:
        raise SystemExit(f"unknown phase: {phase}")
