from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADMIN_", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./data/administrative.db"
    worker_database_url: str | None = None
    dbos_system_database_url: str | None = None
    log_level: str = "INFO"
    external_effects_enabled: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
