"""Audit trail helpers. Entries are written in the same transaction as the change they
describe, so an action is never logged without happening or vice versa."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Fields that changed, as {"field": {"from": old, "to": new}}."""
    return {
        k: {"from": _jsonable(before.get(k)), "to": _jsonable(after.get(k))}
        for k in after
        if before.get(k) != after.get(k)
    }


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int | None,
    user: User | None = None,
    actor: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            actor=actor or ("user" if user else "system"),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details={k: _jsonable(v) for k, v in (details or {}).items()},
            ip_address=ip_address,
        )
    )
