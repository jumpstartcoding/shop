"""Security properties checked across the whole API rather than route by route (spec §52)."""

import re

from app.main import create_app

# Everything else under /api requires a signed-in user.
PUBLIC = {
    "/api/health",
    "/api/auth/login",
    "/api/webhooks/stripe",
}
PUBLIC_PREFIXES = ("/api/public/",)


def _routes():
    # The OpenAPI schema lists every route the app serves, including routers mounted
    # with a prefix. Routes hidden from the schema are added below.
    for path, ops in create_app().openapi()["paths"].items():
        for method in ops:
            yield method.upper(), path
    yield "POST", "/api/webhooks/stripe"  # include_in_schema=False


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_private_route_requires_sign_in(anon):
    checked = 0
    for method, path in _routes():
        if path in PUBLIC or path.startswith(PUBLIC_PREFIXES):
            continue
        r = anon.request(method, _fill(path), json={})
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without sign-in"
        checked += 1
    assert checked > 60  # the list really covered the admin API


def test_state_changes_need_csrf_on_every_private_route(client):
    token = client.headers.pop("X-CSRF-Token")
    try:
        for method, path in _routes():
            if method == "GET" or path in PUBLIC or path.startswith(PUBLIC_PREFIXES):
                continue
            if path == "/api/auth/logout":
                continue  # logging out without the header is harmless and allowed
            r = client.request(method, _fill(path), json={})
            assert r.status_code == 403, f"{method} {path} answered {r.status_code} without CSRF"
    finally:
        client.headers["X-CSRF-Token"] = token


def test_public_routes_are_the_expected_ones():
    public = sorted({p for _, p in _routes() if p in PUBLIC or p.startswith(PUBLIC_PREFIXES)})
    assert public == [
        "/api/auth/login",
        "/api/health",
        "/api/public/appointments",
        "/api/public/business",
        "/api/public/contact",
        "/api/public/links/{token}",
        "/api/public/links/{token}/checkout",
        "/api/public/links/{token}/pdf",
        "/api/public/links/{token}/photos/{photo_id}",
        "/api/public/links/{token}/question",
        "/api/public/links/{token}/receipts/{payment_id}",
        "/api/public/links/{token}/respond",
        "/api/public/logo",
        "/api/public/services",
        "/api/webhooks/stripe",
    ]


def test_customer_link_page_never_carries_internal_fields(client, customer, vehicle):
    est = client.post(
        "/api/estimates",
        json={
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "concern": "Brakes squeal",
            "internal_notes": "SECRET-SHOP-NOTE",
            "items": [
                {
                    "kind": "part",
                    "description": "Pads",
                    "quantity": "1",
                    "unit_cost_cents": 4111,
                    "markup_pct": "50",
                }
            ],
        },
    ).json()
    link = client.post(f"/api/estimates/{est['id']}/send", json={"email": False}).json()["link"]
    from fastapi.testclient import TestClient

    with TestClient(create_app(), base_url="https://testserver") as stranger:
        token = link.rsplit("/", 1)[1]
        body = stranger.get(f"/api/public/links/{token}").text
        pdf = stranger.get(f"/api/public/links/{token}/pdf")
    assert "SECRET-SHOP-NOTE" not in body
    assert "4111" not in body and "unit_cost" not in body and "markup" not in body
    assert pdf.status_code == 200 and b"SECRET-SHOP-NOTE" not in pdf.content


def test_link_tokens_are_not_guessable(anon):
    for token in ("1", "abc", "x" * 43, "../../etc/passwd"):
        assert anon.get(f"/api/public/links/{token}").status_code in (404, 422)
