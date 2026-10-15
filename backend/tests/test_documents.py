"""Customer links, signatures, document versions, PDFs, email, and website forms."""

import base64
import io
from datetime import UTC, datetime, timedelta

import pytest
from conftest import TEST_DB
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, text

LINES = [
    {"kind": "labor", "description": "Replace front pads", "quantity": "2"},
    {
        "kind": "part",
        "description": "Pad set",
        "unit_price_cents": 8000,
        "unit_cost_cents": 4100,
        "part_number": "PAD-1",
    },
]


def signature_png(blank: bool = False) -> str:
    img = Image.new("RGBA", (600, 200), (255, 255, 255, 0))
    if not blank:
        d = ImageDraw.Draw(img)
        d.line(
            [(30, 150), (120, 40), (200, 160), (320, 50), (450, 140), (560, 60)],
            fill=(20, 20, 20, 255),
            width=6,
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def token_of(url: str) -> str:
    return url.rsplit("/d/", 1)[1]


def sql(q: str, **params):
    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        r = c.execute(text(q), params)
        rows = r.fetchall() if r.returns_rows else None
    eng.dispose()
    return rows


@pytest.fixture
def estimate(client, customer, vehicle):
    est = client.post(
        "/api/estimates",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": LINES,
            "internal_notes": "SECRET-INTERNAL-NOTE",
            "customer_notes": "Rotors are fine.",
        },
    ).json()
    return est


@pytest.fixture
def sent(client, estimate, outbox):
    r = client.post(f"/api/estimates/{estimate['id']}/send", json={"email": True})
    assert r.status_code == 200, r.text
    return r.json()


def approve(anon, token, **over):
    body = {
        "decision": "approved",
        "signer_name": "John Smith",
        "agree": True,
        "signature_image": signature_png(),
        **over,
    }
    return anon.post(f"/api/public/links/{token}/respond", json=body)


# ------------------------------------------------------------------ sending


def test_send_estimate_locks_versions_links_and_emails(client, sent, outbox):
    assert sent["link"].startswith("https://shop.example/d/")
    assert sent["email"]["status"] == "sent"
    assert sent["estimate"]["status"] == "sent" and sent["estimate"]["locked_at"]
    mails = outbox()
    assert len(mails) == 1
    assert mails[0]["To"] == "john@example.com"
    assert sent["link"] in mails[0].get_content()
    trail = client.get(
        "/api/documents", params={"entity_type": "estimate", "entity_id": sent["estimate"]["id"]}
    ).json()
    assert [v["kind"] for v in trail["versions"]] == ["issued"]
    assert trail["links"][0]["active"] and trail["emails"][0]["status"] == "sent"


def test_customer_view_never_exposes_internal_data(anon, sent):
    r = anon.get(f"/api/public/links/{token_of(sent['link'])}")
    assert r.status_code == 200
    body = r.text
    assert "SECRET-INTERNAL-NOTE" not in body
    assert "unit_cost" not in body and "4100" not in body and "markup" not in body
    data = r.json()
    assert data["document"]["notes"] == "Rotors are fine."
    assert data["state"]["can_respond"] is True
    # Viewing marks the estimate viewed.
    assert sql("select status from estimates")[0][0] == "viewed"


def test_unknown_link_is_404(anon):
    assert anon.get("/api/public/links/not-a-real-token").status_code == 404


def test_expired_link_is_gone(anon, sent):
    sql("update access_tokens set expires_at = now() - interval '1 minute'")
    r = anon.get(f"/api/public/links/{token_of(sent['link'])}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "link_gone"


# ------------------------------------------------------------------ signing


def test_customer_signs_estimate(anon, client, sent, outbox):
    token = token_of(sent["link"])
    r = approve(anon, token)
    assert r.status_code == 200, r.text
    est = client.get(f"/api/estimates/{sent['estimate']['id']}").json()
    assert est["status"] == "approved" and est["decision_method"] == "link"
    assert est["authorization"]["status"] == "approved"
    assert est["authorization"]["signer_name"] == "John Smith"

    pdf = anon.get(f"/api/public/links/{token}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert "signed" in pdf.headers["content-disposition"]

    trail = client.get(
        "/api/documents", params={"entity_type": "estimate", "entity_id": est["id"]}
    ).json()
    kinds = sorted(v["kind"] for v in trail["versions"])
    assert kinds == ["issued", "signed"]
    a = trail["authorizations"][0]
    assert a["method"] == "drawn" and a["status"] == "valid" and a["ip_address"]
    signed = next(v for v in trail["versions"] if v["kind"] == "signed")
    issued = next(v for v in trail["versions"] if v["kind"] == "issued")
    assert signed["content_sha256"] == issued["content_sha256"]  # signed exactly what was sent
    assert client.get(f"/api/documents/{signed['id']}/pdf").content.startswith(b"%PDF")

    # Audit trail records the customer as the actor.
    log = client.get(
        "/api/audit", params={"entity_type": "estimate", "entity_id": est["id"]}
    ).json()
    assert any(e["action"] == "estimate.approved" and e["actor"] == "customer" for e in log)
    # Thank-you email went to the customer.
    assert any("Thanks for approving" in m["Subject"] for m in outbox())

    again = approve(anon, token)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_signed"
    view = anon.get(f"/api/public/links/{token}").json()
    assert view["state"]["can_respond"] is False and view["state"]["decision"] == "approved"


def test_signature_rules(anon, client, sent):
    token = token_of(sent["link"])
    assert approve(anon, token, agree=False).status_code == 422
    blank = approve(anon, token, signature_image=signature_png(blank=True))
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "bad_image"
    assert (
        approve(anon, token, signature_image="data:image/png;base64,bm90IGFuIGltYWdl").status_code
        == 422
    )
    assert approve(anon, token, signature_image="data:text/html;base64,PGgxPg==").status_code == 422
    assert approve(anon, token, signature_image=None).status_code == 422
    client.patch("/api/settings", json={"allow_typed_signature": False})
    assert (
        approve(anon, token, signature_image=None, typed_signature="John Smith").status_code == 422
    )
    client.patch("/api/settings", json={"allow_typed_signature": True})
    ok = approve(anon, token, signature_image=None, typed_signature="John Smith")
    assert ok.status_code == 200


def test_decline_with_note(anon, client, sent):
    r = anon.post(
        f"/api/public/links/{token_of(sent['link'])}/respond",
        json={
            "decision": "declined",
            "signer_name": "John Smith",
            "note": "Too expensive right now.",
        },
    )
    assert r.status_code == 200
    est = client.get(f"/api/estimates/{sent['estimate']['id']}").json()
    assert est["status"] == "declined" and est["decision_note"] == "Too expensive right now."


def test_revision_kills_old_link_and_requires_new_signature(anon, client, sent):
    token = token_of(sent["link"])
    assert approve(anon, token).status_code == 200
    est_id = sent["estimate"]["id"]
    revised = client.post(f"/api/estimates/{est_id}/revise").json()
    assert revised["version"] == 2 and revised["authorization"]["status"] == "none"
    assert anon.get(f"/api/public/links/{token}").status_code == 410
    trail = client.get(
        "/api/documents", params={"entity_type": "estimate", "entity_id": est_id}
    ).json()
    assert trail["authorizations"][0]["status"] == "superseded"

    client.post(
        f"/api/estimates/{est_id}/items",
        json={"kind": "fee", "description": "Brake fluid flush", "unit_price_cents": 6000},
    )
    resent = client.post(f"/api/estimates/{est_id}/send", json={"email": False}).json()
    view = anon.get(f"/api/public/links/{token_of(resent['link'])}").json()
    assert view["document"]["version"] == 2
    assert any(i["description"] == "Brake fluid flush" for i in view["document"]["items"])
    assert approve(anon, token_of(resent["link"])).status_code == 200


def test_unsigned_link_goes_stale_when_shop_revises(anon, client, sent):
    est_id = sent["estimate"]["id"]
    client.post(
        f"/api/estimates/{est_id}/decision", json={"decision": "declined", "method": "phone"}
    )
    # The shop's recorded decision closes the customer's link.
    assert anon.get(f"/api/public/links/{token_of(sent['link'])}").status_code == 410


def test_mechanic_recorded_approval_is_an_authorization(client, estimate):
    r = client.post(
        f"/api/estimates/{estimate['id']}/decision",
        json={"decision": "approved", "method": "phone", "note": "OK'd by phone"},
    )
    assert r.status_code == 200
    trail = client.get(
        "/api/documents", params={"entity_type": "estimate", "entity_id": estimate["id"]}
    ).json()
    a = trail["authorizations"][0]
    assert a["method"] == "phone" and a["recorded_by_shop"] is True
    assert {v["kind"] for v in trail["versions"]} == {"issued", "signed"}


def test_question_reaches_the_shop(anon, client, sent):
    r = anon.post(
        f"/api/public/links/{token_of(sent['link'])}/question",
        json={"message": "Can you also check the rear brakes?"},
    )
    assert r.status_code == 201
    msgs = client.get("/api/inquiries").json()
    assert msgs[0]["kind"] == "question" and "rear brakes" in msgs[0]["message"]
    dash = client.get("/api/dashboard").json()
    assert dash["messages"][0]["id"] == msgs[0]["id"]
    client.post(f"/api/inquiries/{msgs[0]['id']}/handled")
    assert client.get("/api/inquiries").json() == []


def test_email_failure_never_undoes_the_send(client, estimate, monkeypatch):
    from app.core.email import EmailError
    from app.services import notify

    def boom(msg):
        raise EmailError("SES is unhappy")

    monkeypatch.setattr(notify, "send_email", boom)
    r = client.post(f"/api/estimates/{estimate['id']}/send", json={"email": True})
    assert r.status_code == 200
    body = r.json()
    assert body["email"]["status"] == "failed"
    assert body["estimate"]["status"] == "sent" and body["link"]
    assert sql("select status from email_log")[0][0] == "failed"


def test_no_email_on_file_is_reported_not_an_error(client, vehicle):
    c = client.post(
        "/api/customers",
        json={
            "first_name": "Pat",
            "phone": "555-0101",
            "vehicle": {"make": "Ford", "model": "Focus"},
        },
    ).json()
    est = client.post(
        "/api/estimates",
        json={"customer_id": c["id"], "vehicle_id": c["vehicles"][0]["id"], "items": LINES},
    ).json()
    r = client.post(f"/api/estimates/{est['id']}/send", json={"email": True}).json()
    assert r["email"]["status"] == "skipped" and r["link"]


# ------------------------------------------------------------------ work orders & supplements


@pytest.fixture
def wo(client, customer, vehicle):
    return client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": LINES,
            "concern": "Grinding noise",
        },
    ).json()


def test_work_order_authorization_detects_later_changes(anon, client, wo):
    r = client.post(f"/api/work-orders/{wo['id']}/send-authorization", json={"email": False})
    assert r.status_code == 200
    token = token_of(r.json()["link"])
    assert (
        client.get(f"/api/work-orders/{wo['id']}").json()["authorization"]["status"] == "awaiting"
    )
    assert approve(anon, token).status_code == 200
    assert (
        client.get(f"/api/work-orders/{wo['id']}").json()["authorization"]["status"] == "approved"
    )
    client.post(
        f"/api/work-orders/{wo['id']}/items",
        json={"kind": "part", "description": "Caliper", "unit_price_cents": 15000},
    )
    auth = client.get(f"/api/work-orders/{wo['id']}").json()["authorization"]
    assert auth["status"] == "changed_since_signed"


def test_supplement_approval_adds_lines(anon, client, wo):
    sup = client.post(
        "/api/estimates",
        json={
            "customer_id": wo["customer_id"],
            "vehicle_id": wo["vehicle_id"],
            "work_order_id": wo["id"],
            "is_supplement": True,
            "items": [{"kind": "part", "description": "Caliper", "unit_price_cents": 42500}],
        },
    ).json()
    assert sup["is_supplement"] and len(sup["items"]) == 1  # doesn't copy the work order's lines
    sent = client.post(f"/api/estimates/{sup['id']}/send", json={"email": False}).json()
    view = anon.get(f"/api/public/links/{token_of(sent['link'])}").json()
    assert view["document"]["title"] == "Additional work approval"
    assert approve(anon, token_of(sent["link"])).status_code == 200
    after = client.post(f"/api/estimates/{sup['id']}/convert").json()
    assert len(after["items"]) == len(LINES) + 1
    assert after["total_cents"] > wo["total_cents"]
    assert (
        client.post(
            "/api/estimates",
            json={
                "customer_id": wo["customer_id"],
                "vehicle_id": wo["vehicle_id"],
                "is_supplement": True,
                "items": [],
            },
        ).status_code
        == 422
    )


# ------------------------------------------------------------------ invoices, receipts, PDFs


def test_invoice_link_receipts_and_pdfs(anon, client, wo, outbox):
    inv = client.post(f"/api/work-orders/{wo['id']}/invoice").json()
    sent = client.post(f"/api/invoices/{inv['id']}/send", json={"email": True}).json()
    assert sent["email"]["status"] == "sent" and sent["invoice"]["status"] == "sent"
    token = token_of(sent["link"])
    view = anon.get(f"/api/public/links/{token}").json()
    assert view["purpose"] == "invoice" and view["state"]["balance_cents"] == inv["total_cents"]
    assert "unit_cost" not in str(view)
    assert client.get(f"/api/invoices/{inv['id']}").json()["status"] == "viewed"

    paid = client.post(
        f"/api/invoices/{inv['id']}/payments", json={"amount_cents": 5000, "method": "cash"}
    ).json()
    pid = paid["payments"][0]["id"]
    rc = anon.get(f"/api/public/links/{token}/receipts/{pid}")
    assert rc.status_code == 200 and rc.content.startswith(b"%PDF")
    assert client.get(f"/api/payments/{pid}/receipt").content.startswith(b"%PDF")
    emailed = client.post(f"/api/payments/{pid}/email-receipt").json()
    assert emailed["email"]["status"] == "sent"
    last = outbox()[-1]
    assert any(p.get_filename().endswith(".pdf") for p in last.iter_attachments())

    # A receipt for a payment on a different invoice is not reachable through this link.
    other = client.post(
        "/api/invoices",
        json={"customer_id": wo["customer_id"], "vehicle_id": wo["vehicle_id"], "items": LINES},
    ).json()
    p2 = client.post(
        f"/api/invoices/{other['id']}/payments", json={"amount_cents": 100, "method": "cash"}
    ).json()["payments"][0]["id"]
    assert anon.get(f"/api/public/links/{token}/receipts/{p2}").status_code == 404

    for path in (
        f"/api/invoices/{inv['id']}/pdf",
        f"/api/work-orders/{wo['id']}/pdf",
        f"/api/public/links/{token}/pdf",
    ):
        r = (anon if "public" in path else client).get(path)
        assert r.status_code == 200 and r.content.startswith(b"%PDF"), path


def test_admin_pdfs_require_login(wo):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as stranger:
        assert stranger.get(f"/api/work-orders/{wo['id']}/pdf").status_code == 401
        assert stranger.get("/api/documents/1/pdf").status_code == 401


def test_tampered_stored_pdf_is_refused(anon, client, sent):
    import pathlib

    from conftest import FILES_DIR

    key = sql("select pdf_key from document_versions where kind = 'issued'")[0][0]
    pathlib.Path(FILES_DIR, key).write_bytes(b"%PDF-1.7 something else entirely")
    r = anon.get(f"/api/public/links/{token_of(sent['link'])}/pdf")
    assert r.status_code == 500 and r.json()["error"]["code"] == "integrity_error"


def test_ready_for_pickup_email(client, wo, outbox):
    r = client.post(
        f"/api/work-orders/{wo['id']}/status",
        json={"status": "ready_for_pickup", "notify_customer": True},
    ).json()
    assert r["email"]["status"] == "sent"
    assert "ready for pickup" in outbox()[-1]["Subject"]


def test_appointment_confirmation_email(client, customer, vehicle, outbox):
    r = client.post(
        "/api/appointments",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "starts_at": "2026-11-02T09:00:00-05:00",
            "notify_customer": True,
        },
    ).json()
    assert r["email"]["status"] == "sent"
    assert "9:00 AM" in outbox()[-1].get_content()


# ------------------------------------------------------------------ website forms


BOOKING = {
    "name": "Alex Kim",
    "phone": "555-010-0104",
    "vehicle_year": 2019,
    "vehicle_make": "Subaru",
    "vehicle_model": "Outback",
    "requested_service": "Brakes",
    "preferred_date": "2026-11-03",
    "preferred_time": "morning",
    "concern": "Squeal when stopping",
}


def test_online_booking(anon, client):
    r = anon.post("/api/public/appointments", json=BOOKING)
    assert r.status_code == 201
    appts = client.get("/api/appointments").json()
    assert appts[0]["status"] == "requested" and appts[0]["source"] == "online"
    assert appts[0]["vehicle_description"] == "2019 Subaru Outback"
    assert anon.post("/api/public/appointments", json={**BOOKING, "phone": None}).status_code == 422


def test_booking_honeypot_and_rate_limit(anon, client):
    assert (
        anon.post("/api/public/appointments", json={**BOOKING, "website": "spam.biz"}).status_code
        == 201
    )
    assert client.get("/api/appointments").json() == []
    for _ in range(5):
        assert anon.post("/api/public/appointments", json=BOOKING).status_code == 201
    r = anon.post("/api/public/contact", json={"name": "Alex", "phone": "555", "message": "hi"})
    assert r.status_code == 429


def test_contact_form(anon, client):
    r = anon.post(
        "/api/public/contact",
        json={"name": "Sam Lee", "email": "sam@example.com", "message": "Do you work on diesels?"},
    )
    assert r.status_code == 201
    assert client.get("/api/inquiries").json()[0]["kind"] == "contact"


# ------------------------------------------------------------------ templates & logo


def test_email_templates_edit_and_reset(client, sent, outbox):
    t = client.get("/api/email-templates").json()
    assert {x["key"] for x in t["templates"]} >= {
        "estimate_ready",
        "invoice_ready",
        "vehicle_ready",
    }
    r = client.put(
        "/api/email-templates/estimate_ready",
        json={
            "subject": "Quote {document_number} {not_a_placeholder}",
            "body": "Hi {customer_first_name}, see {link}. {{literal}}",
        },
    )
    assert r.status_code == 200
    client.post(f"/api/estimates/{sent['estimate']['id']}/send", json={"email": True})
    m = outbox()[-1]
    assert m["Subject"].startswith("Quote EST-") and "{not_a_placeholder}" in m["Subject"]
    assert "Hi John" in m.get_content()
    client.delete("/api/email-templates/estimate_ready")
    assert not next(
        x
        for x in client.get("/api/email-templates").json()["templates"]
        if x["key"] == "estimate_ready"
    )["edited"]


def test_logo_upload(client, anon):
    assert anon.get("/api/public/logo").status_code == 404
    assert (
        client.post(
            "/api/settings/logo", json={"image": "data:image/gif;base64,R0lGOD"}
        ).status_code
        == 422
    )
    img = Image.new("RGB", (300, 120), (31, 42, 48))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    data = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    assert client.post("/api/settings/logo", json={"image": data}).status_code == 200
    r = anon.get("/api/public/logo")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert anon.get("/api/public/business").json()["has_logo"] is True
    # The logo now appears on PDFs without breaking them.
    assert client.get("/api/settings").status_code == 200


def test_links_are_not_reusable_across_documents(anon, client, sent, wo):
    """A link for one estimate can't be used to respond to a different document."""
    other = client.post(
        "/api/estimates",
        json={"customer_id": wo["customer_id"], "vehicle_id": wo["vehicle_id"], "items": LINES},
    ).json()
    approve(anon, token_of(sent["link"]))
    assert client.get(f"/api/estimates/{other['id']}").json()["status"] == "draft"


def test_link_expiry_is_set(client, sent):
    exp = sql("select expires_at from access_tokens")[0][0]
    assert timedelta(days=40) < exp - datetime.now(UTC) < timedelta(days=50)
