"""Health endpoints.

- ``/health/live``  - the process is running (for container restarts).
- ``/health/ready`` - the API can serve traffic: DB reachable, pgvector installed,
  migrations applied. Returns 503 otherwise (for load balancers / compose).
"""

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.session import get_engine

router = APIRouter(prefix="/health", tags=["health"])
log = structlog.get_logger(__name__)


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessChecks(BaseModel):
    database: bool
    pgvector_version: str | None
    migration_revision: str | None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


@router.get("/live", response_model=LivenessResponse)
def live(settings: Annotated[Settings, Depends(get_settings)]) -> LivenessResponse:
    return LivenessResponse(service=settings.app_name, version=settings.app_version)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A dependency is not ready"}},
)
def ready(response: Response, engine: Annotated[Engine, Depends(get_engine)]) -> ReadinessResponse:
    checks = ReadinessChecks(database=False, pgvector_version=None, migration_revision=None)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            checks.database = True
            checks.pgvector_version = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()
            has_alembic = conn.execute(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            ).scalar_one()
            if has_alembic:
                checks.migration_revision = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        # Log the error class only: driver messages can contain host/user details.
        log.warning("readiness_check_failed", error_type=type(exc).__name__)

    is_ready = (
        checks.database
        and checks.pgvector_version is not None
        and checks.migration_revision is not None
    )
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
