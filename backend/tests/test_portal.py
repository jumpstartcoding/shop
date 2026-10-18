"""Customer service-history link (spec §27): history, warranties, what's coming, invoices."""

from datetime import timedelta

from fastapi.testclient import TestClient
from test_admin import today
from test_documents import token_of

from app.main import create_app


def test_history_link_shows_only_customer_safe_records(client, customer, vehicle, outbox):
    wo = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "mileage_in": 61000,
            "internal_notes": "SECRET-WO-NOTE",
            "items": [
                {
                    "kind": "part",
                    "description": "Battery",
                    "unit_price_cents": 18000,
                    "unit_cost_cents": 9999,
                    "warranty_months": 36,
                },
            ],
        },
    ).json()
    inv = client.post(f"/api/work-orders/{wo['id']}/invoice").json()
    client.post(f"/api/invoices/{inv['id']}/mark-sent")
    client.post(
        f"/api/work-orders/{wo['id']}/status",
        json={"status": "completed", "override_checklist": True},
    )
    draft = client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": [{"kind": "labor", "description": "x", "quantity": "1"}],
        },
    ).json()
    client.post(
        f"/api/vehicles/{vehicle['id']}/service-records",
        json={
            "service_date": "2025-04-01",
            "summary": "Oil change",
            "performed_by": "Quick lube",
            "notes": "SECRET-MANUAL-NOTE",
            "total_cents": 4999,
        },
    )
    client.post(
        f"/api/vehicles/{vehicle['id']}/reminders",
        json={"kind": "oil_change", "due_date": str(today() + timedelta(days=90))},
    )
    other = client.post(
        "/api/customers",
        json={
            "first_name": "Other",
            "phone": "5550109999",
            "vehicle": {"year": 2010, "make": "Ford", "model": "Focus"},
        },
    ).json()
    other_inv = client.post(
        "/api/invoices",
        json={
            "customer_id": other["id"],
            "vehicle_id": other["vehicles"][0]["id"],
            "items": [{"kind": "labor", "description": "x", "quantity": "1"}],
        },
    ).json()
    client.post(f"/api/invoices/{other_inv['id']}/mark-sent")

    r = client.post(f"/api/vehicles/{vehicle['id']}/share-history", json={"email": True})
    assert r.status_code == 200, r.text
    assert r.json()["email"]["status"] == "sent" and "service record" in outbox()[-1]["Subject"]
    token = token_of(r.json()["link"])

    with TestClient(create_app(), base_url="https://testserver") as stranger:
        view = stranger.get(f"/api/public/links/{token}")
        assert view.status_code == 200
        body = view.json()
        doc = body["document"]
        assert body["purpose"] == "history" and doc["doc_type"] == "history"
        assert [rec["summary"] for rec in doc["records"]] == ["Battery", "Oil change"]
        assert (
            doc["records"][0]["invoice_number"] == inv["number"]
            and doc["records"][0]["by_this_shop"]
        )
        assert (
            doc["records"][1]["performed_by"] == "Quick lube"
            and doc["records"][1]["total_cents"] is None
        )
        assert [i["number"] for i in doc["invoices"]] == [inv["number"]]  # drafts aren't shared
        assert doc["warranties"][0]["state"] == "active"
        assert doc["reminders"][0]["title"] == "Oil change"
        for secret in ("SECRET-WO-NOTE", "SECRET-MANUAL-NOTE", "9999", "unit_cost", "logo_key"):
            assert secret not in view.text

        pdf = stranger.get(f"/api/public/links/{token}/invoices/{inv['id']}/pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        for bad in (draft["id"], other_inv["id"]):
            assert stranger.get(f"/api/public/links/{token}/invoices/{bad}/pdf").status_code == 404
        hist_pdf = stranger.get(f"/api/public/links/{token}/pdf")
        assert (
            hist_pdf.status_code == 200
            and "service-history" in hist_pdf.headers["content-disposition"]
        )
        assert stranger.post(
            f"/api/public/links/{token}/respond",
            json={"decision": "approved", "signer_name": "x"},
        ).status_code in (404, 422)
        q = stranger.post(
            f"/api/public/links/{token}/question",
            json={"message": "When is my next oil change due?"},
        )
        assert q.status_code == 201

    # Sharing again replaces the old link.
    client.post(f"/api/vehicles/{vehicle['id']}/share-history", json={"email": False})
    with TestClient(create_app(), base_url="https://testserver") as stranger:
        assert stranger.get(f"/api/public/links/{token}").status_code == 410
        # A history link can't open invoice PDFs through the invoice-only route of another link type.
        est_link = client.post(
            "/api/estimates",
            json={
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "items": [{"kind": "labor", "description": "y", "quantity": "1"}],
            },
        ).json()
        sent = client.post(f"/api/estimates/{est_link['id']}/send", json={"email": False}).json()
        assert (
            stranger.get(
                f"/api/public/links/{token_of(sent['link'])}/invoices/{inv['id']}/pdf"
            ).status_code
            == 404
        )


def test_work_order_notes_append_with_timestamp(client, customer, vehicle):
    wo = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "concern": "Grinding when braking",
            "internal_notes": "Start",
        },
    ).json()
    r = client.post(f"/api/work-orders/{wo['id']}/notes", json={"text": "  Pads at 2 mm  "})
    assert r.status_code == 200, r.text
    lines = r.json()["internal_notes"].splitlines()
    assert lines[0] == "Start" and lines[1].startswith("[") and lines[1].endswith("] Pads at 2 mm")
    assert (
        client.post(f"/api/work-orders/{wo['id']}/notes", json={"text": "   "}).status_code == 422
    )

    # Customers never see internal notes, timestamped or not.
    sent = client.post(f"/api/work-orders/{wo['id']}/send-authorization", json={"email": False})
    assert sent.status_code == 200, sent.text
    with TestClient(create_app(), base_url="https://testserver") as stranger:
        view = stranger.get(f"/api/public/links/{token_of(sent.json()['link'])}")
        assert view.status_code == 200 and "Pads at 2 mm" not in view.text

    # Completed jobs still take notes (like the Notes form), and each one is audited.
    client.post(
        f"/api/work-orders/{wo['id']}/status",
        json={"status": "completed", "override_checklist": True},
    )
    assert (
        client.post(f"/api/work-orders/{wo['id']}/notes", json={"text": "Called"}).status_code
        == 200
    )
    log = client.get("/api/audit", params={"entity_type": "work_order", "entity_id": wo["id"]})
    assert [e["action"] for e in log.json()].count("work_order.note_added") == 2


def test_paying_in_full_ticks_payment_confirmed(client, customer, vehicle):
    wo = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": [{"kind": "labor", "description": "Diag", "unit_price_cents": 10000}],
        },
    ).json()
    inv = client.post(f"/api/work-orders/{wo['id']}/invoice").json()
    pay = {"method": "cash", "amount_cents": 4000}
    assert client.post(f"/api/invoices/{inv['id']}/payments", json=pay).status_code == 201
    checklist = client.get(f"/api/work-orders/{wo['id']}").json()["qc_checklist"]
    assert checklist.get("invoice_generated") and not checklist.get("payment_confirmed")
    rest = {"method": "cash", "amount_cents": inv["total_cents"] - 4000}
    assert client.post(f"/api/invoices/{inv['id']}/payments", json=rest).status_code == 201
    checklist = client.get(f"/api/work-orders/{wo['id']}").json()["qc_checklist"]
    assert checklist["payment_confirmed"] is True


def test_appointment_follows_its_work_order(client, customer, vehicle):
    appt = client.post(
        "/api/appointments",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "starts_at": "2030-01-07T15:00:00Z",
            "ends_at": "2030-01-07T16:00:00Z",
        },
    )
    assert appt.status_code == 201, appt.text
    appt = appt.json()
    wo = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "appointment_id": appt["id"],
        },
    ).json()

    def status():
        return client.get(f"/api/appointments/{appt['id']}").json()["status"]

    assert status() == "checked_in"
    client.post(f"/api/work-orders/{wo['id']}/status", json={"status": "in_repair"})
    assert status() == "in_progress"
    client.post(
        f"/api/work-orders/{wo['id']}/status",
        json={"status": "completed", "override_checklist": True},
    )
    assert status() == "completed"
    client.post(f"/api/work-orders/{wo['id']}/status", json={"status": "in_repair"})
    assert status() == "in_progress"
