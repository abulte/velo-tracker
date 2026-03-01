"""garmin connect migration

Rename icu_id -> garmin_id, sport -> activity_type, icu_rpe -> rpe,
icu_training_load -> training_load. Drop athlete_id, weighted_average_watts.

Revision ID: b3f1a2c4d5e6
Revises: a9dc85782eb0
Create Date: 2026-03-01 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b3f1a2c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'a9dc85782eb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename columns
    op.alter_column('activity', 'icu_id', new_column_name='garmin_id')
    op.alter_column('activity', 'sport', new_column_name='activity_type')
    op.alter_column('activity', 'icu_rpe', new_column_name='rpe')
    op.alter_column('activity', 'icu_training_load', new_column_name='training_load')

    # Rename indexes to match new column names
    op.drop_index('ix_activity_icu_id', table_name='activity')
    op.create_index('ix_activity_garmin_id', 'activity', ['garmin_id'], unique=True)

    op.drop_index('ix_activity_sport', table_name='activity')
    op.create_index('ix_activity_activity_type', 'activity', ['activity_type'], unique=False)

    # Drop columns no longer needed
    op.drop_index('ix_activity_athlete_id', table_name='activity')
    op.drop_column('activity', 'athlete_id')
    op.drop_column('activity', 'weighted_average_watts')


def downgrade() -> None:
    # Re-add dropped columns
    op.add_column('activity', sa.Column('weighted_average_watts', sa.Float(), nullable=True))
    op.add_column('activity', sa.Column('athlete_id', sa.String(), nullable=True))
    op.create_index('ix_activity_athlete_id', 'activity', ['athlete_id'], unique=False)

    # Rename indexes back
    op.drop_index('ix_activity_activity_type', table_name='activity')
    op.create_index('ix_activity_sport', 'activity', ['sport'], unique=False)

    op.drop_index('ix_activity_garmin_id', table_name='activity')
    op.create_index('ix_activity_icu_id', 'activity', ['icu_id'], unique=True)

    # Rename columns back
    op.alter_column('activity', 'training_load', new_column_name='icu_training_load')
    op.alter_column('activity', 'rpe', new_column_name='icu_rpe')
    op.alter_column('activity', 'activity_type', new_column_name='sport')
    op.alter_column('activity', 'garmin_id', new_column_name='icu_id')
