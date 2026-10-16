"""Phase 4: photos, digital inspections, inspection reports, service history, warranties."""

import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_documents import approve, token_of

from app.main import create_app

GPS_TAG = 0x8825
ORIENTATION_TAG = 0x0112


def jpeg(w=400, h=200, *, gps=True, orientation=None, color=(180, 40, 40)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    if gps:
        exif[GPS_TAG] = {1: "N", 2: (40.0, 42.0, 51.0), 3: "W", 4: (74.0, 0.0, 21.0)}
    if orientation:
        exif[ORIENTATION_TAG] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def upload(client, entity_type, entity_id, data=None, ctype="image/jpeg", **params):
    return client.post(
        "/api/photos",
        params={"entity_type": entity_type, "entity_id": entity_id, **params},
        content=data if data is not None else jpeg(),
        headers={"Content-Type": ctype},
    )


@pytest.fixture
def wo(client, customer, vehicle):
    r = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "concern": "Grinding noise when braking",
            "mileage_in": 61000,
            "items": [
                {
                    "kind": "fee",
                    "description": "Diagnostic",
                    "quantity": "1",
                    "unit_price_cents": 9500,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def inspection(client, wo):
    r = client.post(f"/api/work-orders/{wo['id']}/inspection")
    assert r.status_code == 201, r.text
    return r.json()


def item(insp, category):
    return next(i for i in insp["items"] if i["category"] == category)


def check_all(client, insp, overrides=None):
    overrides = overrides or {}
    out = insp
    for it in insp["items"]:
        body = overrides.get(it["category"], {"status": "good"})
        r = client.patch(f"/api/inspection-items/{it['id']}", json=body)
        assert r.status_code == 200, r.text
        out = r.json()
    return out


FINDINGS = {
    "Brakes": {
        "status": "urgent",
        "notes": "Front pads at 2 mm, rotors scored.",
        "recommendation": "Replace front pads and rotors",
        "estimated_cost_cents": 42500,
    },
    "Tires": {"status": "monitor", "notes": "4/32 tread on rears."},
    "Battery": {
        "status": "attention",
        "recommendation": "Replace battery",
        "estimated_cost_cents": 21000,
    },
}


# ------------------------------------------------------------------ photos


def test_photo_upload_reencodes_upright_and_strips_location(client, wo):
    raw = jpeg(400, 200, orientation=6)  # phone held sideways: stored landscape, shown portrait
    assert b"PhoneMaker" in raw
    r = upload(client, "work_order", wo["id"], raw, caption="  Leak at oil pan  ")
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["width"], p["height"]) == (200, 400)  # rotated upright
    assert p["caption"] == "Leak at oil pan" and p["customer_visible"] is True

    full = client.get(p["url"])
    thumb = client.get(p["thumb_url"])
    assert full.status_code == 200 and full.headers["content-type"] == "image/jpeg"
    assert "private" in full.headers["cache-control"]
    stored = Image.open(io.BytesIO(full.content))
    assert stored.format == "JPEG" and not stored.getexif()
    assert b"PhoneMaker" not in full.content and b"Exif" not in full.content
    assert max(Image.open(io.BytesIO(thumb.content)).size) <= 480

    listed = client.get("/api/photos", params={"entity_type": "work_order", "entity_id": wo["id"]})
    assert [x["id"] for x in listed.json()] == [p["id"]]
    assert client.get(f"/api/vehicles/{wo['vehicle_id']}/photos").json()[0]["id"] == p["id"]


def test_photo_upload_limits(client, wo):
    assert upload(client, "work_order", wo["id"], b"hello", "text/plain").status_code == 422
    assert upload(client, "work_order", wo["id"], b"not really a jpeg").status_code == 422
    assert upload(client, "work_order", wo["id"], jpeg(), "image/heic").status_code == 422
    assert upload(client, "work_order", wo["id"], jpeg(20, 20)).status_code == 422
    big = b"\xff\xd8" + b"0" * 4_100_000
    assert upload(client, "work_order", wo["id"], big).status_code == 413
    assert upload(client, "work_order", 999999).status_code == 404
    assert upload(client, "invoice", wo["id"]).status_code == 422  # not a photo target
    png = io.BytesIO()
    Image.new("RGBA", (300, 300), (0, 0, 0, 0)).save(png, format="PNG")
    assert upload(client, "work_order", wo["id"], png.getvalue(), "image/png").status_code == 201


def test_photo_edit_and_hide(client, wo):
    p = upload(client, "work_order", wo["id"]).json()
    r = client.patch(f"/api/photos/{p['id']}", json={"caption": "Rotor", "customer_visible": False})
    assert r.json()["caption"] == "Rotor" and r.json()["customer_visible"] is False
    assert client.delete(f"/api/photos/{p['id']}").status_code == 204
    assert client.get(p["url"]).status_code == 404
    assert (
        client.get(
            "/api/photos", params={"entity_type": "work_order", "entity_id": wo["id"]}
        ).json()
        == []
    )


# ------------------------------------------------------------------ inspections


def test_inspection_checklist_and_completion_rules(client, wo, inspection):
    assert inspection["number"].startswith("INS-")
    assert len(inspection["items"]) == 14 and inspection["counts"]["unchecked"] == 14
    assert inspection["mileage"] == 61000
    again = client.post(f"/api/work-orders/{wo['id']}/inspection").json()
    assert again["id"] == inspection["id"]
    assert client.get(f"/api/work-orders/{wo['id']}").json()["inspection_id"] == inspection["id"]

    r = client.patch(f"/api/inspections/{inspection['id']}", json={"status": "completed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "inspection_incomplete"

    ac = item(inspection, "AC")
    after = client.delete(f"/api/inspection-items/{ac['id']}").json()
    assert len(after["items"]) == 13
    added = client.post(
        f"/api/inspections/{inspection['id']}/items", json={"name": "Wiper blades"}
    ).json()
    assert (
        added["items"][-1]["name"] == "Wiper blades" and added["items"][-1]["category"] == "Other"
    )

    done = check_all(client, added, FINDINGS)
    assert done["counts"] == {"good": 11, "monitor": 1, "attention": 1, "urgent": 1, "unchecked": 0}
    r = client.patch(
        f"/api/inspections/{inspection['id']}",
        json={"status": "completed", "summary": "Brakes need work now."},
    )
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["completed_at"]
    reopened = client.patch(f"/api/inspections/{inspection['id']}", json={"status": "in_progress"})
    assert reopened.json()["completed_at"] is None
    bad = client.patch(f"/api/inspection-items/{ac['id']}", json={"status": "great"})
    assert bad.status_code in (404, 422)
    neg = client.patch(
        f"/api/inspection-items/{item(inspection, 'Brakes')['id']}",
        json={"estimated_cost_cents": -5},
    )
    assert neg.status_code == 422


def test_estimate_from_findings_on_open_work_order(client, wo, inspection):
    r = client.post(f"/api/inspections/{inspection['id']}/estimate")
    assert r.status_code == 409  # nothing flagged yet
    check_all(client, inspection, FINDINGS)
    est = client.post(f"/api/inspections/{inspection['id']}/estimate").json()
    assert est["inspection_id"] == inspection["id"] and est["is_supplement"] is False
    descriptions = [li["description"] for li in est["items"]]
    # Work order's own lines first, then findings with a recommendation or cost, red first.
    assert descriptions == ["Diagnostic", "Replace front pads and rotors", "Replace battery"]
    assert est["total_cents"] == 9500 + 42500 + 21000
    insp = client.get(f"/api/inspections/{inspection['id']}").json()
    assert insp["estimate_ids"] == [est["id"]]


def test_estimate_from_findings_on_approved_work_is_additional_work(client, wo, inspection):
    client.post(f"/api/work-orders/{wo['id']}/status", json={"status": "approved"})
    check_all(client, inspection, FINDINGS)
    est = client.post(f"/api/inspections/{inspection['id']}/estimate").json()
    assert est["is_supplement"] is True
    assert [li["description"] for li in est["items"]] == [
        "Replace front pads and rotors",
        "Replace battery",
    ]


def test_report_link_shows_findings_photos_and_can_be_signed(client, wo, inspection, outbox):
    insp = check_all(client, inspection, FINDINGS)
    brakes = item(insp, "Brakes")
    shown = upload(client, "inspection_item", brakes["id"], caption="Scored rotor").json()
    private = upload(client, "inspection_item", brakes["id"], customer_visible="false").json()
    vehicle_photo = upload(client, "vehicle", wo["vehicle_id"]).json()

    r = client.post(f"/api/inspections/{inspection['id']}/send", json={"email": True})
    assert r.status_code == 409  # not finished yet
    client.patch(f"/api/inspections/{inspection['id']}", json={"status": "completed"})
    sent = client.post(f"/api/inspections/{inspection['id']}/send", json={"email": True}).json()
    assert sent["email"]["status"] == "sent"
    mail = outbox()[-1]
    assert (
        "inspection report" in mail["Subject"]
        and token_of(sent["link"]) in mail.get_body().get_content()
    )
    token = token_of(sent["link"])

    with TestClient(create_app(), base_url="https://testserver") as stranger:
        view = stranger.get(f"/api/public/links/{token}")
        assert view.status_code == 200
        body = view.json()
        doc = body["document"]
        assert body["purpose"] == "inspection" and doc["doc_type"] == "inspection"
        assert [f["color"] for f in doc["findings"][:3]] == ["red", "red", "yellow"]
        assert doc["findings"][0]["name"].startswith("Brakes")
        assert doc["counts"] == {"red": 2, "yellow": 1, "green": 11}
        assert doc["estimated_total_cents"] == 42500 + 21000
        assert "acknowledge" in body["state"]["authorization_statement"]
        assert (
            '"key"' not in view.text and "thumb_key" not in view.text and "photos/" not in view.text
        )
        photo_ids = [p["id"] for p in doc["findings"][0]["photos"]]
        assert photo_ids == [shown["id"]]

        ok = stranger.get(f"/api/public/links/{token}/photos/{shown['id']}?size=thumb")
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
        for pid in (private["id"], vehicle_photo["id"]):
            assert stranger.get(f"/api/public/links/{token}/photos/{pid}").status_code == 404
        pdf = stranger.get(f"/api/public/links/{token}/pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

        declined = stranger.post(
            f"/api/public/links/{token}/respond",
            json={"decision": "declined", "signer_name": "John Smith"},
        )
        assert declined.status_code == 422
        assert approve(stranger, token).status_code == 200
        assert approve(stranger, token).status_code == 409  # only once

    state = client.get(f"/api/inspections/{inspection['id']}").json()["authorization"]
    assert state["status"] == "approved" and state["signer_name"] == "John Smith"
    trail = client.get(
        "/api/documents", params={"entity_type": "inspection", "entity_id": inspection["id"]}
    ).json()
    assert [v["kind"] for v in trail["versions"]] == ["signed", "issued"]

    # A finished report can't be edited in place (or get new photos) until it's reopened.
    lights = item(insp, "Lights")["id"]
    r = client.patch(f"/api/inspection-items/{lights}", json={"status": "monitor"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "inspection_finished"
    assert upload(client, "inspection_item", lights).status_code == 409
    assert client.delete(f"/api/inspection-items/{lights}").status_code == 409
    # Changing the report after it was signed is flagged; a hidden photo leaves the link.
    client.patch(f"/api/inspections/{inspection['id']}", json={"status": "in_progress"})
    client.patch(f"/api/inspection-items/{lights}", json={"status": "monitor"})
    state = client.get(f"/api/inspections/{inspection['id']}").json()["authorization"]
    assert state["status"] == "changed_since_signed"
    client.delete(f"/api/photos/{shown['id']}")
    with TestClient(create_app(), base_url="https://testserver") as stranger:
        assert stranger.get(f"/api/public/links/{token}/photos/{shown['id']}").status_code == 404


def test_estimate_link_carries_findings_and_its_photos(client, wo, inspection):
    insp = check_all(client, inspection, FINDINGS)
    finding_photo = upload(client, "inspection_item", item(insp, "Brakes")["id"]).json()
    est = client.post(f"/api/inspections/{inspection['id']}/estimate").json()
    est_photo = upload(client, "estimate", est["id"], caption="Pads").json()
    sent = client.post(f"/api/estimates/{est['id']}/send", json={"email": False}).json()
    token = token_of(sent["link"])
    with TestClient(create_app(), base_url="https://testserver") as stranger:
        doc = stranger.get(f"/api/public/links/{token}").json()["document"]
        assert doc["inspection"]["number"] == inspection["number"]
        assert [f["color"] for f in doc["inspection"]["findings"]] == ["red", "red", "yellow"]
        assert [p["id"] for p in doc["photos"]] == [est_photo["id"]]
        for pid in (finding_photo["id"], est_photo["id"]):
            assert stranger.get(f"/api/public/links/{token}/photos/{pid}").status_code == 200


def test_pdfs_embed_photos(client, wo, inspection):
    from sqlalchemy.orm import Session

    from app.db import get_engine
    from app.documents.render import render_html
    from app.documents.snapshot import snapshot_inspection
    from app.models import Inspection

    insp = check_all(client, inspection, FINDINGS)
    upload(client, "inspection_item", item(insp, "Brakes")["id"], caption="Scored rotor")
    with Session(get_engine()) as db:
        snap = snapshot_inspection(db, db.get(Inspection, inspection["id"]), 1)
    html = render_html(snap)
    assert html.count("data:image/jpeg;base64,") == 1 and "Scored rotor" in html
    assert "Replace front pads and rotors" in html and "Checked and good" in html
    r = client.get(f"/api/inspections/{inspection['id']}/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_settings_inspection_statement(client):
    r = client.patch("/api/settings", json={"inspection_statement": "I have read this report."})
    assert r.json()["inspection_statement"] == "I have read this report."
    assert client.patch("/api/settings", json={"inspection_statement": None}).status_code == 422


# ------------------------------------------------------------------ service history


def _complete(client, wo_id):
    r = client.post(
        f"/api/work-orders/{wo_id}/status",
        json={"status": "completed", "override_checklist": True},
    )
    assert r.status_code == 200, r.text


def test_completed_work_becomes_service_history_with_warranties(client, customer, vehicle):
    wo = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "mileage_in": 61000,
            "customer_notes": "Rotors resurfaced.",
            "items": [
                {"kind": "labor", "description": "Replace front pads", "quantity": "1.5"},
                {
                    "kind": "part",
                    "description": "Ceramic pads",
                    "quantity": "1",
                    "unit_price_cents": 8900,
                    "part_number": "D1234",
                    "warranty_months": 12,
                    "warranty_miles": 12000,
                },
                {
                    "kind": "discount",
                    "description": "Loyalty",
                    "quantity": "1",
                    "unit_price_cents": 500,
                },
            ],
        },
    ).json()
    inv = client.post(f"/api/work-orders/{wo['id']}/invoice").json()
    _complete(client, wo["id"])

    h = client.get(f"/api/vehicles/{vehicle['id']}/service-history").json()
    [rec] = h["records"]
    assert rec["source"] == "work_order" and rec["work_order"]["number"] == wo["number"]
    assert rec["invoice"]["number"] == inv["number"] and rec["total_cents"] == inv["total_cents"]
    assert rec["summary"] == "Replace front pads; Ceramic pads" and rec["mileage"] == 61000
    assert [li["kind"] for li in rec["lines"]] == ["labor", "part"]  # discounts left out
    assert rec["notes"] == "Rotors resurfaced."
    [w] = h["warranties"]
    assert w["state"] == "active" and w["expires_mileage"] == 73000 and w["part_number"] == "D1234"

    # Reopening hides the record until the job is completed again (same record).
    client.post(f"/api/work-orders/{wo['id']}/status", json={"status": "in_repair"})
    assert client.get(f"/api/vehicles/{vehicle['id']}/service-history").json()["records"] == []
    _complete(client, wo["id"])
    again = client.get(f"/api/vehicles/{vehicle['id']}/service-history").json()["records"]
    assert [r["id"] for r in again] == [rec["id"]]

    client.post(f"/api/invoices/{inv['id']}/void", json={"reason": "Wrong customer"})
    after = client.get(f"/api/vehicles/{vehicle['id']}/service-history").json()["records"][0]
    assert after["invoice"] is None

    r = client.patch(f"/api/service-records/{rec['id']}", json={"summary": "Changed"})
    assert r.status_code == 409  # comes from a work order
    assert client.delete(f"/api/service-records/{rec['id']}").status_code == 409


def test_manual_service_records(client, vehicle):
    r = client.post(
        f"/api/vehicles/{vehicle['id']}/service-records",
        json={
            "service_date": "2025-03-02",
            "summary": "Timing belt",
            "mileage": 95000,
            "performed_by": "Dealer",
            "total_cents": 89000,
        },
    )
    assert r.status_code == 201, r.text
    [rec] = r.json()["records"]
    assert rec["source"] == "manual" and rec["performed_by"] == "Dealer"
    # Mileage on a record moves the vehicle's mileage forward, never back.
    assert client.get(f"/api/vehicles/{vehicle['id']}").json()["mileage"] == 95000
    upd = client.patch(
        f"/api/service-records/{rec['id']}", json={"summary": "Timing belt and water pump"}
    )
    assert upd.json()["records"][0]["summary"] == "Timing belt and water pump"
    assert (
        client.post(
            f"/api/vehicles/{vehicle['id']}/service-records",
            json={"service_date": "2025-01-01", "summary": "x"},
        ).status_code
        == 422
    )
    gone = client.delete(f"/api/service-records/{rec['id']}")
    assert gone.json()["records"] == []
    assert client.delete(f"/api/service-records/{rec['id']}").status_code == 404


def test_warranty_math():
    from types import SimpleNamespace

    from app.services.history import add_months, warranties

    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 15), 14) == date(2028, 1, 15)

    def rec(d, mileage, **line):
        return SimpleNamespace(
            id=1,
            service_date=d,
            mileage=mileage,
            lines=[{"kind": "part", "description": "Pads", **line}],
        )

    car = SimpleNamespace(mileage=80000)
    today = date(2026, 10, 15)
    by_date = warranties([rec(date(2025, 9, 1), 60000, warranty_months=12)], car, today)
    assert by_date[0]["state"] == "expired" and by_date[0]["expires_on"] == date(2026, 9, 1)
    by_miles = warranties([rec(date(2026, 9, 1), 60000, warranty_miles=12000)], car, today)
    assert by_miles[0]["state"] == "expired"  # 80,000 > 72,000
    active = warranties(
        [rec(date(2026, 9, 1), 75000, warranty_months=24, warranty_miles=24000)], car, today
    )
    assert active[0]["state"] == "active"
    notes = warranties([rec(date(2026, 9, 1), None, warranty_notes="Lifetime")], car, today)
    assert notes[0]["state"] == "see_notes"
    assert warranties([rec(date(2026, 9, 1), 1)], car, today) == []


def test_estimate_from_work_order_shows_finished_inspection(client, wo, inspection):
    est = client.post(
        "/api/estimates",
        json={
            "customer_id": wo["customer_id"],
            "vehicle_id": wo["vehicle_id"],
            "work_order_id": wo["id"],
        },
    ).json()
    assert est["inspection_id"] is None  # inspection not finished yet
    check_all(client, inspection, FINDINGS)
    client.patch(f"/api/inspections/{inspection['id']}", json={"status": "completed"})
    est = client.post(
        "/api/estimates",
        json={
            "customer_id": wo["customer_id"],
            "vehicle_id": wo["vehicle_id"],
            "work_order_id": wo["id"],
        },
    ).json()
    assert est["inspection_id"] == inspection["id"]
    detached = client.patch(f"/api/estimates/{est['id']}", json={"inspection_id": None}).json()
    assert detached["inspection_id"] is None
    other = client.post(
        "/api/customers",
        json={
            "first_name": "Other",
            "phone": "5550109999",
            "vehicle": {"year": 2010, "make": "Ford", "model": "Focus"},
        },
    ).json()
    wrong = client.post(
        "/api/estimates",
        json={"customer_id": other["id"], "vehicle_id": other["vehicles"][0]["id"]},
    ).json()
    r = client.patch(f"/api/estimates/{wrong['id']}", json={"inspection_id": inspection["id"]})
    assert r.status_code == 422
