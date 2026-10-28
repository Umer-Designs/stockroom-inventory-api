"""Shared schema and transactions for SQLite and PostgreSQL."""

from contextlib import contextmanager
from functools import lru_cache
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    func,
)

metadata = MetaData()
products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sku", String(40), unique=True, nullable=False),
    Column("name", String(100), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("price_cents", BigInteger, nullable=False),
    CheckConstraint("quantity >= 0"),
    CheckConstraint("price_cents >= 0"),
)
movements = Table(
    "movements",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False),
    Column("delta", Integer, nullable=False),
    Column("created_at", DateTime, server_default=func.now()),
)
invoices = Table(
    "demo_invoices",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("owner", String(64), nullable=False, index=True),
    Column("customer", String(100), nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("paid", BigInteger, nullable=False),
    Column("date", Date, nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    CheckConstraint("amount > 0 AND paid >= 0 AND paid <= amount"),
)


def database_url(value):
    if value.startswith(("postgres://", "postgresql://")):
        return "postgresql+psycopg://" + value.split("://", 1)[1]
    return value if "://" in value else "sqlite:///" + value


@lru_cache(maxsize=8)
def engine_for(value):
    url = database_url(value)
    options = {"pool_pre_ping": True, "hide_parameters": True}
    options["connect_args"] = (
        {"check_same_thread": False, "timeout": 10}
        if url.startswith("sqlite:")
        else {"connect_timeout": 10}
    )
    engine = create_engine(url, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    return engine


@contextmanager
def transaction(value):
    with engine_for(value).begin() as connection:
        yield connection
