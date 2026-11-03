"""Response models for API v1. Money and quantities are Decimals (serialized as strings)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(description="Total rows matching the filters")
    limit: int
    offset: int


class InvoiceSummary(BaseModel):
    invoice_id: str
    doc_type: str
    supplier_id: str
    supplier_name: str
    company_code: str
    supplier_reference: str
    invoice_date: date
    received_date: date
    currency: str
    gross_amount: Decimal
    payment_status: str
    payment_block: str | None
    match_status: str | None = Field(description="Latest completed matching run; null if none")
    exception_count: int | None
    amount_at_risk: Decimal | None


class InvoiceLineDetail(BaseModel):
    item_no: int
    po_number: str | None
    po_item_no: int | None
    material_id: str | None
    description: str
    invoiced_qty: Decimal
    invoice_price: Decimal
    net_amount: Decimal
    po_qty: Decimal | None
    po_price: Decimal | None
    uom: str | None
    promised_delivery_date: date | None
    contract_id: str | None
    net_received_qty: Decimal | None
    previously_invoiced_qty: Decimal | None
    price_variance_amount: Decimal | None
    price_variance_pct: Decimal | None
    price_outcome: str | None
    qty_outcome: str | None


class GoodsReceiptLine(BaseModel):
    mat_doc: str
    line_no: int
    po_number: str
    po_item_no: int
    movement_type: str
    quantity: Decimal
    posting_date: date
    ref_mat_doc: str | None


class ExceptionOut(BaseModel):
    exception_id: int
    invoice_id: str
    item_no: int | None
    code: str
    severity: str
    blocks_payment: bool
    amount_at_risk: Decimal
    currency: str
    details: dict[str, Any]
    status: str
    supplier_id: str
    supplier_name: str
    invoice_date: date
    payment_status: str


class DuplicatePairOut(BaseModel):
    invoice_id: str
    candidate_invoice_id: str
    score: Decimal
    is_flagged: bool
    features: dict[str, Any]


class InvoiceDetail(InvoiceSummary):
    net_amount: Decimal
    tax_amount: Decimal
    terms_code: str
    posting_date: date | None
    reference_invoice_id: str | None
    lines: list[InvoiceLineDetail]
    goods_receipts: list[GoodsReceiptLine]
    exceptions: list[ExceptionOut]
    duplicate_pairs: list[DuplicatePairOut]


class RunSummaryOut(BaseModel):
    run_id: int
    engine_version: str
    invoice_count: int
    exception_count: int
    blocked_invoices: int | None = None
    blocked_unpaid_invoices: int | None = None
    finished_at: datetime | None = None
    counts_by_code: dict[str, int]


class KpiDefinitionOut(BaseModel):
    kpi_id: str
    name: str
    unit: str
    description: str
    formula: str
    supports_supplier_breakdown: bool


class KpiBreakdownRow(BaseModel):
    key: str
    label: str | None
    value: Decimal | None
    n: int


class KpiValueOut(BaseModel):
    kpi_id: str
    name: str
    unit: str
    company_code: str
    date_from: date | None
    date_to: date | None
    value: Decimal | None
    n: int = Field(description="Sample size the value is based on")
    breakdown: list[KpiBreakdownRow] = []
