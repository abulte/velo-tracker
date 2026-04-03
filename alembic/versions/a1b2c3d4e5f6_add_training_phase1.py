"""add userprofile and goal tables

Revision ID: a1b2c3d4e5f6
Revises: f1a3e5c7b9d2
Create Date: 2026-04-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a3e5c7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'userprofile',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ftp', sa.Integer(), nullable=True),
        sa.Column('availability', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'goal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sqlmodel.AutoString(), nullable=False),
        sa.Column('goal_type', sqlmodel.AutoString(), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=False),
        sa.Column('target_ftp', sa.Integer(), nullable=True),
        sa.Column('notes', sqlmodel.AutoString(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('goal')
    op.drop_table('userprofile')
