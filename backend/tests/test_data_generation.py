"""Unit tests for the synthetic data generator (no database needed)."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.core.config import Environment
from data_generation.generator import content_hash, generate
from data_generation.loader import LoadRefusedError, load
from data_generation.model import PROFILES, Dataset
from data_generation.scenarios import EXCEPTION_CODES, HARD_NEGATIVE_CODES
from data_generation.validation import EXCEPTION_RATE_BAND

SMALL = PROFILES["small"]


@pytest.fixture(scope="module")
def small() -> Dataset:
    return generate(42, SMALL)


def test_same_seed_produces_identical_dataset(small: Dataset) -> None:
    assert content_hash(generate(42, SMALL)) == content_hash(small)


def test_different_seed_produces_different_dataset(small: Dataset) -> None:
    assert content_hash(generate(43, SMALL)) != content_hash(small)


def test_every_scenario_is_present(small: Dataset) -> None:
    codes = {label["label_code"] for label in small.labels}
    assert set(EXCEPTION_CODES) <= codes
    assert set(HARD_NEGATIVE_CODES) <= codes


def test_hard_negative_flag_matches_code(small: Dataset) -> None:
    for label in small.labels:
        assert label["is_hard_negative"] == label["label_code"].startswith("HN_")


def test_labels_reference_existing_invoices_and_items(small: Dataset) -> None:
    items = {(i["invoice_id"], i["item_no"]) for i in small.tables["erp.invoice_item"]}
    invoices = {h["invoice_id"] for h in small.tables["erp.invoice_header"]}
    for label in small.labels:
        assert label["invoice_id"] in invoices
        if label["item_no"] is not None:
            assert (label["invoice_id"], label["item_no"]) in items


def test_invoice_totals_are_consistent(small: Dataset) -> None:
    nets: dict[str, Decimal] = {}
    for item in small.tables["erp.invoice_item"]:
        nets[item["invoice_id"]] = nets.get(item["invoice_id"], Decimal(0)) + item["net_amount"]
    for header in small.tables["erp.invoice_header"]:
        assert header["net_amount"] == nets[header["invoice_id"]]
        assert header["gross_amount"] == header["net_amount"] + header["tax_amount"]


def test_ids_follow_chronology(small: Dataset) -> None:
    received = [
        h["received_date"]
        for h in sorted(small.tables["erp.invoice_header"], key=lambda h: h["invoice_id"])
    ]
    assert received == sorted(received)


def test_full_profile_exception_rate_in_band() -> None:
    dataset = generate(42, PROFILES["full"])
    invoices = [h for h in dataset.tables["erp.invoice_header"] if h["doc_type"] == "INVOICE"]
    flagged = {lb["invoice_id"] for lb in dataset.labels if not lb["is_hard_negative"]}
    low, high = EXCEPTION_RATE_BAND
    assert low <= len(flagged) / len(invoices) <= high


def test_catalog_capacity_guard() -> None:
    with pytest.raises(ValueError, match="materials requested"):
        generate(1, replace(SMALL, n_materials=10_000))


def test_loader_refuses_production(small: Dataset) -> None:
    with pytest.raises(LoadRefusedError):
        load(engine=None, dataset=small, environment=Environment.PRODUCTION)  # type: ignore[arg-type]
