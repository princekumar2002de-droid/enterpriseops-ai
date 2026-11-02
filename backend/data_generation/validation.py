"""Data validation report for the loaded synthetic dataset.

Each check is a SQL query that returns the number of violating rows (0 = pass).
Three groups:
  * integrity  - bookkeeping rules a real ERP enforces (totals, dates, reversals)
  * clean-data - unlabeled invoices really match (catches generator bugs that would
                 otherwise become false "ground truth")
  * coverage   - labels are complete and the exception mix is in the agreed band

The summary section prints distributions for a human sanity check.
"""

from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from data_generation.scenarios import EXCEPTION_CODES, HARD_NEGATIVE_CODES

# Expected share of invoices with >= 1 real exception (full profile only).
EXCEPTION_RATE_BAND = (0.15, 0.25)

# Invoices whose lines may legitimately deviate from the PO (they carry a label).
_UNLABELED = """
    NOT EXISTS (SELECT 1 FROM eval.ground_truth_label g
                WHERE g.invoice_id = h.invoice_id AND NOT g.is_hard_negative)
"""
_PRICE_HN = """
    NOT EXISTS (SELECT 1 FROM eval.ground_truth_label g
                WHERE g.invoice_id = h.invoice_id
                  AND g.label_code IN ('HN_PRICE_WITHIN_TOLERANCE', 'HN_SMALL_DIFFERENCE'))
"""


@dataclass(frozen=True)
class Check:
    name: str
    group: str
    description: str
    sql: str


CHECKS = [
    # ---------------------------------------------------------------- integrity
    Check(
        "invoice_has_items",
        "integrity",
        "Every invoice has at least one item",
        """
        SELECT count(*) FROM erp.invoice_header h
        WHERE NOT EXISTS (SELECT 1 FROM erp.invoice_item i WHERE i.invoice_id = h.invoice_id)
    """,
    ),
    Check(
        "invoice_net_equals_items",
        "integrity",
        "Header net = sum of item nets",
        """
        SELECT count(*) FROM erp.invoice_header h
        JOIN (SELECT invoice_id, sum(net_amount) AS s FROM erp.invoice_item GROUP BY 1) i
          USING (invoice_id)
        WHERE h.net_amount <> i.s
    """,
    ),
    Check(
        "item_amount_consistent",
        "integrity",
        "Item net = round(quantity x unit price, 2)",
        """
        SELECT count(*) FROM erp.invoice_item
        WHERE net_amount <> round(quantity * unit_price, 2)
    """,
    ),
    Check(
        "tax_rate_consistent",
        "integrity",
        "Tax = net x company tax rate (19 % / 7 %)",
        """
        SELECT count(*) FROM erp.invoice_header
        WHERE tax_amount <> round(net_amount *
              CASE company_code WHEN 'DE01' THEN 0.19 WHEN 'US01' THEN 0.07 END, 2)
    """,
    ),
    Check(
        "po_delivery_after_order",
        "integrity",
        "Promised delivery date after PO date",
        """
        SELECT count(*) FROM erp.purchase_order_item i
        JOIN erp.purchase_order_header h USING (po_number)
        WHERE i.delivery_date <= h.doc_date
    """,
    ),
    Check(
        "gr_after_po",
        "integrity",
        "Goods receipt not before the PO date",
        """
        SELECT count(*) FROM erp.goods_receipt g
        JOIN erp.purchase_order_header h USING (po_number)
        WHERE g.posting_date < h.doc_date
    """,
    ),
    Check(
        "invoice_after_po",
        "integrity",
        "Invoice date not before the PO date",
        """
        SELECT count(*) FROM erp.invoice_item i
        JOIN erp.invoice_header ih USING (invoice_id)
        JOIN erp.purchase_order_header h ON h.po_number = i.po_number
        WHERE ih.invoice_date < h.doc_date
    """,
    ),
    Check(
        "reversal_matches_original",
        "integrity",
        "Each 102 reversal references a 101 of the same PO item and quantity, posted earlier",
        """
        SELECT count(*) FROM erp.goods_receipt r
        LEFT JOIN erp.goods_receipt o
          ON (o.mat_doc, o.mat_doc_year, o.line_no)
           = (r.ref_mat_doc, r.ref_mat_doc_year, r.ref_line_no)
        WHERE r.movement_type = '102'
          AND (o.mat_doc IS NULL OR o.movement_type <> '101' OR o.quantity <> r.quantity
               OR (o.po_number, o.po_item_no) <> (r.po_number, r.po_item_no)
               OR o.posting_date > r.posting_date)
    """,
    ),
    Check(
        "net_receipt_not_negative",
        "integrity",
        "Net received quantity per PO item >= 0",
        """
        SELECT count(*) FROM (
          SELECT po_number, po_item_no,
                 sum(CASE movement_type WHEN '101' THEN quantity ELSE -quantity END) AS net
          FROM erp.goods_receipt GROUP BY 1, 2) x
        WHERE net < 0
    """,
    ),
    Check(
        "payment_consistent",
        "integrity",
        "Payment after receipt, amount + discount <= gross, PAID status <-> payment",
        """
        SELECT count(*) FROM erp.invoice_header h
        LEFT JOIN erp.payment p USING (invoice_id)
        WHERE (p.payment_id IS NOT NULL AND (p.payment_date < h.received_date
                OR p.amount + p.discount_taken > h.gross_amount OR h.status <> 'PAID'))
           OR (p.payment_id IS NULL AND h.status = 'PAID')
    """,
    ),
    Check(
        "bank_accounts_not_overlapping",
        "integrity",
        "At most one open bank account per supplier",
        """
        SELECT count(*) FROM (SELECT supplier_id FROM erp.supplier_bank_account
                              WHERE valid_to IS NULL GROUP BY 1 HAVING count(*) > 1) x
    """,
    ),
    # --------------------------------------------------------------- clean data
    Check(
        "clean_price_equals_po",
        "clean-data",
        "Unlabeled invoices: unit price = PO net price",
        f"""
        SELECT count(*) FROM erp.invoice_item i
        JOIN erp.invoice_header h USING (invoice_id)
        JOIN erp.purchase_order_item p ON (p.po_number, p.item_no) = (i.po_number, i.po_item_no)
        WHERE h.doc_type = 'INVOICE' AND i.unit_price <> p.net_price
          AND {_UNLABELED} AND {_PRICE_HN}
    """,
    ),
    Check(
        "clean_header_equals_po",
        "clean-data",
        "Unlabeled invoices: currency and payment terms = PO",
        f"""
        SELECT count(*) FROM erp.invoice_header h
        JOIN (SELECT DISTINCT invoice_id, po_number FROM erp.invoice_item
              WHERE po_number IS NOT NULL) i USING (invoice_id)
        JOIN erp.purchase_order_header p USING (po_number)
        WHERE h.doc_type = 'INVOICE' AND (h.currency <> p.currency OR h.terms_code <> p.terms_code)
          AND h.supplier_id = p.supplier_id AND {_UNLABELED}
    """,
    ),
    Check(
        "clean_po_price_equals_contract",
        "clean-data",
        "PO items without a CONTRACT_PRICE_DEVIATION label use the contract price",
        """
        SELECT count(*) FROM erp.purchase_order_item p
        JOIN erp.contract_item c ON (c.contract_id, c.item_no) = (p.contract_id, p.contract_item_no)
        WHERE p.net_price <> c.agreed_price
          AND NOT EXISTS (
            SELECT 1 FROM erp.invoice_item i JOIN eval.ground_truth_label g
              ON g.invoice_id = i.invoice_id AND g.item_no = i.item_no
            WHERE (i.po_number, i.po_item_no) = (p.po_number, p.item_no)
              AND g.label_code = 'CONTRACT_PRICE_DEVIATION')
    """,
    ),
    Check(
        "clean_quantity_covered",
        "clean-data",
        "PO items without quantity labels: invoiced qty <= net received qty (excl. duplicates)",
        """
        WITH qty_labeled AS (
          SELECT DISTINCT i.po_number, i.po_item_no FROM erp.invoice_item i
          JOIN eval.ground_truth_label g ON g.invoice_id = i.invoice_id
           AND (g.item_no = i.item_no OR g.item_no IS NULL)
          WHERE g.label_code IN ('QTY_VARIANCE', 'NO_GOODS_RECEIPT', 'PO_OVER_INVOICED')),
        dup AS (SELECT invoice_id FROM eval.ground_truth_label
                WHERE label_code = 'DUPLICATE_SUSPECTED'),
        inv AS (
          SELECT i.po_number, i.po_item_no, sum(i.quantity) AS q FROM erp.invoice_item i
          JOIN erp.invoice_header h USING (invoice_id)
          WHERE h.doc_type = 'INVOICE' AND i.po_number IS NOT NULL
            AND i.invoice_id NOT IN (SELECT invoice_id FROM dup)
          GROUP BY 1, 2),
        gr AS (
          SELECT po_number, po_item_no,
                 sum(CASE movement_type WHEN '101' THEN quantity ELSE -quantity END) AS q
          FROM erp.goods_receipt GROUP BY 1, 2)
        SELECT count(*) FROM inv
        LEFT JOIN gr USING (po_number, po_item_no)
        WHERE inv.q > coalesce(gr.q, 0)
          AND (inv.po_number, inv.po_item_no) NOT IN (SELECT po_number, po_item_no FROM qty_labeled)
    """,
    ),
    Check(
        "no_unlabeled_duplicate_reference",
        "clean-data",
        "Same supplier + reference twice only when labeled DUPLICATE_SUSPECTED",
        """
        SELECT count(*) FROM erp.invoice_header h
        WHERE h.doc_type = 'INVOICE'
          AND EXISTS (SELECT 1 FROM erp.invoice_header o
                      WHERE o.doc_type = 'INVOICE' AND o.invoice_id < h.invoice_id
                        AND o.supplier_id = h.supplier_id
                        AND o.supplier_reference = h.supplier_reference)
          AND NOT EXISTS (SELECT 1 FROM eval.ground_truth_label g
                          WHERE g.invoice_id = h.invoice_id
                            AND g.label_code = 'DUPLICATE_SUSPECTED')
    """,
    ),
    # ----------------------------------------------------------------- coverage
    Check(
        "labels_reference_items",
        "coverage",
        "Line-level labels point to existing items",
        """
        SELECT count(*) FROM eval.ground_truth_label g
        WHERE g.item_no IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM erp.invoice_item i
          WHERE (i.invoice_id, i.item_no) = (g.invoice_id, g.item_no))
    """,
    ),
    Check(
        "all_scenarios_present",
        "coverage",
        "Every exception and hard-negative code occurs",
        "SELECT count(*) FROM unnest(ARRAY[{codes}]::text[]) AS c(code) WHERE code NOT IN "
        "(SELECT label_code FROM eval.ground_truth_label)".format(
            codes=", ".join(f"'{c}'" for c in (*EXCEPTION_CODES, *HARD_NEGATIVE_CODES))
        ),
    ),
    Check(
        "exception_rate_in_band",
        "coverage",
        f"Full profile: {EXCEPTION_RATE_BAND[0]:.0%}-{EXCEPTION_RATE_BAND[1]:.0%} of invoices "
        "have an exception",
        f"""
        SELECT CASE WHEN (SELECT profile FROM eval.dataset_run
                          ORDER BY run_id DESC LIMIT 1) <> 'full'
                    THEN 0
                    WHEN rate BETWEEN {EXCEPTION_RATE_BAND[0]} AND {EXCEPTION_RATE_BAND[1]} THEN 0
                    ELSE 1 END
        FROM (SELECT count(DISTINCT g.invoice_id)::numeric / nullif(count(DISTINCT h.invoice_id), 0)
                     AS rate
              FROM erp.invoice_header h
              LEFT JOIN eval.ground_truth_label g
                ON g.invoice_id = h.invoice_id AND NOT g.is_hard_negative
              WHERE h.doc_type = 'INVOICE') r
    """,
    ),
]

SUMMARY_QUERIES = {
    "Row counts": """
        SELECT 'suppliers' AS item, count(*)::text AS value FROM erp.supplier
        UNION ALL SELECT 'purchase orders', count(*)::text FROM erp.purchase_order_header
        UNION ALL SELECT 'PO items', count(*)::text FROM erp.purchase_order_item
        UNION ALL SELECT 'goods receipt lines', count(*)::text FROM erp.goods_receipt
        UNION ALL SELECT 'invoices', count(*)::text FROM erp.invoice_header
                  WHERE doc_type = 'INVOICE'
        UNION ALL SELECT 'credit memos', count(*)::text FROM erp.invoice_header
                  WHERE doc_type = 'CREDIT_MEMO'
        UNION ALL SELECT 'payments', count(*)::text FROM erp.payment
        UNION ALL SELECT 'labels', count(*)::text FROM eval.ground_truth_label
    """,
    "Invoices per label": """
        SELECT label_code AS item,
               count(DISTINCT invoice_id)::text || CASE WHEN bool_or(is_hard_negative)
                                                       THEN '  (hard negative)' ELSE '' END
        FROM eval.ground_truth_label GROUP BY label_code ORDER BY label_code
    """,
    "Delivery performance by persona (first receipt vs promised date)": """
        WITH first_gr AS (
          SELECT po_number, po_item_no, min(posting_date) AS d FROM erp.goods_receipt
          WHERE movement_type = '101' GROUP BY 1, 2)
        SELECT sp.persona AS item,
               'avg delay ' || round(avg(greatest(f.d - i.delivery_date, 0)), 1)::text
               || ' days, on time ' || round(100.0 * avg((f.d <= i.delivery_date)::int), 0)::text
               || ' %'
        FROM first_gr f
        JOIN erp.purchase_order_item i ON (i.po_number, i.item_no) = (f.po_number, f.po_item_no)
        JOIN erp.purchase_order_header h ON h.po_number = i.po_number
        JOIN eval.supplier_persona sp ON sp.supplier_id = h.supplier_id
        GROUP BY sp.persona ORDER BY sp.persona
    """,
    "Exception rate by persona": """
        SELECT sp.persona AS item,
               round(100.0 * count(DISTINCT g.invoice_id) / count(DISTINCT h.invoice_id), 1)::text
               || ' % of ' || count(DISTINCT h.invoice_id)::text || ' invoices'
        FROM erp.invoice_header h
        JOIN eval.supplier_persona sp USING (supplier_id)
        LEFT JOIN eval.ground_truth_label g
          ON g.invoice_id = h.invoice_id AND NOT g.is_hard_negative
        WHERE h.doc_type = 'INVOICE'
        GROUP BY sp.persona ORDER BY sp.persona
    """,
}


@dataclass(frozen=True)
class CheckResult:
    check: Check
    violations: int

    @property
    def passed(self) -> bool:
        return self.violations == 0


def run_checks(conn: Connection) -> list[CheckResult]:
    return [CheckResult(c, int(conn.execute(text(c.sql)).scalar_one())) for c in CHECKS]


def run_summary(conn: Connection) -> dict[str, list[tuple[str, str]]]:
    return {
        title: [(str(r[0]), str(r[1])) for r in conn.execute(text(sql))]
        for title, sql in SUMMARY_QUERIES.items()
    }


def validate(engine: Engine) -> tuple[list[CheckResult], dict[str, list[tuple[str, str]]]]:
    with engine.connect() as conn:
        return run_checks(conn), run_summary(conn)
