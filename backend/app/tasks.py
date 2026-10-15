"""Operational tasks, runnable from the command line or as Lambda invocations.

uv run python -m app.tasks migrate
uv run python -m app.tasks create-admin --email you@shop.com --name "Your Name"
uv run python -m app.tasks nightly
uv run python -m app.tasks seed-demo      # development only
"""

import argparse
import getpass
import os
from pathlib import Path

import structlog
from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import hash_password
from app.db import get_engine, reset_engine
from app.models import Invoice, User

log = structlog.get_logger()
BACKEND_DIR = Path(__file__).resolve().parent.parent


def migrate() -> dict:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")
    return {"ok": True, "task": "migrate"}


def create_admin(email: str, name: str, password: str) -> dict:
    from sqlalchemy.orm import Session

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
    return {"ok": False, "error": f"unknown task {task!r}"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("nightly")
    sub.add_parser("seed-demo")
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
    elif args.cmd == "seed-demo":
        if get_settings().is_production:
            raise SystemExit("Refusing to load demo data into production.")
        from app.seed import seed_demo

        reset_engine()
        print(seed_demo())


if __name__ == "__main__":
    main()
