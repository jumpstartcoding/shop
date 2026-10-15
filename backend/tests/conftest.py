"""Tests run against a real Postgres database (TEST_DATABASE_URL), migrated with Alembic,
so constraints, locking, and numbering behave exactly as in production."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/shop_test"
)
os.environ["DATABASE_URL"] = TEST_DB
os.environ["ENVIRONMENT"] = "test"
os.environ["ORIGIN_SECRET"] = ""

from app.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import reset_engine  # noqa: E402

PASSWORD = "correct-horse-battery"
EMAIL = "owner@example.com"

TABLES = [
    "payments",
    "invoice_items",
    "invoices",
    "estimate_items",
    "estimates",
    "appointments",
    "work_order_items",
    "work_orders",
    "vehicles",
    "customers",
    "services",
    "audit_logs",
    "sessions",
    "users",
    "businesses",
    "document_counters",
]


@pytest.fixture(scope="session", autouse=True)
def database():
    get_settings.cache_clear()
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()
    from app.tasks import migrate

    migrate()
    reset_engine()
    yield


@pytest.fixture(autouse=True)
def clean(database):
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        conn.execute(
            text(
                "INSERT INTO users (email, name, password_hash, role, is_active, "
                "failed_login_count) VALUES (:e, 'Owner', :h, 'owner', true, 0)"
            ),
            {"e": EMAIL, "h": hash_password(PASSWORD)},
        )
        conn.execute(
            text(
                "INSERT INTO businesses (name, hours, social_links, timezone, tax_rate, tax_labor, "
                "tax_parts, tax_fees, default_labor_rate_cents, default_parts_markup_pct, "
                "invoice_prefix, estimate_prefix, work_order_prefix, invoice_due_days, "
                "estimate_valid_days, authorization_statement, allow_typed_signature, offers_towing) "
                "VALUES ('Test Shop', '{}', '{}', 'America/New_York', 8.0, false, true, false, "
                "10000, 50, 'INV', 'EST', 'WO', 0, 30, 'I authorize.', true, false)"
            )
        )
    engine.dispose()
    yield


@pytest.fixture
def anon():
    from app.main import create_app

    # https base URL so the Secure session cookie is sent back, as in production.
    with TestClient(create_app(), base_url="https://testserver") as c:
        yield c


@pytest.fixture
def client(anon):
    r = anon.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    anon.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return anon


@pytest.fixture
def customer(client):
    r = client.post(
        "/api/customers",
        json={
            "first_name": "John",
            "last_name": "Smith",
            "phone": "(555) 010-0101",
            "email": "john@example.com",
            "vehicle": {
                "year": 2018,
                "make": "Honda",
                "model": "Accord",
                "vin": "1hgcv1f13ja000001",
                "license_plate": "abc 123",
                "mileage": 61000,
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def vehicle(customer):
    return customer["vehicles"][0]
