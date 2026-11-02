"""Load the generated dataset into the test database and validate it."""

import pytest
from sqlalchemy import Engine, text

from app.core.config import Environment
from data_generation.generator import generate
from data_generation.loader import load
from data_generation.model import PROFILES
from data_generation.validation import validate

pytestmark = pytest.mark.integration


def test_small_dataset_loads_and_passes_all_checks(migrated_engine: Engine) -> None:
    load(migrated_engine, generate(42, PROFILES["small"]), Environment.TEST)
    results, summary = validate(migrated_engine)
    failed = [(r.check.name, r.violations) for r in results if not r.passed]
    assert failed == []
    assert summary["Row counts"]


def test_reload_is_idempotent(migrated_engine: Engine) -> None:
    dataset = generate(7, PROFILES["small"])
    load(migrated_engine, dataset, Environment.TEST)
    load(migrated_engine, dataset, Environment.TEST)
    with migrated_engine.connect() as conn:
        invoices = conn.execute(text("SELECT count(*) FROM erp.invoice_header")).scalar_one()
        runs = conn.execute(text("SELECT count(*) FROM eval.dataset_run")).scalar_one()
        roles = conn.execute(text("SELECT count(*) FROM iam.role")).scalar_one()
    assert invoices == dataset.row_counts()["erp.invoice_header"]
    assert runs == 1  # previous provenance replaced, not duplicated
    assert roles == 8  # reference data owned by the migration survives reloads


def test_cli_generate_and_validate(
    migrated_engine: Engine, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.session import get_engine
    from data_generation.__main__ import main

    monkeypatch.setenv("EOPS_DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        assert main(["generate", "--seed", "42", "--profile", "small"]) == 0
        assert main(["validate"]) == 0
    finally:
        get_engine().dispose()
        get_settings.cache_clear()
        get_engine.cache_clear()
