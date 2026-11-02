"""Exception injection and ground-truth labeling.

Every function starts from clean data (everything matches) and changes exactly
what its scenario needs, then writes a label. Labels state what a correct
deterministic engine MUST report, following the business rules in
docs/PROJECT_REQUIREMENTS.md section 8.2 (incl. rule precedence):

  R1 A suspected duplicate gets only DUPLICATE_SUSPECTED; its quantities do not count
     as "previously invoiced" for later invoices.
  R2 NO_GOODS_RECEIPT on a line suppresses QTY_VARIANCE for that line.
  R3 CURRENCY_MISMATCH suppresses price checks for the invoice.
  R4 Credit memos are excluded from quantity and duplicate checks.
  R5 Tolerances (ADR-016): BD small difference first (|diff| <= 5.00 accepted), then
     PP is breached if the % OR the absolute limit is exceeded.

Hard negatives (is_hard_negative = true) look suspicious but must NOT be flagged.
At most one scenario touches an invoice (``_used``), so labels stay unambiguous.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from data_generation import reference
from data_generation.model import Row, money, price
from data_generation.reference import Persona

if TYPE_CHECKING:
    from data_generation.generator import Generator

# Share of PO-based invoices per scenario (quota = max(profile minimum, rate * count)).
RATES = {
    "CONTRACT_PRICE_DEVIATION": 0.015,
    "PRICE_VARIANCE": 0.025,
    "HN_PRICE_WITHIN_TOLERANCE": 0.010,
    "HN_SMALL_DIFFERENCE": 0.008,
    "QTY_VARIANCE": 0.030,
    "NO_GOODS_RECEIPT_MISSING": 0.015,
    "NO_GOODS_RECEIPT_REVERSED": 0.005,
    "HN_GR_REVERSAL_REPOSTED": 0.005,
    "PO_OVER_INVOICED": 0.005,
    "CURRENCY_MISMATCH": 0.005,
    "PAYMENT_TERMS_MISMATCH": 0.020,
    "DUPLICATE_SUSPECTED": 0.015,
    "NO_PO_REFERENCE": 0.020,
    "CREDIT_MEMO_SHARE": 0.30,
}

EXCEPTION_CODES = (
    "PRICE_VARIANCE",
    "QTY_VARIANCE",
    "NO_GOODS_RECEIPT",
    "PO_OVER_INVOICED",
    "NO_PO_REFERENCE",
    "CONTRACT_PRICE_DEVIATION",
    "PAYMENT_TERMS_MISMATCH",
    "CURRENCY_MISMATCH",
    "DUPLICATE_SUSPECTED",
    "BANK_DETAILS_CHANGED",
)
HARD_NEGATIVE_CODES = (
    "HN_PARTIAL_DELIVERY",
    "HN_PRICE_WITHIN_TOLERANCE",
    "HN_SMALL_DIFFERENCE",
    "HN_GR_REVERSAL_REPOSTED",
    "HN_CREDIT_MEMO_SAME_REF",
    "HN_SAME_AMOUNT_DIFFERENT_PO",
    "HN_OLD_BANK_CHANGE",
)


def apply_all(gen: "Generator") -> None:
    _price_creep(gen)
    _fraud_bank_change(gen)
    _old_bank_changes(gen)
    _contract_price_deviation(gen)
    _price_variance(gen)
    _price_within_tolerance(gen)
    _small_difference(gen)
    _qty_variance(gen)
    _no_goods_receipt_missing(gen)
    _no_goods_receipt_reversed(gen)
    _gr_reversal_reposted(gen)
    _po_over_invoiced(gen)
    _currency_mismatch(gen)
    _payment_terms_mismatch(gen)
    _duplicates(gen)
    _non_po_invoices(gen)
    _credit_memos(gen)
    _label_structural_hard_negatives(gen)


# ------------------------------------------------------------------ helpers


def _eligible(gen: "Generator", extra: Callable[[Row], bool] = lambda inv: True) -> list[Row]:
    """Clean, untouched, single-shipment PO invoices outside repeat-order pairs."""
    out = []
    for inv in gen.invoices:
        po = inv.get("_po")
        if (
            inv["doc_type"] != "INVOICE"
            or inv["_used"]
            or po is None
            or inv["_shipment"]["partial"]
            or "_repeat_of" in po
            or po.get("_repeat_source")
            or gen.persona(inv["supplier_id"]) == Persona.FRAUD_SIGNAL
        ):
            continue
        if extra(inv):
            out.append(inv)
    return out


def _choose(
    gen: "Generator",
    key: str,
    candidates: list[Row],
    boost: dict[Persona, float] | None = None,
) -> list[Row]:
    """Pick the scenario quota, preferring personas in ``boost``; mark them used."""
    factors = boost or {}
    chosen = gen.pick(
        candidates,
        gen.quota(RATES[key]),
        lambda inv: factors.get(gen.persona(inv["supplier_id"]), 1.0),
    )
    for inv in chosen:
        inv["_used"] = True
    return chosen


def _lines_where(inv: Row, cond: Callable[[Row], bool]) -> list[Row]:
    return [li for li in inv["_lines"] if cond(li)]


def _reprice(gen: "Generator", inv: Row, line: Row, factor: Decimal) -> dict[str, Any]:
    old_net = line["net_amount"]
    po_price = line["_po_item"]["net_price"]
    line["unit_price"] = price(po_price * factor)
    gen.recompute(inv)
    diff = line["net_amount"] - old_net
    return {
        "po_price": str(po_price),
        "invoice_price": str(line["unit_price"]),
        "variance_amount": str(diff),
        "variance_pct": str(money((line["unit_price"] - po_price) / po_price * 100)),
    }


def _within_window(gen: "Generator", d: date) -> bool:
    return d <= gen.profile.window_end


# ------------------------------------------------------------- persona-driven


def _price_creep(gen: "Generator") -> None:
    """Price-creep suppliers bill progressively above the PO price after month 6."""
    start = gen.profile.window_start
    total_days = (gen.profile.window_end - start).days
    for inv in _eligible(gen, lambda i: gen.persona(i["supplier_id"]) == Persona.PRICE_CREEP):
        months = (inv["invoice_date"] - start).days / 30.4
        if months < 6 or gen.rng.random() > 0.7:
            continue
        progress = (inv["invoice_date"] - start).days / total_days
        factor = Decimal("1") + Decimal(
            str(round(0.03 + 0.07 * progress + gen.rng.uniform(0, 0.01), 4))
        )
        lines = _lines_where(inv, lambda li: li["net_amount"] >= 200)
        if not lines:
            continue
        inv["_used"] = True
        for line in lines:
            details = _reprice(gen, inv, line, factor)
            gen.label(inv, line["item_no"], "PRICE_VARIANCE", cause="price_creep", **details)


def _fraud_bank_change(gen: "Generator") -> None:
    """Bank details change shortly before invoices: classic payment-fraud signal."""
    supplier = next(s for s in gen.suppliers if s["_persona"] == Persona.FRAUD_SIGNAL)
    invs = sorted(
        (i for i in gen.invoices if i["supplier_id"] == supplier["supplier_id"]),
        key=lambda i: i["invoice_date"],
    )
    if not invs:
        return
    late = invs[int(len(invs) * 0.6) :] or invs
    target = gen.rng.choice(late)
    change = target["invoice_date"] - gen.days(3, 12)
    gen._add_bank_account(supplier, change, "SUPPLIER_PORTAL")
    for inv in invs:
        if 0 <= (inv["invoice_date"] - change).days <= 30:
            inv["_used"] = True
            gen.label(
                inv,
                None,
                "BANK_DETAILS_CHANGED",
                bank_change_date=change,
                days_before_invoice=(inv["invoice_date"] - change).days,
            )


def _old_bank_changes(gen: "Generator") -> None:
    """Legitimate bank changes long before any invoice: must NOT be flagged."""
    candidates = [
        s
        for s in gen.suppliers
        if s["_persona"] == Persona.RELIABLE
        and s["country"] != "US"
        and any(i["supplier_id"] == s["supplier_id"] for i in gen.invoices)
    ]
    for supplier in gen.rng.sample(candidates, min(3, len(candidates))):
        change = gen.profile.window_start - gen.days(40, 80)
        if change <= supplier["created_on"]:
            continue
        gen._add_bank_account(supplier, change, "AP_MASTER_DATA")
        first = min(
            (i for i in gen.invoices if i["supplier_id"] == supplier["supplier_id"]),
            key=lambda i: i["invoice_date"],
        )
        first["_used"] = True
        gen.label(
            first,
            None,
            "HN_OLD_BANK_CHANGE",
            hard_negative=True,
            bank_change_date=change,
            days_before_invoice=(first["invoice_date"] - change).days,
        )


# ------------------------------------------------------------ price scenarios


def _contract_price_deviation(gen: "Generator") -> None:
    """Buyer ordered above the contract price; invoice matches the PO."""
    has_contract = lambda inv: any(li["_po_item"]["contract_id"] for li in inv["_lines"])  # noqa: E731
    for inv in _choose(gen, "CONTRACT_PRICE_DEVIATION", _eligible(gen, has_contract)):
        line = next(li for li in inv["_lines"] if li["_po_item"]["contract_id"])
        item = line["_po_item"]
        agreed = item["net_price"]
        item["net_price"] = price(agreed * gen.uniform_dec(1.03, 1.08, "0.001"))
        line["unit_price"] = item["net_price"]
        gen.recompute(inv)
        gen.label(
            inv,
            line["item_no"],
            "CONTRACT_PRICE_DEVIATION",
            agreed_price=agreed,
            po_price=item["net_price"],
            deviation_pct=money((item["net_price"] - agreed) / agreed * 100),
        )


def _price_variance(gen: "Generator") -> None:
    """Invoice price 4-15 % above PO price: breaches the 2 % limit (and BD)."""
    big_line = lambda inv: bool(_lines_where(inv, lambda li: li["net_amount"] >= 200))  # noqa: E731
    for inv in _choose(gen, "PRICE_VARIANCE", _eligible(gen, big_line)):
        line = max(
            _lines_where(inv, lambda li: li["net_amount"] >= 200), key=lambda li: li["net_amount"]
        )
        details = _reprice(gen, inv, line, Decimal("1") + gen.uniform_dec(0.04, 0.15, "0.001"))
        gen.label(inv, line["item_no"], "PRICE_VARIANCE", cause="random", **details)


def _price_within_tolerance(gen: "Generator") -> None:
    """+0.4-1.5 % on a 1,000-4,000 line: below 2 % AND below 100 -> accepted."""
    cond = lambda li: Decimal(1000) <= li["net_amount"] <= Decimal(4000)  # noqa: E731
    for inv in _choose(
        gen, "HN_PRICE_WITHIN_TOLERANCE", _eligible(gen, lambda i: bool(_lines_where(i, cond)))
    ):
        line = _lines_where(inv, cond)[0]
        details = _reprice(gen, inv, line, Decimal("1") + gen.uniform_dec(0.004, 0.015, "0.0001"))
        gen.label(inv, line["item_no"], "HN_PRICE_WITHIN_TOLERANCE", hard_negative=True, **details)


def _small_difference(gen: "Generator") -> None:
    """% above 2 but difference <= 4.50 (BD limit 5.00) on a 20-150 line -> accepted.

    The markup is capped at 4.50 / line value, so the absolute difference stays
    below the small-difference limit while the percentage stays above 2.5 %.
    """
    cond = lambda li: Decimal(20) <= li["net_amount"] <= Decimal(150)  # noqa: E731
    candidates = _eligible(gen, lambda i: bool(_lines_where(i, cond)))
    for inv in _choose(gen, "HN_SMALL_DIFFERENCE", candidates):
        line = _lines_where(inv, cond)[0]
        cap = min(0.04, 4.5 / float(line["net_amount"]))
        details = _reprice(gen, inv, line, Decimal("1") + gen.uniform_dec(0.025, cap, "0.0001"))
        gen.label(inv, line["item_no"], "HN_SMALL_DIFFERENCE", hard_negative=True, **details)


# --------------------------------------------------------- quantity / GR scenarios


def _qty_variance(gen: "Generator") -> None:
    """Short delivery (80-95 %) but the supplier invoices the full PO quantity."""
    cond = lambda li: li["quantity"] >= 5  # noqa: E731
    boost = {Persona.SLOPPY: 6.0}
    for inv in _choose(
        gen, "QTY_VARIANCE", _eligible(gen, lambda i: bool(_lines_where(i, cond))), boost
    ):
        line = _lines_where(inv, cond)[0]
        gr = line["_gr"]
        received = Decimal(int(line["quantity"] * gen.uniform_dec(0.80, 0.95, "0.001")))
        received = min(max(received, Decimal(1)), line["quantity"] - 1)
        gr["quantity"] = received
        gen.label(
            inv,
            line["item_no"],
            "QTY_VARIANCE",
            po_qty=line["_po_item"]["quantity"],
            received_qty=received,
            invoiced_qty=line["quantity"],
        )


def _no_goods_receipt_missing(gen: "Generator") -> None:
    """Invoice arrives but the goods receipt was never posted."""
    boost = {Persona.LATE: 5.0}
    for inv in _choose(gen, "NO_GOODS_RECEIPT_MISSING", _eligible(gen), boost):
        doc = inv["_shipment"]["mat_doc"]
        gen.mat_docs.remove(doc)
        for line in inv["_lines"]:
            gen.label(inv, line["item_no"], "NO_GOODS_RECEIPT", cause="not_posted")


def _reverse(gen: "Generator", doc: Row, on: date) -> Row:
    lines = [(gr["_po_item"], gr["quantity"], "102", gr) for gr in doc["lines"]]
    return gen._mat_doc(on, lines)


def _no_goods_receipt_reversed(gen: "Generator") -> None:
    """Goods receipt posted, then fully reversed and never re-posted."""
    ok = lambda inv: _within_window(gen, inv["_shipment"]["date"] + timedelta(days=5))  # noqa: E731
    for inv in _choose(gen, "NO_GOODS_RECEIPT_REVERSED", _eligible(gen, ok)):
        _reverse(gen, inv["_shipment"]["mat_doc"], inv["_shipment"]["date"] + gen.days(2, 5))
        for line in inv["_lines"]:
            gen.label(inv, line["item_no"], "NO_GOODS_RECEIPT", cause="reversed")


def _gr_reversal_reposted(gen: "Generator") -> None:
    """Receipt reversed and posted again (wrong storage location) - net quantity correct."""
    ok = lambda inv: _within_window(gen, inv["_shipment"]["date"] + timedelta(days=5))  # noqa: E731
    for inv in _choose(gen, "HN_GR_REVERSAL_REPOSTED", _eligible(gen, ok)):
        doc = inv["_shipment"]["mat_doc"]
        rev_date = inv["_shipment"]["date"] + gen.days(1, 3)
        _reverse(gen, doc, rev_date)
        repost = gen._mat_doc(
            rev_date, [(gr["_po_item"], gr["quantity"], "101", None) for gr in doc["lines"]]
        )
        for line, gr in zip(inv["_lines"], repost["lines"], strict=True):
            line["_gr"] = gr
        gen.label(inv, None, "HN_GR_REVERSAL_REPOSTED", hard_negative=True)


def _po_over_invoiced(gen: "Generator") -> None:
    """Over-delivery accepted at goods receipt and invoiced: invoice > PO quantity."""
    cond = lambda li: li["quantity"] >= 10  # noqa: E731
    for inv in _choose(
        gen, "PO_OVER_INVOICED", _eligible(gen, lambda i: bool(_lines_where(i, cond)))
    ):
        line = _lines_where(inv, cond)[0]
        po_qty = line["_po_item"]["quantity"]
        extra = max(Decimal(1), Decimal(int(po_qty * gen.uniform_dec(0.05, 0.10, "0.001"))))
        line["quantity"] = po_qty + extra
        line["_gr"]["quantity"] = po_qty + extra
        gen.recompute(inv)
        gen.label(
            inv,
            line["item_no"],
            "PO_OVER_INVOICED",
            po_qty=po_qty,
            received_qty=po_qty + extra,
            invoiced_qty=po_qty + extra,
        )


# ------------------------------------------------------------ header scenarios


def _currency_mismatch(gen: "Generator") -> None:
    """German PO in EUR, supplier invoices in USD."""
    de = lambda inv: inv["company_code"] == "DE01"  # noqa: E731
    for inv in _choose(gen, "CURRENCY_MISMATCH", _eligible(gen, de)):
        inv["currency"] = "USD"
        gen.label(inv, None, "CURRENCY_MISMATCH", po_currency="EUR", invoice_currency="USD")


def _payment_terms_mismatch(gen: "Generator") -> None:
    """Supplier states different payment terms than agreed on the PO."""
    codes = [t["terms_code"] for t in reference.PAYMENT_TERMS]
    boost = {Persona.SLOPPY: 4.0}
    for inv in _choose(gen, "PAYMENT_TERMS_MISMATCH", _eligible(gen), boost):
        po_terms = inv["terms_code"]
        inv["terms_code"] = gen.rng.choice([c for c in codes if c != po_terms])
        gen.label(
            inv, None, "PAYMENT_TERMS_MISMATCH", po_terms=po_terms, invoice_terms=inv["terms_code"]
        )


def _copy_invoice(gen: "Generator", src: Row, **changes: object) -> Row:
    dup = {k: v for k, v in src.items() if k not in ("_lines", "invoice_id")}
    dup.update(changes)
    dup["_seq"] = len(gen.invoices)
    dup["_lines"] = [{**li} for li in src["_lines"]]
    gen.recompute(dup)
    gen.invoices.append(dup)
    return dup


def _reformat(ref: str) -> str:
    cleaned = ref.replace("-", "").replace("/", "")
    return cleaned if cleaned != ref else f"0{ref}"


def _duplicates(gen: "Generator") -> None:
    """Same invoice entered twice: exact, re-formatted reference, or other vendor master."""
    end = gen.profile.window_end
    ok = lambda inv: inv["received_date"] + timedelta(days=25) <= end  # noqa: E731
    boost = {Persona.SLOPPY: 6.0}
    sources = _choose(gen, "DUPLICATE_SUSPECTED", _eligible(gen, ok), boost)
    master = next(s for s in gen.suppliers if s["_persona"] == Persona.DUPLICATE_MASTER)
    original_id = master["_original"]["supplier_id"]
    master_sources = [i for i in _eligible(gen, ok) if i["supplier_id"] == original_id]
    cross_master = master_sources[0] if master_sources else None
    if cross_master:  # the cross-vendor-master variant occurs exactly once
        cross_master["_used"] = True
        sources = [*sources, cross_master]

    for n, src in enumerate(sources):
        variant = (
            "other_vendor_master"
            if src is cross_master
            else ("exact" if n % 2 == 0 else "reformatted_reference")
        )
        received = src["received_date"] + gen.days(5, 20)
        changes: dict[str, object] = {
            "received_date": received,
            "posting_date": received if received <= end else None,
            "status": "RECEIVED",
        }
        if variant == "reformatted_reference":
            changes["supplier_reference"] = _reformat(src["supplier_reference"])
            changes["invoice_date"] = src["invoice_date"] + gen.days(0, 3)
        if variant == "other_vendor_master":
            changes["supplier_id"] = master["supplier_id"]
        dup = _copy_invoice(gen, src, **changes)
        dup["_used"] = True
        gen.label(dup, None, "DUPLICATE_SUSPECTED", variant=variant, original_invoice=src)


def _non_po_invoices(gen: "Generator") -> None:
    """Service invoices without purchase order (maverick buying / approval needed)."""
    span = (gen.profile.window_end - gen.profile.window_start).days - 10
    suppliers = [
        s
        for s in gen.suppliers
        if s["_company"] == "DE01" and s["_persona"] in (Persona.RELIABLE, Persona.SLOPPY)
    ]
    for _ in range(gen.quota(RATES["NO_PO_REFERENCE"])):
        s = gen.rng.choice(suppliers)
        invoice_date = gen.profile.window_start + timedelta(days=gen.rng.randint(0, span))
        received = invoice_date + gen.days(1, 5)
        inv: Row = {
            "doc_type": "INVOICE",
            "supplier_id": s["supplier_id"],
            "company_code": "DE01",
            "supplier_reference": gen.next_reference(s, invoice_date),
            "invoice_date": invoice_date,
            "received_date": received,
            "posting_date": received + gen.days(0, 2),
            "currency": "EUR",
            "terms_code": s["terms_code"],
            "status": "RECEIVED",
            "payment_block": None,
            "_lines": [],
            "_used": True,
            "_seq": len(gen.invoices),
        }
        if inv["posting_date"] > gen.profile.window_end:
            inv["posting_date"] = None
        for n, (desc, (lo, hi)) in enumerate(
            gen.rng.sample(reference.SERVICE_LINES, gen.rng.randint(1, 2)), start=1
        ):
            hours = "hours" in desc
            inv["_lines"].append(
                {
                    "item_no": n,
                    "material_id": None,
                    "description": desc,
                    "quantity": Decimal(gen.rng.randint(2, 16) if hours else 1),
                    "unit_price": gen.uniform_dec(lo, hi),
                    "tax_code": reference.TAX["DE01"][0],
                }
            )
        gen.recompute(inv)
        gen.invoices.append(inv)
        for line in inv["_lines"]:
            gen.label(inv, line["item_no"], "NO_PO_REFERENCE")


def _credit_memos(gen: "Generator") -> None:
    """Historic price variances settled by a credit memo with the SAME supplier reference."""
    cutoff = gen.profile.window_end - timedelta(days=60)
    flagged: dict[int, Row] = {}
    for lb in gen.labels:
        if lb.code == "PRICE_VARIANCE" and lb.invoice["received_date"] <= cutoff:
            flagged[id(lb.invoice)] = lb.invoice
    candidates = sorted(flagged.values(), key=lambda i: i["_seq"])
    k = max(gen.profile.min_per_scenario, round(RATES["CREDIT_MEMO_SHARE"] * len(candidates)))
    for inv in gen.pick(candidates, k):
        variance_lines = [
            li for li in inv["_lines"] if li["unit_price"] > li["_po_item"]["net_price"]
        ]
        cm_date = inv["received_date"] + gen.days(7, 25)
        received = cm_date + gen.days(1, 4)
        cm: Row = {
            "doc_type": "CREDIT_MEMO",
            "supplier_id": inv["supplier_id"],
            "company_code": inv["company_code"],
            "supplier_reference": inv["supplier_reference"],
            "invoice_date": cm_date,
            "received_date": received,
            "posting_date": received,
            "currency": inv["currency"],
            "terms_code": inv["terms_code"],
            "status": "RECEIVED",
            "payment_block": None,
            "_reference": inv,
            "_lines": [],
            "_used": True,
            "_seq": len(gen.invoices),
            "_po": inv["_po"],
        }
        for n, li in enumerate(variance_lines, start=1):
            cm["_lines"].append(
                {
                    "item_no": n,
                    "_po_item": li["_po_item"],
                    "material_id": li["material_id"],
                    "description": f"Price correction: {li['description']}"[:120],
                    "quantity": li["quantity"],
                    "unit_price": price(li["unit_price"] - li["_po_item"]["net_price"]),
                    "tax_code": li["tax_code"],
                }
            )
        gen.recompute(cm)
        gen.invoices.append(cm)
        gen.label(cm, None, "HN_CREDIT_MEMO_SAME_REF", hard_negative=True, original_invoice=inv)


def _label_structural_hard_negatives(gen: "Generator") -> None:
    """Partial deliveries and repeat orders are clean by construction; label them."""
    for inv in gen.invoices:
        if inv["doc_type"] == "INVOICE" and inv.get("_shipment", {}).get("partial"):
            gen.label(
                inv,
                None,
                "HN_PARTIAL_DELIVERY",
                hard_negative=True,
                shipments=len(inv["_po"]["_shipments"]),
            )
    for po in gen.pos:
        src = po.get("_repeat_of")
        if not src or not po["_shipments"] or not src["_shipments"]:
            continue
        rep_inv = po["_shipments"][0].get("invoice")
        src_inv = src["_shipments"][0].get("invoice")
        if rep_inv and src_inv and not rep_inv["_used"] and not src_inv["_used"]:
            gen.label(
                rep_inv,
                None,
                "HN_SAME_AMOUNT_DIFFERENT_PO",
                hard_negative=True,
                original_invoice=src_inv,
            )
