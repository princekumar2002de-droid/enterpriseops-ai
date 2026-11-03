"""Loads a generated dataset into PostgreSQL in one transaction.

Re-loading replaces all generator-owned data (TRUNCATE ... CASCADE), so running
the generator twice with the same seed leaves the database in the same state.
CASCADE also clears ops tables that reference ERP rows (e.g. match results from
Task 3) - they are derived data and must be recomputed after a reload anyway.
"""

from sqlalchemy import Connection, Engine, insert

from app.core.config import Environment
from app.db import tables as t
from data_generation import GENERATOR_VERSION
from data_generation.generator import content_hash
from data_generation.model import Dataset

# Insert order respects foreign keys.
LOAD_ORDER = [
    t.company_code,
    t.plant,
    t.payment_terms,
    t.supplier,
    t.supplier_bank_account,
    t.material,
    t.contract_header,
    t.contract_item,
    t.purchase_order_header,
    t.purchase_order_item,
    t.goods_receipt,
    t.invoice_header,
    t.invoice_item,
    t.payment,
    t.inventory_level,
    t.app_user,
    t.tolerance_rule,
]
EVAL_TABLES = [t.supplier_persona, t.ground_truth_label, t.dataset_run]
# Derived results become meaningless when the data is replaced (CASCADE clears the rest).
DERIVED_TABLES = [t.match_run]

# iam.role is reference data owned by the migration and is never truncated.
TRUNCATE_SQL = (
    "TRUNCATE "
    + ", ".join(f"{tbl.schema}.{tbl.name}" for tbl in [*LOAD_ORDER, *EVAL_TABLES, *DERIVED_TABLES])
    + " RESTART IDENTITY CASCADE"
)


class LoadRefusedError(RuntimeError):
    """Raised when loading synthetic data would be unsafe."""


def load(engine: Engine, dataset: Dataset, environment: Environment) -> dict[str, int]:
    if environment == Environment.PRODUCTION:
        raise LoadRefusedError("Refusing to overwrite data in a production environment.")
    with engine.begin() as conn:
        conn.exec_driver_sql(TRUNCATE_SQL)
        for table in LOAD_ORDER:
            _insert(conn, table, dataset.tables[f"{table.schema}.{table.name}"])
        _insert(conn, t.supplier_persona, dataset.personas)
        _insert(conn, t.ground_truth_label, dataset.labels)
        conn.execute(
            insert(t.dataset_run).values(
                seed=dataset.seed,
                profile=dataset.profile.name,
                generator_version=GENERATOR_VERSION,
                row_counts=dataset.row_counts(),
                content_hash=content_hash(dataset),
            )
        )
    return dataset.row_counts()


def _insert(conn: Connection, table: object, rows: list[dict[str, object]]) -> None:
    if rows:
        conn.execute(insert(table), rows)  # type: ignore[arg-type]
