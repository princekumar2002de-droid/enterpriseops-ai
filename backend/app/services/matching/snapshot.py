"""Immutable, typed snapshot of the ERP data the matching engine needs.

The engine never touches the database: it receives a ``Snapshot``. The same
snapshot can be built from database rows (``load_snapshot``) or from rows of a
generated dataset (``Snapshot.from_rows``) - both have identical column names.
That makes the engine fast to unit-test and lets the evaluation harness run on
any seed in memory.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Table, select

from app.db import tables as t

Rows = Sequence[Mapping[str, Any]]
PoKey = tuple[str, int]


@dataclass(frozen=True)
class PoItem:
    po_number: str
    item_no: int
    supplier_id: str
    currency: str
    terms_code: str
    quantity: Decimal
    net_price: Decimal
    gr_based_iv: bool
    contract_id: str | None
    contract_item_no: int | None


@dataclass(frozen=True)
class InvoiceLine:
    item_no: int
    po_number: str | None
    po_item_no: int | None
    quantity: Decimal
    unit_price: Decimal
    net_amount: Decimal

    @property
    def po_key(self) -> PoKey | None:
        if self.po_number is None or self.po_item_no is None:
            return None
        return (self.po_number, self.po_item_no)


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    doc_type: str
    supplier_id: str
    company_code: str
    supplier_reference: str
    invoice_date: date
    received_date: date
    currency: str
    terms_code: str
    net_amount: Decimal
    gross_amount: Decimal
    status: str
    lines: tuple[InvoiceLine, ...]

    @property
    def po_numbers(self) -> frozenset[str]:
        return frozenset(li.po_number for li in self.lines if li.po_number)


@dataclass(frozen=True)
class Tolerances:
    """Limits per company code (ops.tolerance_rule), see ADR-016."""

    pp_upper_pct: Decimal
    pp_upper_abs: Decimal
    pp_lower_pct: Decimal
    pp_lower_abs: Decimal
    bd_abs: Decimal

    def as_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class Snapshot:
    invoices: tuple[Invoice, ...]  # in processing order (received date, invoice id)
    po_items: Mapping[PoKey, PoItem]
    net_received: Mapping[PoKey, Decimal]
    contract_prices: Mapping[tuple[str, int], Decimal]
    supplier_vat: Mapping[str, str]
    bank_changes: Mapping[str, tuple[date, ...]]  # non-initial account start dates
    tolerances: Mapping[str, Tolerances]
    po_currency: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, tables: Mapping[str, Rows]) -> "Snapshot":
        headers = {h["po_number"]: h for h in tables["erp.purchase_order_header"]}
        po_items = {
            (i["po_number"], i["item_no"]): PoItem(
                po_number=i["po_number"],
                item_no=i["item_no"],
                supplier_id=headers[i["po_number"]]["supplier_id"],
                currency=headers[i["po_number"]]["currency"],
                terms_code=headers[i["po_number"]]["terms_code"],
                quantity=i["quantity"],
                net_price=i["net_price"],
                gr_based_iv=i["gr_based_iv"],
                contract_id=i["contract_id"],
                contract_item_no=i["contract_item_no"],
            )
            for i in tables["erp.purchase_order_item"]
        }

        net_received: dict[PoKey, Decimal] = defaultdict(Decimal)
        for gr in tables["erp.goods_receipt"]:
            sign = 1 if gr["movement_type"] == "101" else -1
            net_received[(gr["po_number"], gr["po_item_no"])] += sign * gr["quantity"]

        lines: dict[str, list[InvoiceLine]] = defaultdict(list)
        for li in tables["erp.invoice_item"]:
            lines[li["invoice_id"]].append(
                InvoiceLine(
                    item_no=li["item_no"],
                    po_number=li["po_number"],
                    po_item_no=li["po_item_no"],
                    quantity=li["quantity"],
                    unit_price=li["unit_price"],
                    net_amount=li["net_amount"],
                )
            )
        invoices = tuple(
            Invoice(
                invoice_id=h["invoice_id"],
                doc_type=h["doc_type"],
                supplier_id=h["supplier_id"],
                company_code=h["company_code"],
                supplier_reference=h["supplier_reference"],
                invoice_date=h["invoice_date"],
                received_date=h["received_date"],
                currency=h["currency"],
                terms_code=h["terms_code"],
                net_amount=h["net_amount"],
                gross_amount=h["gross_amount"],
                status=h["status"],
                lines=tuple(sorted(lines[h["invoice_id"]], key=lambda x: x.item_no)),
            )
            for h in sorted(
                tables["erp.invoice_header"], key=lambda h: (h["received_date"], h["invoice_id"])
            )
        )

        accounts: dict[str, list[date]] = defaultdict(list)
        for b in tables["erp.supplier_bank_account"]:
            accounts[b["supplier_id"]].append(b["valid_from"])
        bank_changes = {s: tuple(sorted(d)[1:]) for s, d in accounts.items()}

        tolerances: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
        for r in tables["ops.tolerance_rule"]:
            tolerances[r["company_code"]][r["tolerance_key"]] = r

        return cls(
            invoices=invoices,
            po_items=po_items,
            net_received=dict(net_received),
            contract_prices={
                (c["contract_id"], c["item_no"]): c["agreed_price"]
                for c in tables["erp.contract_item"]
            },
            supplier_vat={s["supplier_id"]: s["vat_id"] for s in tables["erp.supplier"]},
            bank_changes=bank_changes,
            tolerances={
                cc: Tolerances(
                    pp_upper_pct=rules["PP"]["upper_pct"],
                    pp_upper_abs=rules["PP"]["upper_abs"],
                    pp_lower_pct=rules["PP"]["lower_pct"],
                    pp_lower_abs=rules["PP"]["lower_abs"],
                    bd_abs=rules["BD"]["upper_abs"],
                )
                for cc, rules in tolerances.items()
            },
            po_currency={po: h["currency"] for po, h in headers.items()},
        )


SNAPSHOT_TABLES: list[Table] = [
    t.purchase_order_header,
    t.purchase_order_item,
    t.goods_receipt,
    t.invoice_header,
    t.invoice_item,
    t.supplier_bank_account,
    t.contract_item,
    t.supplier,
    t.tolerance_rule,
]


def load_snapshot(conn: Connection) -> Snapshot:
    """Read everything the engine needs in one consistent transaction."""
    rows = {
        f"{table.schema}.{table.name}": [dict(r) for r in conn.execute(select(table)).mappings()]
        for table in SNAPSHOT_TABLES
    }
    return Snapshot.from_rows(rows)
