"""Unit tests for the matching rules (PROJECT_REQUIREMENTS 8.2) and duplicate scoring."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.matching import rules
from app.services.matching.duplicates import DuplicateConfig, normalize_reference, score_pair
from app.services.matching.rules import PriceOutcome, QtyOutcome
from app.services.matching.snapshot import Invoice, InvoiceLine, Tolerances

D = Decimal  # short alias keeps the rule tables readable

TOL = Tolerances(
    pp_upper_pct=D("2.000"),
    pp_upper_abs=D("100.00"),
    pp_lower_pct=D("10.000"),
    pp_lower_abs=D("500.00"),
    bd_abs=D("5.00"),
)


@pytest.mark.parametrize(
    ("po", "inv", "qty", "expected"),
    [
        (D("10.00"), D("10.00"), D(5), PriceOutcome.MATCH),
        # T1: +4 % but only 2.00 difference -> small difference accepted
        (D("10.00"), D("10.40"), D(5), PriceOutcome.SMALL_DIFFERENCE),
        # T2: +1 % on 2,000 = 20.00 -> below 2 % and below 100 -> within tolerance
        (D("100.00"), D("101.00"), D(20), PriceOutcome.WITHIN_TOLERANCE),
        # T2 % limit: +3 % on 300 = 9.00 > BD, 3 % > 2 % -> variance
        (D("100.00"), D("103.00"), D(3), PriceOutcome.VARIANCE),
        # T2 absolute limit: +1.5 % (< 2 %) but 150.00 > 100.00 -> variance (EITHER rule)
        (D("100.00"), D("101.50"), D(100), PriceOutcome.VARIANCE),
        # exactly at the limits is still within tolerance
        (D("100.00"), D("102.00"), D(50), PriceOutcome.WITHIN_TOLERANCE),
        # lower side: -5 % on 1,000 = -50 -> within the generous lower limits
        (D("100.00"), D("95.00"), D(10), PriceOutcome.WITHIN_TOLERANCE),
        # lower side: -12 % breaches the 10 % lower limit
        (D("100.00"), D("88.00"), D(10), PriceOutcome.VARIANCE),
    ],
)
def test_price_rules(po: D, inv: D, qty: D, expected: PriceOutcome) -> None:
    assert rules.check_price(po, inv, qty, TOL).outcome == expected


def test_price_variance_amount_and_pct() -> None:
    check = rules.check_price(D("10.0000"), D("10.5000"), D(100), TOL)
    assert check.variance_amount == D("50.00")
    assert check.variance_pct == D("5.000")


@pytest.mark.parametrize(
    ("invoiced", "received", "previous", "outcome", "variance"),
    [
        (D(10), D(10), D(0), QtyOutcome.MATCH, D(0)),
        (D(10), D(0), D(0), QtyOutcome.NO_GOODS_RECEIPT, D(10)),  # R2
        (D(10), D(9), D(0), QtyOutcome.QTY_VARIANCE, D(1)),  # T3, zero tolerance
        (D(4), D(10), D(6), QtyOutcome.MATCH, D(0)),  # partial delivery, 2nd invoice
        (D(5), D(10), D(6), QtyOutcome.QTY_VARIANCE, D(1)),
    ],
)
def test_quantity_rules(
    invoiced: D, received: D, previous: D, outcome: QtyOutcome, variance: D
) -> None:
    check = rules.check_quantity(invoiced, received, previous, gr_based_iv=True)
    assert (check.outcome, check.variance_qty) == (outcome, variance)


def test_no_goods_receipt_requires_gr_based_iv() -> None:
    assert rules.check_quantity(D(1), D(0), D(0), gr_based_iv=False).outcome == (
        QtyOutcome.QTY_VARIANCE
    )


def test_over_invoicing_and_contract_deviation() -> None:
    assert rules.over_invoiced_qty(D(100), D(60), D(50)) == D(10)
    assert rules.over_invoiced_qty(D(100), D(60), D(40)) == D(0)
    assert rules.contract_deviation(D("10.50"), D("10.00")) == D("0.50")
    assert rules.contract_deviation(D("10.00"), D("10.00")) is None
    assert rules.contract_deviation(D("10.00"), None) is None


def test_bank_change_window() -> None:
    day = date(2026, 5, 31).toordinal()
    assert rules.bank_change_within(day, (day - 10,), 30) == 10
    assert rules.bank_change_within(day, (day - 31,), 30) is None
    assert rules.bank_change_within(day, (day + 1,), 30) is None  # change after the invoice
    assert rules.bank_change_within(day, (day - 40, day - 3), 30) == 3


@pytest.mark.parametrize(
    ("a", "b"),
    [("INV-2025-0042", "INV20250042"), ("0700012", "700012"), ("re-25/00012", "RE2500012")],
)
def test_reference_normalisation(a: str, b: str) -> None:
    assert normalize_reference(a) == normalize_reference(b)


def _invoice(ref: str, day: int, gross: str, po: str) -> Invoice:
    return Invoice(
        invoice_id=f"I{day}",
        doc_type="INVOICE",
        supplier_id="V1",
        company_code="DE01",
        supplier_reference=ref,
        invoice_date=date(2026, 1, day),
        received_date=date(2026, 1, day),
        currency="EUR",
        terms_code="Z030",
        net_amount=D(gross),
        gross_amount=D(gross),
        status="RECEIVED",
        lines=(InvoiceLine(1, po, 10, D(1), D(gross), D(gross)),),
    )


def test_exact_duplicate_scores_one() -> None:
    score, _ = score_pair(
        _invoice("RE-001", 10, "100.00", "PO1"),
        _invoice("RE-001", 9, "100.00", "PO1"),
        DuplicateConfig(),
    )
    assert score == D("1.00")


def test_repeat_order_is_recorded_but_not_flagged() -> None:
    cfg = DuplicateConfig()
    score, feats = score_pair(
        _invoice("RE-077", 28, "100.00", "PO2"), _invoice("RE-051", 2, "100.00", "PO1"), cfg
    )
    assert score == D("0.30")  # exact amount + date within window only
    assert cfg.record_floor <= score < cfg.threshold
    assert feats["reference_match"] is False
