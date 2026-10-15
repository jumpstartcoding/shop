def test_create_customer_with_vehicle_in_one_step(customer):
    assert customer["full_name"] == "John Smith"
    v = customer["vehicles"][0]
    assert v["vin"] == "1HGCV1F13JA000001"  # normalized to uppercase
    assert v["license_plate"] == "ABC123"
    assert v["display_name"] == "2018 Honda Accord"


def test_customer_needs_phone_or_email(client):
    r = client.post("/api/customers", json={"first_name": "No", "last_name": "Contact"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_blank_fields_become_null(client):
    r = client.post(
        "/api/customers",
        json={"first_name": "  Ann ", "phone": "555-0000", "email": "  ", "city": ""},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["first_name"] == "Ann" and body["email"] is None and body["city"] is None


def test_vin_rules(client, customer):
    cid = customer["id"]
    bad = client.post("/api/vehicles", json={"customer_id": cid, "vin": "1HGCV1F13JA00000I"})
    assert bad.status_code == 422  # I/O/Q not allowed in 17-char VIN
    dup = client.post(
        "/api/vehicles", json={"customer_id": cid, "make": "Honda", "vin": "1HGCV1F13JA000001"}
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_vin"
    old = client.post(
        "/api/vehicles", json={"customer_id": cid, "make": "Ford", "vin": "7F02H123456"}
    )
    assert old.status_code == 201  # pre-1981 shorter VINs are allowed


def test_search_by_name_phone_vin_plate(client, customer):
    for q in ("smith", "0100101", "555-010-0101", "A000001", "abc 123", "accord"):
        r = client.get("/api/customers", params={"q": q})
        assert r.status_code == 200
        assert [c["id"] for c in r.json()["items"]] == [customer["id"]], q
    assert client.get("/api/customers", params={"q": "zzz"}).json()["total"] == 0


def test_global_search(client, customer):
    r = client.get("/api/search", params={"q": "ABC123"}).json()
    assert r["vehicles"][0]["owner"] == "John Smith"
    r = client.get("/api/search", params={"q": "John"}).json()
    assert r["customers"][0]["id"] == customer["id"]


def test_update_and_archive(client, customer):
    cid = customer["id"]
    r = client.patch(
        f"/api/customers/{cid}", json={"phone": "555 222 3333", "internal_notes": "Secret note"}
    )
    assert r.status_code == 200 and r.json()["phone"] == "555 222 3333"
    assert client.get("/api/customers", params={"q": "2223333"}).json()["total"] == 1
    # Can't clear the only remaining contact method.
    assert (
        client.patch(f"/api/customers/{cid}", json={"phone": None, "email": None}).status_code
        == 409
    )
    assert client.patch(f"/api/customers/{cid}", json={"first_name": ""}).status_code == 422

    client.post(f"/api/customers/{cid}/archive")
    assert client.get("/api/customers").json()["total"] == 0
    assert client.get("/api/customers", params={"include_archived": True}).json()["total"] == 1


def test_audit_does_not_copy_internal_notes(client, customer):
    client.patch(f"/api/customers/{customer['id']}", json={"internal_notes": "Pays late"})
    log = client.get(
        "/api/audit", params={"entity_type": "customer", "entity_id": customer["id"]}
    ).json()
    updated = next(e for e in log if e["action"] == "customer.updated")
    assert "Pays late" not in str(updated["details"])


def test_vehicle_transfer_and_history(client, customer, vehicle):
    other = client.post("/api/customers", json={"first_name": "Jane", "phone": "555"}).json()
    r = client.patch(f"/api/vehicles/{vehicle['id']}", json={"customer_id": other["id"]})
    assert r.status_code == 200 and r.json()["customer_id"] == other["id"]
    h = client.get(f"/api/vehicles/{vehicle['id']}/history").json()
    assert set(h) == {"work_orders", "estimates", "invoices", "appointments", "payments"}


def test_unknown_ids_are_404(client):
    assert client.get("/api/customers/999").status_code == 404
    assert client.get("/api/vehicles/999").status_code == 404
    assert client.get("/api/work-orders/999").status_code == 404
    assert client.get("/api/invoices/999").status_code == 404


def test_appointments(client, customer, vehicle):
    body = {
        "customer_id": customer["id"],
        "vehicle_id": vehicle["id"],
        "starts_at": "2026-11-02T09:00:00-05:00",
        "ends_at": "2026-11-02T11:00:00-05:00",
        "requested_service": "Brake Service",
    }
    r = client.post("/api/appointments", json=body)
    assert r.status_code == 201
    appt = r.json()
    assert appt["status"] == "confirmed" and appt["vehicle_name"] == "2018 Honda Accord"

    # Drag to a new slot.
    r = client.patch(
        f"/api/appointments/{appt['id']}",
        json={"starts_at": "2026-11-03T13:00:00-05:00", "ends_at": "2026-11-03T14:00:00-05:00"},
    )
    assert r.status_code == 200
    week = client.get(
        "/api/appointments",
        params={"from": "2026-11-02T00:00:00-05:00", "to": "2026-11-09T00:00:00-05:00"},
    ).json()
    assert [a["id"] for a in week] == [appt["id"]]

    # End before start, and a naive timestamp, are rejected.
    assert (
        client.patch(
            f"/api/appointments/{appt['id']}", json={"ends_at": "2026-11-03T12:00:00-05:00"}
        ).status_code
        == 422
    )
    body2 = {**body, "starts_at": "2026-11-02T09:00:00", "ends_at": None}
    assert client.post("/api/appointments", json=body2).status_code == 422

    # Vehicle must belong to the customer.
    other = client.post("/api/customers", json={"first_name": "Jane", "phone": "555"}).json()
    assert (
        client.post("/api/appointments", json={**body, "customer_id": other["id"]}).status_code
        == 422
    )


def test_length_limits_still_enforced(client):
    r = client.post("/api/customers", json={"first_name": "A", "phone": "555", "city": "x" * 101})
    assert r.status_code == 422
