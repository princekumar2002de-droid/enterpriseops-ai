"""The migrated database must match app/db/tables.py exactly (ADR-017).

If this fails, a table definition changed without a migration (or vice versa):
run ``uv run alembic revision --autogenerate -m "..."`` and review the result.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine

from app.db.tables import include_name, metadata

pytestmark = pytest.mark.integration


def test_migrations_match_table_definitions(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "include_name": include_name,
                "compare_type": True,
                "target_metadata": metadata,
            },
        )
        assert compare_metadata(context, metadata) == []
