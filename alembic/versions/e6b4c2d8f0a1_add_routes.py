"""add routes table and activity.route_id

Revision ID: e6b4c2d8f0a1
Revises: d5a3b1c7e9f2
Create Date: 2026-03-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'e6b4c2d8f0a1'
down_revision: Union[str, Sequence[str], None] = 'd5a3b1c7e9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'route',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.AutoString(), nullable=False),
        sa.Column('reference_activity_id', sqlmodel.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.add_column('activity', sa.Column('route_id', sa.Integer(), nullable=True))
    op.create_index('ix_activity_route_id', 'activity', ['route_id'])
    op.create_foreign_key('fk_activity_route_id', 'activity', 'route', ['route_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_activity_route_id', 'activity', type_='foreignkey')
    op.drop_index('ix_activity_route_id', table_name='activity')
    op.drop_column('activity', 'route_id')
    op.drop_table('route')
