"""Engine behaviour: rule precedence on hand-built cases + accuracy gate on generated data."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.matching.engine import run_matching
from app.services.matching.snapshot import Invoice, InvoiceLine, PoItem, Snapshot, Tolerances
from data_generation.generator import generate
from data_generation.model import PROFILES
from evaluation.matching_eval import evaluate_tables

D = Decimal  # short alias keeps the rule tables readable

TOL = Tolerances(D("2"), D("100"), D("10"), D("500"), D("5"))


def _snapshot(
    *invoices: Invoice, received: str = "10", bank_change: date | None = None
) -> Snapshot:
    item = PoItem("4500000001", 10, "V1", "EUR", "Z030", D(10), D("50.0000"), True, None, None)
    return Snapshot(
        invoices=invoices,
        po_items={("4500000001", 10): item},
        net_received={("4500000001", 10): D(received)},
        contract_prices={},
        supplier_vat={"V1": "DE1", "V2": "DE1"},
        bank_changes={"V1": (bank_change,)} if bank_change else {},
        tolerances={"DE01": TOL},
    )


def _inv(
    invoice_id: str,
    *,
    qty: str = "10",
    price: str = "50.0000",
    currency: str = "EUR",
    ref: str = "RE-1",
    day: int = 10,
    doc_type: str = "INVOICE",
    supplier: str = "V1",
) -> Invoice:
    net = (D(qty) * D(price)).quantize(D("0.01"))
    return Invoice(
        invoice_id=invoice_id,
        doc_type=doc_type,
        supplier_id=supplier,
        company_code="DE01",
        supplier_reference=ref,
        invoice_date=date(2026, 3, day),
        received_date=date(2026, 3, day),
        currency=currency,
        terms_code="Z030",
        net_amount=net,
        gross_amount=net,
        status="RECEIVED",
        lines=(InvoiceLine(1, "4500000001", 10, D(qty), D(price), net),),
    )


def _codes(snapshot: Snapshot) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for e in run_matching(snapshot).exceptions:
        out.setdefault(e.invoice_id, []).append(e.code)
    return out


def test_clean_invoice_is_matched() -> None:
    outcome = run_matching(_snapshot(_inv("A")))
    assert outcome.exceptions == []
    assert outcome.invoice_results[0].status == "MATCHED"


def test_r1_duplicate_gets_only_duplicate_code_and_does_not_consume_quantity() -> None:
    codes = _codes(_snapshot(_inv("A", day=10), _inv("B", day=11)))
    assert codes == {"B": ["DUPLICATE_SUSPECTED"]}  # no QTY_VARIANCE / PO_OVER_INVOICED on B


def test_r2_no_goods_receipt_suppresses_quantity_variance() -> None:
    assert _codes(_snapshot(_inv("A"), received="0")) == {"A": ["NO_GOODS_RECEIPT"]}


def test_r3_currency_mismatch_suppresses_price_check() -> None:
    codes = _codes(_snapshot(_inv("A", currency="USD", price="80.0000")))
    assert codes == {"A": ["CURRENCY_MISMATCH"]}


def test_r4_credit_memo_is_not_checked() -> None:
    outcome = run_matching(_snapshot(_inv("A"), _inv("CM", doc_type="CREDIT_MEMO", day=12)))
    statuses = {r.invoice_id: r.status for r in outcome.invoice_results}
    assert statuses == {"A": "MATCHED", "CM": "NOT_APPLICABLE"}
    assert outcome.exceptions == []


def test_r5_recent_bank_change_blocks() -> None:
    outcome = run_matching(_snapshot(_inv("A", day=10), bank_change=date(2026, 3, 1)))
    assert [e.code for e in outcome.exceptions] == ["BANK_DETAILS_CHANGED"]
    assert outcome.invoice_results[0].status == "BLOCKED"


def test_non_blocking_codes_flag_only() -> None:
    inv = _inv("A")
    snap = _snapshot(
        Invoice(**{**inv.__dict__, "terms_code": "Z060"})  # PAYMENT_TERMS_MISMATCH
    )
    result = run_matching(snap).invoice_results[0]
    assert (result.status, result.blocks_payment) == ("FLAGGED", False)


def test_params_hash_is_stable() -> None:
    snap = _snapshot(_inv("A"))
    assert run_matching(snap).params_hash == run_matching(snap).params_hash


@pytest.mark.parametrize(("seed", "profile"), [(42, "full"), (42, "small"), (3, "small")])
def test_engine_meets_task3_targets(seed: int, profile: str) -> None:
    """CI gate for decision D3 on generated datasets (seed 42 = reporting seed)."""
    dataset = generate(seed, PROFILES[profile])
    _, report = evaluate_tables(dataset.tables, dataset.labels)
    misses = {k: v for k, v in report.target_checks().items() if not v[2]}
    assert misses == {}, (misses, report.false_negative_examples, report.false_positive_examples)
