"""FastAPI application factory."""

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller-supplied request ID only if it is short and harmless
# (prevents log injection through the header).
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

log = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Procurement intelligence and invoice exception management. "
            "Agents reason, services compute, humans approve, the audit log remembers."
        ),
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed", method=request.method, path=request.url.path)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    app.include_router(health_router)
    return app


app = create_app()
