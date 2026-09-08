from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    runtime_profile: Literal["test", "development", "governed"] = "development"

    # Agent Kernel convergence is opt-in and monotonic. `shadow` records only
    # the proposal prefix; `admission` additionally asks Kernel to materialize
    # Work under a server-owned policy. Neither mode authorizes provider effects.
    # `cutover` remains fail-closed until the unique Kernel execution path exists.
    kernel_bridge_mode: Literal["disabled", "shadow", "admission", "cutover"] = "disabled"
    kernel_base_url: str = "http://127.0.0.1:8020"
    kernel_contract_timeout_seconds: float = 3.0
    kernel_responsibility_admission_policy_ref: str = (
        "responsibility-admission:bounded-local@1"
    )

    # Authentication is intentionally fail-closed by default. The local Compose
    # sandbox opts into development identity transport explicitly.
    auth_mode: str = "jwt"
    jwt_secret: str | None = None
    jwt_issuer: str = "administrative-orchestrator"
    jwt_audience: str = "administrative-orchestrator"

    # Compatibility switch for tests/development. A governed profile always
    # forces this on; deployment configuration cannot disable that invariant.
    authority_enforcement_enabled: bool = False

    # One-shot bootstrap input used only by the foundation bootstrap command.
    bootstrap_authority_json: str = ""

    @model_validator(mode="after")
    def governed_profile_fails_closed(self) -> Settings:
        if self.runtime_profile == "governed":
            object.__setattr__(self, "authority_enforcement_enabled", True)
        if self.kernel_contract_timeout_seconds <= 0:
            raise ValueError("kernel_contract_timeout_seconds must be positive")
        if (
            self.kernel_bridge_mode == "admission"
            and not self.kernel_responsibility_admission_policy_ref.strip()
        ):
            raise ValueError(
                "kernel_responsibility_admission_policy_ref is required in admission mode"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
