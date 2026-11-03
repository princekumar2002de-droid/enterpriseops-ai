"""Duplicate invoice detection (UC-03) - transparent scoring, no ML.

Candidates: an earlier INVOICE (credit memos excluded, R4) with the same VAT ID
(covers the same supplier and duplicate vendor masters), gross amount within
``amount_tolerance_pct`` and invoice date within ``window_days``.

Score (0..1) = sum of the weights of the features that hold. The threshold is
tuned on a separate seed (decision D2) - see evaluation/ and TESTING_AND_EVALUATION.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from app.services.matching.snapshot import Invoice

WEIGHTS: Mapping[str, Decimal] = {
    "reference_match": Decimal("0.45"),  # normalized supplier reference identical
    "amount_exact": Decimal("0.25"),
    "amount_close": Decimal("0.10"),  # only if not exact
    "date_close": Decimal("0.15"),  # <= 3 days apart
    "date_in_window": Decimal("0.05"),  # only if not close
    "same_po": Decimal("0.15"),
}


@dataclass(frozen=True)
class DuplicateConfig:
    threshold: Decimal = Decimal("0.60")
    record_floor: Decimal = Decimal("0.30")
    amount_tolerance_pct: Decimal = Decimal("0.5")
    window_days: int = 30
    close_days: int = 3

    def as_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class DuplicatePair:
    invoice_id: str
    candidate_invoice_id: str
    score: Decimal
    is_flagged: bool
    features: dict[str, object] = field(default_factory=dict)


_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalize_reference(reference: str) -> str:
    """'INV-2025-0042' == 'INV20250042'; '0700012' == '700012'."""
    return _NON_ALNUM.sub("", reference.upper()).lstrip("0")


def score_pair(
    invoice: Invoice, earlier: Invoice, cfg: DuplicateConfig
) -> tuple[Decimal, dict[str, object]]:
    days = abs((invoice.invoice_date - earlier.invoice_date).days)
    amount_diff = abs(invoice.gross_amount - earlier.gross_amount)
    feats: dict[str, bool] = {
        "reference_match": normalize_reference(invoice.supplier_reference)
        == normalize_reference(earlier.supplier_reference),
        "amount_exact": amount_diff == 0,
        "amount_close": amount_diff != 0,
        "date_close": days <= cfg.close_days,
        "date_in_window": days > cfg.close_days,
        "same_po": bool(invoice.po_numbers) and invoice.po_numbers == earlier.po_numbers,
    }
    score = sum((WEIGHTS[k] for k, on in feats.items() if on), Decimal("0"))
    details: dict[str, object] = {k: v for k, v in feats.items()}
    details.update(
        days_apart=days,
        amount_difference=str(amount_diff),
        same_supplier=invoice.supplier_id == earlier.supplier_id,
    )
    return score, details


def find_duplicates(
    invoices: Iterable[Invoice], supplier_vat: Mapping[str, str], cfg: DuplicateConfig
) -> list[DuplicatePair]:
    """Compare each invoice with earlier invoices (processing order) of the same VAT ID."""
    seen: dict[str, list[Invoice]] = defaultdict(list)
    pairs: list[DuplicatePair] = []
    for inv in invoices:
        if inv.doc_type != "INVOICE":
            continue
        vat = supplier_vat[inv.supplier_id]
        for earlier in seen[vat]:
            if abs((inv.invoice_date - earlier.invoice_date).days) > cfg.window_days:
                continue
            limit = earlier.gross_amount * cfg.amount_tolerance_pct / 100
            if abs(inv.gross_amount - earlier.gross_amount) > limit:
                continue
            score, feats = score_pair(inv, earlier, cfg)
            if score >= cfg.record_floor:
                pairs.append(
                    DuplicatePair(
                        inv.invoice_id, earlier.invoice_id, score, score >= cfg.threshold, feats
                    )
                )
        seen[vat].append(inv)
    return pairs
