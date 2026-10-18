"""customer service history links

A customer link can now show a vehicle's service history (purpose 'history').

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17 21:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "('estimate', 'work_order', 'invoice', 'inspection')"
NEW = "('estimate', 'work_order', 'invoice', 'inspection', 'history')"


def upgrade() -> None:
    op.drop_constraint("purpose", "access_tokens", type_="check")
    op.create_check_constraint("purpose", "access_tokens", f"purpose IN {NEW}")


def downgrade() -> None:
    op.execute("DELETE FROM access_tokens WHERE purpose = 'history'")
    op.drop_constraint("purpose", "access_tokens", type_="check")
    op.create_check_constraint("purpose", "access_tokens", f"purpose IN {OLD}")
