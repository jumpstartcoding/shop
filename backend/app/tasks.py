"""Operational tasks, runnable from the command line or as Lambda invocations.

uv run python -m app.tasks migrate
uv run python -m app.tasks create-admin --email you@shop.com --name "Your Name"
uv run python -m app.tasks nightly
uv run python -m app.tasks doctor         # go-live checks
uv run python -m app.tasks setup-shop     # placeholder shop profile + services list
uv run python -m app.tasks seed-demo      # development only
"""

import argparse
import getpass
import os

import structlog
from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import hash_password
from app.db import get_engine, reset_engine
from app.models import Invoice, User

log = structlog.get_logger()


def migrate() -> dict:
    from alembic import command

    from app.doctor import alembic_config

    command.upgrade(alembic_config(), "head")
    return {"ok": True, "task": "migrate"}


MIN_PASSWORD = 12


def create_admin(email: str, name: str, password: str) -> dict:
    from email_validator import EmailNotValidError, validate_email
    from sqlalchemy.orm import Session

    name = name.strip()
    try:
        # Same rules as the login form, so the account can actually sign in.
        email = validate_email(email.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        return {"ok": False, "error": f"Email address: {exc}"}
    if not name:
        return {"ok": False, "error": "Give a name."}
    if len(password) < MIN_PASSWORD:
        return {"ok": False, "error": f"Use a password of at least {MIN_PASSWORD} characters."}

    with Session(get_engine()) as db:
        if db.scalar(select(User).where(func.lower(User.email) == email.lower())):
            return {"ok": False, "error": "A user with that email already exists."}
        user = User(email=email, name=name, password_hash=hash_password(password), role="owner")
        db.add(user)
        db.commit()
        log.info("admin_created", user_id=user.id)
        return {"ok": True, "user_id": user.id}


def nightly() -> dict:
    """Flip unpaid invoices past their due date to overdue. Later phases add reminders and
    estimate expiry here."""
    from sqlalchemy.orm import Session

    from app.services.business import get_business, shop_today
    from app.services.workflow import settle_invoice_status

    with Session(get_engine()) as db:
        today = shop_today(get_business(db))
        changed = 0
        for inv in db.scalars(
            select(Invoice).where(Invoice.status.in_(("sent", "viewed")), Invoice.due_date < today)
        ):
            settle_invoice_status(inv, today)
            changed += 1
        db.commit()
    log.info("nightly_done", invoices_overdue=changed)
    return {"ok": True, "invoices_marked_overdue": changed}


def run(event: dict) -> dict:
    task = event.get("task")
    if task == "migrate":
        return migrate()
    if task == "create_admin":
        return create_admin(event["email"], event["name"], event["password"])
    if task == "nightly":
        return nightly()
    if task == "doctor":
        from app.doctor import run_checks

        return run_checks()
    if task == "setup_shop":
        from app.seed import setup_shop

        return setup_shop()
    return {"ok": False, "error": f"unknown task {task!r}"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("nightly")
    sub.add_parser("seed-demo")
    sub.add_parser("doctor")
    sub.add_parser("setup-shop")
    ca = sub.add_parser("create-admin")
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", required=True)
    args = parser.parse_args()

    if args.cmd == "migrate":
        print(migrate())
    elif args.cmd == "nightly":
        print(nightly())
    elif args.cmd == "create-admin":
        password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password (12+ chars): ")
        print(create_admin(args.email, args.name, password))
    elif args.cmd == "doctor":
        from app.doctor import as_markdown, run_checks

        report = run_checks()
        print(as_markdown(report))
        raise SystemExit(0 if report["ok"] else 1)
    elif args.cmd == "setup-shop":
        from app.seed import setup_shop

        print(setup_shop())
    elif args.cmd == "seed-demo":
        if get_settings().is_production:
            raise SystemExit("Refusing to load demo data into production.")
        from app.seed import seed_demo

        reset_engine()
        print(seed_demo())


if __name__ == "__main__":
    main()
