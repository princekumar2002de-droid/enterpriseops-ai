"""Persist matching runs and read run summaries.

One run = one transaction: snapshot, match, write results, set payment blocks.
A transaction-scoped advisory lock serialises concurrent runs.
"""

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Engine, bindparam, func, insert, select, text, update

from app.db import tables as t
from app.services.matching.engine import ENGINE_VERSION, MatchConfig, MatchOutcome, run_matching
from app.services.matching.snapshot import load_snapshot

_RUN_LOCK_KEY = 4_200_001  # arbitrary constant, unique to matching runs
PAYMENT_BLOCK_REASON = "R"  # SAP-style "invoice verification" block


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    engine_version: str
    invoice_count: int
    exception_count: int
    blocked_invoices: int
    blocked_unpaid_invoices: int
    counts_by_code: dict[str, int]


def execute_run(engine: Engine, triggered_by: str, config: MatchConfig | None = None) -> RunSummary:
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _RUN_LOCK_KEY})
        outcome = run_matching(load_snapshot(conn), config)
        run_id = persist(conn, outcome, triggered_by)
    return summarize(outcome, run_id)


def persist(conn: Connection, outcome: MatchOutcome, triggered_by: str) -> int:
    run_id: int = conn.execute(
        insert(t.match_run)
        .values(
            engine_version=ENGINE_VERSION,
            params=outcome.params,
            params_hash=outcome.params_hash,
            status="COMPLETED",
            triggered_by=triggered_by,
            finished_at=func.now(),
            invoice_count=len(outcome.invoice_results),
            exception_count=len(outcome.exceptions),
        )
        .returning(t.match_run.c.run_id)
    ).scalar_one()

    _bulk(
        conn,
        t.invoice_result,
        [
            {**{k: v for k, v in asdict(r).items() if k != "is_unpaid"}, "run_id": run_id}
            for r in outcome.invoice_results
        ],
    )
    _bulk(conn, t.line_result, [{**asdict(r), "run_id": run_id} for r in outcome.line_results])
    _bulk(
        conn,
        t.exception,
        [
            {
                "run_id": run_id,
                "invoice_id": e.invoice_id,
                "item_no": e.item_no,
                "code": e.code,
                "severity": e.severity,
                "blocks_payment": e.blocks_payment,
                "amount_at_risk": e.amount_at_risk,
                "currency": e.currency,
                "details": _json_safe(e.details),
            }
            for e in outcome.exceptions
        ],
    )
    _bulk(
        conn,
        t.duplicate_candidate,
        [
            {
                "run_id": run_id,
                "invoice_id": p.invoice_id,
                "candidate_invoice_id": p.candidate_invoice_id,
                "score": p.score,
                "is_flagged": p.is_flagged,
                "features": _json_safe(p.features),
            }
            for p in outcome.duplicate_pairs
        ],
    )
    _apply_payment_blocks(conn, outcome)
    return run_id


def _apply_payment_blocks(conn: Connection, outcome: MatchOutcome) -> None:
    """Block unpaid invoices with blocking exceptions; release all others (decision D1)."""
    blocked = [r.invoice_id for r in outcome.invoice_results if r.blocks_payment and r.is_unpaid]
    header = t.invoice_header
    conn.execute(
        update(header).where(header.c.payment_block.is_not(None)).values(payment_block=None)
    )
    if blocked:
        conn.execute(
            update(header)
            .where(header.c.invoice_id.in_(bindparam("ids", expanding=True)))
            .values(payment_block=PAYMENT_BLOCK_REASON),
            {"ids": blocked},
        )


def summarize(outcome: MatchOutcome, run_id: int) -> RunSummary:
    blocked = [r for r in outcome.invoice_results if r.blocks_payment]
    return RunSummary(
        run_id=run_id,
        engine_version=ENGINE_VERSION,
        invoice_count=len(outcome.invoice_results),
        exception_count=len(outcome.exceptions),
        blocked_invoices=len(blocked),
        blocked_unpaid_invoices=sum(1 for r in blocked if r.is_unpaid),
        counts_by_code=outcome.counts_by_code(),
    )


def latest_run_id(conn: Connection) -> int | None:
    run_id: int | None = conn.execute(
        select(func.max(t.match_run.c.run_id)).where(t.match_run.c.status == "COMPLETED")
    ).scalar_one()
    return run_id


def _bulk(conn: Connection, table: Any, rows: list[dict[str, Any]]) -> None:
    if rows:
        conn.execute(insert(table), rows)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda v: str(v) if isinstance(v, Decimal) else v))
