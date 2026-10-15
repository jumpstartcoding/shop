"""Online payments. Webhooks are signed exactly the way Stripe signs them and verified by the
real Stripe library, so these tests exercise the same path as production."""

import hashlib
import hmac
import json
import threading
import time

import pytest
from conftest import TEST_DB
from sqlalchemy import create_engine, text

SECRET = "whsec_test_secret"
LINES = [
    {"kind": "labor", "description": "Brake job", "quantity": "2"},
    {"kind": "part", "description": "Pads", "unit_price_cents": 10000},
]  # labor 20000 + parts 10000 + 8% tax on parts 800 = 30800


def sign(payload: bytes, ts: int | None = None, secret: str = SECRET) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def post_event(anon, event: dict, **sign_kw):
    body = json.dumps(event).encode()
    return anon.post(
        "/api/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": sign(body, **sign_kw), "Content-Type": "application/json"},
    )


_n = 0


def session_event(
    invoice_id: int,
    amount: int,
    *,
    intent: str | None = None,
    type_: str = "checkout.session.completed",
    payment_status: str = "paid",
    event_id: str | None = None,
    currency: str = "usd",
    source: str = "shop-app",
):
    global _n
    _n += 1
    return {
        "id": event_id or f"evt_{_n}",
        "type": type_,
        "created": int(time.time()),
        "data": {
            "object": {
                "id": f"cs_test_{_n}",
                "object": "checkout.session",
                "mode": "payment",
                "payment_status": payment_status,
                "amount_total": amount,
                "currency": currency,
                "payment_intent": intent or f"pi_{_n}",
                "metadata": {"source": source, "invoice_id": str(invoice_id)},
                "customer_details": {"email": "john@example.com"},
            }
        },
    }


def sql(q: str, **params):
    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        r = c.execute(text(q), params)
        rows = r.fetchall() if r.returns_rows else None
    eng.dispose()
    return rows


@pytest.fixture
def invoice(client, customer, vehicle):
    inv = client.post(
        "/api/invoices",
        json={"customer_id": customer["id"], "vehicle_id": vehicle["id"], "items": LINES},
    ).json()
    assert inv["total_cents"] == 30800
    return inv


@pytest.fixture
def link(client, invoice):
    sent = client.post(f"/api/invoices/{invoice['id']}/send", json={"email": False}).json()
    return sent["link"].rsplit("/d/", 1)[1]


def get_inv(client, inv_id):
    return client.get(f"/api/invoices/{inv_id}").json()


# ------------------------------------------------------------------ checkout


def test_customer_view_offers_online_payment(anon, link):
    state = anon.get(f"/api/public/links/{link}").json()["state"]
    assert state["can_pay_online"] is True and state["min_online_cents"] == 100


def test_checkout_full_and_partial(anon, link, gateway, invoice):
    r = anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": 30800})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.test/")
    call = gateway.checkouts[-1]
    assert call["amount_cents"] == 30800 and call["currency"] == "usd"
    assert call["metadata"] == {
        "source": "shop-app",
        "invoice_id": str(invoice["id"]),
        "invoice_number": invoice["number"],
    }
    assert call["success_url"].endswith(f"/d/{link}?paid=1")
    assert call["customer_email"] == "john@example.com"
    # Double tap within the same minute -> same idempotency key -> same Stripe session.
    anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": 30800})
    assert gateway.checkouts[-1]["idempotency_key"] == call["idempotency_key"]
    assert (
        anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": 5000}).status_code
        == 200
    )


def test_checkout_amount_rules(anon, link):
    for amount, code in [(50, 422), (30801, 422)]:
        r = anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": amount})
        assert r.status_code == code, amount
    assert (
        anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": 0}).status_code == 422
    )


def test_checkout_refused_when_not_payable(anon, client, link, invoice):
    client.patch("/api/settings", json={"online_payments_enabled": False})
    r = anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": 1000})
    assert r.status_code == 409 and r.json()["error"]["code"] == "payments_unavailable"
    assert anon.get(f"/api/public/links/{link}").json()["state"]["can_pay_online"] is False
    client.patch("/api/settings", json={"online_payments_enabled": True})

    client.post(
        f"/api/invoices/{invoice['id']}/payments", json={"amount_cents": 30800, "method": "cash"}
    )
    r = anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": 1000})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_paid"


def test_estimate_link_cannot_start_checkout(anon, client, customer, vehicle):
    est = client.post(
        "/api/estimates",
        json={"customer_id": customer["id"], "vehicle_id": vehicle["id"], "items": LINES},
    ).json()
    url = client.post(f"/api/estimates/{est['id']}/send", json={"email": False}).json()["link"]
    r = anon.post(
        f"/api/public/links/{url.rsplit('/d/', 1)[1]}/checkout", json={"amount_cents": 1000}
    )
    assert r.status_code == 409


def test_checkout_unavailable_without_stripe_keys(anon, link, monkeypatch):
    from app.config import get_settings
    from app.core.payments import set_gateway

    set_gateway(None)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    get_settings.cache_clear()
    try:
        r = anon.post(f"/api/public/links/{link}/checkout", json={"amount_cents": 1000})
        assert r.status_code == 409
    finally:
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_not_a_real_key")
        get_settings.cache_clear()


# ------------------------------------------------------------------ webhook security


def test_webhook_rejects_bad_signatures(anon, invoice):
    ev = session_event(invoice["id"], 30800)
    body = json.dumps(ev).encode()
    assert anon.post("/api/webhooks/stripe", content=body).status_code == 400  # unsigned
    bad = anon.post(
        "/api/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": sign(body, secret="whsec_wrong")},
    )
    assert bad.status_code == 400
    stale = post_event(anon, ev, ts=int(time.time()) - 3600)  # replayed an hour later
    assert stale.status_code == 400
    tampered = anon.post(
        "/api/webhooks/stripe",
        content=body.replace(b"30800", b"99999"),
        headers={"Stripe-Signature": sign(body)},
    )
    assert tampered.status_code == 400
    assert get_inv(anon, invoice["id"])["amount_paid_cents"] == 0


def test_unknown_event_types_are_acknowledged(anon):
    r = post_event(anon, {"id": "evt_x", "type": "customer.created", "data": {"object": {}}})
    assert r.status_code == 200 and r.json()["outcome"] == "ignored"


def test_events_from_other_integrations_are_ignored(anon, invoice):
    r = post_event(anon, session_event(invoice["id"], 30800, source="some-other-app"))
    assert r.json()["outcome"] == "ignored_not_ours"
    assert get_inv(anon, invoice["id"])["amount_paid_cents"] == 0


# ------------------------------------------------------------------ recording payments


def test_successful_payment_is_recorded_once(anon, client, invoice, link, outbox):
    ev = session_event(invoice["id"], 30800, intent="pi_full")
    r = post_event(anon, ev)
    assert r.status_code == 200 and r.json()["outcome"] == "payment_recorded"
    inv = get_inv(client, invoice["id"])
    assert inv["status"] == "paid" and inv["balance_cents"] == 0
    p = inv["payments"][0]
    assert p["method"] == "online" and p["provider_ref"] == "pi_full" and p["amount_cents"] == 30800

    # Same event delivered again (Stripe retries) -> nothing changes.
    again = post_event(anon, ev)
    assert again.json()["outcome"] == "duplicate"
    # A different event for the same payment (async succeeded after completed) -> no double.
    other = session_event(
        invoice["id"], 30800, intent="pi_full", type_="checkout.session.async_payment_succeeded"
    )
    assert post_event(anon, other).json()["outcome"] == "already_recorded"
    inv = get_inv(client, invoice["id"])
    assert len(inv["payments"]) == 1 and inv["amount_paid_cents"] == 30800

    # Receipt emailed with the PDF attached; customer link shows the receipt.
    receipt = next(m for m in outbox() if "Receipt" in m["Subject"])
    assert any(a.get_filename().endswith(".pdf") for a in receipt.iter_attachments())
    view = anon.get(f"/api/public/links/{link}").json()
    assert view["state"]["balance_cents"] == 0 and len(view["receipts"]) == 1
    log = client.get(
        "/api/audit", params={"entity_type": "invoice", "entity_id": invoice["id"]}
    ).json()
    assert any(e["action"] == "payment.received" and e["actor"] == "customer" for e in log)


def test_partial_online_payments(anon, client, invoice):
    post_event(anon, session_event(invoice["id"], 10000))
    inv = get_inv(client, invoice["id"])
    assert inv["status"] == "partially_paid" and inv["balance_cents"] == 20800
    post_event(anon, session_event(invoice["id"], 20800))
    assert get_inv(client, invoice["id"])["status"] == "paid"


def test_delayed_payment_waits_for_success(anon, client, invoice):
    pending = session_event(invoice["id"], 30800, intent="pi_ach", payment_status="unpaid")
    assert post_event(anon, pending).json()["outcome"] == "awaiting_payment"
    assert get_inv(client, invoice["id"])["amount_paid_cents"] == 0
    failed = session_event(
        invoice["id"],
        30800,
        intent="pi_ach",
        type_="checkout.session.async_payment_failed",
        payment_status="unpaid",
    )
    assert post_event(anon, failed).json()["outcome"] == "payment_failed"
    ok = session_event(
        invoice["id"], 30800, intent="pi_ach2", type_="checkout.session.async_payment_succeeded"
    )
    assert post_event(anon, ok).json()["outcome"] == "payment_recorded"
    assert get_inv(client, invoice["id"])["status"] == "paid"


def test_overlapping_payments_flag_overpayment(anon, client, invoice, outbox):
    """Two tabs, two checkouts, both paid. The money was taken, so both are recorded and the
    shop is told to refund the difference."""
    client.patch("/api/settings", json={"email": "shop@example.com"})
    post_event(anon, session_event(invoice["id"], 30800))
    r = post_event(anon, session_event(invoice["id"], 30800))
    assert r.json()["outcome"] == "payment_recorded_needs_refund"
    inv = get_inv(client, invoice["id"])
    assert inv["status"] == "paid" and inv["overpaid_cents"] == 30800 and inv["balance_cents"] == 0
    dash = client.get("/api/dashboard").json()
    assert dash["notifications"][0]["kind"] == "needs_refund"
    assert any(m["Subject"].startswith("ACTION NEEDED") for m in outbox())


def test_payment_on_void_invoice_is_kept_and_flagged(anon, client, invoice):
    client.post(f"/api/invoices/{invoice['id']}/void", json={"reason": "Wrong customer"})
    r = post_event(anon, session_event(invoice["id"], 30800))
    assert r.json()["outcome"] == "payment_recorded_needs_refund"
    inv = get_inv(client, invoice["id"])
    assert inv["status"] == "void" and inv["overpaid_cents"] == 30800


def test_wrong_currency_and_missing_invoice(anon, client, invoice):
    assert (
        post_event(anon, session_event(invoice["id"], 30800, currency="eur")).json()["outcome"]
        == "wrong_currency"
    )
    assert post_event(anon, session_event(999999, 30800)).json()["outcome"] == "unknown_invoice"
    assert get_inv(client, invoice["id"])["amount_paid_cents"] == 0


def test_failed_processing_rolls_back_so_stripe_can_retry(anon, client, invoice, monkeypatch):
    from app.services import payments

    def boom(*a, **k):
        raise RuntimeError("database hiccup")

    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setattr(payments, "recompute_paid", boom)
    ev = session_event(invoice["id"], 30800, event_id="evt_retry")
    with TestClient(
        create_app(), base_url="https://testserver", raise_server_exceptions=False
    ) as c:
        r = post_event(c, ev)
    assert r.status_code == 500
    assert sql("select count(*) from stripe_events")[0][0] == 0
    assert sql("select count(*) from payments")[0][0] == 0
    monkeypatch.undo()
    assert post_event(anon, ev).json()["outcome"] == "payment_recorded"


def test_concurrent_delivery_records_one_payment(anon, invoice):
    """The same event arriving twice at once (two Lambda containers) records one payment."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    ev = session_event(invoice["id"], 30800, event_id="evt_race", intent="pi_race")
    body = json.dumps(ev).encode()
    results = []

    def deliver():
        with TestClient(create_app(), base_url="https://testserver") as c:
            results.append(
                c.post(
                    "/api/webhooks/stripe", content=body, headers={"Stripe-Signature": sign(body)}
                ).json()["outcome"]
            )

    threads = [threading.Thread(target=deliver) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results).count("payment_recorded") == 1
    assert sql("select count(*) from payments")[0][0] == 1


def test_email_failure_never_undoes_a_payment(anon, client, invoice, monkeypatch):
    from app.core.email import EmailError
    from app.services import notify

    monkeypatch.setattr(notify, "send_email", lambda m: (_ for _ in ()).throw(EmailError("down")))
    r = post_event(anon, session_event(invoice["id"], 30800))
    assert r.status_code == 200
    assert get_inv(client, invoice["id"])["status"] == "paid"


# ------------------------------------------------------------------ refunds


def paid_online(anon, invoice, amount=30800, intent="pi_paid"):
    post_event(anon, session_event(invoice["id"], amount, intent=intent))


def test_partial_then_full_refund_through_stripe(anon, client, invoice, gateway):
    paid_online(anon, invoice)
    pid = get_inv(client, invoice["id"])["payments"][0]["id"]
    r = client.post(
        f"/api/payments/{pid}/refund", json={"amount_cents": 5000, "reason": "Goodwill"}
    )
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["status"] == "partially_paid" and inv["amount_paid_cents"] == 25800
    assert (
        inv["payments"][0]["refunded_cents"] == 5000 and inv["payments"][0]["status"] == "succeeded"
    )
    call = gateway.refunds[-1]
    assert call["payment_intent"] == "pi_paid" and call["amount_cents"] == 5000

    # Stripe then sends charge.refunded with the same total: nothing double-counts.
    ev = {
        "id": "evt_ref1",
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_paid", "amount_refunded": 5000}},
    }
    assert post_event(anon, ev).json()["outcome"] == "refund_already_recorded"
    assert get_inv(client, invoice["id"])["amount_paid_cents"] == 25800

    too_much = client.post(
        f"/api/payments/{pid}/refund", json={"amount_cents": 30000, "reason": "too much"}
    )
    assert too_much.status_code == 409 and too_much.json()["error"]["code"] == "refund_too_large"
    rest = client.post(
        f"/api/payments/{pid}/refund", json={"amount_cents": 25800, "reason": "Job cancelled"}
    ).json()
    assert rest["payments"][0]["status"] == "refunded" and rest["amount_paid_cents"] == 0
    assert (
        client.post(
            f"/api/payments/{pid}/refund", json={"amount_cents": 1, "reason": "again"}
        ).status_code
        == 409
    )


def test_refund_failure_changes_nothing(anon, client, invoice, gateway):
    paid_online(anon, invoice)
    pid = get_inv(client, invoice["id"])["payments"][0]["id"]
    gateway.fail_refunds = True
    r = client.post(
        f"/api/payments/{pid}/refund", json={"amount_cents": 5000, "reason": "Goodwill"}
    )
    assert r.status_code == 502 and "No money was moved" in r.json()["error"]["message"]
    inv = get_inv(client, invoice["id"])
    assert inv["amount_paid_cents"] == 30800 and inv["payments"][0]["refunded_cents"] == 0


def test_refund_made_in_stripe_dashboard_is_synced(anon, client, invoice):
    paid_online(anon, invoice)
    ev = {
        "id": "evt_dash",
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_paid", "amount_refunded": 10000}},
    }
    assert post_event(anon, ev).json()["outcome"] == "refund_synced"
    inv = get_inv(client, invoice["id"])
    assert inv["amount_paid_cents"] == 20800 and inv["status"] == "partially_paid"
    log = client.get(
        "/api/audit", params={"entity_type": "invoice", "entity_id": invoice["id"]}
    ).json()
    assert any(
        e["action"] == "payment.refunded" and e["details"]["source"] == "stripe_dashboard"
        for e in log
    )


def test_overpayment_resolved_by_refunding_one_payment(anon, client, invoice):
    paid_online(anon, invoice, intent="pi_a")
    paid_online(anon, invoice, intent="pi_b")
    second = get_inv(client, invoice["id"])["payments"][1]["id"]
    inv = client.post(
        f"/api/payments/{second}/refund", json={"amount_cents": 30800, "reason": "Paid twice"}
    ).json()
    assert inv["overpaid_cents"] == 0 and inv["status"] == "paid"


def test_manual_refund_is_recorded_without_stripe(client, invoice, gateway):
    paid = client.post(
        f"/api/invoices/{invoice['id']}/payments", json={"amount_cents": 30800, "method": "cash"}
    ).json()
    pid = paid["payments"][0]["id"]
    inv = client.post(
        f"/api/payments/{pid}/refund",
        json={"amount_cents": 800, "reason": "Discount after the fact"},
    ).json()
    assert inv["amount_paid_cents"] == 30000 and gateway.refunds == []
    # Refunded payments can't be voided (that would double-reverse).
    assert (
        client.post(f"/api/payments/{pid}/void", json={"reason": "oops wrong"}).status_code == 409
    )


def test_online_payments_cannot_be_voided(anon, client, invoice):
    paid_online(anon, invoice)
    pid = get_inv(client, invoice["id"])["payments"][0]["id"]
    assert (
        client.post(f"/api/payments/{pid}/void", json={"reason": "not allowed"}).status_code == 409
    )


def test_dispute_notifies_shop(anon, client, invoice, outbox):
    client.patch("/api/settings", json={"email": "shop@example.com"})
    paid_online(anon, invoice)
    ev = {
        "id": "evt_dp",
        "type": "charge.dispute.created",
        "data": {"object": {"payment_intent": "pi_paid", "amount": 30800, "reason": "fraudulent"}},
    }
    assert post_event(anon, ev).json()["outcome"] == "dispute_noted"
    assert any("dispute" in m["Subject"] for m in outbox())


def test_refund_requires_login(invoice, anon):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as stranger:
        assert (
            stranger.post(
                "/api/payments/1/refund", json={"amount_cents": 1, "reason": "xyz"}
            ).status_code
            == 401
        )


def test_revenue_is_net_of_refunds(anon, client, invoice):
    paid_online(anon, invoice)
    pid = get_inv(client, invoice["id"])["payments"][0]["id"]
    client.post(f"/api/payments/{pid}/refund", json={"amount_cents": 800, "reason": "Adjust"})
    assert client.get("/api/dashboard").json()["revenue"]["today_cents"] == 30000


def test_payment_settings_report(client):
    s = client.get("/api/settings/payments").json()
    assert s == {
        "configured": True,
        "mode": "test",
        "enabled": True,
        "currency": "usd",
        "min_cents": 100,
    }
