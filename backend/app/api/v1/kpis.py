"""KPI catalog and values (FR-AN-01, FR-AN-02)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import Engine

from app.api.v1.errors import ERROR_RESPONSES, ApiError
from app.api.v1.schemas import KpiBreakdownRow, KpiDefinitionOut, KpiValueOut
from app.db.session import get_engine
from app.services import kpis

router = APIRouter(prefix="/kpis", tags=["kpis"])


@router.get("", response_model=list[KpiDefinitionOut])
def list_kpis() -> list[KpiDefinitionOut]:
    return [
        KpiDefinitionOut(
            kpi_id=k.kpi_id,
            name=k.name,
            unit=k.unit,
            description=k.description,
            formula=k.formula,
            supports_supplier_breakdown=k.sql_by_supplier is not None,
        )
        for k in kpis.KPIS.values()
    ]


@router.get(
    "/{kpi_id}",
    response_model=KpiValueOut,
    responses={**ERROR_RESPONSES, 400: ERROR_RESPONSES[422]},
)
def get_kpi(
    kpi_id: Annotated[str, Path(max_length=64)],
    engine: Annotated[Engine, Depends(get_engine)],
    company_code: Annotated[str, Query(pattern="^[A-Z]{2}[0-9]{2}$")] = "DE01",
    date_from: date | None = None,
    date_to: date | None = None,
    group_by: Annotated[str | None, Query(pattern="^supplier$")] = None,
) -> KpiValueOut:
    if kpi_id not in kpis.KPIS:
        raise ApiError(404, "kpi_not_found", f"Unknown KPI '{kpi_id}'. See GET /api/v1/kpis.")
    if date_from and date_to and date_from > date_to:
        raise ApiError(400, "invalid_period", "date_from must not be after date_to.")
    definition = kpis.KPIS[kpi_id]
    try:
        with engine.connect() as conn:
            result = kpis.compute(
                conn,
                kpi_id,
                company_code=company_code,
                date_from=date_from,
                date_to=date_to,
                by_supplier=group_by == "supplier",
            )
    except kpis.BreakdownNotSupportedError as exc:
        raise ApiError(
            400, "breakdown_not_supported", f"KPI '{kpi_id}' has no supplier breakdown."
        ) from exc
    return KpiValueOut(
        kpi_id=kpi_id,
        name=definition.name,
        unit=definition.unit,
        company_code=company_code,
        date_from=date_from,
        date_to=date_to,
        value=result.value,
        n=result.n,
        breakdown=[KpiBreakdownRow(**b.__dict__) for b in result.breakdown],
    )
