"""API version 1 - mounted under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import exceptions, invoices, kpis, matching

router = APIRouter(prefix="/api/v1")
for module in (invoices, exceptions, kpis, matching):
    router.include_router(module.router)
