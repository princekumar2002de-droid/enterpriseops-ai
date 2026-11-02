"""Baseline: pgvector extension and the five domain schemas.

Schemas separate concerns *and* permissions (see DATABASE_SCHEMA.md):
  erp   - simulated SAP-aligned source system (POs, GRs, invoices, ...)
  ops   - EnterpriseOps results and workflow (matches, exceptions, cases, actions)
  docs  - RAG corpus (documents, chunks, embeddings)
  audit - append-only audit trail
  iam   - users and roles

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("erp", "ops", "docs", "audit", "iam")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def downgrade() -> None:
    # RESTRICT: refuse to drop a schema that still contains objects.
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} RESTRICT")
    op.execute("DROP EXTENSION IF EXISTS vector")
