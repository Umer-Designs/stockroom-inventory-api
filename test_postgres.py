"""Run with TEST_POSTGRES_URL pointing to a disposable PostgreSQL database."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app
from database import invoices, movements, products, transaction


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="Disposable PostgreSQL URL not configured",
)
def test_postgres_persistence_and_transactions(monkeypatch):
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setattr(app, "DB", url)
    monkeypatch.setenv("INVENTORY_API_KEY", "integration-secret")
    headers = {"X-API-Key": "integration-secret"}
    session = {"X-Demo-Session": uuid.uuid4().hex + uuid.uuid4().hex}
    product_id = None
    with TestClient(app.app) as client:
        created = client.post(
            "/products",
            json={
                "sku": uuid.uuid4().hex,
                "name": "Integration sample",
                "quantity": 5,
                "price_cents": 101,
            },
            headers=headers,
        )
        assert created.status_code == 201
        product_id = created.json()["id"]
        try:
            assert client.get("/products?q=Integration").json()["total"] >= 1
            assert (
                client.post(
                    f"/products/{product_id}/movements",
                    json={"delta": -6},
                    headers=headers,
                ).status_code
                == 409
            )
            assert client.get(f"/products/{product_id}").json()["quantity"] == 5
            assert (
                client.post(
                    f"/products/{product_id}/movements",
                    json={"delta": -2},
                    headers=headers,
                ).json()["quantity"]
                == 3
            )
            record = client.post(
                "/invoices",
                json={
                    "customer": "Postgres sample",
                    "amount": 125,
                    "date": "2026-10-28",
                },
                headers=session,
            ).json()
            with TestClient(app.app) as second_client:
                assert (
                    second_client.get("/invoices", headers=session).json()["items"][0][
                        "id"
                    ]
                    == record["id"]
                )
            with transaction(url) as connection:
                assert (
                    connection.scalar(
                        select(products.c.quantity).where(products.c.id == product_id)
                    )
                    == 3
                )
        finally:
            with transaction(url) as connection:
                connection.execute(
                    delete(movements).where(movements.c.product_id == product_id)
                )
                connection.execute(delete(products).where(products.c.id == product_id))
                connection.execute(
                    delete(invoices).where(
                        invoices.c.owner == app.demo_owner(session["X-Demo-Session"])
                    )
                )
