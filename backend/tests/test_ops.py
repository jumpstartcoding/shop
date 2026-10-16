"""Production plumbing: secrets loading, client IP trust, database URLs, go-live checks,
operational tasks, and the Lambda entry point."""

import base64
import json
import os

import pytest
from conftest import EMAIL
from starlette.requests import Request

from app.config import Settings, get_settings
from app.core.storage import get_storage

WEBHOOK_URL = "https://shop.example/api/webhooks/stripe"
ALL_EVENTS = [
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "charge.refunded",
    "charge.dispute.created",
]


@pytest.fixture
def settings_env(monkeypatch):
    """Set environment variables for one test and rebuild settings around them."""

    def apply(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        get_storage.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()
    get_storage.cache_clear()


# --- Parameter Store -------------------------------------------------------------------


class FakeSSM:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_parameters_by_path(self, **kw):
        self.calls.append(kw)
        i = int(kw.get("NextToken", 0))
        page = {"Parameters": self.pages[i]}
        if i + 1 < len(self.pages):
            page["NextToken"] = str(i + 1)
        return page


def test_ssm_loads_every_page_and_overrides_env(monkeypatch):
    from app.core.ssm import load_parameters

    monkeypatch.setenv("SHOP_TEST_A", "from-env")
    fake = FakeSSM(
        [
            [{"Name": "/shop/prod/SHOP_TEST_A", "Value": "from-ssm"}],
            [
                {"Name": "/shop/prod/SHOP_TEST_B", "Value": "b"},
                {"Name": "/shop/prod/not-a-var", "Value": "ignored"},
            ],
        ]
    )
    loaded = load_parameters("shop/prod", client=fake)
    assert loaded == ["SHOP_TEST_A", "SHOP_TEST_B"]
    assert os.environ["SHOP_TEST_A"] == "from-ssm"
    assert os.environ["SHOP_TEST_B"] == "b"
    assert "not-a-var" not in os.environ
    assert fake.calls[0]["Path"] == "/shop/prod/" and fake.calls[0]["WithDecryption"]
    monkeypatch.delenv("SHOP_TEST_B")


# --- Client IP ---------------------------------------------------------------------------


def _request(headers: dict, peer="10.0.0.9") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    }
    return Request(scope)


def test_client_ip_never_trusts_x_forwarded_for(settings_env):
    from app.core.deps import client_ip

    settings_env(ORIGIN_SECRET="")
    assert client_ip(_request({"x-forwarded-for": "1.2.3.4"})) == "10.0.0.9"
    assert client_ip(_request({"x-viewer-ip": "1.2.3.4"})) == "10.0.0.9"

    settings_env(ORIGIN_SECRET="cf")
    assert client_ip(_request({"x-viewer-ip": "203.0.113.7", "x-forwarded-for": "1.2.3.4"})) == (
        "203.0.113.7"
    )
    assert client_ip(_request({"x-forwarded-for": "1.2.3.4"})) == "10.0.0.9"


def test_spoofed_forwarded_for_cannot_dodge_the_booking_limit(anon):
    body = {"name": "Spam Bot", "phone": "5550100000", "requested_service": "Oil change"}
    codes = [
        anon.post(
            "/api/public/appointments", json=body, headers={"x-forwarded-for": f"9.9.9.{i}"}
        ).status_code
        for i in range(6)
    ]
    assert codes[:5] == [201] * 5 and codes[5] == 429


# --- Database URL ------------------------------------------------------------------------


def test_database_url_uses_psycopg3():
    for given in ("postgresql://u:p@h/db", "postgres://u:p@h/db"):
        assert Settings(database_url=given).database_url == "postgresql+psycopg://u:p@h/db"
    url = "postgresql+psycopg://u@h/db"
    assert Settings(database_url=url).database_url == url


def test_connect_args_turn_off_prepared_statements_on_neon_pooler():
    from app.db import connect_args

    assert connect_args("postgresql+psycopg://u@ep-x-pooler.us-east-1.aws.neon.tech/db") == {
        "connect_timeout": 10,
        "prepare_threshold": None,
    }
    assert connect_args("postgresql+psycopg://u@ep-x.us-east-1.aws.neon.tech/db") == {
        "connect_timeout": 10
    }


# --- Go-live checks ----------------------------------------------------------------------


def _by_id(report):
    return {c["id"]: c for c in report["checks"]}


def test_doctor_in_development(gateway):
    from app.doctor import as_markdown, run_checks

    gateway.endpoints = [{"url": WEBHOOK_URL, "status": "enabled", "events": ALL_EVENTS}]
    report = run_checks()
    checks = _by_id(report)
    assert report["ok"]
    for id in ("database", "migrations", "storage", "pdf", "accounts", "public_url", "stripe"):
        assert checks[id]["status"] == "ok", checks[id]
    assert "Test mode" in checks["stripe"]["detail"]
    assert checks["shop"]["status"] == "warn"  # test shop has no email
    assert "| ✅ | Database |" in as_markdown(report)


def test_doctor_checks_the_stripe_webhook(gateway):
    from app.doctor import run_checks

    assert _by_id(run_checks())["stripe"]["status"] == "fail"  # no endpoint registered
    gateway.endpoints = [
        {"url": WEBHOOK_URL, "status": "enabled", "events": ["checkout.session.completed"]}
    ]
    detail = _by_id(run_checks())["stripe"]["detail"]
    assert "charge.refunded" in detail and "missing" in detail
    gateway.endpoints = [{"url": WEBHOOK_URL, "status": "disabled", "events": ["*"]}]
    assert "disabled" in _by_id(run_checks())["stripe"]["detail"]
    gateway.endpoints[0]["status"] = "enabled"
    assert _by_id(run_checks())["stripe"]["status"] == "ok"


def test_doctor_flags_unsafe_production_settings(settings_env, client):
    from app.doctor import run_checks
    from app.tasks import create_admin

    create_admin("demo@example.com", "Demo", "demo-password-123")
    settings_env(ENVIRONMENT="production", PUBLIC_BASE_URL="http://localhost:5173")
    report = run_checks()
    checks = _by_id(report)
    assert checks["origin_secret"]["status"] == "fail"
    assert checks["public_url"]["status"] == "fail"
    assert checks["storage"]["status"] == "fail"  # local disk in production
    assert checks["email"]["status"] == "fail"  # file backend in production
    assert checks["accounts"]["status"] == "fail"  # demo login present
    assert not report["ok"]  # storage is critical


def test_doctor_survives_a_dead_database(settings_env):
    from app.db import reset_engine
    from app.doctor import run_checks

    settings_env(DATABASE_URL="postgresql+psycopg://nobody@127.0.0.1:1/none")
    reset_engine()
    try:
        report = run_checks()
    finally:
        os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or (
            "postgresql+psycopg://postgres@127.0.0.1:5433/shop_test"
        )
        get_settings.cache_clear()
        reset_engine()
    checks = _by_id(report)
    assert not report["ok"]
    assert checks["database"]["status"] == "fail"
    assert checks["migrations"]["detail"].startswith("Skipped")


# --- Tasks -------------------------------------------------------------------------------


def test_create_admin_rules():
    from app.tasks import create_admin

    assert not create_admin("new@example.com", "New", "short")["ok"]
    assert not create_admin("not-an-email", "New", "long-enough-password")["ok"]
    assert not create_admin("new@shop.test", "New", "long-enough-password")["ok"]  # login rejects
    assert not create_admin(EMAIL.upper(), "Dup", "long-enough-password")["ok"]
    assert create_admin(" new@example.com ", "New", "long-enough-password")["ok"]


def test_setup_shop_only_runs_once(anon):
    from sqlalchemy import text

    from app.db import get_engine
    from app.seed import setup_shop

    with get_engine().begin() as conn:
        conn.execute(text("UPDATE businesses SET name = 'My Auto Repair'"))
    result = setup_shop()
    assert result["ok"] and result["services"] > 10
    shop = anon.get("/api/public/business").json()
    assert shop["name"] == "Ridgeline Auto Repair"
    assert len(anon.get("/api/public/services").json()) == result["services"]
    assert not setup_shop()["ok"]


# --- Lambda entry point ------------------------------------------------------------------


def _function_url_event(method: str, path: str, body: bytes | None = None, headers=None):
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": "abc.lambda-url.us-east-1.on.aws", **(headers or {})},
        "requestContext": {
            "accountId": "anonymous",
            "apiId": "abc",
            "domainName": "abc.lambda-url.us-east-1.on.aws",
            "domainPrefix": "abc",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "130.176.0.1",
                "userAgent": "Amazon CloudFront",
            },
            "requestId": "r1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "15/Oct/2026:00:00:00 +0000",
            "timeEpoch": 1792022400000,
        },
        "body": base64.b64encode(body).decode() if body else None,
        "isBase64Encoded": bool(body),
    }


def test_lambda_handler_serves_http_and_tasks():
    from app.lambda_handler import handler

    r = handler(_function_url_event("GET", "/api/health"), None)
    assert r["statusCode"] == 200 and json.loads(r["body"])["database"] is True

    r = handler(_function_url_event("GET", "/api/public/business"), None)
    assert json.loads(r["body"])["name"] == "Test Shop"

    assert handler({"task": "doctor"}, None)["task"] == "doctor"
    assert handler({"task": "nope"}, None)["ok"] is False


def test_email_from_uses_shop_name_when_address_is_bare():
    from app.core.email import sender_for

    assert sender_for("service@shop.example", "Ridgeline Auto") == (
        "Ridgeline Auto <service@shop.example>"
    )
    assert sender_for("Fixed <service@shop.example>", "Ridgeline") == "Fixed <service@shop.example>"
    assert sender_for("service@shop.example", None) == "service@shop.example"
    assert sender_for("service@shop.example", 'Joe\'s "Best"\n Auto') == (
        "Joe's Best Auto <service@shop.example>"
    )


def test_customer_email_shows_shop_name(client, customer, outbox):
    client.patch("/api/settings", json={"name": "Ridgeline Auto", "email": "owner@example.com"})
    inv = client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "vehicle_id": customer["vehicles"][0]["id"],
            "items": [{"kind": "labor", "description": "x", "quantity": "1"}],
        },
    ).json()
    assert client.post(f"/api/invoices/{inv['id']}/send", json={"email": True}).status_code == 200
    sent = [m for m in outbox() if m["To"] == "john@example.com"]
    assert sent and sent[-1]["From"].startswith("Ridgeline Auto <")
