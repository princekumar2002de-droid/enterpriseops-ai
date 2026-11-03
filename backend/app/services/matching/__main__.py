"""Run the matching engine against the database in EOPS_DATABASE_URL.

uv run python -m app.services.matching
"""

import sys

from app.db.session import get_engine
from app.services.matching.repository import execute_run


def main() -> int:
    summary = execute_run(get_engine(), triggered_by="cli")
    print(
        f"Match run {summary.run_id} (engine {summary.engine_version}): "
        f"{summary.invoice_count} documents, {summary.exception_count} exceptions, "
        f"{summary.blocked_invoices} blocked ({summary.blocked_unpaid_invoices} unpaid -> "
        "payment block set)"
    )
    for code, count in summary.counts_by_code.items():
        print(f"  {code:<26} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
