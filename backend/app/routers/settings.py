import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import require_role, require_user
from app.core.errors import AppError
from app.db import get_db
from app.models import Service, User
from app.schemas.settings import (
    BusinessOut,
    BusinessUpdate,
    PublicBusinessOut,
    ServiceIn,
    ServiceOut,
    ServiceUpdate,
)
from app.services.business import get_business
from app.services.workflow import get_or_404

router = APIRouter(tags=["settings"])
public = APIRouter(prefix="/public", tags=["public website"])

TAX_NOTICE = (
    "Tax settings are applied exactly as you configure them. This app does not provide tax "
    "or accounting advice; confirm what is taxable in your state with a tax professional."
)


@router.get("/settings", response_model=BusinessOut)
def get_settings_(db: Session = Depends(get_db), _: User = Depends(require_user)):
    return get_business(db)


@router.get("/settings/tax-notice")
def tax_notice(_: User = Depends(require_user)):
    return {"notice": TAX_NOTICE}


@router.patch("/settings", response_model=BusinessOut)
def update_settings(
    data: BusinessUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("owner"))
):
    business = get_business(db)
    changes = data.model_dump(exclude_unset=True)
    for required in (
        "name",
        "invoice_prefix",
        "estimate_prefix",
        "work_order_prefix",
        "authorization_statement",
    ):
        if required in changes and changes[required] is None:
            raise AppError(
                f"{required.replace('_', ' ').capitalize()} can't be blank.",
                status_code=422,
                code="validation_error",
            )
    if "hours" in changes and changes["hours"] is not None:
        changes["hours"] = {d: (h if h is None else dict(h)) for d, h in changes["hours"].items()}
    if "social_links" in changes and changes["social_links"] is None:
        changes["social_links"] = {}
    before = {k: getattr(business, k) for k in changes}
    for k, v in changes.items():
        setattr(business, k, v)
    delta = audit.diff(before, changes)
    if delta:
        audit.record(
            db,
            user=user,
            action="settings.updated",
            entity_type="business",
            entity_id=business.id,
            details=delta,
        )
    db.flush()
    return business


# ------------------------------------------------------------------ services catalog


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:120] or "service"


def _unique_slug(db: Session, name: str, exclude_id: int | None = None) -> str:
    base = _slugify(name)
    slug, n = base, 2
    while True:
        stmt = select(Service.id).where(Service.slug == slug)
        if exclude_id:
            stmt = stmt.where(Service.id != exclude_id)
        if db.scalar(stmt) is None:
            return slug
        slug, n = f"{base}-{n}", n + 1


@router.get("/services", response_model=list[ServiceOut])
def list_services(
    include_archived: bool = False, db: Session = Depends(get_db), _: User = Depends(require_user)
):
    stmt = select(Service)
    if not include_archived:
        stmt = stmt.where(Service.archived_at.is_(None))
    return list(db.scalars(stmt.order_by(Service.sort_order, Service.name)))


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(
    data: ServiceIn, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    svc = Service(**data.model_dump(), slug=_unique_slug(db, data.name))
    db.add(svc)
    db.flush()
    audit.record(
        db,
        user=user,
        action="service.created",
        entity_type="service",
        entity_id=svc.id,
        details={"name": svc.name},
    )
    return svc


@router.patch("/services/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: int,
    data: ServiceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    svc = get_or_404(db, Service, service_id, "Service")
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes:
        if not changes["name"]:
            raise AppError("Service name can't be blank.", status_code=422, code="validation_error")
        svc.slug = _unique_slug(db, changes["name"], exclude_id=svc.id)
    for k, v in changes.items():
        setattr(svc, k, v)
    audit.record(
        db,
        user=user,
        action="service.updated",
        entity_type="service",
        entity_id=svc.id,
        details={"fields": sorted(changes)},
    )
    db.flush()
    return svc


@router.post("/services/{service_id}/archive", response_model=ServiceOut)
def archive_service(
    service_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    svc = get_or_404(db, Service, service_id, "Service")
    svc.archived_at = svc.archived_at or datetime.now(UTC)
    audit.record(db, user=user, action="service.archived", entity_type="service", entity_id=svc.id)
    return svc


# ------------------------------------------------------------------ public (no auth)


@public.get("/business", response_model=PublicBusinessOut)
def public_business(db: Session = Depends(get_db)):
    return get_business(db)


@public.get("/services", response_model=list[ServiceOut])
def public_services(db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Service)
            .where(Service.archived_at.is_(None), Service.is_published.is_(True))
            .order_by(Service.sort_order, Service.name)
        )
    )
