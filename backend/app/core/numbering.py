"""Sequential document numbers like INV-2026-0001.

The counter row is incremented with INSERT ... ON CONFLICT DO UPDATE ... RETURNING, which
Postgres executes atomically under a row lock, so two concurrent requests can never receive
the same number. Because it runs in the caller's transaction, a rolled-back document also
rolls back its number, keeping the sequence gap-free.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

_NEXT = text(
    """
    INSERT INTO document_counters (kind, year, last_value)
    VALUES (:kind, :year, 1)
    ON CONFLICT (kind, year)
    DO UPDATE SET last_value = document_counters.last_value + 1
    RETURNING last_value
    """
)


def next_number(db: Session, kind: str, prefix: str, year: int) -> str:
    value = db.execute(_NEXT, {"kind": kind, "year": year}).scalar_one()
    return f"{prefix}-{year}-{value:04d}"
