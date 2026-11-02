"""Shared test fixtures.

Unit tests need no database. Integration tests use a *separate* test database
given by ``EOPS_TEST_DATABASE_URL`` so tests never touch development data.

- Variable missing locally  -> integration tests are skipped (with a reason).
- ``EOPS_REQUIRE_DB=1`` (CI) -> a missing/unreachable DB fails the run instead,
  so CI can never go green by silently skipping integration tests.
"""

import os
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Order matters: values already in the shell (e.g. set by CI) win over .env,
# and the test environment marker wins over EOPS_ENVIRONMENT=local from .env.
os.environ.setdefault("EOPS_ENVIRONMENT", "test")
load_dotenv(BACKEND_DIR.parent / ".env", override=False)
# The app reads settings at import time; without a .env, give unit tests a harmless dummy URL.
os.environ.setdefault("EOPS_DATABASE_URL", "postgresql+psycopg://unused:unused@127.0.0.1:1/unused")

from app.db.session import build_engine  # noqa: E402

TEST_DB_ENV = "EOPS_TEST_DATABASE_URL"


def alembic_config(db_url: str) -> Config:
    """Alembic config pointed at ``db_url`` (equivalent to ``alembic -x db_url=...``)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"), cmd_opts=Namespace(x=[f"db_url={db_url}"]))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def _missing_db(reason: str) -> None:
    if os.environ.get("EOPS_REQUIRE_DB") == "1":
        pytest.fail(f"Integration database required but unavailable: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get(TEST_DB_ENV)
    if not url:
        _missing_db(f"{TEST_DB_ENV} is not set")
        raise AssertionError("unreachable")
    return url


@pytest.fixture(scope="session")
def test_engine(test_database_url: str) -> Iterator[Engine]:
    engine = build_engine(test_database_url, connect_timeout_seconds=3)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        engine.dispose()
        _missing_db(f"cannot connect to test database ({type(exc).__name__})")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_engine(test_engine: Engine, test_database_url: str) -> Iterator[Engine]:
    """Test engine with all migrations applied."""
    command.upgrade(alembic_config(test_database_url), "head")
    yield test_engine
