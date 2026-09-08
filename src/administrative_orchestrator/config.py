from __future__ import annotations

from functools import lru_cache

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
