"""replace session text fields with structured steps; add plan rationale

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-04-03 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'd4e5f6a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trainingplan', sa.Column('rationale', sqlmodel.AutoString(), nullable=True))
    op.drop_column('trainingsession', 'warmup')
    op.drop_column('trainingsession', 'main_set')
    op.drop_column('trainingsession', 'cooldown')
    op.add_column('trainingsession', sa.Column('steps', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('trainingsession', 'steps')
    op.add_column('trainingsession', sa.Column('cooldown', sqlmodel.AutoString(), nullable=False, server_default=''))
    op.add_column('trainingsession', sa.Column('main_set', sqlmodel.AutoString(), nullable=False, server_default=''))
    op.add_column('trainingsession', sa.Column('warmup', sqlmodel.AutoString(), nullable=False, server_default=''))
    op.drop_column('trainingplan', 'rationale')
