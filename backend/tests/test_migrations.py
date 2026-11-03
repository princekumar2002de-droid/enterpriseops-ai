"""Migration tests against the real test database.

Checks that the baseline migration creates what the architecture promises and
that it can be rolled back and re-applied (no one-way migrations by accident).
"""

import pytest
from alembic import command
from sqlalchemy import Engine, text

from tests.conftest import alembic_config

EXPECTED_SCHEMAS = {"erp", "ops", "docs", "audit", "iam", "eval", "agent"}
EXPECTED_TABLES = 26  # base tables; agent views are counted separately


def _schemas(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT schema_name FROM information_schema.schemata"))
        return {r[0] for r in rows}


@pytest.mark.integration
def test_baseline_creates_domain_schemas(migrated_engine: Engine) -> None:
    assert _schemas(migrated_engine) >= EXPECTED_SCHEMAS


@pytest.mark.integration
def test_head_creates_all_tables(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema IN ('erp', 'ops', 'iam', 'eval') AND table_type = 'BASE TABLE'"
            )
        ).scalar_one()
    assert count == EXPECTED_TABLES


@pytest.mark.integration
def test_baseline_installs_pgvector(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        version = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    assert version is not None


@pytest.mark.integration
def test_downgrade_and_reupgrade_round_trip(
    migrated_engine: Engine, test_database_url: str
) -> None:
    cfg = alembic_config(test_database_url)
    command.downgrade(cfg, "base")
    assert not (EXPECTED_SCHEMAS & _schemas(migrated_engine))
    command.upgrade(cfg, "head")
    assert _schemas(migrated_engine) >= EXPECTED_SCHEMAS
