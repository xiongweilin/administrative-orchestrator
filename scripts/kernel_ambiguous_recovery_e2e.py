from __future__ import annotations

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
from administrative_orchestrator.integrations.kernel.client import HttpKernelResponsibilityClient
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
)
from administrative_orchestrator.obligations import AdministrativeObligation
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)

FIXED_TIME = datetime(2026, 9, 9, 8, 30, tzinfo=UTC)
CASE_ID = UUID("71fa11b2-3e79-5f69-91ab-6f16dfba5101")
SNAPSHOT_ID = UUID("71fa11b2-3e79-5f69-91ab-6f16dfba5102")
GOVERNANCE_ID = UUID("71fa11b2-3e79-5f69-91ab-6f16dfba5103")
APPROVAL_ID = UUID("71fa11b2-3e79-5f69-91ab-6f16dfba5104")
OBLIGATION_ID = UUID("71fa11b2-3e79-5f69-91ab-6f16dfba5105")
AUTHORIZATION_ID = UUID("71fa11b2-3e79-5f69-91ab-6f16dfba5106")
EFFECT_ID = UUID("71fa11b2-3e79-5f69-91ab-6f16dfba5107")
SUBJECT_REF = "employee:kernel-ambiguous-result-commit"
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
        "manager_principal_id": "person:ambiguous-manager",
        "start_date": "2026-09-18",
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
        source="cross-repo-ambiguous-recovery-e2e",
        owner="administrative-orchestrator",
        authority=FactAuthority.ATTESTED,
        observed_at=FIXED_TIME,
        facts=facts,
    )
    case = AdministrativeCase(
        case_id=CASE_ID,
        case_kind="employee-onboarding",
        requester_principal_id="person:ambiguous-requester",
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
        fact_digest="ambiguous-recovery-fact-digest",
        policy_ref=policy,
        policy_definition_digest="ambiguous-recovery-policy-digest",
        organization_scope="department:engineering",
        approval_satisfaction_id=APPROVAL_ID,
        qualifications=(),
        authority_digest="ambiguous-recovery-authority-digest",
        basis_digest="ambiguous-recovery-basis-digest",
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


def _settings() -> Settings:
    return Settings(
        kernel_bridge_mode="cutover",
        kernel_base_url=os.getenv("ADMIN_KERNEL_BASE_URL", "http://127.0.0.1:8020"),
        kernel_contract_timeout_seconds=10.0,
        external_effects_enabled=True,
    )


def _database_path() -> Path:
    return Path(os.environ["ADMIN_AMBIGUOUS_RECOVERY_DB_PATH"]).resolve()


def _fault_marker_path() -> Path:
    return Path(os.environ["PORTABLE_RUNTIME_ADMIN_E2E_RESULT_COMMIT_FAIL_ONCE_PATH"]).resolve()


def _store() -> SqlStore:
    path = _database_path()
    store = SqlStore(f"sqlite+pysqlite:///{path}")
    store.init_schema()
    return store


def _bridge() -> KernelExecutionBridge:
    return KernelExecutionBridge(_store(), settings=_settings())


def _effect(case: AdministrativeCase) -> EffectRecord:
    return EffectRecord(
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


def _sandbox_observation() -> dict[str, object]:
    base_url = os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    effect_id = sandbox_effect_id(CAPABILITY, SUBJECT_REF)
    response = httpx.get(f"{base_url}/v1/effects/{effect_id}", timeout=5.0)
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, dict):
        raise AssertionError("sandbox observation must be a JSON object")
    return raw


def _historical_unknown(bridge: KernelExecutionBridge):
    projection = bridge.repository.get_projection_for_obligation(OBLIGATION_ID)
    if projection is None:
        raise AssertionError("Administrative projection is unavailable")
    if projection.status is not KernelProjectionStatus.ADMITTED:
        raise AssertionError(
            f"ambiguous execution must remain ADMITTED historically, got {projection.status.value}"
        )
    if projection.kernel_execution_status is not KernelExecutionStatus.EXECUTION_UNKNOWN:
        raise AssertionError("Administrative projection did not preserve execution-unknown")
    required = {
        "execution_ref": projection.kernel_execution_ref,
        "work_ref": projection.kernel_work_ref,
        "run_ref": projection.kernel_run_ref,
        "request_ref": projection.kernel_request_ref,
        "provider_id": projection.kernel_provider_id,
        "action_ref": projection.kernel_action_ref,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise AssertionError("execution-unknown projection lacks lineage: " + ", ".join(missing))
    if projection.kernel_outcome_ref is not None or projection.kernel_evidence_ref is not None:
        raise AssertionError("execution-unknown historical projection cannot carry objective completion")
    return projection


def _phase1() -> None:
    database_path = _database_path()
    database_path.unlink(missing_ok=True)
    case, governance, obligation = _inputs()
    bridge = _bridge()

    projection = bridge.prepare(case, obligation, governance)
    if projection is None:
        raise AssertionError("Kernel ambiguity phase did not create Administrative projection")
    historical = _historical_unknown(bridge)
    if projection != historical:
        raise AssertionError("persisted ambiguous projection differs from returned receipt projection")
    if not _fault_marker_path().exists():
        raise AssertionError("Kernel result-commit failure marker was not written")

    sandbox = _sandbox_observation()
    if sandbox.get("state") != obligation.expected_postcondition:
        raise AssertionError("provider changed reality to an unexpected postcondition")
    if sandbox.get("apply_attempts") != 1:
        raise AssertionError(
            "provider boundary did not execute exactly once before ambiguity: "
            f"apply_attempts={sandbox.get('apply_attempts')!r}"
        )

    execution_ref = historical.kernel_execution_ref
    assert execution_ref is not None
    kernel_receipt = HttpKernelResponsibilityClient(
        _settings().kernel_base_url,
        timeout_seconds=_settings().kernel_contract_timeout_seconds,
    ).inspect_execution(execution_ref, expected_work_ref=historical.kernel_work_ref)
    if kernel_receipt is None or kernel_receipt.status != "execution-unknown":
        raise AssertionError("Kernel did not durably publish execution-unknown")

    replay = bridge.prepare(case, obligation, governance)
    if replay != historical:
        raise AssertionError("ordinary Administrative replay changed ambiguous execution history")
    if _sandbox_observation().get("apply_attempts") != 1:
        raise AssertionError("ordinary replay redispatched the physical provider")

    print(
        "ambiguous result-commit boundary verified: "
        f"execution_ref={execution_ref} historical=execution-unknown apply_attempts=1"
    )


def _phase2() -> None:
    case, _, obligation = _inputs()
    bridge = _bridge()
    historical_before = _historical_unknown(bridge)
    trap = ForbiddenFallbackProvider()
    provider = KernelCutoverEffectProvider(trap, bridge)
    effect = _effect(case)

    execution = provider.execute(effect, dict(case.fact_snapshot.facts))
    if execution.status is not ProviderExecutionStatus.SUCCEEDED:
        raise AssertionError(
            "Administrative recovery consumption did not surface recovered success: "
            f"{execution.status.value}"
        )

    execution_ref = historical_before.kernel_execution_ref
    assert execution_ref is not None
    resolution = bridge.recovery_client().inspect(
        execution_ref,
        expected_work_ref=historical_before.kernel_work_ref,
    )
    if resolution is None or resolution.current_status != "recovered-completed":
        raise AssertionError("fresh Kernel process did not produce recovered-completed resolution")
    if resolution.original_status != "execution-unknown":
        raise AssertionError("Kernel recovery rewrote original ambiguity semantics")
    if not resolution.evidence_ref or not resolution.outcome_ref:
        raise AssertionError("recovered completion lacks Kernel evidence/outcome refs")

    historical_after = _historical_unknown(bridge)
    if historical_after != historical_before:
        raise AssertionError("Administrative historical Kernel execution projection was rewritten")

    kernel_receipt = HttpKernelResponsibilityClient(
        _settings().kernel_base_url,
        timeout_seconds=_settings().kernel_contract_timeout_seconds,
    ).inspect_execution(execution_ref, expected_work_ref=historical_before.kernel_work_ref)
    if kernel_receipt is None or kernel_receipt.status != "execution-unknown":
        raise AssertionError("Kernel historical execution receipt was rewritten by recovery")

    observation = provider.observe(effect)
    verification = verify_onboarding_observation(
        effect,
        observation,
        expected_postcondition=obligation.expected_postcondition,
    )
    if verification.disposition is not VerificationDisposition.VERIFIED:
        raise AssertionError(
            "Administrative business verification rejected recovered Kernel evidence: "
            + verification.reason
        )

    replay = provider.execute(effect, dict(case.fact_snapshot.facts))
    if replay.status is not ProviderExecutionStatus.SUCCEEDED:
        raise AssertionError("recovered execution replay did not remain successful")
    sandbox = _sandbox_observation()
    if sandbox.get("state") != obligation.expected_postcondition:
        raise AssertionError("Kernel recovery changed already-correct physical reality")
    if sandbox.get("apply_attempts") != 1:
        raise AssertionError(
            "Kernel recovery or replay redispatched physical execution: "
            f"apply_attempts={sandbox.get('apply_attempts')!r}"
        )
    if trap.execute_calls != 0 or trap.observe_calls != 0:
        raise AssertionError("ambiguous Kernel recovery touched legacy Administrative provider")

    print(
        "cross-process ambiguous recovery verified: "
        f"execution_ref={execution_ref} resolution={resolution.current_status} "
        f"evidence_ref={resolution.evidence_ref} apply_attempts=1 "
        "legacy_execute=0 legacy_observe=0"
    )


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "phase2"
    if phase == "phase1":
        _phase1()
    elif phase == "phase2":
        _phase2()
    else:
        raise SystemExit(f"unknown phase: {phase}")
