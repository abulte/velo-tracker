"""replace userprofile.availability with week_a/week_b, add availabilityweek table

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-04-03 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'b2c3d4e5f6a1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('userprofile', 'availability')
    op.add_column('userprofile', sa.Column('week_a', sa.JSON(), nullable=True))
    op.add_column('userprofile', sa.Column('week_b', sa.JSON(), nullable=True))
    op.create_table(
        'availabilityweek',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('week_type', sqlmodel.AutoString(), nullable=False),
        sa.Column('hours', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_availabilityweek_week_start', 'availabilityweek', ['week_start'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_availabilityweek_week_start', table_name='availabilityweek')
    op.drop_table('availabilityweek')
    op.drop_column('userprofile', 'week_b')
    op.drop_column('userprofile', 'week_a')
    op.add_column('userprofile', sa.Column('availability', sa.JSON(), nullable=True))
