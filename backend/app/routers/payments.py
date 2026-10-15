"""Online checkout (customer), Stripe webhook (Stripe), refunds and payment settings (shop)."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy.orm import Session

from app.core.deps import require_user
from app.core.payments import verify_webhook
from app.db import get_db, get_engine
from app.models import Invoice, User
from app.schemas.common import _strip
from app.services import payments
from app.services.serialize import invoice_out
from app.services.workflow import get_or_404

log = structlog.get_logger()
router = APIRouter(tags=["online payments"])


class CheckoutIn(BaseModel):
    amount_cents: Annotated[int, Field(gt=0, le=100_000_000)]


@router.post("/public/links/{token}/checkout")
def checkout(token: str, data: CheckoutIn, db: Session = Depends(get_db)):
    """Returns the Stripe Checkout URL to send the customer to."""
    return {"url": payments.start_checkout(db, token, data.amount_cents)}


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request):
    payload = await request.body()
    event = verify_webhook(payload, request.headers.get("stripe-signature"))
    outcome = await run_in_threadpool(_handle, event)
    return {"received": True, "outcome": outcome}


def _handle(event: dict) -> str:
    # Own transaction: the event record and the payment commit together or not at all.
    with Session(get_engine(), expire_on_commit=False) as db:
        try:
            outcome, after = payments.process_event(db, event)
            db.commit()
        except Exception:
            db.rollback()
            log.exception("stripe_webhook_failed", event_id=event.get("id"), type=event.get("type"))
            raise
        log.info("stripe_webhook", event_id=event["id"], type=event["type"], outcome=outcome)
        for task in after:  # receipts and shop notices; failures are logged, never raised
            try:
                task(db)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("stripe_webhook_after_commit_failed", event_id=event["id"])
        return outcome


class RefundIn(BaseModel):
    amount_cents: Annotated[int, Field(gt=0, le=100_000_000)]
    reason: Annotated[str, BeforeValidator(_strip), Field(min_length=3, max_length=300)]


@router.post("/payments/{payment_id}/refund")
def refund(
    payment_id: int,
    data: RefundIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Online payments are refunded through Stripe. Cash/check/card-terminal refunds are
    recorded here; hand the money back yourself."""
    p = payments.refund_payment(db, user, payment_id, data.amount_cents, data.reason)
    db.flush()
    inv = get_or_404(db, Invoice, p.invoice_id, "Invoice")
    db.refresh(inv)
    return invoice_out(inv)


@router.get("/settings/payments")
def payment_settings(db: Session = Depends(get_db), _: User = Depends(require_user)):
    return payments.payment_settings(db)
