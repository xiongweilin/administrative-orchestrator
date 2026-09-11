from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_KERNEL_RESPONSIBILITY_ADMISSION_POLICY_REF = (
    "responsibility-admission:administrative-public@2"
)
SUPPORTED_KERNEL_REVISION = "1f8497087b6a95632b1ae179d9ffd6c3e8fe6bb8"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADMIN_", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./data/administrative.db"
    worker_database_url: str | None = None
    dbos_system_database_url: str | None = None
    sandbox_database_url: str = "sqlite+pysqlite:///./data/administrative-sandbox.db"
    sandbox_base_url: str = "http://127.0.0.1:8010"
    provider_timeout_seconds: float = 10.0
    worker_poll_seconds: float = 1.0
    outbox_batch: int = 20
    outbox_lease_seconds: int = 30
    outbox_max_attempts: int = 10
    log_level: str = "INFO"
    external_effects_enabled: bool = False
    auto_create_schema: bool = True

    # Optional M6 Feishu runtime. Secret values are held as SecretStr and are
    # never returned by readiness endpoints or written to intake records.
    feishu_base_url: str = "https://open.feishu.cn"
    # Worker-only Feishu app credentials used to obtain short-lived tenant
    # access tokens for canonical reads. They are intentionally separate from
    # the ingress verification token and the gateway's transport credentials.
    feishu_app_id: str = ""
    feishu_app_id_file: str = ""
    feishu_app_secret: SecretStr | None = None
    feishu_app_secret_file: str = ""
    feishu_verification_token: SecretStr | None = None
    # Secret used only by the trusted gateway-to-Administrative metadata
    # handoff. Feishu's official long connection does not provide the HTTP
    # callback token on every event, so this transport credential is separate
    # from the callback verification material.
    feishu_ingress_shared_secret: SecretStr | None = None
    feishu_encrypt_key: SecretStr | None = None
    # Explicit test/manual override. Production/staging should use the app
    # credential pair above and the dynamic tenant-token provider.
    feishu_access_token: SecretStr | None = None
    feishu_artifact_root: str = "./data/intake-artifacts"
    intake_model_url: str = ""
    intake_model_api_key: SecretStr | None = None
    intake_model_protocol: Literal["json", "openai-chat", "openai-responses"] = "json"
    intake_model_name: str = ""
    intake_model_max_tokens: int = 2400
    intake_model_provider: str = "configured-model-gateway"
    intake_model_identity: str = "configured-model"
    intake_model_version: str = "configured"
    intake_model_profile_ref: str = "feishu-onboarding-v1"
    intake_model_schema_ref: str = "candidate-interpretation-v1"
    intake_model_instruction: str = (
        "Extract a candidate administrative intent and candidate facts only. "
        "Never authorize, execute, or communicate on behalf of the system. "
        "For employee-onboarding requests, use only these candidate fact keys: "
        "employee_ref, department_ref, manager_principal_id, start_date, "
        "employment_type, requested_systems, requires_privileged_access. "
        "For employee-offboarding requests, use only these additional candidate "
        "fact keys: requested_termination_date, reason, successor_principal_id. "
        "Put every requested account or system into requested_systems. "
        "Do not invent other fact keys."
    )

    runtime_profile: Literal["test", "development", "governed", "staging", "production"] = "development"

    # Kernel convergence is capability-scoped and already supports physical
    # cutover. Production pins a supported revision/tag while CI may run a
    # separate canary lane against agent-kernel/main.
    kernel_bridge_mode: Literal["disabled", "shadow", "admission", "cutover"] = "disabled"
    kernel_base_url: str = "http://127.0.0.1:8020"
    kernel_contract_timeout_seconds: float = 3.0
    kernel_supported_revision: str = SUPPORTED_KERNEL_REVISION
    kernel_responsibility_admission_policy_ref: str = (
        DEFAULT_KERNEL_RESPONSIBILITY_ADMISSION_POLICY_REF
    )

    # Authentication. `jwt` is retained only for compatibility/test fixtures;
    # the production profile requires OIDC/JWKS and asymmetric verification.
    auth_mode: Literal["development", "jwt", "oidc"] = "jwt"
    jwt_secret: str | None = None
    jwt_issuer: str = "administrative-orchestrator"
    jwt_audience: str = "administrative-orchestrator"

    oidc_issuer: str = ""
    oidc_audience: str = "administrative-orchestrator"
    oidc_allowed_algorithms: str = "RS256,ES256"
    # Optional service-network endpoints for an externally issued OIDC token.
    # The issuer remains the authoritative external identity provider URL;
    # these endpoints only avoid a broken container-to-host backchannel.
    oidc_metadata_url: str = ""
    oidc_jwks_url: str = ""
    oidc_jwks_cache_ttl_seconds: int = 300
    oidc_clock_skew_seconds: int = 60
    oidc_http_timeout_seconds: float = 5.0
    oidc_allow_insecure_http: bool = False

    # Authoritative read adapters. Credentials are referenced by environment
    # variable name and resolved only inside connector processes; secret values
    # are never persisted in domain or Kernel records.
    hris_source_kind: Literal["disabled", "odoo"] = "disabled"
    odoo_base_url: str = ""
    odoo_database: str = ""
    odoo_reader_username: str = ""
    odoo_reader_secret_env: str = "ADMIN_ODOO_READER_SECRET"
    odoo_writer_username: str = ""
    odoo_writer_secret_env: str = "ADMIN_ODOO_WRITER_SECRET"
    odoo_verifier_username: str = ""
    odoo_verifier_secret_env: str = "ADMIN_ODOO_VERIFIER_SECRET"
    odoo_request_ref_field: str = "x_administrative_request_ref"
    odoo_deactivate_request_ref_field: str = (
        "x_administrative_deactivate_request_ref"
    )
    odoo_termination_status_field: str = "x_administrative_termination_status"
    odoo_termination_effective_at_field: str = (
        "x_administrative_termination_effective_at"
    )
    odoo_employment_episode_field: str = "x_administrative_employment_episode_ref"
    odoo_principal_id_field: str = "x_administrative_principal_id"

    iam_source_kind: Literal["disabled", "keycloak"] = "disabled"
    keycloak_base_url: str = ""
    keycloak_realm: str = ""
    keycloak_reader_client_id: str = ""
    keycloak_reader_secret_env: str = "ADMIN_KEYCLOAK_READER_SECRET"
    keycloak_writer_client_id: str = ""
    keycloak_writer_secret_env: str = "ADMIN_KEYCLOAK_WRITER_SECRET"
    keycloak_verifier_client_id: str = ""
    keycloak_verifier_secret_env: str = "ADMIN_KEYCLOAK_VERIFIER_SECRET"
    keycloak_request_ref_attribute: str = "administrative_request_ref"
    keycloak_disable_request_ref_attribute: str = (
        "administrative_disable_request_ref"
    )
    keycloak_session_revoke_request_ref_attribute: str = (
        "administrative_session_revoke_request_ref"
    )

    connector_timeout_seconds: float = 10.0
    authoritative_fact_max_age_seconds: int = 300

    # Compatibility switch for tests/development. Governed/production profiles
    # always force authority enforcement on.
    authority_enforcement_enabled: bool = False

    # One-shot bootstrap input used only by the foundation bootstrap command.
    bootstrap_authority_json: str = ""

    @property
    def oidc_algorithms(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.oidc_allowed_algorithms.split(",") if item.strip())

    @model_validator(mode="after")
    def fail_closed_profiles(self) -> Settings:
        if self.runtime_profile in {"governed", "staging", "production"}:
            object.__setattr__(self, "authority_enforcement_enabled", True)
        if self.kernel_contract_timeout_seconds <= 0:
            raise ValueError("kernel_contract_timeout_seconds must be positive")
        if self.connector_timeout_seconds <= 0:
            raise ValueError("connector_timeout_seconds must be positive")
        if self.authoritative_fact_max_age_seconds <= 0:
            raise ValueError("authoritative_fact_max_age_seconds must be positive")
        if self.intake_model_max_tokens <= 0:
            raise ValueError("intake_model_max_tokens must be positive")
        if self.kernel_bridge_mode in {"admission", "cutover"} and not (
            self.kernel_responsibility_admission_policy_ref.strip()
        ):
            raise ValueError(
                "kernel_responsibility_admission_policy_ref is required in admission mode and cutover mode"
            )
        if self.runtime_profile in {"staging", "production"}:
            if self.auth_mode != "oidc":
                raise ValueError(f"{self.runtime_profile} runtime requires ADMIN_AUTH_MODE=oidc")
            if not self.oidc_issuer.strip() or not self.oidc_audience.strip():
                raise ValueError(f"{self.runtime_profile} OIDC issuer and audience are required")
            if self.runtime_profile == "production" and not self.oidc_issuer.startswith("https://"):
                raise ValueError("production OIDC issuer must use HTTPS")
            if self.runtime_profile == "production" and self.oidc_allow_insecure_http:
                raise ValueError("production OIDC cannot allow insecure HTTP")
            if self.oidc_issuer.startswith("http://") and not self.oidc_allow_insecure_http:
                raise ValueError(
                    f"{self.runtime_profile} OIDC HTTP requires ADMIN_OIDC_ALLOW_INSECURE_HTTP=true"
                )
            disallowed = set(self.oidc_algorithms) - {"RS256", "ES256"}
            if disallowed or not self.oidc_algorithms:
                raise ValueError("production OIDC algorithms are restricted to RS256/ES256")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
