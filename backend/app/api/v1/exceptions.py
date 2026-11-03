"""Exception worklist of the latest matching run, largest amount at risk first."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine, text

from app.api.v1.errors import ERROR_RESPONSES
from app.api.v1.schemas import ExceptionOut, Page
from app.db.session import get_engine
from app.services.matching.engine import BLOCKING

router = APIRouter(prefix="/exceptions", tags=["exceptions"])

_FILTERS = """
    FROM agent.open_exception
    WHERE (CAST(:code AS text) IS NULL OR code = :code)
      AND (CAST(:severity AS text) IS NULL OR severity = :severity)
      AND (CAST(:supplier_id AS text) IS NULL OR supplier_id = :supplier_id)
      AND (CAST(:blocks_payment AS boolean) IS NULL OR blocks_payment = :blocks_payment)
      AND (CAST(:unpaid_only AS boolean) IS NOT TRUE OR payment_status <> 'PAID')
"""


@router.get("", response_model=Page[ExceptionOut], responses=ERROR_RESPONSES)
def list_exceptions(
    engine: Annotated[Engine, Depends(get_engine)],
    code: Annotated[str | None, Query(pattern="^(" + "|".join(BLOCKING) + ")$")] = None,
    severity: Annotated[str | None, Query(pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")] = None,
    supplier_id: Annotated[str | None, Query(max_length=10)] = None,
    blocks_payment: bool | None = None,
    unpaid_only: Annotated[bool, Query(description="Hide exceptions on paid invoices")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ExceptionOut]:
    params: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "supplier_id": supplier_id,
        "blocks_payment": blocks_payment,
        "unpaid_only": unpaid_only,
        "limit": limit,
        "offset": offset,
    }
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) {_FILTERS}"), params).scalar_one()
        rows = conn.execute(
            text(
                f"SELECT * {_FILTERS} ORDER BY amount_at_risk DESC, exception_id "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings()
        items = [ExceptionOut.model_validate(dict(r)) for r in rows]
    return Page[ExceptionOut](items=items, total=total, limit=limit, offset=offset)
