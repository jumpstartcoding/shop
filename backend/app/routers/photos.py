"""Photos: upload from the phone's camera, list, caption, hide."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_user
from app.core.errors import AppError, NotFound
from app.core.photos import MAX_UPLOAD_BYTES
from app.core.storage import get_storage
from app.db import get_db
from app.models import Photo, User
from app.models.inspections import PHOTO_ENTITIES
from app.schemas.common import _strip
from app.services import photos

router = APIRouter(tags=["photos"])

EntityType = Literal["inspection_item", "work_order", "estimate", "vehicle", "customer"]
assert set(EntityType.__args__) == set(PHOTO_ENTITIES)


def _get(db: Session, photo_id: int) -> Photo:
    p = db.get(Photo, photo_id)
    if p is None or p.deleted_at is not None:
        raise NotFound("Photo not found.")
    return p


@router.post("/photos", status_code=201)
async def upload_photo(
    request: Request,
    entity_type: EntityType,
    entity_id: int,
    caption: Annotated[str | None, Query(max_length=300)] = None,
    customer_visible: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Send the image itself as the request body (Content-Type image/jpeg, image/png, or
    image/webp), not as a form. The app shrinks photos on the phone first."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_UPLOAD_BYTES:
        raise AppError(
            "That photo is too large (over 4 MB). Try taking it again.",
            status_code=413,
            code="too_large",
        )
    raw = await request.body()
    from fastapi.concurrency import run_in_threadpool

    photo = await run_in_threadpool(
        photos.add_photo,
        db,
        user,
        entity_type=entity_type,
        entity_id=entity_id,
        raw=raw,
        content_type=request.headers.get("content-type"),
        caption=(caption or "").strip() or None,
        customer_visible=customer_visible,
    )
    return photos.photo_out(photo)


@router.get("/photos")
def list_photos(
    entity_type: EntityType,
    entity_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    return [photos.photo_out(p) for p in photos.photos_for(db, entity_type, [entity_id])[entity_id]]


@router.get("/vehicles/{vehicle_id}/photos")
def vehicle_photos(vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    """Every photo of this vehicle, from inspections, work orders, estimates, and the
    vehicle itself, newest first."""
    rows = db.scalars(
        select(Photo)
        .where(Photo.vehicle_id == vehicle_id, Photo.deleted_at.is_(None))
        .order_by(Photo.created_at.desc(), Photo.id.desc())
        .limit(200)
    )
    return [photos.photo_out(p) for p in rows]


@router.get("/photos/{photo_id}/image")
def photo_image(
    photo_id: int,
    size: Literal["thumb", "full"] = "full",
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    p = _get(db, photo_id)
    data = get_storage().get(p.thumb_key if size == "thumb" else p.key)
    # Photos never change once stored, so the browser may keep them for a day.
    return Response(
        content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"}
    )


class PhotoUpdate(BaseModel):
    caption: Annotated[str | None, BeforeValidator(_strip), Field(max_length=300)] = None
    customer_visible: bool | None = None


@router.patch("/photos/{photo_id}")
def update_photo(
    photo_id: int,
    data: PhotoUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    p = _get(db, photo_id)
    fields = data.model_dump(exclude_unset=True)
    if "caption" in fields:
        p.caption = fields["caption"] or None
    if fields.get("customer_visible") is not None:
        p.customer_visible = fields["customer_visible"]
    return photos.photo_out(p)


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    photos.hide_photo(db, user, _get(db, photo_id))
