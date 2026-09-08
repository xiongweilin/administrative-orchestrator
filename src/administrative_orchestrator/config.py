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
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
