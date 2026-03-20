"""add route.garmin_course_url

Revision ID: f1a3e5c7b9d2
Revises: e6b4c2d8f0a1
Create Date: 2026-03-20 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'f1a3e5c7b9d2'
down_revision: Union[str, Sequence[str], None] = 'e6b4c2d8f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('route', sa.Column('garmin_course_url', sqlmodel.AutoString(), nullable=True))


def downgrade() -> None:
    op.drop_column('route', 'garmin_course_url')
