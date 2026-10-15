from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Business


def get_business(db: Session) -> Business:
    """The shop's single settings row, created with safe defaults on first use."""
    business = db.scalar(select(Business).order_by(Business.id).limit(1))
    if business is None:
        business = Business(name="My Auto Repair", hours={}, social_links={})
        db.add(business)
        db.flush()
    return business


def shop_now(business: Business) -> datetime:
    return datetime.now(ZoneInfo(business.timezone))


def shop_today(business: Business) -> date:
    return shop_now(business).date()
