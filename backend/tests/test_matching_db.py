"""Matching runs against the real test database."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from app.core.config import Environment
from app.services.matching.repository import execute_run, latest_run_id
from data_generation.generator import generate
from data_generation.loader import load
from data_generation.model import PROFILES
from evaluation.matching_eval import evaluate_tables

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def loaded(migrated_engine: Engine) -> Iterator[Engine]:
    load(migrated_engine, generate(42, PROFILES["small"]), Environment.TEST)
    yield migrated_engine


def test_db_run_equals_in_memory_run(loaded: Engine) -> None:
    dataset = generate(42, PROFILES["small"])
    expected, _ = evaluate_tables(dataset.tables, dataset.labels)
    summary = execute_run(loaded, triggered_by="test")
    assert summary.exception_count == len(expected.exceptions)
    assert summary.counts_by_code == expected.counts_by_code()
    with loaded.connect() as conn:
        stored = conn.execute(
            text("SELECT count(*) FROM ops.exception WHERE run_id = :r"), {"r": summary.run_id}
        ).scalar_one()
    assert stored == summary.exception_count


def test_payment_block_only_on_unpaid_blocked_invoices(loaded: Engine) -> None:
    summary = execute_run(loaded, triggered_by="test")
    with loaded.connect() as conn:
        wrong = conn.execute(
            text("""
            SELECT count(*) FROM erp.invoice_header h
            JOIN ops.invoice_result r ON r.invoice_id = h.invoice_id AND r.run_id = :r
            WHERE (h.payment_block = 'R') <> (r.blocks_payment AND h.status <> 'PAID')
        """),
            {"r": summary.run_id},
        ).scalar_one()
        blocked = conn.execute(
            text("SELECT count(*) FROM erp.invoice_header WHERE payment_block = 'R'")
        ).scalar_one()
    assert wrong == 0
    assert blocked == summary.blocked_unpaid_invoices > 0


def test_runs_are_versioned_not_overwritten(loaded: Engine) -> None:
    first = execute_run(loaded, triggered_by="test")
    second = execute_run(loaded, triggered_by="test")
    with loaded.connect() as conn:
        assert latest_run_id(conn) == second.run_id == first.run_id + 1
        hashes = conn.execute(
            text("SELECT count(DISTINCT params_hash) FROM ops.match_run WHERE run_id IN (:a, :b)"),
            {"a": first.run_id, "b": second.run_id},
        ).scalar_one()
    assert hashes == 1  # same configuration -> same fingerprint


def test_agent_views_show_latest_run(loaded: Engine) -> None:
    summary = execute_run(loaded, triggered_by="test")
    with loaded.connect() as conn:
        conn.execute(text("SET ROLE eops_agent_ro"))
        exceptions = conn.execute(text("SELECT count(*) FROM agent.open_exception")).scalar_one()
        latest = conn.execute(text("SELECT run_id FROM agent.latest_match_run")).scalar_one()
        blocked = conn.execute(
            text("SELECT count(*) FROM agent.invoice_overview WHERE match_status = 'BLOCKED'")
        ).scalar_one()
        conn.execute(text("RESET ROLE"))
    assert latest == summary.run_id
    assert exceptions == summary.exception_count
    assert blocked == summary.blocked_invoices


def test_cli_and_db_evaluation(
    loaded: Engine, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.session import get_engine
    from app.services.matching.__main__ import main as run_main
    from evaluation.__main__ import main as eval_main

    monkeypatch.setenv("EOPS_DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        assert run_main() == 0
        assert eval_main(["db"]) == 0
    finally:
        get_engine().dispose()
        get_settings.cache_clear()
        get_engine.cache_clear()
