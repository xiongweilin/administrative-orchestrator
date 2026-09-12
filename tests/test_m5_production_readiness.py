from __future__ import annotations

import pytest

from administrative_orchestrator.config import Settings
from administrative_orchestrator.integrations.kernel.compatibility import KernelContractIdentity
from administrative_orchestrator.production_readiness import (
    ProductionReadinessError,
    validate_kernel_runtime_compatibility,
    validate_production_connector_isolation,
    validate_production_control_plane,
)

TEST_KERNEL_REVISION = "kernel-revision-a"


def _production_settings(**overrides) -> Settings:
    values = {
        "runtime_profile": "production",
        "auth_mode": "oidc",
        "oidc_issuer": "https://idp.example.test",
        "oidc_audience": "administrative-orchestrator",
        "database_url": "postgresql+psycopg://admin:secret@db/admin",
        "worker_database_url": "postgresql+psycopg://worker:secret@db/admin",
        "dbos_system_database_url": "postgresql+psycopg://dbos:secret@db/admin_dbos",
        "auto_create_schema": False,
        "external_effects_enabled": True,
        "kernel_bridge_mode": "cutover",
        "kernel_supported_revision": TEST_KERNEL_REVISION,
        "hris_source_kind": "odoo",
        "odoo_base_url": "https://odoo.example.test",
        "odoo_database": "company",
        "odoo_reader_username": "admin-reader",
        "odoo_writer_username": "kernel-writer",
        "odoo_verifier_username": "kernel-verifier",
        "odoo_reader_secret_env": "ADMIN_ODOO_READER_SECRET",
        "odoo_writer_secret_env": "ADMIN_ODOO_WRITER_SECRET",
        "odoo_verifier_secret_env": "ADMIN_ODOO_VERIFIER_SECRET",
        "odoo_financial_writer_username": "financial-writer",
        "odoo_financial_verifier_username": "financial-verifier",
        "odoo_financial_writer_secret_env": "ADMIN_ODOO_FINANCIAL_WRITER_SECRET",
        "odoo_financial_verifier_secret_env": "ADMIN_ODOO_FINANCIAL_VERIFIER_SECRET",
        "iam_source_kind": "keycloak",
        "keycloak_base_url": "https://keycloak.example.test",
        "keycloak_realm": "company",
        "keycloak_reader_client_id": "admin-reader",
        "keycloak_writer_client_id": "kernel-writer",
        "keycloak_verifier_client_id": "kernel-verifier",
        "keycloak_reader_secret_env": "ADMIN_KEYCLOAK_READER_SECRET",
        "keycloak_writer_secret_env": "ADMIN_KEYCLOAK_WRITER_SECRET",
        "keycloak_verifier_secret_env": "ADMIN_KEYCLOAK_VERIFIER_SECRET",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_readiness_accepts_pinned_cutover_with_isolated_connectors():
    settings = _production_settings()

    validate_production_control_plane(settings)
    validate_production_connector_isolation(settings)


def test_production_control_plane_rejects_non_cutover_or_sqlite():
    with pytest.raises(ProductionReadinessError, match="Kernel cutover mode"):
        validate_production_control_plane(_production_settings(kernel_bridge_mode="shadow"))

    with pytest.raises(ProductionReadinessError, match="ADMIN_DATABASE_URL must use PostgreSQL"):
        validate_production_control_plane(_production_settings(database_url="sqlite:///admin.db"))


def _kernel_identity(build_revision: str | None) -> KernelContractIdentity:
    return KernelContractIdentity(
        catalog_version="portable-runtime-contracts-v1",
        owner="portable-runtime/contracts",
        runtime_protocol="2.0",
        persistent_responsibility_contract="persistent-responsibility-v1",
        domain_responsibility_proposal_contract="domain-responsibility-proposal-v1",
        build_revision=build_revision,
    )


def test_kernel_runtime_revision_matches_expected_value():
    settings = _production_settings(kernel_supported_revision=TEST_KERNEL_REVISION)
    identity = validate_kernel_runtime_compatibility(
        settings,
        identity=_kernel_identity(TEST_KERNEL_REVISION),
    )
    assert identity.build_revision == TEST_KERNEL_REVISION


def test_kernel_runtime_revision_mismatch_fails_closed():
    settings = _production_settings(kernel_supported_revision=TEST_KERNEL_REVISION)
    with pytest.raises(ProductionReadinessError, match="does not match"):
        validate_kernel_runtime_compatibility(
            settings,
            identity=_kernel_identity("kernel-revision-b"),
        )


def test_kernel_runtime_revision_missing_fails_closed():
    settings = _production_settings(kernel_supported_revision=TEST_KERNEL_REVISION)
    with pytest.raises(ProductionReadinessError, match="does not match"):
        validate_kernel_runtime_compatibility(
            settings,
            identity=_kernel_identity(None),
        )


def test_production_control_plane_requires_a_deployment_revision():
    with pytest.raises(ProductionReadinessError, match="AGENT_KERNEL_REF"):
        validate_production_control_plane(
            _production_settings(kernel_supported_revision="")
        )


def test_production_connector_isolation_rejects_shared_writer_verifier_identity():
    with pytest.raises(ProductionReadinessError, match="Odoo writer and verifier identities"):
        validate_production_connector_isolation(
            _production_settings(odoo_verifier_username="kernel-writer")
        )

    with pytest.raises(ProductionReadinessError, match="Keycloak writer and verifier identities"):
        validate_production_connector_isolation(
            _production_settings(keycloak_verifier_client_id="kernel-writer")
        )

    with pytest.raises(
        ProductionReadinessError,
        match="Odoo financial writer and verifier identities",
    ):
        validate_production_connector_isolation(
            _production_settings(odoo_financial_verifier_username="financial-writer")
        )


def test_production_connector_isolation_rejects_shared_secret_reference():
    with pytest.raises(ProductionReadinessError, match="Odoo writer and verifier secret references"):
        validate_production_connector_isolation(
            _production_settings(odoo_verifier_secret_env="ADMIN_ODOO_WRITER_SECRET")
        )

    with pytest.raises(
        ProductionReadinessError,
        match="Keycloak writer and verifier secret references",
    ):
        validate_production_connector_isolation(
            _production_settings(keycloak_verifier_secret_env="ADMIN_KEYCLOAK_WRITER_SECRET")
        )

    with pytest.raises(
        ProductionReadinessError,
        match="Odoo financial writer and verifier secret references",
    ):
        validate_production_connector_isolation(
            _production_settings(
                odoo_financial_verifier_secret_env="ADMIN_ODOO_FINANCIAL_WRITER_SECRET"
            )
        )
