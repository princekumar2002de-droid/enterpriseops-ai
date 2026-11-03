"""Matching runs: trigger a run and read the latest run summary.

Runs are synchronous (about 1-2 s for the full dataset). Authentication arrives in
Task 5; until then the API is bound to localhost only (docker-compose).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import Engine, text

from app.api.v1.errors import ERROR_RESPONSES, ApiError
from app.api.v1.schemas import RunSummaryOut
from app.db.session import get_engine
from app.services.matching.repository import execute_run

router = APIRouter(prefix="/matching", tags=["matching"])


@router.post("/runs", response_model=RunSummaryOut, status_code=status.HTTP_201_CREATED)
def start_run(engine: Annotated[Engine, Depends(get_engine)]) -> RunSummaryOut:
    summary = execute_run(engine, triggered_by="api")
    return RunSummaryOut(**summary.__dict__)


@router.get("/runs/latest", response_model=RunSummaryOut, responses=ERROR_RESPONSES)
def latest_run(engine: Annotated[Engine, Depends(get_engine)]) -> RunSummaryOut:
    with engine.connect() as conn:
        run = conn.execute(text("SELECT * FROM agent.latest_match_run")).mappings().one_or_none()
        if run is None:
            raise ApiError(
                404, "no_match_run", "No completed matching run yet. POST /api/v1/matching/runs."
            )
        counts = {
            row.code: row.n
            for row in conn.execute(
                text(
                    "SELECT code, count(*) AS n FROM agent.open_exception "
                    "GROUP BY code ORDER BY code"
                )
            )
        }
    return RunSummaryOut(
        run_id=run["run_id"],
        engine_version=run["engine_version"],
        invoice_count=run["invoice_count"],
        exception_count=run["exception_count"],
        finished_at=run["finished_at"],
        counts_by_code=counts,
    )
