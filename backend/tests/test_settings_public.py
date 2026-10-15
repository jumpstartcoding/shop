from decimal import Decimal


def test_settings_update_and_validation(client):
    r = client.patch(
        "/api/settings",
        json={
            "name": "Ridgeline Auto",
            "tax_rate": "6.625",
            "invoice_prefix": "rid",
            "hours": {"mon": {"open": "08:00", "close": "17:00"}, "sun": None},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["invoice_prefix"] == "RID"
    assert Decimal(client.get("/api/settings").json()["tax_rate"]) == Decimal("6.625")
    assert client.patch("/api/settings", json={"tax_rate": "-1"}).status_code == 422
    assert client.patch("/api/settings", json={"invoice_prefix": "IN V"}).status_code == 422
    assert client.patch("/api/settings", json={"hours": {"funday": None}}).status_code == 422
    assert client.patch("/api/settings", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.patch("/api/settings", json={"name": None}).status_code == 422


def test_new_prefix_used_for_next_invoice(client, customer, vehicle):
    client.patch("/api/settings", json={"invoice_prefix": "RID"})
    inv = client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "items": [{"kind": "labor", "description": "x", "quantity": "1"}],
        },
    ).json()
    assert inv["number"].startswith("RID-")


def test_public_endpoints_need_no_login_and_hide_internal_settings(anon, client):
    client.post("/api/services", json={"name": "Brake Service", "category": "Brakes"})
    client.post("/api/services", json={"name": "Hidden", "is_published": False})
    biz = anon.get("/api/public/business")
    assert biz.status_code == 200
    assert "tax_rate" not in biz.json() and "default_labor_rate_cents" not in biz.json()
    names = [s["name"] for s in anon.get("/api/public/services").json()]
    assert names == ["Brake Service"]


def test_service_slugs_are_unique(client):
    a = client.post("/api/services", json={"name": "Oil Change"}).json()
    b = client.post("/api/services", json={"name": "Oil  Change!"}).json()
    assert a["slug"] == "oil-change" and b["slug"] == "oil-change-2"


def test_health(anon):
    r = anon.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": True}


def test_errors_have_consistent_shape(client):
    r = client.post("/api/customers", json={"first_name": 5})
    assert r.status_code == 422
    assert set(r.json()["error"]) >= {"code", "message"}
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_seed_demo_runs_full_workflow():
    from app.seed import seed_demo

    result = seed_demo()
    assert result["ok"] and result["demo_total_cents"] == 65000
    assert seed_demo()["ok"] is False  # refuses to run twice
