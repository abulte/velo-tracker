"""add trainingplan, trainingweek, trainingsession tables

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-04-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'c3d4e5f6a1b2'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'trainingplan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.Column('summary', sqlmodel.AutoString(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['goal.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trainingplan_goal_id', 'trainingplan', ['goal_id'])
    op.create_table(
        'trainingweek',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('week_number', sa.Integer(), nullable=False),
        sa.Column('phase', sqlmodel.AutoString(), nullable=False),
        sa.Column('tss_target', sa.Integer(), nullable=False),
        sa.Column('description', sqlmodel.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['trainingplan.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trainingweek_plan_id', 'trainingweek', ['plan_id'])
    op.create_table(
        'trainingsession',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('week_id', sa.Integer(), nullable=False),
        sa.Column('day_of_week', sqlmodel.AutoString(), nullable=False),
        sa.Column('session_type', sqlmodel.AutoString(), nullable=False),
        sa.Column('tss_target', sa.Integer(), nullable=False),
        sa.Column('duration_min', sa.Integer(), nullable=False),
        sa.Column('title', sqlmodel.AutoString(), nullable=False),
        sa.Column('warmup', sqlmodel.AutoString(), nullable=False),
        sa.Column('main_set', sqlmodel.AutoString(), nullable=False),
        sa.Column('cooldown', sqlmodel.AutoString(), nullable=False),
        sa.Column('notes', sqlmodel.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(['week_id'], ['trainingweek.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trainingsession_week_id', 'trainingsession', ['week_id'])


def downgrade() -> None:
    op.drop_index('ix_trainingsession_week_id', table_name='trainingsession')
    op.drop_table('trainingsession')
    op.drop_index('ix_trainingweek_plan_id', table_name='trainingweek')
    op.drop_table('trainingweek')
    op.drop_index('ix_trainingplan_goal_id', table_name='trainingplan')
    op.drop_table('trainingplan')
