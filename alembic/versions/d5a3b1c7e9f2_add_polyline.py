"""add polyline column

Revision ID: d5a3b1c7e9f2
Revises: c4e2f7a8b9d1
Create Date: 2026-03-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'd5a3b1c7e9f2'
down_revision: Union[str, Sequence[str], None] = 'c4e2f7a8b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('activity', sa.Column('polyline', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('activity', 'polyline')
