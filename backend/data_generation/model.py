"""Shared types and money helpers for the generator.

Rows are plain dicts keyed by column name. While generating, rows may reference
each other directly (e.g. an invoice line holds its PO item dict); IDs that depend
on chronological order (invoice numbers, material documents) are assigned at the end.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

Row = dict[str, Any]

CENT = Decimal("0.01")
TENTH_MILLI = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    """Round to cents, commercial rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def price(value: Decimal) -> Decimal:
    """Round a unit price to 4 decimals."""
    return value.quantize(TENTH_MILLI, rounding=ROUND_HALF_UP)


def dec(value: float, places: str = "0.01") -> Decimal:
    """Float from the RNG -> Decimal with fixed places (never used for arithmetic)."""
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Profile:
    name: str
    n_suppliers: int
    n_materials: int
    n_purchase_orders: int
    window_start: date
    window_end: date
    min_per_scenario: int


PROFILES: dict[str, Profile] = {
    "full": Profile("full", 60, 400, 3000, date(2025, 4, 1), date(2026, 9, 30), 3),
    "small": Profile("small", 20, 80, 320, date(2025, 4, 1), date(2026, 9, 30), 2),
}


@dataclass
class Label:
    invoice: Row
    item_no: int | None
    code: str
    hard_negative: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dataset:
    """Generated rows per qualified table name, plus labels and provenance."""

    seed: int
    profile: Profile
    tables: dict[str, list[Row]]
    labels: list[Row]
    personas: list[Row]

    def row_counts(self) -> dict[str, int]:
        counts = {name: len(rows) for name, rows in self.tables.items()}
        counts["eval.ground_truth_label"] = len(self.labels)
        counts["eval.supplier_persona"] = len(self.personas)
        return counts
