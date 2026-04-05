"""add icu fields to userprofile

Revision ID: f6a1b2c3d4e5
Revises: d4e5f6a1b2c3
Create Date: 2026-04-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('userprofile', sa.Column('weight_kg', sa.Float(), nullable=True))
    op.add_column('userprofile', sa.Column('icu_athlete_id', sqlmodel.AutoString(), nullable=True))
    op.add_column('userprofile', sa.Column('icu_api_key', sqlmodel.AutoString(), nullable=True))
    op.add_column('userprofile', sa.Column('peak_ctl', sa.Float(), nullable=True))
    op.add_column('userprofile', sa.Column('athlete_level', sqlmodel.AutoString(), nullable=True))
    op.add_column('userprofile', sa.Column('icu_synced_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('userprofile', 'icu_synced_at')
    op.drop_column('userprofile', 'athlete_level')
    op.drop_column('userprofile', 'peak_ctl')
    op.drop_column('userprofile', 'icu_api_key')
    op.drop_column('userprofile', 'icu_athlete_id')
    op.drop_column('userprofile', 'weight_kg')
