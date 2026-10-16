"""Phase 5: vendors, parts and stock, expenses, reminders, nightly upkeep, reports, export, VIN."""

import csv
import io
from datetime import date, timedelta

import pytest
from conftest import TEST_DB
from sqlalchemy import create_engine, text
from test_inspections import jpeg, upload


def sql(q: str, **params):
    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        r = c.execute(text(q), params)
        rows = r.fetchall() if r.returns_rows else None
    eng.dispose()
    return rows


def today() -> date:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).date()


# ------------------------------------------------------------------ vendors & parts


def test_vendors(client):
    r = client.post(
        "/api/vendors", json={"name": "  NAPA  ", "phone": "5550100200", "account_number": "A-77"}
    )
    assert r.status_code == 201 and r.json()["name"] == "NAPA"
    v = r.json()
    assert client.post("/api/vendors", json={"name": ""}).status_code == 422
    assert client.post("/api/vendors", json={"name": "X", "email": "nope"}).status_code == 422
    upd = client.patch(f"/api/vendors/{v['id']}", json={"notes": "Delivers twice a day"})
    assert upd.json()["notes"] == "Delivers twice a day" and upd.json()["name"] == "NAPA"
    client.post(f"/api/vendors/{v['id']}/archive")
    assert client.get("/api/vendors").json() == []
    assert [x["id"] for x in client.get("/api/vendors?archived=true").json()] == [v["id"]]


def test_parts_list_pricing_search_and_stock(client):
    vendor = client.post("/api/vendors", json={"name": "Sample Parts"}).json()
    assert client.post("/api/parts", json={"name": "Wiper"}).status_code == 422  # no price at all
    assert (
        client.post(
            "/api/parts", json={"name": "Wiper", "cost_cents": 500, "vendor_id": 999}
        ).status_code
        == 422
    )
    pad = client.post(
        "/api/parts",
        json={
            "name": "Ceramic brake pads",
            "part_number": "D1234",
            "category": "Brakes",
            "vendor_id": vendor["id"],
            "cost_cents": 4000,
            "quantity": "4",
            "reorder_at": "2",
            "warranty_months": 12,
        },
    ).json()
    # No customer price: the shop's default markup (50% in tests) is applied to cost.
    assert pad["effective_price_cents"] == 6000 and pad["price_from_markup"] is True
    assert pad["vendor_name"] == "Sample Parts" and pad["low_stock"] is False
    oil = client.post("/api/parts", json={"name": "5W-30 oil, quart", "price_cents": 900}).json()
    assert oil["quantity"] is None  # not tracked

    assert [p["id"] for p in client.get("/api/parts?q=d12").json()] == [pad["id"]]
    assert [p["id"] for p in client.get("/api/parts?q=brakes").json()] == [pad["id"]]
    assert client.get("/api/parts?q=%25").json() == []  # wildcards are literal

    low = client.post(
        f"/api/parts/{pad['id']}/stock", json={"change": "-2", "reason": "Count"}
    ).json()
    assert float(low["quantity"]) == 2 and low["low_stock"] is True
    assert [p["id"] for p in client.get("/api/parts?low_stock=true").json()] == [pad["id"]]
    dash = client.get("/api/dashboard").json()
    assert any(n["kind"] == "low_stock" for n in dash["notifications"])
    started = client.post(f"/api/parts/{oil['id']}/stock", json={"change": "12"}).json()
    assert float(started["quantity"]) == 12  # adjusting starts tracking

    upd = client.patch(f"/api/parts/{pad['id']}", json={"price_cents": 6500})
    assert upd.json()["effective_price_cents"] == 6500 and upd.json()["price_from_markup"] is False


def test_stock_follows_completed_work(client, customer, vehicle):
    pad = client.post(
        "/api/parts", json={"name": "Pads", "price_cents": 6000, "quantity": "5"}
    ).json()
    untracked = client.post("/api/parts", json={"name": "Shop rag", "price_cents": 100}).json()
    bad = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": [
                {"kind": "part", "description": "Ghost", "unit_price_cents": 1, "part_id": 999999}
            ],
        },
    )
    assert bad.status_code == 422
    wo = client.post(
        "/api/work-orders",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": [
                {
                    "kind": "part",
                    "description": "Pads",
                    "quantity": "2",
                    "unit_price_cents": 6000,
                    "part_id": pad["id"],
                },
                {
                    "kind": "part",
                    "description": "Rag",
                    "unit_price_cents": 100,
                    "part_id": untracked["id"],
                },
            ],
        },
    ).json()
    assert [li["part_id"] for li in wo["items"]] == [pad["id"], untracked["id"]]
    inv = client.post(f"/api/work-orders/{wo['id']}/invoice").json()
    assert inv["items"][0]["part_id"] == pad["id"]

    def qty(pid):
        return float(
            next(p for p in client.get("/api/parts").json() if p["id"] == pid)["quantity"] or 0
        )

    def status(s):
        r = client.post(
            f"/api/work-orders/{wo['id']}/status", json={"status": s, "override_checklist": True}
        )
        assert r.status_code == 200, r.text

    assert qty(pad["id"]) == 5  # nothing taken until the job is done
    status("completed")
    assert qty(pad["id"]) == 3
    status("in_repair")  # reopened: parts go back
    assert qty(pad["id"]) == 5
    status("completed")
    assert qty(pad["id"]) == 3
    assert qty(untracked["id"]) == 0  # untracked stays untracked


# ------------------------------------------------------------------ expenses


def test_expenses(client):
    vendor = client.post("/api/vendors", json={"name": "Snap-on"}).json()
    t = today()
    e1 = client.post(
        "/api/expenses",
        json={
            "expense_date": str(t),
            "category": "tools",
            "amount_cents": 25999,
            "vendor_id": vendor["id"],
            "description": "Torque wrench",
        },
    )
    assert e1.status_code == 201 and e1.json()["vendor_name"] == "Snap-on"
    client.post(
        "/api/expenses",
        json={
            "expense_date": str(t),
            "category": "rent",
            "amount_cents": 150000,
            "vendor_name": "Landlord",
        },
    )
    old = client.post(
        "/api/expenses",
        json={"expense_date": "2025-01-15", "category": "rent", "amount_cents": 140000},
    ).json()
    assert (
        client.post(
            "/api/expenses", json={"expense_date": str(t), "category": "fun", "amount_cents": 1}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/expenses", json={"expense_date": str(t), "category": "rent", "amount_cents": 0}
        ).status_code
        == 422
    )

    month = client.get("/api/expenses").json()
    assert month["total_cents"] == 175999 and month["by_category"] == {
        "tools": 25999,
        "rent": 150000,
    }
    rent = client.get(
        "/api/expenses", params={"start": "2025-01-01", "end": str(t), "category": "rent"}
    ).json()
    assert rent["total_cents"] == 290000

    receipt = upload(client, "expense", e1.json()["id"], jpeg(), caption="Receipt")
    assert receipt.status_code == 201
    listed = client.get("/api/expenses").json()["items"]
    assert (
        next(x for x in listed if x["id"] == e1.json()["id"])["receipts"][0]["caption"] == "Receipt"
    )

    assert (
        client.patch(f"/api/expenses/{old['id']}", json={"amount_cents": 145000}).json()[
            "amount_cents"
        ]
        == 145000
    )
    assert client.delete(f"/api/expenses/{old['id']}").status_code == 204
    assert upload(client, "expense", old["id"]).status_code == 404
    assert (
        client.get("/api/expenses", params={"start": "2025-01-01", "end": "2025-12-31"}).json()[
            "items"
        ]
        == []
    )


# ------------------------------------------------------------------ reminders & nightly


@pytest.fixture
def reminder_setup(client, vehicle):
    client.patch("/api/settings", json={"email": "owner@example.com", "reminder_lead_days": 14})
    return vehicle


def test_reminders_due_send_and_close(client, reminder_setup, outbox):
    v = reminder_setup
    t = today()
    r = client.post(
        f"/api/vehicles/{v['id']}/reminders",
        json={"kind": "oil_change", "due_date": str(t + timedelta(days=10))},
    )
    assert r.status_code == 201 and r.json()["title"] == "Oil change" and r.json()["due"] is True
    soon = r.json()
    later = client.post(
        f"/api/vehicles/{v['id']}/reminders",
        json={"kind": "brake_inspection", "due_date": str(t + timedelta(days=60))},
    ).json()
    assert later["due"] is False
    by_miles = client.post(
        f"/api/vehicles/{v['id']}/reminders",
        json={"kind": "custom", "title": "Timing belt", "due_mileage": 61300},  # vehicle at 61,000
    ).json()
    assert by_miles["due"] is True
    assert (
        client.post(f"/api/vehicles/{v['id']}/reminders", json={"kind": "custom"}).status_code
        == 422
    )

    due = client.get("/api/reminders").json()
    assert {x["id"] for x in due} == {soon["id"], by_miles["id"]}
    dash = client.get("/api/dashboard").json()
    assert any(n["kind"] == "reminders_due" and n["count"] == 2 for n in dash["notifications"])

    sent = client.post(f"/api/reminders/{soon['id']}/send").json()
    assert sent["email"]["status"] == "sent" and sent["reminder"]["emailed_at"]
    mail = outbox()[-1]
    body = mail.get_body().get_content()
    assert "oil change" in body and "https://shop.example/book" in body

    done = client.patch(f"/api/reminders/{soon['id']}", json={"status": "done"}).json()
    assert done["status"] == "done" and done["due"] is False
    assert {x["id"] for x in client.get("/api/reminders").json()} == {by_miles["id"]}
    assert len(client.get(f"/api/vehicles/{v['id']}/reminders").json()) == 3
    reopened = client.patch(f"/api/reminders/{soon['id']}", json={"status": "open"}).json()
    assert reopened["emailed_at"] is None
    cleared = client.patch(f"/api/reminders/{later['id']}", json={"due_date": None})
    assert cleared.status_code == 422  # would leave it with no due date or mileage


def test_nightly_upkeep(client, customer, vehicle, outbox):
    from app.tasks import nightly

    t = today()
    client.patch("/api/settings", json={"email": "owner@example.com"})
    client.post(
        f"/api/vehicles/{vehicle['id']}/reminders", json={"kind": "oil_change", "due_date": str(t)}
    )
    est = client.post(
        "/api/estimates",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": [{"kind": "labor", "description": "x", "quantity": "1"}],
        },
    ).json()
    client.post(f"/api/estimates/{est['id']}/send", json={"email": False})
    sql("UPDATE estimates SET expires_on = :d WHERE id = :i", d=t - timedelta(days=1), i=est["id"])

    off = nightly()
    assert off["estimates_expired"] == 1 and off["reminder_emails"] == "off"
    assert client.get(f"/api/estimates/{est['id']}").json()["status"] == "expired"
    before = len(outbox())
    client.patch("/api/settings", json={"reminder_emails": True})
    on = nightly()
    assert on["reminders_emailed"] == 1 and len(outbox()) == before + 1
    assert nightly()["reminders_emailed"] == 0  # once per reminder


# ------------------------------------------------------------------ reports


def _invoice(client, customer, vehicle, labor_hours="1", part_cents=None):
    items = [{"kind": "labor", "description": "Labor", "quantity": labor_hours}]
    if part_cents:
        items.append({"kind": "part", "description": "Part", "unit_price_cents": part_cents})
    return client.post(
        "/api/invoices",
        json={"customer_id": customer["id"], "vehicle_id": vehicle["id"], "items": items},
    ).json()


def test_report_summary(client, customer, vehicle):
    t = today()
    a = _invoice(
        client, customer, vehicle, "2", 10000
    )  # labor 20000 (rate 10000) + part 10000 + 8% tax on part
    b = _invoice(client, customer, vehicle, "1")
    void = _invoice(client, customer, vehicle, "5")
    client.post(f"/api/invoices/{void['id']}/void", json={"reason": "Mistake"})
    client.post(f"/api/invoices/{a['id']}/mark-sent")
    client.post(f"/api/invoices/{b['id']}/mark-sent")
    client.post(
        f"/api/invoices/{a['id']}/payments",
        json={"amount_cents": a["total_cents"], "method": "cash"},
    )
    client.post(f"/api/invoices/{b['id']}/payments", json={"amount_cents": 4000, "method": "card"})
    old = client.post(
        f"/api/invoices/{b['id']}/payments",
        json={"amount_cents": 1000, "method": "check", "paid_at": "2025-06-01T12:00:00-04:00"},
    )
    assert old.status_code == 201
    client.post(
        "/api/expenses", json={"expense_date": str(t), "category": "supplies", "amount_cents": 5000}
    )

    r = client.get(
        "/api/reports/summary", params={"start": str(t.replace(day=1)), "end": str(t)}
    ).json()
    assert r["collected"]["total_cents"] == a["total_cents"] + 4000
    assert r["collected"]["by_method"] == {"cash": a["total_cents"], "card": 4000}
    assert r["collected"]["period"] == "day" and r["collected"]["by_period"][-1]["period"] == str(t)
    inv = r["invoiced"]
    assert inv["count"] == 2 and inv["labor_cents"] == 30000 and inv["parts_cents"] == 10000
    assert inv["tax_cents"] == 800 and inv["total_cents"] == a["total_cents"] + b["total_cents"]
    assert inv["average_cents"] == round((a["total_cents"] + b["total_cents"]) / 2)
    assert inv["paid_count"] == 1 and inv["unpaid_count"] == 1
    assert r["outstanding_cents"] == b["total_cents"] - 5000
    assert r["expenses"]["total_cents"] == 5000
    assert r["collected_less_expenses_cents"] == a["total_cents"] + 4000 - 5000
    assert "not tax or accounting advice" in r["notice"]

    year = client.get("/api/reports/summary", params={"start": "2025-01-01", "end": str(t)}).json()
    assert (
        year["collected"]["period"] == "month"
        and year["collected"]["total_cents"] == a["total_cents"] + 5000
    )
    assert (
        client.get(
            "/api/reports/summary", params={"start": str(t), "end": "2020-01-01"}
        ).status_code
        == 422
    )


# ------------------------------------------------------------------ export


def test_csv_exports(client, customer, vehicle):
    client.post(
        "/api/customers",
        json={"first_name": '=HYPERLINK("http://x")', "last_name": "Évora", "phone": "5550101234"},
    )
    _invoice(client, customer, vehicle, "1.5", 2599)
    client.post(
        "/api/expenses",
        json={"expense_date": str(today()), "category": "tools", "amount_cents": 1234},
    )
    for ds in (
        "customers",
        "vehicles",
        "work_orders",
        "invoices",
        "payments",
        "expenses",
        "parts",
        "service_history",
    ):
        r = client.get(f"/api/export/{ds}.csv")
        assert r.status_code == 200, (ds, r.text)
        assert r.headers["content-type"].startswith("text/csv")
        assert f"shop-{ds.replace('_', '-')}-" in r.headers["content-disposition"]
        assert r.content.startswith("﻿".encode())
    rows = list(
        csv.reader(io.StringIO(client.get("/api/export/customers.csv").content.decode("utf-8-sig")))
    )
    assert rows[0][:3] == ["id", "first_name", "last_name"]
    hostile = next(r for r in rows if "HYPERLINK" in r[1])
    assert hostile[1].startswith("'=") and hostile[2] == "Évora"
    inv = list(
        csv.DictReader(
            io.StringIO(client.get("/api/export/invoices.csv").content.decode("utf-8-sig"))
        )
    )
    assert inv[0]["labor"] == "150.00" and inv[0]["parts"] == "25.99"
    exp = list(
        csv.DictReader(
            io.StringIO(client.get("/api/export/expenses.csv").content.decode("utf-8-sig"))
        )
    )
    assert exp[0]["amount"] == "12.34"
    assert client.get("/api/export/users.csv").status_code == 422
    logged = sql("SELECT count(*) FROM audit_logs WHERE action = 'export.downloaded'")[0][0]
    assert logged >= 10


# ------------------------------------------------------------------ VIN


VPIC = {
    "Results": [
        {
            "ModelYear": "2018",
            "Make": "HONDA",
            "Model": "Accord",
            "Trim": "LX",
            "DisplacementL": "1.5",
            "EngineCylinders": "4",
            "FuelTypePrimary": "Gasoline",
            "TransmissionStyle": "Continuously Variable Transmission (CVT)",
            "TransmissionSpeeds": "",
            "BodyClass": "Sedan/Saloon",
            "ErrorCode": "0",
            "ErrorText": "0 - VIN decoded clean.",
        }
    ]
}


@pytest.fixture
def vpic():
    from app.core import vin

    calls = []

    def fake(url):
        calls.append(url)
        if fake.fail:
            raise TimeoutError("slow")
        return fake.data

    fake.fail = False
    fake.data = VPIC
    vin.set_fetcher(fake)
    yield fake, calls
    vin.set_fetcher(None)


def test_vin_lookup(client, vpic):
    fake, calls = vpic
    r = client.get("/api/vin/1hgcv1f13ja000001")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d == {
        "vin": "1HGCV1F13JA000001",
        "year": 2018,
        "make": "Honda",
        "model": "Accord",
        "trim": "LX",
        "engine": "1.5L 4-cyl",
        "transmission": "Continuously Variable Transmission (CVT)",
        "body": "Sedan/Saloon",
        "warning": None,
    }
    assert calls[-1].startswith(
        "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/1HGCV1F13JA000001"
    )
    assert client.get("/api/vin/SHORT1234").status_code == 422
    assert client.get("/api/vin/1HGCV1F13JA00000I").status_code == 422
    fake.fail = True
    down = client.get("/api/vin/1HGCV1F13JA000001")
    assert down.status_code == 503 and "by hand" in down.json()["error"]["message"]
    fake.fail = False
    fake.data = {"Results": [{"ModelYear": "", "Make": "", "ErrorCode": "11", "ErrorText": "bad"}]}
    assert client.get("/api/vin/1HGCV1F13JA000001").status_code == 404
