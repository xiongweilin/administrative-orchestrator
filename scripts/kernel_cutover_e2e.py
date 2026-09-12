from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.mapper import capability_for
from administrative_orchestrator.integrations.kernel.models import KernelProjectionStatus
from administrative_orchestrator.obligations import AdministrativeObligation
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)


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


def _install_kernel_http_error_diagnostics(kernel_base_url: str) -> None:
    """Expose trusted local Kernel problem details when this CI harness fails."""

    original_post = httpx.post

    def diagnostic_post(url, *args, **kwargs):
        response = original_post(url, *args, **kwargs)
        if response.status_code >= 400 and str(url).startswith(kernel_base_url):
            print(
                "kernel_http_error "
                f"status={response.status_code} url={url} body={response.text}",
                flush=True,
            )
        return response

    httpx.post = diagnostic_post


def _inputs(
    now: datetime,
) -> tuple[AdministrativeCase, GovernanceBasis, tuple[AdministrativeObligation, ...]]:
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

    def obligation(
        *,
        target_system: str,
        operation: str,
        authority_class: AuthorityClass,
    ) -> AdministrativeObligation:
        return AdministrativeObligation(
            obligation_id=uuid4(),
            case_id=case_id,
            authority_epoch=case.authority_epoch,
            governance_basis_id=governance_id,
            kind=f"{target_system}.{operation}",
            subject_ref=case.subject_ref,
            target_system=target_system,
            required_operation=operation,
            expected_postcondition={
                "target_system": target_system,
                "operation": operation,
                "subject_ref": case.subject_ref,
                "active": True,
                "payload": {**facts, "subject_ref": case.subject_ref},
            },
            authority_class=authority_class,
        )

    obligations = (
        obligation(
            target_system="hris",
            operation="employee.create",
            authority_class=AuthorityClass.EMPLOYMENT,
        ),
        obligation(
            target_system="iam",
            operation="identity.create",
            authority_class=AuthorityClass.PRIVILEGED_ACCESS,
        ),
    )
    return case, governance, obligations


def _assert_kernel_lineage(projection, *, capability: str) -> None:
    if projection.status is not KernelProjectionStatus.CUTOVER:
        raise AssertionError(f"{capability}: expected CUTOVER projection, got {projection.status.value}")
    if projection.kernel_execution_status is None or projection.kernel_execution_status.value != "completed":
        raise AssertionError(f"{capability}: Kernel cutover did not persist completed bounded execution")
    required_refs = {
        "run": projection.kernel_run_ref,
        "request": projection.kernel_request_ref,
        "authorization": projection.kernel_authorization_ref,
        "provider": projection.kernel_provider_id,
        "action": projection.kernel_action_ref,
        "outcome": projection.kernel_outcome_ref,
        "evidence": projection.kernel_evidence_ref,
        "responsibility": projection.kernel_execution_responsibility_ref,
    }
    missing = [name for name, value in required_refs.items() if not value]
    if missing:
        raise AssertionError(f"{capability}: Kernel completed receipt lacks lineage: " + ", ".join(missing))


def main() -> None:
    kernel_base_url = os.getenv("ADMIN_KERNEL_BASE_URL", "http://127.0.0.1:8020").rstrip("/")
    sandbox_base_url = os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    _install_kernel_http_error_diagnostics(kernel_base_url)
    now = datetime.now(UTC)
    case, governance, obligations = _inputs(now)

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    settings = Settings(
        kernel_bridge_mode="cutover",
        kernel_base_url=kernel_base_url,
        kernel_contract_timeout_seconds=10.0,
        external_effects_enabled=True,
    )
    bridge = KernelExecutionBridge(store, settings=settings)
    trap = ForbiddenFallbackProvider()
    provider = KernelCutoverEffectProvider(trap, bridge)

    summaries: list[str] = []
    for obligation in obligations:
        capability = capability_for(obligation)
        first = bridge.prepare(case, obligation, governance)
        second = bridge.prepare(case, obligation, governance)
        if first is None or second is None:
            raise AssertionError(f"{capability}: Kernel cutover did not create a durable projection")
        if second != first:
            raise AssertionError(f"{capability}: replay changed the durable execution projection")
        _assert_kernel_lineage(first, capability=capability)

        effect_id = sandbox_effect_id(capability, obligation.subject_ref)
        response = httpx.get(f"{sandbox_base_url}/v1/effects/{effect_id}", timeout=5.0)
        response.raise_for_status()
        observed = response.json()
        if observed.get("state") != obligation.expected_postcondition:
            raise AssertionError(f"{capability}: sandbox reality does not match frozen postcondition")

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
            raise AssertionError(f"{capability}: Admin Kernel projection did not surface success")
        observation = provider.observe(effect)
        verification = verify_onboarding_observation(
            effect,
            observation,
            expected_postcondition=obligation.expected_postcondition,
        )
        if verification.disposition is not VerificationDisposition.VERIFIED:
            raise AssertionError(
                f"{capability}: Admin semantic verification rejected Kernel-confirmed outcome: "
                + verification.reason
            )
        summaries.append(
            f"{capability} execution_ref={first.kernel_execution_ref} provider={first.kernel_provider_id}"
        )

    if trap.execute_calls != 0 or trap.observe_calls != 0:
        raise AssertionError("Kernel-owned HRIS/IAM capabilities touched the legacy provider")

    print(
        "cross-repo dual cutover verified: "
        + " | ".join(summaries)
        + " | legacy_execute=0 legacy_observe=0"
    )


if __name__ == "__main__":
    main()
