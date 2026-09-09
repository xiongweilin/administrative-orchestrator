from __future__ import annotations

from urllib.parse import urlparse

from .config import SUPPORTED_KERNEL_REVISION, Settings


class ProductionReadinessError(RuntimeError):
    pass


def validate_production_connector_isolation(settings: Settings) -> None:
    """Fail closed before the production Kernel can own real external writes."""

    if settings.runtime_profile != "production":
        raise ProductionReadinessError("production connectors require runtime_profile=production")
    if settings.hris_source_kind != "odoo":
        raise ProductionReadinessError("production onboarding requires ADMIN_HRIS_SOURCE_KIND=odoo")
    if settings.iam_source_kind != "keycloak":
        raise ProductionReadinessError("production onboarding requires ADMIN_IAM_SOURCE_KIND=keycloak")

    _require_https(settings.odoo_base_url, "Odoo")
    _require_nonempty(settings.odoo_database, "ADMIN_ODOO_DATABASE")
    _require_nonempty(settings.odoo_reader_username, "ADMIN_ODOO_READER_USERNAME")
    _require_nonempty(settings.odoo_writer_username, "ADMIN_ODOO_WRITER_USERNAME")
    _require_nonempty(settings.odoo_verifier_username, "ADMIN_ODOO_VERIFIER_USERNAME")
    if settings.odoo_writer_username == settings.odoo_verifier_username:
        raise ProductionReadinessError("Odoo writer and verifier identities must be distinct")
    if settings.odoo_writer_secret_env == settings.odoo_verifier_secret_env:
        raise ProductionReadinessError("Odoo writer and verifier secret references must be distinct")
    if not settings.odoo_request_ref_field.startswith("x_"):
        raise ProductionReadinessError("Odoo durable request identity must use a custom x_ field")

    _require_https(settings.keycloak_base_url, "Keycloak")
    _require_nonempty(settings.keycloak_realm, "ADMIN_KEYCLOAK_REALM")
    _require_nonempty(settings.keycloak_reader_client_id, "ADMIN_KEYCLOAK_READER_CLIENT_ID")
    _require_nonempty(settings.keycloak_writer_client_id, "ADMIN_KEYCLOAK_WRITER_CLIENT_ID")
    _require_nonempty(settings.keycloak_verifier_client_id, "ADMIN_KEYCLOAK_VERIFIER_CLIENT_ID")
    if settings.keycloak_writer_client_id == settings.keycloak_verifier_client_id:
        raise ProductionReadinessError("Keycloak writer and verifier identities must be distinct")
    if settings.keycloak_writer_secret_env == settings.keycloak_verifier_secret_env:
        raise ProductionReadinessError("Keycloak writer and verifier secret references must be distinct")
    _require_nonempty(
        settings.keycloak_request_ref_attribute,
        "ADMIN_KEYCLOAK_REQUEST_REF_ATTRIBUTE",
    )


def validate_production_control_plane(settings: Settings) -> None:
    """Validate deploy-time controls that keep Administrative and Kernel authority separated."""

    if settings.runtime_profile != "production":
        raise ProductionReadinessError("production control plane requires runtime_profile=production")
    if settings.auth_mode != "oidc":
        raise ProductionReadinessError("production control plane requires OIDC authentication")
    if settings.kernel_bridge_mode != "cutover":
        raise ProductionReadinessError("production external effects require Kernel cutover mode")
    if not settings.external_effects_enabled:
        raise ProductionReadinessError("production cutover requires external effects to be enabled")
    if settings.kernel_supported_revision != SUPPORTED_KERNEL_REVISION:
        raise ProductionReadinessError(
            "production Kernel revision does not match the Administrative supported revision"
        )
    if settings.auto_create_schema:
        raise ProductionReadinessError("production schema auto-create must be disabled; use Alembic")

    _require_postgres(settings.database_url, "ADMIN_DATABASE_URL")
    _require_postgres(settings.worker_database_url or "", "ADMIN_WORKER_DATABASE_URL")
    _require_postgres(settings.dbos_system_database_url or "", "ADMIN_DBOS_SYSTEM_DATABASE_URL")


def _require_nonempty(value: str, setting_name: str) -> None:
    if not value.strip():
        raise ProductionReadinessError(f"{setting_name} is required")


def _require_https(value: str, system: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProductionReadinessError(f"production {system} endpoint must use HTTPS")


def _require_postgres(value: str, setting_name: str) -> None:
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ProductionReadinessError(f"{setting_name} must use PostgreSQL in production")


__all__ = [
    "ProductionReadinessError",
    "validate_production_connector_isolation",
    "validate_production_control_plane",
]
