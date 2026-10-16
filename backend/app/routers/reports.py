"""Reports with date filters, CSV export, and VIN lookup."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import audit, vin
from app.core.deps import require_user
from app.core.errors import AppError
from app.db import get_db
from app.models import User
from app.schemas.customers import normalize_vin
from app.services import export, reports
from app.services.business import get_business, shop_today

router = APIRouter(tags=["reports & export"])

NOT_ADVICE = (
    "These figures come straight from your invoices, payments, and expenses. They're for "
    "running the shop day to day, not tax or accounting advice; your accountant may count "
    "things differently."
)


@router.get("/reports/summary")
def report_summary(
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    """Money collected, work invoiced, what's owed, and expenses for a date range
    (inclusive, in the shop's time zone). Defaults to the current month."""
    today = shop_today(get_business(db))
    start = start or today.replace(day=1)
    end = end or today
    if end < start:
        raise AppError(
            "The end date is before the start date.", status_code=422, code="validation_error"
        )
    if (end - start).days > 3700:
        raise AppError(
            "Pick a range of ten years or less.", status_code=422, code="validation_error"
        )
    return {**reports.summary(db, start, end), "notice": NOT_ADVICE}


Dataset = Literal[tuple(export.DATASETS)]  # type: ignore[valid-type]


@router.get("/export/{dataset}.csv")
def export_csv(dataset: Dataset, db: Session = Depends(get_db), user: User = Depends(require_user)):
    body, rows = export.to_csv(db, dataset)
    audit.record(
        db,
        user=user,
        action="export.downloaded",
        entity_type="export",
        entity_id=None,
        details={"dataset": dataset, "rows": rows},
    )
    name = f"shop-{dataset.replace('_', '-')}-{shop_today(get_business(db)).isoformat()}.csv"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/vin/{raw_vin}")
def vin_lookup(raw_vin: str, _: User = Depends(require_user)):
    """Decode a VIN with NHTSA's free vPIC service. Optional: the app works without it."""
    try:
        value = normalize_vin(raw_vin)
    except ValueError as exc:
        raise AppError(str(exc), status_code=422, code="validation_error") from exc
    if not value or len(value) != 17:
        raise AppError(
            "VIN lookup needs a full 17-character VIN.", status_code=422, code="validation_error"
        )
    return vin.decode(value)
