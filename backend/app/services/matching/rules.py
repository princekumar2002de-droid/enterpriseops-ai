"""Business rules for three-way matching as pure functions.

Rule IDs refer to docs/PROJECT_REQUIREMENTS.md section 8.2 (T1-T4, R1-R5).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.services.matching.snapshot import Tolerances

CENT = Decimal("0.01")
PCT_PLACES = Decimal("0.001")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class PriceOutcome(StrEnum):
    MATCH = "MATCH"
    SMALL_DIFFERENCE = "SMALL_DIFFERENCE"  # T1: accepted by BD
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"  # T2: below both PP limits
    VARIANCE = "VARIANCE"  # T2: % OR absolute limit exceeded


class QtyOutcome(StrEnum):
    MATCH = "MATCH"
    NO_GOODS_RECEIPT = "NO_GOODS_RECEIPT"  # R2
    QTY_VARIANCE = "QTY_VARIANCE"  # T3


@dataclass(frozen=True)
class PriceCheck:
    outcome: PriceOutcome
    variance_amount: Decimal  # line net at invoice price - line net at PO price
    variance_pct: Decimal  # unit price deviation in %


@dataclass(frozen=True)
class QtyCheck:
    outcome: QtyOutcome
    available_qty: Decimal
    variance_qty: Decimal


def check_price(
    po_price: Decimal, invoice_price: Decimal, quantity: Decimal, tol: Tolerances
) -> PriceCheck:
    """T1 small difference first, then T2 percentage OR absolute limit (ADR-016)."""
    diff = money(quantity * invoice_price) - money(quantity * po_price)
    pct = ((invoice_price - po_price) / po_price * 100).quantize(PCT_PLACES, ROUND_HALF_UP)
    if invoice_price == po_price:
        return PriceCheck(PriceOutcome.MATCH, diff, pct)
    if abs(diff) <= tol.bd_abs:
        return PriceCheck(PriceOutcome.SMALL_DIFFERENCE, diff, pct)
    if diff > 0:
        breached = pct > tol.pp_upper_pct or diff > tol.pp_upper_abs
    else:
        breached = -pct > tol.pp_lower_pct or -diff > tol.pp_lower_abs
    outcome = PriceOutcome.VARIANCE if breached else PriceOutcome.WITHIN_TOLERANCE
    return PriceCheck(outcome, diff, pct)


def check_quantity(
    invoiced: Decimal, net_received: Decimal, previously_invoiced: Decimal, gr_based_iv: bool
) -> QtyCheck:
    """R2 no goods receipt; T3 invoiced > net received - previously invoiced (zero tolerance)."""
    available = net_received - previously_invoiced
    if gr_based_iv and net_received <= 0:
        return QtyCheck(QtyOutcome.NO_GOODS_RECEIPT, available, invoiced)
    if invoiced > available:
        return QtyCheck(QtyOutcome.QTY_VARIANCE, available, invoiced - available)
    return QtyCheck(QtyOutcome.MATCH, available, Decimal(0))


def over_invoiced_qty(po_qty: Decimal, previously_invoiced: Decimal, invoiced: Decimal) -> Decimal:
    """Quantity invoiced beyond the PO quantity (0 if none)."""
    return max(Decimal(0), previously_invoiced + invoiced - po_qty)


def contract_deviation(po_price: Decimal, agreed_price: Decimal | None) -> Decimal | None:
    """T4: PO price above the valid contract price -> deviation per unit, else None."""
    if agreed_price is None or po_price <= agreed_price:
        return None
    return po_price - agreed_price


def bank_change_within(
    invoice_date_ordinal: int, change_ordinals: tuple[int, ...], window_days: int
) -> int | None:
    """R5: days since the most recent non-initial bank change within the window, else None."""
    hits = [invoice_date_ordinal - c for c in change_ordinals if invoice_date_ordinal - c >= 0]
    recent = [d for d in hits if d <= window_days]
    return min(recent) if recent else None


def price_severity(amount: Decimal, pct: Decimal) -> str:
    """PROJECT_REQUIREMENTS 8.3: HIGH if > 1,000 or > 10 %, else MEDIUM."""
    return "HIGH" if abs(amount) > 1000 or abs(pct) > 10 else "MEDIUM"
