"""Tests run against a real Postgres database (TEST_DATABASE_URL), migrated with Alembic,
so constraints, locking, and numbering behave exactly as in production."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/shop_test"
)
os.environ["DATABASE_URL"] = TEST_DB
os.environ["ENVIRONMENT"] = "test"
os.environ["ORIGIN_SECRET"] = ""
FILES_DIR = tempfile.mkdtemp(prefix="shop-test-files-")
os.environ["FILES_DIR"] = FILES_DIR
os.environ["STORAGE_BACKEND"] = "local"
os.environ["EMAIL_BACKEND"] = "file"
os.environ["PUBLIC_BASE_URL"] = "https://shop.example"
# Payments are "configured" in tests, but every Stripe call goes to FakeGateway below.
os.environ["STRIPE_SECRET_KEY"] = "sk_test_not_a_real_key"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_secret"

from app.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import reset_engine  # noqa: E402

PASSWORD = "correct-horse-battery"
EMAIL = "owner@example.com"

TABLES = [
    "service_records",
    "photos",
    "inspection_items",
    "inspections",
    "stripe_events",
    "authorizations",
    "access_tokens",
    "document_versions",
    "inquiries",
    "email_templates",
    "email_log",
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
def outbox():
    """Emails 'sent' during the test, as parsed messages."""
    import email
    from email import policy

    box = Path(FILES_DIR) / "outbox"
    shutil.rmtree(box, ignore_errors=True)

    def read():
        if not box.exists():
            return []
        return [
            email.message_from_bytes(p.read_bytes(), policy=policy.default)
            for p in sorted(box.glob("*.eml"), key=lambda p: p.stat().st_mtime)
        ]

    return read


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


class FakeGateway:
    """Stands in for Stripe. Records calls; can be told to fail."""

    def __init__(self):
        self.checkouts = []
        self.refunds = []
        self.fail_refunds = False
        self.endpoints = []

    def create_checkout(self, **kw):
        from app.core.payments import CheckoutSession

        self.checkouts.append(kw)
        n = len(self.checkouts)
        return CheckoutSession(id=f"cs_test_{n}", url=f"https://checkout.stripe.test/c/{n}")

    def refund(self, **kw):
        from app.core.payments import PaymentProviderError

        if self.fail_refunds:
            raise PaymentProviderError("The refund could not be processed. No money was moved.")
        self.refunds.append(kw)
        return f"re_test_{len(self.refunds)}"

    def webhook_endpoints(self):
        return self.endpoints


@pytest.fixture(autouse=True)
def gateway():
    from app.core.payments import set_gateway

    g = FakeGateway()
    set_gateway(g)
    yield g
    set_gateway(None)
