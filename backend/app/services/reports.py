"""Simple business numbers for a date range (spec §18). Not accounting.

Two views, labeled as such everywhere:
- Collected: money actually received (payments, less refunds), by payment date.
- Invoiced: what was billed on invoices dated in the range (labor, parts, fees, discounts,
  tax), excluding void invoices.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Expense, Invoice, Payment
from app.models.documents import COUNTED
from app.services.business import get_business

UNPAID = ("sent", "viewed", "partially_paid", "overdue")


def summary(db: Session, start: date, end: date) -> dict:
    business = get_business(db)
    tz = ZoneInfo(business.timezone)
    since = datetime.combine(start, time.min, tz)
    until = datetime.combine(end + timedelta(days=1), time.min, tz)

    net = Payment.amount_cents - Payment.refunded_cents
    paid_window = (Payment.paid_at >= since, Payment.paid_at < until, Payment.status.in_(COUNTED))
    collected = db.scalar(select(func.coalesce(func.sum(net), 0)).where(*paid_window))
    payment_count = db.scalar(select(func.count()).select_from(Payment).where(*paid_window))
    by_method = dict(
        db.execute(
            select(Payment.method, func.coalesce(func.sum(net), 0))
            .where(*paid_window)
            .group_by(Payment.method)
        ).all()
    )

    issued = (Invoice.issue_date >= start, Invoice.issue_date <= end, Invoice.status != "void")
    row = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Invoice.total_cents), 0),
            func.coalesce(func.sum(Invoice.labor_cents), 0),
            func.coalesce(func.sum(Invoice.parts_cents), 0),
            func.coalesce(func.sum(Invoice.fees_cents), 0),
            func.coalesce(func.sum(Invoice.discount_cents), 0),
            func.coalesce(func.sum(Invoice.tax_cents), 0),
            func.coalesce(func.sum(case((Invoice.status == "paid", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.status.in_(UNPAID), 1), else_=0)), 0),
        ).where(*issued)
    ).one()
    count, total, labor, parts, fees, discounts, tax, paid_n, unpaid_n = row
    outstanding = db.scalar(
        select(func.coalesce(func.sum(Invoice.total_cents - Invoice.amount_paid_cents), 0)).where(
            Invoice.status.in_(UNPAID)
        )
    )

    exp_window = (
        Expense.expense_date >= start,
        Expense.expense_date <= end,
        Expense.deleted_at.is_(None),
    )
    expenses_by_cat = dict(
        db.execute(
            select(Expense.category, func.sum(Expense.amount_cents))
            .where(*exp_window)
            .group_by(Expense.category)
        ).all()
    )
    expenses_total = sum(expenses_by_cat.values())

    # Collected per day for short ranges, per month for longer ones.
    monthly = (end - start).days > 62
    local_paid = func.timezone(business.timezone, Payment.paid_at)
    bucket = func.date_trunc("month" if monthly else "day", local_paid)
    periods = db.execute(
        select(bucket.label("p"), func.sum(net)).where(*paid_window).group_by("p").order_by("p")
    ).all()

    return {
        "start": start,
        "end": end,
        "collected": {
            "total_cents": collected,
            "payments": payment_count,
            "by_method": by_method,
            "by_period": [
                {"period": p.date().isoformat()[: 7 if monthly else 10], "cents": c}
                for p, c in periods
            ],
            "period": "month" if monthly else "day",
        },
        "invoiced": {
            "count": count,
            "total_cents": total,
            "labor_cents": labor,
            "parts_cents": parts,
            "fees_cents": fees,
            "discount_cents": discounts,
            "tax_cents": tax,
            "average_cents": round(total / count) if count else 0,
            "paid_count": paid_n,
            "unpaid_count": unpaid_n,
        },
        "outstanding_cents": outstanding,
        "expenses": {"total_cents": expenses_total, "by_category": expenses_by_cat},
        "collected_less_expenses_cents": collected - expenses_total,
    }
