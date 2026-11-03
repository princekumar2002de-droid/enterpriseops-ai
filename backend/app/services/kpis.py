"""KPI catalog (PROJECT_REQUIREMENTS 8.4) - every KPI defined once, in SQL.

Each KPI query returns ``value`` and ``n`` (sample size). KPIs that support a
supplier breakdown also define a grouped query returning
``key, label, value, n``. All queries take the parameters
:date_from, :date_to and :company_code. Money KPIs are in the company currency.
Results use the latest completed matching run (via the ``agent`` views).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

_INVOICES = """
    SELECT o.*, (o.match_status IN ('MATCHED', 'WITHIN_TOLERANCE')) AS first_pass,
           (o.match_status IN ('BLOCKED', 'FLAGGED')) AS has_exception
    FROM agent.invoice_overview o
    WHERE o.doc_type = 'INVOICE' AND o.company_code = :company_code
      AND o.received_date BETWEEN :date_from AND :date_to
"""

_DELIVERIES = """
    SELECT p.po_number, p.item_no, p.supplier_id, p.delivery_date, p.quantity,
           f.first_date, f.first_qty, p.doc_date
    FROM agent.purchase_order p
    JOIN (SELECT DISTINCT ON (po_number, po_item_no) po_number, po_item_no,
                 posting_date AS first_date, quantity AS first_qty
          FROM agent.goods_receipt_line WHERE movement_type = '101'
          ORDER BY po_number, po_item_no, posting_date, mat_doc) f
      ON f.po_number = p.po_number AND f.po_item_no = p.item_no
    WHERE p.company_code = :company_code AND p.delivery_date BETWEEN :date_from AND :date_to
"""

_PAID = """
    SELECT o.invoice_id, o.supplier_id, o.supplier_name, o.invoice_date, o.received_date,
           o.gross_amount, pay.payment_date, pay.discount_taken,
           t.net_days, t.discount_pct
    FROM agent.invoice_overview o
    JOIN erp.payment pay ON pay.invoice_id = o.invoice_id
    JOIN erp.payment_terms t ON t.terms_code = o.terms_code
    WHERE o.doc_type = 'INVOICE' AND o.company_code = :company_code
      AND pay.payment_date BETWEEN :date_from AND :date_to
"""

_SUPPLIER_LABEL = (
    "(SELECT name FROM agent.supplier_profile sp WHERE sp.supplier_id = x.supplier_id)"
)


@dataclass(frozen=True)
class KpiDefinition:
    kpi_id: str
    name: str
    unit: str
    description: str
    formula: str
    sql: str
    sql_by_supplier: str | None = None


def _pct(numerator: str) -> str:
    return f"round(100.0 * avg(({numerator})::int), 2)"


KPIS: dict[str, KpiDefinition] = {
    k.kpi_id: k
    for k in [
        KpiDefinition(
            "first_pass_match_rate",
            "First-pass match rate",
            "%",
            "Share of invoices that passed matching without any exception (touchless).",
            "invoices MATCHED or WITHIN_TOLERANCE / all invoices",
            f"SELECT {_pct('first_pass')} AS value, count(*) AS n FROM ({_INVOICES}) x",
        ),
        KpiDefinition(
            "exception_rate",
            "Exception rate (supplier discrepancy rate)",
            "%",
            "Share of invoices with at least one exception; per supplier this is the "
            "supplier discrepancy rate.",
            "invoices BLOCKED or FLAGGED / all invoices",
            f"SELECT {_pct('has_exception')} AS value, count(*) AS n FROM ({_INVOICES}) x",
            f"SELECT supplier_id AS key, max(supplier_name) AS label, "
            f"{_pct('has_exception')} AS value, count(*) AS n FROM ({_INVOICES}) x "
            f"GROUP BY supplier_id",
        ),
        KpiDefinition(
            "open_value_at_risk",
            "Open value at risk",
            "currency",
            "Amount at risk of exceptions on invoices that are not paid yet.",
            "sum(amount_at_risk) of exceptions on unpaid invoices",
            f"""SELECT coalesce(sum(e.amount_at_risk), 0) AS value, count(*) AS n
                FROM agent.open_exception e JOIN ({_INVOICES}) x ON x.invoice_id = e.invoice_id
                WHERE e.payment_status <> 'PAID'""",
            f"""SELECT x.supplier_id AS key, max(x.supplier_name) AS label,
                       coalesce(sum(e.amount_at_risk), 0) AS value, count(*) AS n
                FROM agent.open_exception e JOIN ({_INVOICES}) x ON x.invoice_id = e.invoice_id
                WHERE e.payment_status <> 'PAID' GROUP BY x.supplier_id""",
        ),
        KpiDefinition(
            "blocked_open_invoices",
            "Blocked open invoices",
            "count",
            "Unpaid invoices currently carrying a payment block.",
            "count of unpaid invoices with payment_block set",
            f"""SELECT count(*) AS value, count(*) AS n FROM ({_INVOICES}) x
                WHERE x.payment_block IS NOT NULL""",
        ),
        KpiDefinition(
            "supplier_otif",
            "Supplier OTIF",
            "%",
            "Deliveries on time and in full: first receipt on/before the promised date and "
            "first receipt quantity >= ordered quantity.",
            "PO items with first_date <= delivery_date AND first_qty >= quantity"
            " / PO items received",
            f"""SELECT {_pct("first_date <= delivery_date AND first_qty >= quantity")} AS value,
                       count(*) AS n FROM ({_DELIVERIES}) x""",
            f"""SELECT supplier_id AS key, {_SUPPLIER_LABEL} AS label,
                       {_pct("first_date <= delivery_date AND first_qty >= quantity")} AS value,
                       count(*) AS n FROM ({_DELIVERIES}) x GROUP BY supplier_id""",
        ),
        KpiDefinition(
            "avg_delivery_delay_days",
            "Average delivery delay",
            "days",
            "Average days the first receipt came after the promised date (early = 0).",
            "avg(max(first_date - delivery_date, 0))",
            f"""SELECT round(avg(greatest(first_date - delivery_date, 0)), 2) AS value,
                       count(*) AS n FROM ({_DELIVERIES}) x""",
            f"""SELECT supplier_id AS key, {_SUPPLIER_LABEL} AS label,
                       round(avg(greatest(first_date - delivery_date, 0)), 2) AS value,
                       count(*) AS n FROM ({_DELIVERIES}) x GROUP BY supplier_id""",
        ),
        KpiDefinition(
            "price_variance_pct",
            "Price variance",
            "%",
            "Price variances above tolerance relative to the invoiced value of PO lines.",
            "sum(price_variance_amount where outcome = VARIANCE) / sum(net_amount of PO lines)",
            f"""SELECT round(100.0 * coalesce(sum(l.price_variance_amount)
                         FILTER (WHERE l.price_outcome = 'VARIANCE'), 0)
                         / nullif(sum(l.net_amount), 0), 3) AS value, count(*) AS n
                FROM agent.invoice_line_match l JOIN ({_INVOICES}) x
                  ON x.invoice_id = l.invoice_id WHERE l.po_number IS NOT NULL""",
            f"""SELECT x.supplier_id AS key, max(x.supplier_name) AS label,
                       round(100.0 * coalesce(sum(l.price_variance_amount)
                         FILTER (WHERE l.price_outcome = 'VARIANCE'), 0)
                         / nullif(sum(l.net_amount), 0), 3) AS value, count(*) AS n
                FROM agent.invoice_line_match l JOIN ({_INVOICES}) x
                  ON x.invoice_id = l.invoice_id WHERE l.po_number IS NOT NULL
                GROUP BY x.supplier_id""",
        ),
        KpiDefinition(
            "non_po_invoice_share",
            "Non-PO invoice share",
            "%",
            "Invoices without any purchase order reference (maverick-buying indicator).",
            "invoices without PO lines / all invoices",
            f"""SELECT {
                _pct(
                    "NOT EXISTS (SELECT 1 FROM agent.invoice_line_match l "
                    "WHERE l.invoice_id = x.invoice_id AND l.po_number IS NOT NULL)"
                )
            }
                       AS value, count(*) AS n FROM ({_INVOICES}) x""",
        ),
        KpiDefinition(
            "cash_discount_capture_rate",
            "Cash discount capture rate",
            "%",
            "Discount taken relative to discount available on paid invoices with discount terms.",
            "sum(discount_taken) / sum(gross_amount x discount_pct)",
            f"""SELECT round(100.0 * sum(discount_taken)
                         / nullif(sum(gross_amount * discount_pct / 100), 0), 2) AS value,
                       count(*) AS n FROM ({_PAID}) x WHERE discount_pct IS NOT NULL""",
        ),
        KpiDefinition(
            "late_payment_rate",
            "Late payment rate",
            "%",
            "Paid invoices settled after their due date (invoice date + net days).",
            "invoices with payment_date > invoice_date + net_days / paid invoices",
            f"""SELECT {_pct("payment_date > invoice_date + net_days")} AS value, count(*) AS n
                FROM ({_PAID}) x""",
        ),
        KpiDefinition(
            "median_receipt_to_payment_days",
            "Receipt-to-payment cycle time",
            "days",
            "Median days from invoice receipt to payment.",
            "median(payment_date - received_date)",
            f"""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY payment_date - received_date)
                       AS value, count(*) AS n FROM ({_PAID}) x""",
        ),
        KpiDefinition(
            "median_po_to_receipt_days",
            "PO-to-receipt lead time",
            "days",
            "Median days from purchase order to first goods receipt.",
            "median(first_date - po doc_date)",
            f"""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY first_date - doc_date)
                       AS value, count(*) AS n FROM ({_DELIVERIES}) x""",
        ),
    ]
}

MIN_DATE = date(1900, 1, 1)
MAX_DATE = date(2999, 12, 31)


@dataclass(frozen=True)
class BreakdownRow:
    key: str
    label: str | None
    value: Decimal | None
    n: int


@dataclass(frozen=True)
class KpiValue:
    kpi_id: str
    value: Decimal | None
    n: int
    breakdown: list[BreakdownRow] = field(default_factory=list)


class UnknownKpiError(KeyError):
    pass


class BreakdownNotSupportedError(ValueError):
    pass


def compute(
    conn: Connection,
    kpi_id: str,
    *,
    company_code: str = "DE01",
    date_from: date | None = None,
    date_to: date | None = None,
    by_supplier: bool = False,
) -> KpiValue:
    try:
        kpi = KPIS[kpi_id]
    except KeyError as exc:
        raise UnknownKpiError(kpi_id) from exc
    params: dict[str, Any] = {
        "company_code": company_code,
        "date_from": date_from or MIN_DATE,
        "date_to": date_to or MAX_DATE,
    }
    row = conn.execute(text(kpi.sql), params).one()
    value = None if row.value is None else Decimal(str(row.value))
    breakdown: list[BreakdownRow] = []
    if by_supplier:
        if kpi.sql_by_supplier is None:
            raise BreakdownNotSupportedError(kpi_id)
        rows = conn.execute(text(f"{kpi.sql_by_supplier} ORDER BY value DESC NULLS LAST"), params)
        breakdown = [
            BreakdownRow(
                r.key, r.label, None if r.value is None else Decimal(str(r.value)), int(r.n)
            )
            for r in rows
        ]
    return KpiValue(kpi_id, value, int(row.n), breakdown)
