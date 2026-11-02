"""Application settings.

All configuration comes from environment variables (prefix ``EOPS_``) or a local
``.env`` file. Secrets are typed as ``SecretStr`` so they are never printed in
logs, reprs or tracebacks by accident (NFR-SEC-01).
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    CI = "ci"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EOPS_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "EnterpriseOps AI"
    app_version: str = "0.1.0"
    environment: Environment = Environment.LOCAL
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host:5432/eops
    database_url: SecretStr
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)

    @property
    def json_logs(self) -> bool:
        """Human-readable logs locally, JSON everywhere else."""
        return self.environment != Environment.LOCAL


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance (one per process)."""
    return Settings()  # values come from the environment
