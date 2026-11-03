"""Deterministic three-way matching engine (UC-01, UC-02, UC-03).

``run_matching`` is a pure function: Snapshot + config -> MatchOutcome.
It processes invoices in receipt order because "previously invoiced quantity"
depends on order. Rule precedence follows PROJECT_REQUIREMENTS section 8.2.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.services.matching import rules
from app.services.matching.duplicates import DuplicateConfig, DuplicatePair, find_duplicates
from app.services.matching.rules import PriceOutcome, QtyOutcome
from app.services.matching.snapshot import Invoice, PoKey, Snapshot

ENGINE_VERSION = "1.0.0"

# PROJECT_REQUIREMENTS 8.3 - which codes block payment.
BLOCKING = {
    "DUPLICATE_SUSPECTED": True,
    "BANK_DETAILS_CHANGED": True,
    "PRICE_VARIANCE": True,
    "QTY_VARIANCE": True,
    "NO_GOODS_RECEIPT": True,
    "PO_OVER_INVOICED": True,
    "NO_PO_REFERENCE": True,
    "CURRENCY_MISMATCH": True,
    "CONTRACT_PRICE_DEVIATION": False,
    "PAYMENT_TERMS_MISMATCH": False,
}


@dataclass(frozen=True)
class MatchConfig:
    duplicates: DuplicateConfig = field(default_factory=DuplicateConfig)
    bank_change_window_days: int = 30


@dataclass(frozen=True)
class ExceptionRecord:
    invoice_id: str
    item_no: int | None
    code: str
    severity: str
    amount_at_risk: Decimal
    currency: str
    details: dict[str, Any]

    @property
    def blocks_payment(self) -> bool:
        return BLOCKING[self.code]


@dataclass(frozen=True)
class LineResult:
    invoice_id: str
    item_no: int
    po_number: str | None
    po_item_no: int | None
    po_qty: Decimal | None
    net_received_qty: Decimal | None
    previously_invoiced_qty: Decimal | None
    invoiced_qty: Decimal
    po_price: Decimal | None
    invoice_price: Decimal
    price_variance_amount: Decimal | None
    price_variance_pct: Decimal | None
    price_outcome: str | None
    qty_outcome: str | None


@dataclass(frozen=True)
class InvoiceResult:
    invoice_id: str
    status: str
    blocks_payment: bool
    exception_count: int
    amount_at_risk: Decimal
    currency: str
    is_unpaid: bool


@dataclass
class MatchOutcome:
    params: dict[str, Any]
    invoice_results: list[InvoiceResult] = field(default_factory=list)
    line_results: list[LineResult] = field(default_factory=list)
    exceptions: list[ExceptionRecord] = field(default_factory=list)
    duplicate_pairs: list[DuplicatePair] = field(default_factory=list)

    @property
    def params_hash(self) -> str:
        blob = json.dumps(self.params, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def counts_by_code(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for e in self.exceptions:
            counts[e.code] += 1
        return dict(sorted(counts.items()))


def run_matching(snapshot: Snapshot, config: MatchConfig | None = None) -> MatchOutcome:
    cfg = config or MatchConfig()
    outcome = MatchOutcome(
        params={
            "engine_version": ENGINE_VERSION,
            "duplicates": cfg.duplicates.as_dict(),
            "bank_change_window_days": cfg.bank_change_window_days,
            "tolerances": {cc: t.as_dict() for cc, t in sorted(snapshot.tolerances.items())},
        }
    )
    # R1: duplicates are decided first; a flagged duplicate gets nothing else.
    outcome.duplicate_pairs = find_duplicates(
        snapshot.invoices, snapshot.supplier_vat, cfg.duplicates
    )
    best_match: dict[str, DuplicatePair] = {}
    for pair in outcome.duplicate_pairs:
        current = best_match.get(pair.invoice_id)
        if pair.is_flagged and (current is None or pair.score > current.score):
            best_match[pair.invoice_id] = pair

    previously_invoiced: dict[PoKey, Decimal] = defaultdict(Decimal)
    for inv in snapshot.invoices:
        if inv.doc_type == "CREDIT_MEMO":  # R4
            outcome.invoice_results.append(_result(inv, "NOT_APPLICABLE", []))
            continue
        if inv.invoice_id in best_match:
            pair = best_match[inv.invoice_id]
            exc = _exception(
                inv,
                None,
                "DUPLICATE_SUSPECTED",
                "CRITICAL",
                inv.gross_amount,
                original_invoice_id=pair.candidate_invoice_id,
                score=str(pair.score),
                features=pair.features,
            )
            outcome.exceptions.append(exc)
            outcome.invoice_results.append(_result(inv, "BLOCKED", [exc]))
            continue
        found, lines, tolerated = _match_invoice(inv, snapshot, cfg, previously_invoiced)
        outcome.exceptions.extend(found)
        outcome.line_results.extend(lines)
        if any(e.blocks_payment for e in found):
            status = "BLOCKED"
        elif found:
            status = "FLAGGED"
        elif tolerated:
            status = "WITHIN_TOLERANCE"
        else:
            status = "MATCHED"
        outcome.invoice_results.append(_result(inv, status, found))
    return outcome


def _match_invoice(
    inv: Invoice,
    snap: Snapshot,
    cfg: MatchConfig,
    previously_invoiced: dict[PoKey, Decimal],
) -> tuple[list[ExceptionRecord], list[LineResult], bool]:
    found: list[ExceptionRecord] = []
    lines: list[LineResult] = []
    tolerated = False

    # R5: bank details changed shortly before the invoice date.
    days = rules.bank_change_within(
        inv.invoice_date.toordinal(),
        tuple(d.toordinal() for d in snap.bank_changes.get(inv.supplier_id, ())),
        cfg.bank_change_window_days,
    )
    if days is not None:
        found.append(
            _exception(
                inv,
                None,
                "BANK_DETAILS_CHANGED",
                "CRITICAL",
                inv.gross_amount,
                days_since_change=days,
            )
        )

    po_lines = [li for li in inv.lines if li.po_key]
    currency_mismatch = False
    if po_lines:
        first = snap.po_items[po_lines[0].po_key]  # type: ignore[index]
        if inv.currency != first.currency:
            currency_mismatch = True  # R3: suppress price checks
            found.append(
                _exception(
                    inv,
                    None,
                    "CURRENCY_MISMATCH",
                    "HIGH",
                    inv.gross_amount,
                    po_currency=first.currency,
                    invoice_currency=inv.currency,
                )
            )
        if inv.terms_code != first.terms_code:
            found.append(
                _exception(
                    inv,
                    None,
                    "PAYMENT_TERMS_MISMATCH",
                    "LOW",
                    Decimal("0.00"),
                    po_terms=first.terms_code,
                    invoice_terms=inv.terms_code,
                )
            )

    tol = snap.tolerances[inv.company_code]
    for li in inv.lines:
        key = li.po_key
        if key is None:
            found.append(_exception(inv, li.item_no, "NO_PO_REFERENCE", "MEDIUM", li.net_amount))
            lines.append(
                LineResult(
                    inv.invoice_id,
                    li.item_no,
                    None,
                    None,
                    None,
                    None,
                    None,
                    li.quantity,
                    None,
                    li.unit_price,
                    None,
                    None,
                    None,
                    None,
                )
            )
            continue
        item = snap.po_items[key]
        received = snap.net_received.get(key, Decimal(0))
        prev = previously_invoiced[key]

        qty = rules.check_quantity(li.quantity, received, prev, item.gr_based_iv)
        if qty.outcome == QtyOutcome.NO_GOODS_RECEIPT:
            found.append(
                _exception(
                    inv,
                    li.item_no,
                    "NO_GOODS_RECEIPT",
                    "MEDIUM",
                    li.net_amount,
                    net_received_qty=str(received),
                )
            )
        else:
            if qty.outcome == QtyOutcome.QTY_VARIANCE:
                found.append(
                    _exception(
                        inv,
                        li.item_no,
                        "QTY_VARIANCE",
                        "HIGH",
                        rules.money(qty.variance_qty * li.unit_price),
                        invoiced_qty=str(li.quantity),
                        available_qty=str(qty.available_qty),
                        net_received_qty=str(received),
                        previously_invoiced_qty=str(prev),
                    )
                )
            over = rules.over_invoiced_qty(item.quantity, prev, li.quantity)
            if over > 0:
                found.append(
                    _exception(
                        inv,
                        li.item_no,
                        "PO_OVER_INVOICED",
                        "HIGH",
                        rules.money(over * li.unit_price),
                        po_qty=str(item.quantity),
                        invoiced_total_qty=str(prev + li.quantity),
                    )
                )

        price = None
        if not currency_mismatch:
            price = rules.check_price(item.net_price, li.unit_price, li.quantity, tol)
            if price.outcome == PriceOutcome.VARIANCE:
                found.append(
                    _exception(
                        inv,
                        li.item_no,
                        "PRICE_VARIANCE",
                        rules.price_severity(price.variance_amount, price.variance_pct),
                        abs(price.variance_amount),
                        po_price=str(item.net_price),
                        invoice_price=str(li.unit_price),
                        variance_amount=str(price.variance_amount),
                        variance_pct=str(price.variance_pct),
                    )
                )
            elif price.outcome in (PriceOutcome.WITHIN_TOLERANCE, PriceOutcome.SMALL_DIFFERENCE):
                tolerated = True

        if item.contract_id is not None and item.contract_item_no is not None:
            agreed = snap.contract_prices.get((item.contract_id, item.contract_item_no))
            deviation = rules.contract_deviation(item.net_price, agreed)
            if deviation is not None:
                found.append(
                    _exception(
                        inv,
                        li.item_no,
                        "CONTRACT_PRICE_DEVIATION",
                        "MEDIUM",
                        rules.money(deviation * li.quantity),
                        contract_id=item.contract_id,
                        agreed_price=str(agreed),
                        po_price=str(item.net_price),
                    )
                )

        lines.append(
            LineResult(
                inv.invoice_id,
                li.item_no,
                item.po_number,
                item.item_no,
                item.quantity,
                received,
                prev,
                li.quantity,
                item.net_price,
                li.unit_price,
                price.variance_amount if price else None,
                price.variance_pct if price else None,
                str(price.outcome) if price else None,
                str(qty.outcome),
            )
        )
        previously_invoiced[key] += li.quantity
    return found, lines, tolerated


def _exception(
    inv: Invoice, item_no: int | None, code: str, severity: str, amount: Decimal, **details: Any
) -> ExceptionRecord:
    return ExceptionRecord(inv.invoice_id, item_no, code, severity, amount, inv.currency, details)


def _result(inv: Invoice, status: str, found: list[ExceptionRecord]) -> InvoiceResult:
    return InvoiceResult(
        invoice_id=inv.invoice_id,
        status=status,
        blocks_payment=any(e.blocks_payment for e in found),
        exception_count=len(found),
        amount_at_risk=sum((e.amount_at_risk for e in found), Decimal("0.00")),
        currency=inv.currency,
        is_unpaid=inv.status != "PAID",
    )
