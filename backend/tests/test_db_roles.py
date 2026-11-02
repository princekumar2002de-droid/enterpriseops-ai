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


def test_agent_role_can_read_erp_and_ops(migrated_engine: Engine) -> None:
    _as_role(migrated_engine, "eops_agent_ro", "SELECT count(*) FROM erp.invoice_header")
    _as_role(migrated_engine, "eops_agent_ro", "SELECT count(*) FROM ops.tolerance_rule")


@pytest.mark.parametrize(
    "sql",
    [
        INSERT_TERMS,
        "UPDATE erp.invoice_header SET payment_block = 'R'",
        "DELETE FROM erp.payment",
        "SELECT count(*) FROM eval.ground_truth_label",
        "SELECT count(*) FROM iam.app_user",
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
