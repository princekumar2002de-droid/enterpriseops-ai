"""API v1 against the test database (small dataset + one matching run)."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.config import Environment
from app.db.session import get_engine
from app.main import app
from app.services import kpis
from data_generation.generator import generate
from data_generation.loader import load
from data_generation.model import PROFILES, Dataset

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return generate(42, PROFILES["small"])


@pytest.fixture(scope="module")
def client(migrated_engine: Engine, dataset: Dataset) -> Iterator[TestClient]:
    load(migrated_engine, dataset, Environment.TEST)
    app.dependency_overrides[get_engine] = lambda: migrated_engine
    with TestClient(app) as c:
        assert c.post("/api/v1/matching/runs").status_code == 201
        yield c
    app.dependency_overrides.clear()


def test_latest_run_summary(client: TestClient) -> None:
    body = client.get("/api/v1/matching/runs/latest").json()
    assert body["exception_count"] == sum(body["counts_by_code"].values()) > 0


def test_invoice_list_filters_and_paging(client: TestClient) -> None:
    page = client.get("/api/v1/invoices", params={"limit": 5}).json()
    assert len(page["items"]) == 5 and page["total"] > 5
    blocked = client.get("/api/v1/invoices", params={"blocked": "true", "limit": 200}).json()
    assert blocked["total"] > 0
    assert all(i["payment_block"] == "R" for i in blocked["items"])
    statuses = client.get("/api/v1/invoices", params={"match_status": "MATCHED"}).json()
    assert {i["match_status"] for i in statuses["items"]} == {"MATCHED"}


def test_invoice_detail_shows_three_way_evidence(client: TestClient) -> None:
    exc = client.get("/api/v1/exceptions", params={"code": "QTY_VARIANCE", "limit": 1}).json()
    invoice_id = exc["items"][0]["invoice_id"]
    detail = client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert detail["match_status"] == "BLOCKED"
    assert "QTY_VARIANCE" in [e["code"] for e in detail["exceptions"]]
    flagged = next(li for li in detail["lines"] if li["qty_outcome"] == "QTY_VARIANCE")
    assert Decimal(flagged["invoiced_qty"]) > Decimal(flagged["net_received_qty"])
    assert detail["goods_receipts"], "receipts for the PO items are included"


def test_duplicate_detail_links_original(client: TestClient) -> None:
    exc = client.get("/api/v1/exceptions", params={"code": "DUPLICATE_SUSPECTED"}).json()
    item = exc["items"][0]
    detail = client.get(f"/api/v1/invoices/{item['invoice_id']}").json()
    pair = next(p for p in detail["duplicate_pairs"] if p["is_flagged"])
    assert pair["candidate_invoice_id"] == item["details"]["original_invoice_id"]


def test_exceptions_sorted_by_amount_at_risk(client: TestClient) -> None:
    items = client.get("/api/v1/exceptions", params={"limit": 50}).json()["items"]
    amounts = [Decimal(i["amount_at_risk"]) for i in items]
    assert amounts == sorted(amounts, reverse=True)


@pytest.mark.parametrize(
    ("url", "status", "code"),
    [
        ("/api/v1/invoices/123", 422, "validation_error"),
        ("/api/v1/invoices/9999999999", 404, "invoice_not_found"),
        ("/api/v1/kpis/unknown", 404, "kpi_not_found"),
        ("/api/v1/kpis/late_payment_rate?group_by=supplier", 400, "breakdown_not_supported"),
        (
            "/api/v1/kpis/exception_rate?date_from=2026-02-01&date_to=2026-01-01",
            400,
            "invalid_period",
        ),
        ("/api/v1/exceptions?severity=EXTREME", 422, "validation_error"),
        ("/api/v1/invoices?limit=1000", 422, "validation_error"),
    ],
)
def test_error_envelope(client: TestClient, url: str, status: int, code: str) -> None:
    response = client.get(url)
    assert response.status_code == status
    body = response.json()["error"]
    assert body["code"] == code
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_kpi_catalog_and_every_kpi_computes(client: TestClient) -> None:
    catalog = client.get("/api/v1/kpis").json()
    assert {k["kpi_id"] for k in catalog} == set(kpis.KPIS)
    for kpi in catalog:
        body = client.get(f"/api/v1/kpis/{kpi['kpi_id']}").json()
        assert body["n"] >= 0, kpi["kpi_id"]


def test_kpis_match_independent_python_calculation(client: TestClient, dataset: Dataset) -> None:
    """Re-compute two KPIs from the raw generated rows and compare with the SQL result."""
    invoices = [
        h
        for h in dataset.tables["erp.invoice_header"]
        if h["doc_type"] == "INVOICE" and h["company_code"] == "DE01"
    ]
    po_invoices = {
        i["invoice_id"] for i in dataset.tables["erp.invoice_item"] if i["po_number"] is not None
    }
    expected_non_po = round(
        Decimal(100)
        * sum(1 for h in invoices if h["invoice_id"] not in po_invoices)
        / len(invoices),
        2,
    )
    body = client.get("/api/v1/kpis/non_po_invoice_share").json()
    assert Decimal(body["value"]) == expected_non_po
    assert body["n"] == len(invoices)

    first_gr: dict[tuple[str, int], tuple[date, Decimal]] = {}
    for g in sorted(
        dataset.tables["erp.goods_receipt"], key=lambda g: (g["posting_date"], g["mat_doc"])
    ):
        if g["movement_type"] == "101":
            first_gr.setdefault(
                (g["po_number"], g["po_item_no"]), (g["posting_date"], g["quantity"])
            )
    company = {
        h["po_number"]: h["company_code"] for h in dataset.tables["erp.purchase_order_header"]
    }
    hits = [
        first_gr[(i["po_number"], i["item_no"])][0] <= i["delivery_date"]
        and first_gr[(i["po_number"], i["item_no"])][1] >= i["quantity"]
        for i in dataset.tables["erp.purchase_order_item"]
        if (i["po_number"], i["item_no"]) in first_gr and company[i["po_number"]] == "DE01"
    ]
    otif = client.get("/api/v1/kpis/supplier_otif").json()
    assert Decimal(otif["value"]) == round(Decimal(100) * sum(hits) / len(hits), 2)


def test_supplier_breakdown(client: TestClient) -> None:
    body = client.get(
        "/api/v1/kpis/avg_delivery_delay_days", params={"group_by": "supplier"}
    ).json()
    values = [Decimal(b["value"]) for b in body["breakdown"]]
    assert values == sorted(values, reverse=True) and body["breakdown"][0]["label"]
