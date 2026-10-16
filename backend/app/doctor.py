"""Go-live checks. Run after every deploy (the deploy workflow prints them to the GitHub job
summary) or by hand:

    uv run python -m app.tasks doctor
    aws lambda invoke --function-name <fn> --payload '{"task":"doctor"}' out.json

Each check is "ok", "warn" (works, but something needs attention before customers use it),
or "fail". Checks marked critical fail the deploy: without them the app cannot work at all.
"""

from collections.abc import Callable
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEMO_EMAIL = "demo@example.com"


class Check:
    def __init__(self, id: str, title: str, critical: bool = False):
        self.id, self.title, self.critical = id, title, critical
        self.status, self.detail = "ok", ""

    def ok(self, detail: str = "") -> None:
        self.status, self.detail = "ok", detail

    def warn(self, detail: str) -> None:
        self.status, self.detail = "warn", detail

    def fail(self, detail: str) -> None:
        self.status, self.detail = "fail", detail

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "critical": self.critical,
            "detail": self.detail,
        }


def alembic_config():
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def _database(c: Check) -> None:
    from app.db import get_engine

    with get_engine().connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar()
    c.ok(f"Connected (PostgreSQL {version}).")


def _migrations(c: Check) -> None:
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.db import get_engine

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with get_engine().connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current == head:
        c.ok(f"Schema is up to date ({head}).")
    else:
        c.fail(f"Database is at {current or 'nothing'}, code expects {head}. Run migrations.")


def _accounts(c: Check) -> None:
    from app.db import get_engine
    from app.models import User

    with Session(get_engine()) as db:
        owners = db.scalar(
            select(func.count()).select_from(User).where(User.is_active, User.role == "owner")
        )
        demo = db.scalar(select(User).where(func.lower(User.email) == DEMO_EMAIL))
    if demo is not None and get_settings().is_production:
        c.fail(f"The demo login {DEMO_EMAIL} exists in production. Deactivate it.")
    elif not owners:
        c.warn("No login yet. Create the owner account (see DEPLOYMENT.md, step 7).")
    else:
        c.ok(f"{owners} owner account(s).")


def _public_url(c: Check) -> None:
    s = get_settings()
    url = urlparse(s.public_base_url)
    if s.is_production and (url.scheme != "https" or url.hostname in (None, "localhost")):
        c.fail(
            f"PUBLIC_BASE_URL is {s.public_base_url!r}. Customer links, payment pages, and "
            "emails use it, so it must be the site's https:// address."
        )
    elif s.public_base_url.endswith("/"):
        c.warn("PUBLIC_BASE_URL should not end with a slash.")
    else:
        c.ok(s.public_base_url)


def _origin_secret(c: Check) -> None:
    s = get_settings()
    if s.origin_secret.get_secret_value():
        c.ok("Requests must come through CloudFront.")
    elif s.is_production:
        c.fail("ORIGIN_SECRET is empty: the Lambda Function URL can be called directly.")
    else:
        c.ok("Not required outside production.")


def _storage(c: Check) -> None:
    from app.core.storage import get_storage

    s = get_settings()
    if s.is_production and s.storage_backend != "s3":
        c.fail("STORAGE_BACKEND must be s3 in production; Lambda's disk is temporary.")
        return
    store = get_storage()
    store.put("_checks/probe.txt", b"ok", "text/plain")
    if store.get("_checks/probe.txt") != b"ok":
        c.fail("Wrote a test file but read back something else.")
        return
    where = f"s3://{s.files_bucket}" if s.storage_backend == "s3" else s.files_dir
    c.ok(f"Read and write work ({where}).")


def _pdf(c: Check) -> None:
    """Render a page with the bundled fonts: proves WeasyPrint, Pango, and the fonts all
    work in this runtime (the Lambda image needs system libraries for this)."""
    from weasyprint import HTML

    from app.documents.render import HERE

    html = (
        "<html><head><link rel='stylesheet' href='templates/base.css'></head>"
        "<body><h1>Check</h1><p>Shop documents render here.</p></body></html>"
    )
    doc = HTML(string=html, base_url=str(HERE)).render()
    pdf = doc.write_pdf()
    families = {f.family for f in doc.fonts.values()}
    if not pdf.startswith(b"%PDF"):
        c.fail("WeasyPrint did not produce a PDF.")
    elif "Barlow" not in families:
        c.fail("PDF rendered without the bundled Barlow fonts: " + ", ".join(sorted(families)))
    else:
        c.ok(f"Rendered a test page ({len(pdf) // 1024} KB) with the shop fonts.")


def _email(c: Check) -> None:
    s = get_settings()
    _, address = parseaddr(s.email_from)
    if s.email_backend != "ses":
        if s.is_production:
            c.fail(f"EMAIL_BACKEND is {s.email_backend!r}; customers will get no email.")
        else:
            c.ok(f"{s.email_backend} backend (development).")
        return
    if not address or address.endswith("@example.com"):
        c.fail(f"EMAIL_FROM is {s.email_from!r}. Set it to an address at your domain.")
        return
    import boto3

    ses = boto3.client("sesv2", region_name=s.aws_region)
    domain = address.rsplit("@", 1)[1]
    verified = False
    for identity in (address, domain):
        try:
            info = ses.get_email_identity(EmailIdentity=identity)
        except ses.exceptions.NotFoundException:
            continue
        if info.get("VerifiedForSendingStatus"):
            verified = True
            break
    if not verified:
        c.fail(
            f"{domain} is not verified in Amazon SES yet. Add the DKIM records shown in the "
            "stack outputs to your DNS, then wait for SES to confirm."
        )
        return
    account = ses.get_account()
    if not account.get("ProductionAccessEnabled"):
        c.warn(
            f"Sending as {address}, but SES is still in sandbox mode: email only reaches "
            "addresses you have verified in SES. Request production access (DEPLOYMENT.md)."
        )
        return
    c.ok(f"Sending as {address}.")


def _stripe(c: Check) -> None:
    from app.core.payments import get_gateway
    from app.services.payments import HANDLERS

    s = get_settings()
    if not s.stripe_secret_key.get_secret_value():
        c.warn("Stripe is not set up. Invoices work; customers can't pay online yet.")
        return
    if not s.stripe_webhook_secret.get_secret_value():
        c.fail("STRIPE_WEBHOOK_SECRET is missing: payments would never be recorded.")
        return
    want_url = s.public_base_url.rstrip("/") + "/api/webhooks/stripe"
    try:
        endpoints = get_gateway().webhook_endpoints()
    except Exception as exc:  # restricted keys may not be allowed to read endpoints
        c.warn(f"Stripe {s.stripe_mode} mode. Couldn't list webhook endpoints: {exc}")
        return
    match = next((e for e in endpoints if e["url"] == want_url), None)
    if match is None:
        c.fail(f"No Stripe webhook endpoint for {want_url} in {s.stripe_mode} mode.")
        return
    if match["status"] != "enabled":
        c.fail(f"The Stripe webhook endpoint is {match['status']}.")
        return
    missing = sorted(set(HANDLERS) - set(match["events"])) if "*" not in match["events"] else []
    if missing:
        c.fail("The Stripe webhook is missing events: " + ", ".join(missing))
        return
    note = " Switch to live keys when you're ready to take real payments." * (
        s.stripe_mode == "test"
    )
    c.ok(f"{s.stripe_mode.capitalize()} mode, webhook endpoint registered.{note}")


def _shop(c: Check) -> None:
    from app.db import get_engine
    from app.services.business import get_business

    with Session(get_engine()) as db:
        b = get_business(db)
        texts = [b.name, b.phone, b.about_text, b.certifications, b.invoice_footer]
        issues = []
        if b.name == "My Auto Repair":
            issues.append("shop name")
        if any(t and "PLACEHOLDER" in t for t in texts) or "555" in (b.phone or ""):
            issues.append("placeholder text or phone number")
        if not b.email or b.email.endswith("@example.com"):
            issues.append("shop email (needed for new-booking and payment notices)")
        db.rollback()
    if issues:
        c.warn("Update in Settings: " + "; ".join(issues) + ".")
    else:
        c.ok(b.name)


CHECKS: list[tuple[str, str, bool, Callable[[Check], None]]] = [
    ("database", "Database", True, _database),
    ("migrations", "Database schema", True, _migrations),
    ("storage", "File storage", True, _storage),
    ("pdf", "PDF documents", True, _pdf),
    ("public_url", "Public address", False, _public_url),
    ("origin_secret", "CloudFront-only access", False, _origin_secret),
    ("accounts", "Owner login", False, _accounts),
    ("email", "Email", False, _email),
    ("stripe", "Online payments", False, _stripe),
    ("shop", "Shop details", False, _shop),
]


def run_checks() -> dict:
    results = []
    db_ok = True
    for id, title, critical, fn in CHECKS:
        c = Check(id, title, critical)
        if not db_ok and id in ("migrations", "accounts", "shop"):
            c.fail("Skipped: no database connection.")
        else:
            try:
                fn(c)
            except Exception as exc:
                c.fail(f"{type(exc).__name__}: {exc}"[:500])
        if id == "database" and c.status == "fail":
            db_ok = False
        results.append(c.as_dict())
    ok = not any(r["critical"] and r["status"] == "fail" for r in results)
    return {"ok": ok, "task": "doctor", "checks": results}


def as_markdown(report: dict) -> str:
    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    lines = ["| | Check | Result |", "|---|---|---|"]
    for r in report["checks"]:
        detail = r["detail"].replace("|", "\\|")
        lines.append(f"| {icon[r['status']]} | {r['title']} | {detail} |")
    return "\n".join(lines)
