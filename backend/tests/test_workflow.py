"""The repair workflow end to end, and the rules that protect money and records."""

import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

BRAKES = [
    {"kind": "labor", "description": "Replace front pads and rotors", "quantity": "2.0"},
    {"kind": "part", "description": "Pad set", "unit_price_cents": 8911, "unit_cost_cents": 5400},
    {"kind": "part", "description": "Rotor", "quantity": "2", "unit_price_cents": 13600},
    {"kind": "fee", "description": "Shop supplies", "unit_price_cents": 2000},
]


@pytest.fixture
def wo(client, customer, vehicle):
    r = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "mileage_in": 61240,
            "concern": "Shakes when braking.",
            "internal_notes": "Customer supplied nothing.",
            "items": BRAKES,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _check_all(client, wo_id):
    keys = client.get("/api/work-orders/board").json()["checklist_keys"]
    client.patch(f"/api/work-orders/{wo_id}", json={"qc_checklist": {k: True for k in keys}})


def test_work_order_totals_use_shop_defaults(wo):
    # Labor at the default $100/h, parts taxed at 8%, fee untaxed.
    assert wo["number"] == "WO-" + wo["number"].split("-")[1] + "-0001"
    labor = next(i for i in wo["items"] if i["kind"] == "labor")
    assert labor["unit_price_cents"] == 10000 and labor["taxable"] is False
    assert wo["labor_cents"] == 20000
    assert wo["parts_cents"] == 8911 + 27200
    assert wo["taxable_cents"] == 36111
    assert wo["tax_cents"] == 2889  # 2888.88 rounded half-up
    assert wo["total_cents"] == 20000 + 36111 + 2000 + 2889


def test_part_price_from_markup(client, wo):
    r = client.post(
        f"/api/work-orders/{wo['id']}/items",
        json={"kind": "part", "description": "Bulb", "unit_cost_cents": 1000},
    )
    bulb = r.json()["items"][-1]
    assert bulb["unit_price_cents"] == 1500  # shop default markup 50%
    r = client.post(
        f"/api/work-orders/{wo['id']}/items", json={"kind": "fee", "description": "No amount"}
    )
    assert r.status_code == 422


def test_vehicle_must_belong_to_customer(client, vehicle):
    other = client.post("/api/customers", json={"first_name": "Jane", "phone": "555"}).json()
    r = client.post(
        "/api/work-orders", json={"customer_id": other["id"], "vehicle_id": vehicle["id"]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_reference"


def test_numbers_are_sequential(client, customer, vehicle):
    body = {"customer_id": customer["id"], "vehicle_id": vehicle["id"]}
    numbers = [client.post("/api/work-orders", json=body).json()["number"] for _ in range(3)]
    assert [n[-4:] for n in numbers] == ["0001", "0002", "0003"]


def test_concurrent_numbering_never_duplicates():
    from conftest import TEST_DB

    from app.core.numbering import next_number

    engine = create_engine(TEST_DB, pool_size=10)
    results, errors = [], []

    def take():
        try:
            with Session(engine) as db:
                results.append(next_number(db, "invoice", "INV", 2030))
                db.commit()
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=take) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    assert not errors
    assert sorted(results) == [f"INV-2030-{i:04d}" for i in range(1, 21)]


def test_estimate_lifecycle_and_conversion(client, wo):
    est = client.post(
        "/api/estimates",
        json={
            "customer_id": wo["customer_id"],
            "vehicle_id": wo["vehicle_id"],
            "work_order_id": wo["id"],
        },
    ).json()
    assert est["total_cents"] == wo["total_cents"]  # copied from the work order
    assert est["status"] == "draft" and est["expires_on"] is not None

    # Can't approve conversion before approval.
    assert client.post(f"/api/estimates/{est['id']}/convert").status_code == 409

    sent = client.post(f"/api/estimates/{est['id']}/mark-sent").json()
    assert sent["status"] == "sent" and sent["locked_at"]
    # Locked: lines and customer-facing fields can't change; internal notes can.
    r = client.post(
        f"/api/estimates/{est['id']}/items",
        json={"kind": "fee", "description": "x", "unit_price_cents": 1},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "estimate_locked"
    assert client.patch(f"/api/estimates/{est['id']}", json={"concern": "x"}).status_code == 409
    assert (
        client.patch(f"/api/estimates/{est['id']}", json={"internal_notes": "ok"}).status_code
        == 200
    )

    approved = client.post(
        f"/api/estimates/{est['id']}/decision", json={"decision": "approved", "method": "phone"}
    ).json()
    assert approved["status"] == "approved" and approved["approved_at"]
    assert client.get(f"/api/work-orders/{wo['id']}").json()["status"] == "approved"

    converted = client.post(f"/api/estimates/{est['id']}/convert")
    assert converted.status_code == 201
    assert converted.json()["id"] == wo["id"]
    assert converted.json()["total_cents"] == est["total_cents"]
    assert client.post(f"/api/estimates/{est['id']}/convert").status_code == 409

    actions = [
        e["action"]
        for e in client.get(
            "/api/audit", params={"entity_type": "estimate", "entity_id": est["id"]}
        ).json()
    ]
    assert {"estimate.created", "estimate.sent", "estimate.approved", "estimate.converted"} <= set(
        actions
    )


def test_standalone_estimate_converts_to_new_work_order(client, customer, vehicle):
    est = client.post(
        "/api/estimates",
        json={"customer_id": customer["id"], "vehicle_id": vehicle["id"], "items": BRAKES},
    ).json()
    client.post(
        f"/api/estimates/{est['id']}/decision", json={"decision": "approved", "method": "in_person"}
    )
    wo = client.post(f"/api/estimates/{est['id']}/convert").json()
    assert wo["status"] == "approved" and len(wo["items"]) == 4
    assert client.get(f"/api/estimates/{est['id']}").json()["work_order_id"] == wo["id"]


def test_revision_creates_new_version_and_drops_approval(client, customer, vehicle):
    est = client.post(
        "/api/estimates",
        json={"customer_id": customer["id"], "vehicle_id": vehicle["id"], "items": BRAKES},
    ).json()
    client.post(
        f"/api/estimates/{est['id']}/decision",
        json={"decision": "declined", "method": "phone", "note": "Too expensive"},
    )
    revised = client.post(f"/api/estimates/{est['id']}/revise").json()
    assert revised["version"] == 2 and revised["status"] == "draft"
    assert revised["declined_at"] is None and revised["locked_at"] is None
    assert (
        client.post(
            f"/api/estimates/{est['id']}/items",
            json={"kind": "discount", "description": "Loyalty", "unit_price_cents": 2500},
        ).status_code
        == 201
    )


def test_invoice_payment_flow(client, wo):
    r = client.post(f"/api/work-orders/{wo['id']}/invoice")
    assert r.status_code == 201
    inv = r.json()
    assert inv["total_cents"] == wo["total_cents"] and inv["status"] == "draft"
    assert inv["number"].endswith("-0001")
    # One active invoice per work order.
    dup = client.post(f"/api/work-orders/{wo['id']}/invoice")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_invoiced"

    # Invoice lines are a snapshot: editing the work order doesn't change the invoice.
    client.post(
        f"/api/work-orders/{wo['id']}/items",
        json={"kind": "fee", "description": "Late add", "unit_price_cents": 999},
    )
    assert client.get(f"/api/invoices/{inv['id']}").json()["total_cents"] == inv["total_cents"]

    client.post(f"/api/invoices/{inv['id']}/mark-sent")
    total = inv["total_cents"]

    partial = client.post(
        f"/api/invoices/{inv['id']}/payments", json={"amount_cents": 20000, "method": "cash"}
    )
    assert partial.status_code == 201
    body = partial.json()
    assert body["status"] == "partially_paid" and body["balance_cents"] == total - 20000

    # Charges are frozen once money is received.
    r = client.post(
        f"/api/invoices/{inv['id']}/items",
        json={"kind": "fee", "description": "x", "unit_price_cents": 1},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "invoice_has_payments"

    over = client.post(
        f"/api/invoices/{inv['id']}/payments", json={"amount_cents": total, "method": "check"}
    )
    assert over.status_code == 409 and over.json()["error"]["code"] == "overpayment"
    online = client.post(
        f"/api/invoices/{inv['id']}/payments", json={"amount_cents": 100, "method": "online"}
    )
    assert online.status_code == 422

    paid = client.post(
        f"/api/invoices/{inv['id']}/payments",
        json={"amount_cents": total - 20000, "method": "check", "reference": "Check #1042"},
    ).json()
    assert paid["status"] == "paid" and paid["balance_cents"] == 0 and paid["paid_at"]
    assert (
        client.post(
            f"/api/invoices/{inv['id']}/payments", json={"amount_cents": 1, "method": "cash"}
        ).status_code
        == 409
    )

    # Voiding the invoice requires voiding payments first.
    assert (
        client.post(f"/api/invoices/{inv['id']}/void", json={"reason": "Mistake"}).status_code
        == 409
    )
    pay_id = paid["payments"][0]["id"]
    after = client.post(f"/api/payments/{pay_id}/void", json={"reason": "Entered twice"}).json()
    assert after["status"] == "partially_paid"
    assert after["balance_cents"] == 20000
    assert client.post(f"/api/payments/{pay_id}/void", json={"reason": "again"}).status_code == 409

    payments = client.get("/api/payments").json()
    assert payments["total"] == 2 and payments["items"][0]["invoice_number"] == inv["number"]


def test_void_unpaid_invoice_allows_reinvoicing(client, wo):
    inv = client.post(f"/api/work-orders/{wo['id']}/invoice").json()
    voided = client.post(f"/api/invoices/{inv['id']}/void", json={"reason": "Wrong vehicle"})
    assert voided.json()["status"] == "void"
    assert (
        client.post(
            f"/api/invoices/{inv['id']}/payments", json={"amount_cents": 100, "method": "cash"}
        ).status_code
        == 409
    )
    assert client.post(f"/api/work-orders/{wo['id']}/invoice").status_code == 201


def test_overdue_status(client, customer, vehicle):
    inv = client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "issue_date": "2026-01-01",
            "due_date": "2026-01-15",
            "items": [{"kind": "labor", "description": "Diag", "quantity": "1"}],
        },
    ).json()
    assert inv["status"] == "draft"  # drafts are never overdue
    sent = client.post(f"/api/invoices/{inv['id']}/mark-sent").json()
    assert sent["status"] == "overdue"
    bad = client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "issue_date": "2026-02-01",
            "due_date": "2026-01-01",
            "items": [],
        },
    )
    assert bad.status_code == 422


def test_completion_requires_checklist(client, wo):
    r = client.post(f"/api/work-orders/{wo['id']}/status", json={"status": "completed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "checklist_incomplete"
    _check_all(client, wo["id"])
    done = client.post(f"/api/work-orders/{wo['id']}/status", json={"status": "completed"}).json()
    assert done["status"] == "completed" and done["completed_at"]
    # Completed work orders are frozen until reopened.
    assert (
        client.post(
            f"/api/work-orders/{wo['id']}/items",
            json={"kind": "fee", "description": "x", "unit_price_cents": 1},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/work-orders/{wo['id']}", json={"internal_notes": "still editable"}
        ).status_code
        == 200
    )
    reopened = client.post(
        f"/api/work-orders/{wo['id']}/status", json={"status": "in_repair"}
    ).json()
    assert reopened["completed_at"] is None


def test_override_checklist_is_audited(client, wo):
    r = client.post(
        f"/api/work-orders/{wo['id']}/status",
        json={"status": "completed", "override_checklist": True},
    )
    assert r.status_code == 200
    log = client.get(
        "/api/audit", params={"entity_type": "work_order", "entity_id": wo["id"]}
    ).json()
    assert any(e["details"].get("checklist_overridden") for e in log)


def test_board_and_dashboard(client, wo):
    board = client.get("/api/work-orders/board").json()
    new_col = next(c for c in board["columns"] if c["status"] == "new")
    assert [w["id"] for w in new_col["work_orders"]] == [wo["id"]]

    inv = client.post(f"/api/work-orders/{wo['id']}/invoice").json()
    client.post(f"/api/invoices/{inv['id']}/mark-sent")
    client.post(
        f"/api/invoices/{inv['id']}/payments", json={"amount_cents": 10000, "method": "cash"}
    )
    d = client.get("/api/dashboard").json()
    assert d["revenue"]["today_cents"] == 10000
    assert d["outstanding_cents"] == inv["total_cents"] - 10000
    assert [w["id"] for w in d["open_work_orders"]] == [wo["id"]]
    assert d["unpaid_invoices"][0]["number"] == inv["number"]


def test_mileage_updates_vehicle(client, wo, vehicle):
    assert client.get(f"/api/vehicles/{vehicle['id']}").json()["mileage"] == 61240
    client.patch(f"/api/work-orders/{wo['id']}", json={"mileage_out": 61260})
    assert client.get(f"/api/vehicles/{vehicle['id']}").json()["mileage"] == 61260
