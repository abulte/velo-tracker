"""wipe old icu data

Revision ID: c4e2f7a8b9d1
Revises: b3f1a2c4d5e6
Create Date: 2026-03-01 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c4e2f7a8b9d1'
down_revision: Union[str, Sequence[str], None] = 'b3f1a2c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM activity")


def downgrade() -> None:
    pass  # data is gone, can't undo
