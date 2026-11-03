"""Uniform error envelope for all API errors.

{"error": {"code": "not_found", "message": "...", "details": [...], "request_id": "..."}}
"""

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

_CODES = {400: "bad_request", 404: "not_found", 409: "conflict", 422: "validation_error"}


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[Any] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(HTTPException):
    """Raise with a machine-readable code, e.g. ApiError(404, "invoice_not_found", "...")."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def _envelope(
    request: Request, status: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            request_id=getattr(request.state, "request_id", None),
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = getattr(exc, "code", None) or _CODES.get(exc.status_code, "error")
        return _envelope(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"location": list(err["loc"]), "message": err["msg"]} for err in exc.errors()]
        return _envelope(request, 422, "validation_error", "Invalid request parameters.", details)


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Not found"},
    422: {"model": ErrorResponse, "description": "Invalid parameters"},
}
