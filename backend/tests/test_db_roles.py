"""Database role permissions (NFR-SEC-02, ADR-018, ADR-020).

The agent role must be able to read ERP data but never write it, and must never
see the evaluation ground truth or user data.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.integration

INSERT_TERMS = (
    "INSERT INTO erp.payment_terms (terms_code, description, net_days) VALUES ('ZTST', 'test', 10)"
)


def _as_role(engine: Engine, role: str, sql: str) -> None:
    """Run ``sql`` as ``role`` inside a transaction that is always rolled back."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(f"SET LOCAL ROLE {role}"))
            conn.execute(text(sql))
        finally:
            trans.rollback()


AGENT_VIEWS = [
    "latest_match_run",
    "invoice_overview",
    "invoice_line_match",
    "goods_receipt_line",
    "purchase_order",
    "contract_price",
    "supplier_profile",
    "open_exception",
    "duplicate_pair",
]


@pytest.mark.parametrize("view", AGENT_VIEWS)
def test_agent_role_can_read_curated_views(migrated_engine: Engine, view: str) -> None:
    _as_role(migrated_engine, "eops_agent_ro", f"SELECT * FROM agent.{view} LIMIT 1")


@pytest.mark.parametrize(
    "sql",
    [
        INSERT_TERMS,
        "UPDATE erp.invoice_header SET payment_block = 'R'",
        "DELETE FROM erp.payment",
        "SELECT count(*) FROM eval.ground_truth_label",
        "SELECT count(*) FROM iam.app_user",
        # since migration 0003 the agent reads curated views only (ADR-022)
        "SELECT count(*) FROM erp.invoice_header",
        "SELECT count(*) FROM erp.supplier_bank_account",
        "SELECT count(*) FROM ops.exception",
    ],
)
def test_agent_role_is_denied(migrated_engine: Engine, sql: str) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        _as_role(migrated_engine, "eops_agent_ro", sql)


def test_app_role_cannot_write_erp(migrated_engine: Engine) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        _as_role(migrated_engine, "eops_app", INSERT_TERMS)


def test_action_role_can_write_erp(migrated_engine: Engine) -> None:
    _as_role(migrated_engine, "eops_action", INSERT_TERMS)


def test_app_role_may_only_set_payment_block(migrated_engine: Engine) -> None:
    """Decision D1: the engine sets payment blocks; nothing else in erp is writable."""
    _as_role(migrated_engine, "eops_app", "UPDATE erp.invoice_header SET payment_block = NULL")
    with pytest.raises(ProgrammingError, match="permission denied"):
        _as_role(migrated_engine, "eops_app", "UPDATE erp.invoice_header SET status = 'PAID'")


def test_agent_views_expose_no_bank_details(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        columns = (
            conn.execute(
                text("""
            SELECT column_name FROM information_schema.columns WHERE table_schema = 'agent'
        """)
            )
            .scalars()
            .all()
        )
    assert not [c for c in columns if "iban" in c]
