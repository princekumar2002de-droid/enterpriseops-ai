"""Invoices: worklist and three-way-match detail (FR-UI-02).

Reads through the ``agent`` views so the API and the agents share one definition of
"latest matching run". All filters are bound parameters - no SQL string building
from user input.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import Engine, bindparam, text

from app.api.v1.errors import ERROR_RESPONSES, ApiError
from app.api.v1.schemas import (
    DuplicatePairOut,
    ExceptionOut,
    GoodsReceiptLine,
    InvoiceDetail,
    InvoiceLineDetail,
    InvoiceSummary,
    Page,
)
from app.db.session import get_engine

router = APIRouter(prefix="/invoices", tags=["invoices"])

MATCH_STATUSES = ("MATCHED", "WITHIN_TOLERANCE", "BLOCKED", "FLAGGED", "NOT_APPLICABLE")
InvoiceId = Annotated[str, Path(pattern=r"^\d{10}$", description="10-digit invoice number")]

_FILTERS = """
    FROM agent.invoice_overview
    WHERE (CAST(:match_status AS text) IS NULL OR match_status = :match_status)
      AND (CAST(:supplier_id AS text) IS NULL OR supplier_id = :supplier_id)
      AND (CAST(:company_code AS text) IS NULL OR company_code = :company_code)
      AND (CAST(:blocked AS boolean) IS NULL OR (payment_block IS NOT NULL) = :blocked)
"""


@router.get("", response_model=Page[InvoiceSummary], responses=ERROR_RESPONSES)
def list_invoices(
    engine: Annotated[Engine, Depends(get_engine)],
    match_status: Annotated[
        str | None, Query(pattern="^(" + "|".join(MATCH_STATUSES) + ")$")
    ] = None,
    supplier_id: Annotated[str | None, Query(max_length=10)] = None,
    company_code: Annotated[str | None, Query(pattern="^[A-Z]{2}[0-9]{2}$")] = None,
    blocked: Annotated[bool | None, Query(description="Only invoices with a payment block")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[InvoiceSummary]:
    params: dict[str, Any] = {
        "match_status": match_status,
        "supplier_id": supplier_id,
        "company_code": company_code,
        "blocked": blocked,
        "limit": limit,
        "offset": offset,
    }
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) {_FILTERS}"), params).scalar_one()
        rows = conn.execute(
            text(
                f"SELECT * {_FILTERS} ORDER BY received_date DESC, invoice_id DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings()
        items = [InvoiceSummary.model_validate(dict(r)) for r in rows]
    return Page[InvoiceSummary](items=items, total=total, limit=limit, offset=offset)


@router.get("/{invoice_id}", response_model=InvoiceDetail, responses=ERROR_RESPONSES)
def get_invoice(
    invoice_id: InvoiceId, engine: Annotated[Engine, Depends(get_engine)]
) -> InvoiceDetail:
    with engine.connect() as conn:
        header = (
            conn.execute(
                text("SELECT * FROM agent.invoice_overview WHERE invoice_id = :id"),
                {"id": invoice_id},
            )
            .mappings()
            .one_or_none()
        )
        if header is None:
            raise ApiError(404, "invoice_not_found", f"Invoice {invoice_id} does not exist.")
        lines = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM agent.invoice_line_match WHERE invoice_id = :id ORDER BY item_no"
                ),
                {"id": invoice_id},
            ).mappings()
        ]
        po_keys = sorted({(li["po_number"], li["po_item_no"]) for li in lines if li["po_number"]})
        receipts: list[dict[str, Any]] = []
        if po_keys:
            receipts = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT * FROM agent.goods_receipt_line "
                        "WHERE (po_number || '/' || po_item_no) IN :keys "
                        "ORDER BY posting_date, mat_doc, line_no"
                    ).bindparams(bindparam("keys", expanding=True)),
                    {"keys": [f"{p}/{i}" for p, i in po_keys]},
                ).mappings()
            ]
        exceptions = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM agent.open_exception WHERE invoice_id = :id "
                    "ORDER BY item_no NULLS FIRST, code"
                ),
                {"id": invoice_id},
            ).mappings()
        ]
        pairs = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM agent.duplicate_pair "
                    "WHERE invoice_id = :id OR candidate_invoice_id = :id ORDER BY score DESC"
                ),
                {"id": invoice_id},
            ).mappings()
        ]
    return InvoiceDetail.model_validate(
        {
            **dict(header),
            "lines": [InvoiceLineDetail.model_validate(li) for li in lines],
            "goods_receipts": [GoodsReceiptLine.model_validate(r) for r in receipts],
            "exceptions": [ExceptionOut.model_validate(e) for e in exceptions],
            "duplicate_pairs": [DuplicatePairOut.model_validate(p) for p in pairs],
        }
    )
