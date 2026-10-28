"""Inventory, session-isolated invoice demo and CSV reconciliation API."""

import csv
import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from database import invoices, movements, products, transaction
from reconciliation import reconcile_csv

DB = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PATH", "inventory.db")
app = FastAPI(title="Stockroom and Ledger API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "ALLOWED_ORIGINS",
        "https://umer-designs.github.io,http://127.0.0.1:8765,http://127.0.0.1:5173",
    ).split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Demo-Session", "X-API-Key"],
)


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, _error):
    return JSONResponse(
        {"detail": "Database unavailable. Please try again shortly."}, status_code=503
    )


def db():
    return transaction(DB)


def authorize(x_api_key: str = Header(default="")):
    expected = os.getenv("INVENTORY_API_KEY", "")
    if not expected:
        raise HTTPException(503, "Write endpoints have not been configured")
    if not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid API key")


def demo_owner(x_demo_session: str = Header(default="")):
    if not re.fullmatch(r"[a-f0-9]{64}", x_demo_session):
        raise HTTPException(401, "A valid demo session is required")
    return hashlib.sha256(x_demo_session.encode()).hexdigest()


class Product(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    sku: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=0, le=1_000_000, strict=True)
    price_cents: int = Field(ge=0, le=1_000_000_000, strict=True)


class Movement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delta: int = Field(strict=True, ge=-1_000_000, le=1_000_000)

    @field_validator("delta")
    @classmethod
    def nonzero(cls, value):
        if value == 0:
            raise ValueError("Movement must be nonzero")
        return value


class InvoiceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    customer: str = Field(min_length=1, max_length=100)
    amount: int = Field(gt=0, le=1_000_000_000, strict=True)
    date: date


@app.get("/health")
def health():
    with db() as connection:
        connection.execute(select(1))
    return {"status": "ok"}


@app.get("/products")
def list_products(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    match = (
        func.strpos(func.lower(products.c.name), q.lower()) > 0
        if DB.startswith("postgres")
        else func.instr(func.lower(products.c.name), q.lower()) > 0
    )
    with db() as connection:
        rows = (
            connection.execute(
                select(products)
                .where(match)
                .order_by(products.c.id)
                .limit(limit)
                .offset(offset)
            )
            .mappings()
            .all()
        )
        total = connection.scalar(
            select(func.count()).select_from(products).where(match)
        )
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/products", status_code=201, dependencies=[Depends(authorize)])
def create_product(product: Product):
    try:
        with db() as connection:
            identifier = connection.execute(
                insert(products).values(**product.model_dump()).returning(products.c.id)
            ).scalar_one()
        return {"id": identifier, **product.model_dump()}
    except IntegrityError:
        raise HTTPException(409, "SKU already exists")


@app.get("/products/{product_id}")
def get_product(product_id: int):
    with db() as connection:
        row = (
            connection.execute(select(products).where(products.c.id == product_id))
            .mappings()
            .first()
        )
    if not row:
        raise HTTPException(404, "Product not found")
    return dict(row)


@app.post("/products/{product_id}/movements", dependencies=[Depends(authorize)])
def move_stock(product_id: int, movement: Movement):
    with db() as connection:
        # Condition and update run together, preventing concurrent overdrafts.
        row = (
            connection.execute(
                update(products)
                .where(
                    products.c.id == product_id,
                    products.c.quantity + movement.delta >= 0,
                    products.c.quantity + movement.delta <= 1_000_000,
                )
                .values(quantity=products.c.quantity + movement.delta)
                .returning(*products.c)
            )
            .mappings()
            .first()
        )
        if not row:
            exists = connection.scalar(
                select(products.c.id).where(products.c.id == product_id)
            )
            raise HTTPException(
                409 if exists else 404,
                "Stock adjustment outside permitted range"
                if exists
                else "Product not found",
            )
        connection.execute(
            insert(movements).values(product_id=product_id, delta=movement.delta)
        )
        return dict(row)


@app.get("/movements")
def history(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    with db() as connection:
        return {
            "items": [
                dict(row)
                for row in connection.execute(
                    select(movements)
                    .order_by(movements.c.id.desc())
                    .limit(limit)
                    .offset(offset)
                ).mappings()
            ]
        }


@app.get("/summary")
def summary():
    with db() as connection:
        row = (
            connection.execute(
                select(
                    func.count().label("products"),
                    func.coalesce(func.sum(products.c.quantity), 0).label("units"),
                    func.coalesce(
                        func.sum(products.c.quantity * products.c.price_cents), 0
                    ).label("value_cents"),
                ).select_from(products)
            )
            .mappings()
            .one()
        )
    return dict(row)


def invoice_rows(connection, owner):
    columns = [
        invoices.c[name] for name in ["id", "customer", "amount", "paid", "date"]
    ]
    return [
        dict(row)
        for row in connection.execute(
            select(*columns)
            .where(invoices.c.owner == owner)
            .order_by(invoices.c.date.desc(), invoices.c.id)
        ).mappings()
    ]


@app.get("/invoices")
def list_invoices(owner: str = Depends(demo_owner)):
    with db() as connection:
        return {"items": invoice_rows(connection, owner)}


@app.post("/invoices", status_code=201)
def create_invoice(invoice: InvoiceInput, owner: str = Depends(demo_owner)):
    record = {"id": str(uuid.uuid4()), **invoice.model_dump(), "paid": 0}
    with db() as connection:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
        connection.execute(delete(invoices).where(invoices.c.created_at < cutoff))
        count = connection.scalar(
            select(func.count()).select_from(invoices).where(invoices.c.owner == owner)
        )
        if count >= 100:
            raise HTTPException(
                409, "Demo limit reached: reset before adding more invoices"
            )
        connection.execute(insert(invoices).values(**record, owner=owner))
    return record


@app.patch("/invoices/{invoice_id}/paid")
def mark_paid(invoice_id: str, owner: str = Depends(demo_owner)):
    with db() as connection:
        changed = connection.execute(
            update(invoices)
            .where(invoices.c.id == invoice_id, invoices.c.owner == owner)
            .values(paid=invoices.c.amount)
            .returning(invoices.c.id)
        ).scalar_one_or_none()
        if changed is None:
            raise HTTPException(404, "Invoice not found")
        return {"items": invoice_rows(connection, owner)}


@app.post("/invoices/reset")
def reset_invoices(owner: str = Depends(demo_owner)):
    samples = [
        ("Acme Studio", 125000, 50000, "2026-10-05"),
        ("North Workshop", 89999, 89999, "2026-10-12"),
        ("Field Collective", 34050, 0, "2026-09-18"),
        ("Paper & Form", 178000, 178000, "2026-10-20"),
        ("Harbor Design", 64000, 0, "2026-08-29"),
    ]
    with db() as connection:
        connection.execute(delete(invoices).where(invoices.c.owner == owner))
        connection.execute(
            insert(invoices),
            [
                {
                    "id": str(uuid.uuid4()),
                    "owner": owner,
                    "customer": name,
                    "amount": amount,
                    "paid": paid,
                    "date": date.fromisoformat(issued),
                }
                for name, amount, paid, issued in samples
            ],
        )
        return {"items": invoice_rows(connection, owner)}


@app.post("/reconcile")
async def reconcile(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 150_000:
            raise HTTPException(413, "Request exceeds 150 KB limit")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("csv"), str):
            raise ValueError("Provide a JSON object with a csv text field")
        return await run_in_threadpool(reconcile_csv, payload["csv"].encode("utf-8"))
    except (ValueError, UnicodeError, csv.Error) as error:
        raise HTTPException(422, str(error))
