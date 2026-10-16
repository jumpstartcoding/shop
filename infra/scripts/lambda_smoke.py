"""Smoke-test the Lambda container image through the AWS Lambda Runtime Interface Emulator.

CI starts the image with the emulator (see .github/workflows/ci.yml), then runs:

    python infra/scripts/lambda_smoke.py http://127.0.0.1:9000 cf-test-secret

It drives the app exactly as Lambda would: direct task invocations and Function URL
(payload v2) events, including cookies, CSRF, the origin secret, and a binary PDF response.
Standard library only.
"""

import base64
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:9000"
SECRET = sys.argv[2] if len(sys.argv) > 2 else "cf-test-secret"
URL = f"{BASE}/2015-03-31/functions/function/invocations"
cookies: dict[str, str] = {}


def invoke(payload: dict) -> dict:
    req = urllib.request.Request(URL, json.dumps(payload).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def http(method: str, path: str, body=None, secret: str | None = SECRET):
    headers = {
        "host": "abc.lambda-url.us-east-1.on.aws",
        "content-type": "application/json",
        "x-viewer-ip": "203.0.113.9",
        "x-forwarded-for": "6.6.6.6, 130.176.0.1",
    }
    if secret:
        headers["x-origin-secret"] = secret
    if "shop_csrf" in cookies:
        headers["x-csrf-token"] = cookies["shop_csrf"]
    raw = json.dumps(body).encode() if body is not None else None
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "cookies": [f"{k}={v}" for k, v in cookies.items()],
        "headers": headers,
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
            "requestId": "smoke",
            "routeKey": "$default",
            "stage": "$default",
            "time": "15/Oct/2026:00:00:00 +0000",
            "timeEpoch": 0,
        },
        "body": base64.b64encode(raw).decode() if raw else None,
        "isBase64Encoded": bool(raw),
    }
    r = invoke(event)
    for c in r.get("cookies", []):
        k, v = c.split(";")[0].split("=", 1)
        cookies[k] = v
    data = r.get("body") or ""
    data = base64.b64decode(data) if r.get("isBase64Encoded") else data.encode()
    return r["statusCode"], r.get("headers", {}), data


def check(label: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f": {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


r = invoke({"task": "migrate"})
check("migrations", r.get("ok") is True, r)

r = invoke({"task": "doctor"})
status = {c["id"]: c["status"] for c in r["checks"]}
for id in ("database", "migrations", "storage", "pdf"):
    check(f"doctor {id}", status[id] == "ok", [c for c in r["checks"] if c["id"] == id])

check("setup_shop", invoke({"task": "setup_shop"}).get("ok") is True)
r = invoke(
    {
        "task": "create_admin",
        "email": "owner@example.com",
        "name": "Owner",
        "password": "smoke-test-password",
    }
)
check("create_admin", r.get("ok") is True, r)

check("direct call without origin secret is refused", http("GET", "/api/health", secret=None)[0] == 403)
check("health", http("GET", "/api/health")[0] == 200)
s, _, b = http("GET", "/api/public/business")
check("public site data", s == 200 and json.loads(b)["name"] == "Ridgeline Auto Repair")

s, _, b = http(
    "POST", "/api/auth/login", {"email": "owner@example.com", "password": "smoke-test-password"}
)
check("login sets session + csrf cookies", s == 200 and {"shop_session", "shop_csrf"} <= set(cookies))

s, _, b = http(
    "POST",
    "/api/customers",
    {
        "first_name": "Smoke",
        "last_name": "Test",
        "phone": "5550100100",
        "vehicle": {"year": 2018, "make": "Honda", "model": "Accord"},
    },
)
check("create customer", s == 201, b[:200])
cust = json.loads(b)

s, _, b = http(
    "POST",
    "/api/invoices",
    {
        "customer_id": cust["id"],
        "vehicle_id": cust["vehicles"][0]["id"],
        "items": [{"kind": "labor", "description": "Brake inspection", "quantity": "1"}],
    },
)
check("create invoice", s == 201, b[:200])
inv = json.loads(b)

s, h, b = http("GET", f"/api/invoices/{inv['id']}/pdf")
check(
    "invoice PDF through Lambda",
    s == 200 and h.get("content-type") == "application/pdf" and b.startswith(b"%PDF"),
    f"{len(b)} bytes",
)
print("Lambda image smoke test passed.")
