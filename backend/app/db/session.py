"""Database engine management.

Week 1 only needs an engine for health checks and migrations. Sessions and the
separate read-only agent role (NFR-SEC-02) follow in week 2 when tables exist.
"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.core.config import get_settings


def build_engine(database_url: str, connect_timeout_seconds: int = 3) -> Engine:
    """Create an engine with production-sane defaults."""
    return create_engine(
        database_url,
        pool_pre_ping=True,  # drop dead connections after a DB restart
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )


@lru_cache
def get_engine() -> Engine:
    """Process-wide engine built from settings (FastAPI dependency)."""
    settings = get_settings()
    return build_engine(
        settings.database_url.get_secret_value(),
        settings.db_connect_timeout_seconds,
    )
