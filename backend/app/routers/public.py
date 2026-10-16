"""Unauthenticated endpoints: the public website and customer document links.

Abuse controls: customer links are 256-bit random tokens stored only as hashes; booking and
contact forms have a honeypot field and a per-IP hourly limit kept in Postgres.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.deps import client_ip
from app.core.errors import NotFound, TooManyRequests
from app.core.storage import get_storage
from app.db import get_db
from app.documents.render import render_pdf
from app.documents.snapshot import snapshot_receipt
from app.models import Appointment, Inquiry, Payment
from app.schemas.public import BookingIn, ContactIn, QuestionIn, RespondIn
from app.services import customer_links, documents, notify
from app.services.business import get_business

router = APIRouter(prefix="/public", tags=["public website & customer links"])


def pdf_response(data: bytes, filename: str, *, inline: bool = True) -> Response:
    disposition = "inline" if inline else "attachment"
    safe = "".join(c for c in filename if c.isalnum() or c in "-_.") or "document.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe}"',
            "Cache-Control": "private, no-store",
        },
    )


# ------------------------------------------------------------------ customer links


@router.get("/links/{token}")
def view_link(token: str, db: Session = Depends(get_db)):
    return customer_links.view(db, token)


@router.get("/links/{token}/pdf")
def link_pdf(token: str, db: Session = Depends(get_db)):
    data, name = customer_links.pdf_for_link(db, token)
    return pdf_response(data, name)


@router.get("/links/{token}/photos/{photo_id}")
def link_photo(
    token: str,
    photo_id: int,
    size: Literal["thumb", "full"] = "full",
    db: Session = Depends(get_db),
):
    data = customer_links.photo_for_link(db, token, photo_id, size)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/links/{token}/receipts/{payment_id}")
def link_receipt(token: str, payment_id: int, db: Session = Depends(get_db)):
    link = documents.resolve_link(db, token)
    payment = db.get(Payment, payment_id)
    if link.purpose != "invoice" or payment is None or payment.invoice_id != link.entity_id:
        raise NotFound("Receipt not found.")
    return pdf_response(render_pdf(snapshot_receipt(db, payment)), f"receipt-{payment.id}.pdf")


@router.post("/links/{token}/respond")
def respond(token: str, data: RespondIn, request: Request, db: Session = Depends(get_db)):
    return customer_links.respond(
        db, token, data, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )


@router.post("/links/{token}/question", status_code=201)
def question(token: str, data: QuestionIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    _limit(db, ip)
    customer_links.ask_question(db, token, data, ip=ip)
    return {"ok": True}


# ------------------------------------------------------------------ website forms


def _limit(db: Session, ip: str | None) -> None:
    if not ip:
        return
    since = datetime.now(UTC) - timedelta(hours=1)
    n = (
        db.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.source_ip == ip, Appointment.created_at >= since)
        )
        or 0
    )
    n += (
        db.scalar(
            select(func.count())
            .select_from(Inquiry)
            .where(Inquiry.ip_address == ip, Inquiry.created_at >= since)
        )
        or 0
    )
    if n >= get_settings().public_submissions_per_hour:
        raise TooManyRequests(
            "Too many requests from this connection. Please call the shop instead."
        )


@router.post("/appointments", status_code=201)
def book(data: BookingIn, request: Request, db: Session = Depends(get_db)):
    if data.website:  # honeypot filled: accept silently, store nothing
        return {"ok": True}
    ip = client_ip(request)
    _limit(db, ip)
    vehicle = " ".join(
        str(p) for p in [data.vehicle_year, data.vehicle_make, data.vehicle_model] if p
    )
    appt = Appointment(
        status="requested",
        source="online",
        requested_service=data.requested_service,
        concern=data.concern,
        customer_notes=data.notes,
        preferred_date=data.preferred_date,
        preferred_time=data.preferred_time,
        contact_name=data.name,
        contact_phone=data.phone,
        contact_email=data.email,
        vehicle_description=vehicle or None,
        reported_mileage=data.mileage,
        source_ip=ip,
    )
    db.add(appt)
    db.flush()
    audit.record(
        db,
        actor="customer",
        action="appointment.requested",
        entity_type="appointment",
        entity_id=appt.id,
        ip_address=ip,
    )
    notify.notify_shop(
        db,
        f"New appointment request from {data.name}",
        f"{data.name} requested {data.requested_service or 'an appointment'}"
        f"{' for a ' + vehicle if vehicle else ''}.\n"
        f"Prefers: {data.preferred_date or 'any day'}, {data.preferred_time or 'any time'}\n"
        f"Phone: {data.phone or '-'}  Email: {data.email or '-'}\n\n{data.concern or ''}",
    )
    return {"ok": True}


@router.post("/contact", status_code=201)
def contact(data: ContactIn, request: Request, db: Session = Depends(get_db)):
    if data.website:
        return {"ok": True}
    ip = client_ip(request)
    _limit(db, ip)
    db.add(
        Inquiry(
            kind="contact",
            name=data.name,
            email=data.email,
            phone=data.phone,
            message=data.message,
            ip_address=ip,
        )
    )
    notify.notify_shop(
        db,
        f"Website message from {data.name}",
        f"{data.name} ({data.phone or data.email}) wrote:\n\n{data.message}",
    )
    return {"ok": True}


@router.get("/logo")
def logo(db: Session = Depends(get_db)):
    key = get_business(db).logo_key
    if not key:
        raise NotFound("No logo uploaded.")
    return Response(
        content=get_storage().get(key),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )
