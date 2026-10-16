"""Attaching, listing, and hiding photos. See app/models/inspections.py for the rules."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import AppError, NotFound
from app.core.photos import process_photo
from app.core.storage import get_storage, new_key
from app.models import (
    Customer,
    Estimate,
    Expense,
    Inspection,
    InspectionItem,
    Photo,
    User,
    Vehicle,
    WorkOrder,
)

MAX_PER_THING = 30


def owner_of(db: Session, entity_type: str, entity_id: int) -> tuple[int | None, int | None]:
    """(customer_id, vehicle_id) for the thing a photo is attached to."""
    if entity_type == "inspection_item":
        item = db.get(InspectionItem, entity_id)
        if item is not None:
            insp = db.get(Inspection, item.inspection_id)
            if insp.status == "completed":
                raise AppError(
                    f"Inspection {insp.number} is finished. Reopen it to add photos.",
                    status_code=409,
                    code="inspection_finished",
                )
            return insp.customer_id, insp.vehicle_id
    elif entity_type in ("work_order", "estimate"):
        doc = db.get(WorkOrder if entity_type == "work_order" else Estimate, entity_id)
        if doc is not None:
            return doc.customer_id, doc.vehicle_id
    elif entity_type == "vehicle":
        v = db.get(Vehicle, entity_id)
        if v is not None:
            return v.customer_id, v.id
    elif entity_type == "customer":
        if db.get(Customer, entity_id) is not None:
            return entity_id, None
    elif entity_type == "expense":
        e = db.get(Expense, entity_id)
        if e is not None and e.deleted_at is None:
            return None, None
    raise NotFound("The thing you're adding a photo to wasn't found.")


def _live(entity_type: str, entity_ids: list[int]):
    return (
        select(Photo)
        .where(
            Photo.entity_type == entity_type,
            Photo.entity_id.in_(entity_ids),
            Photo.deleted_at.is_(None),
        )
        .order_by(Photo.created_at, Photo.id)
    )


def add_photo(
    db: Session,
    user: User,
    *,
    entity_type: str,
    entity_id: int,
    raw: bytes,
    content_type: str | None,
    caption: str | None,
    customer_visible: bool,
) -> Photo:
    customer_id, vehicle_id = owner_of(db, entity_type, entity_id)
    if len(db.scalars(_live(entity_type, [entity_id])).all()) >= MAX_PER_THING:
        raise AppError(
            f"There are already {MAX_PER_THING} photos here. Remove one to add another.",
            status_code=409,
            code="too_many_photos",
        )
    processed = process_photo(raw, content_type)
    storage = get_storage()
    key = new_key(f"photos/{customer_id or 'shop'}", "jpg")
    thumb_key = key.replace(".jpg", "-thumb.jpg")
    storage.put(key, processed.full, "image/jpeg")
    storage.put(thumb_key, processed.thumb, "image/jpeg")
    photo = Photo(
        entity_type=entity_type,
        entity_id=entity_id,
        customer_id=customer_id,
        vehicle_id=vehicle_id,
        key=key,
        thumb_key=thumb_key,
        width=processed.width,
        height=processed.height,
        size_bytes=len(processed.full),
        caption=caption,
        customer_visible=customer_visible,
        uploaded_by_user_id=user.id,
    )
    db.add(photo)
    db.flush()
    audit.record(
        db,
        user=user,
        action="photo.added",
        entity_type=entity_type,
        entity_id=entity_id,
        details={"photo_id": photo.id},
    )
    return photo


def hide_photo(db: Session, user: User, photo: Photo) -> None:
    """Photos are never erased: one already shown on a signed document must stay with it.
    Hiding removes it from the app and from customer links."""
    if photo.deleted_at is None:
        photo.deleted_at = datetime.now(UTC)
        db.flush()
        audit.record(
            db,
            user=user,
            action="photo.removed",
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            details={"photo_id": photo.id},
        )


def photos_for(db: Session, entity_type: str, entity_ids: list[int]) -> dict[int, list[Photo]]:
    out: dict[int, list[Photo]] = {i: [] for i in entity_ids}
    if entity_ids:
        for p in db.scalars(_live(entity_type, entity_ids)):
            out[p.entity_id].append(p)
    return out


def photo_out(p: Photo) -> dict:
    return {
        "id": p.id,
        "entity_type": p.entity_type,
        "entity_id": p.entity_id,
        "caption": p.caption,
        "customer_visible": p.customer_visible,
        "width": p.width,
        "height": p.height,
        "created_at": p.created_at,
        "thumb_url": f"/api/photos/{p.id}/image?size=thumb",
        "url": f"/api/photos/{p.id}/image",
    }


def snapshot_photos(photos: list[Photo]) -> list[dict]:
    """The customer-safe form stored in document snapshots."""
    return [
        {
            "id": p.id,
            "caption": p.caption,
            "key": p.key,
            "thumb_key": p.thumb_key,
            "width": p.width,
            "height": p.height,
        }
        for p in photos
        if p.customer_visible and p.deleted_at is None
    ]


def photo_ids_in(snapshot: dict) -> set[int]:
    """Every photo a document version shows, wherever it appears in the snapshot."""
    ids = {p["id"] for p in snapshot.get("photos") or []}
    for item in snapshot.get("findings") or []:
        ids |= {p["id"] for p in item.get("photos") or []}
    inspection = snapshot.get("inspection") or {}
    for item in inspection.get("findings") or []:
        ids |= {p["id"] for p in item.get("photos") or []}
    return ids
