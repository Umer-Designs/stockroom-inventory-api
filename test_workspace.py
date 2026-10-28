import json

import pytest
from fastapi.testclient import TestClient

import app

SESSION_A = {"X-Demo-Session": "a" * 64}
SESSION_B = {"X-Demo-Session": "b" * 64}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB", str(tmp_path / "workspace.db"))
    return TestClient(app.app)


def test_session_required(client):
    assert client.get("/invoices").status_code == 401
    assert (
        client.get("/invoices", headers={"X-Demo-Session": "short"}).status_code == 401
    )


def test_invoice_lifecycle(client):
    payload = {"customer": "Demo", "amount": 125050, "date": "2026-10-28"}
    created = client.post("/invoices", json=payload, headers=SESSION_A)
    assert created.status_code == 201
    invoice = created.json()
    assert client.get("/invoices", headers=SESSION_A).json()["items"][0]["paid"] == 0
    paid = client.patch(f"/invoices/{invoice['id']}/paid", headers=SESSION_A)
    assert paid.json()["items"][0]["paid"] == 125050
    # Updating twice is idempotent.
    assert (
        client.patch(f"/invoices/{invoice['id']}/paid", headers=SESSION_A).json()
        == paid.json()
    )


def test_session_isolation(client):
    row = client.post(
        "/invoices",
        json={"customer": "A", "amount": 100, "date": "2026-10-28"},
        headers=SESSION_A,
    ).json()
    assert client.get("/invoices", headers=SESSION_B).json()["items"] == []
    assert (
        client.patch(f"/invoices/{row['id']}/paid", headers=SESSION_B).status_code
        == 404
    )
    client.post("/invoices/reset", headers=SESSION_B)
    assert len(client.get("/invoices", headers=SESSION_A).json()["items"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"amount": -1},
        {"amount": 1.1},
        {"customer": " "},
        {"date": "2026-02-30"},
        {"paid": 100},
    ],
)
def test_invoice_validation(client, change):
    payload = {"customer": "Demo", "amount": 100, "date": "2026-10-28", **change}
    assert client.post("/invoices", json=payload, headers=SESSION_A).status_code == 422


def test_reset_only_replaces_own_records(client):
    for _ in range(2):
        assert (
            len(client.post("/invoices/reset", headers=SESSION_A).json()["items"]) == 5
        )
    assert client.get("/invoices", headers=SESSION_B).json()["items"] == []


def test_python_reconciliation(client):
    source = 'invoice_id,customer,amount,paid\nA,"Demo, Studio",1.01,0.29\nA,Duplicate,10,0\n'
    result = client.post("/reconcile", json={"csv": source})
    assert result.status_code == 200
    assert result.json()["totals"] == {"invoices": 1, "due_cents": 72}
    assert result.json()["rejected"][0]["line"] == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"csv": "bad,header\na,b"},
        {"csv": 12},
        [],
        {"csv": 'invoice_id,customer,amount,paid\nA,"broken,1,0'},
    ],
)
def test_invalid_reconciliation(client, payload):
    assert client.post("/reconcile", json=payload).status_code == 422


def test_reconciliation_size_limit(client):
    assert (
        client.post(
            "/reconcile", content=json.dumps({"csv": "x" * 150_000})
        ).status_code
        == 413
    )


def test_cors(client):
    response = client.options(
        "/invoices",
        headers={
            "Origin": "https://umer-designs.github.io",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Demo-Session",
        },
    )
    assert (
        response.headers["access-control-allow-origin"]
        == "https://umer-designs.github.io"
    )
    assert (
        "access-control-allow-origin"
        not in client.get(
            "/health", headers={"Origin": "https://untrusted.example"}
        ).headers
    )
