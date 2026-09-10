from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import AuthorityClass
from administrative_orchestrator.integrations.kernel.bridge import KernelExecutionBridge
from administrative_orchestrator.integrations.kernel.capabilities import (
    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
    ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
    ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
    OFFBOARDING_CUTOVER_CAPABILITIES,
)
from administrative_orchestrator.obligations import AdministrativeObligation
from administrative_orchestrator.persistence import SqlStore


def _obligation(target: str, operation: str) -> AdministrativeObligation:
    return AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=uuid4(),
        authority_epoch=1,
        governance_basis_id=uuid4(),
        kind=f"{target}.{operation}",
        subject_ref="employee:1",
        target_system=target,
        required_operation=operation,
        authority_class=AuthorityClass.EMPLOYMENT,
    )


def test_bridge_owns_all_three_offboarding_capabilities_and_rejects_unknown() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = KernelExecutionBridge(
        store, settings=Settings(kernel_bridge_mode="cutover")
    )
    assert bridge.owns(_obligation("hris", "employee.deactivate"))
    assert bridge.owns(_obligation("iam", "identity.disable"))
    assert bridge.owns(_obligation("iam", "sessions.revoke"))
    assert not bridge.owns(_obligation("iam", "identity.force-delete"))


def _production_settings() -> SimpleNamespace:
    return SimpleNamespace(
        runtime_profile="staging",
        odoo_base_url="https://odoo.example.test",
        odoo_database="company",
        odoo_writer_username="writer",
        odoo_writer_secret_env="ADMIN_TEST_ODOO_WRITER_SECRET",
        odoo_verifier_username="verifier",
        odoo_verifier_secret_env="ADMIN_TEST_ODOO_VERIFIER_SECRET",
        odoo_request_ref_field="x_administrative_request_ref",
        odoo_deactivate_request_ref_field="x_administrative_deactivate_request_ref",
        keycloak_base_url="https://idp.example.test",
        keycloak_realm="company",
        keycloak_writer_client_id="writer",
        keycloak_writer_secret_env="ADMIN_TEST_KEYCLOAK_WRITER_SECRET",
        keycloak_verifier_client_id="verifier",
        keycloak_verifier_secret_env="ADMIN_TEST_KEYCLOAK_VERIFIER_SECRET",
        keycloak_request_ref_attribute="administrative_request_ref",
        keycloak_disable_request_ref_attribute="administrative_disable_request_ref",
        keycloak_session_revoke_request_ref_attribute=(
            "administrative_session_revoke_request_ref"
        ),
        connector_timeout_seconds=3.0,
        oidc_allow_insecure_http=False,
    )


@pytest.mark.asyncio
async def test_production_stack_registers_irreversible_reconcilable_profiles(
    monkeypatch, tmp_path
) -> None:
    domain_effect = pytest.importorskip(
        "portable_runtime.public_contracts.domain_effect"
    )
    import scripts.production_kernel_stack as stack

    monkeypatch.setattr(stack, "get_settings", _production_settings)
    monkeypatch.setenv(
        "PORTABLE_RUNTIME_ADMIN_PRODUCTION_STATE_PATH",
        str(tmp_path / "kernel-state.db"),
    )
    runtime, service = stack.build()

    assert service.profiles.keys() >= OFFBOARDING_CUTOVER_CAPABILITIES
    for capability in OFFBOARDING_CUTOVER_CAPABILITIES:
        contract = runtime.contract_registry.resolve(capability)
        assert contract is not None
        assert contract.effect_semantics == "reconcilable"
        assert contract.reversibility == "irreversible"
        profile = service.profiles[capability]
        writers = runtime.registry.descriptors_for(capability, [])
        assert [item.id for item in writers] == [profile.provider_id]
        assert writers[0].reversibility == "irreversible"

    unknown = domain_effect.BoundedDomainEffectExecutionV1(
        work_ref="work:unknown",
        domain_intent_ref="intent:unknown",
        domain_grant_ref="grant:unknown",
        governance_basis_ref="basis:unknown",
        approval_satisfaction_ref="approval:unknown",
        capability="administrative.iam.identity.force-delete.v1",
        subject_ref="employee:1",
        authority_epoch=1,
        observed_at=datetime.now(UTC),
    )
    with pytest.raises(
        ValueError, match="capability is not configured server-side"
    ):
        await service.execute(unknown)

    assert ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE in service.profiles
    assert ADMINISTRATIVE_IAM_IDENTITY_DISABLE in service.profiles
    assert ADMINISTRATIVE_IAM_SESSIONS_REVOKE in service.profiles
