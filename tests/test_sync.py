"""Tests for Garmin sync logic."""
import datetime
from sqlmodel import select

from cli import sync_activities, _map_activity
from models import Activity
from tests.factories import garmin_activity

SINCE = datetime.date(2024, 1, 1)


# ---------------------------------------------------------------------------
# sync_activities
# ---------------------------------------------------------------------------

def test_creates_new_activity(garmin_client, db):
    garmin_client.get_activities.return_value = [garmin_activity(activity_id=1)]

    result = sync_activities(db, SINCE)

    assert result == {"created": 1, "updated": 0, "skipped": 0}
    assert db.exec(select(Activity)).first().garmin_id == "1"


def test_updates_existing_activity(garmin_client, db):
    garmin_client.get_activities.return_value = [garmin_activity(activity_id=1, name="First")]
    sync_activities(db, SINCE)

    garmin_client.get_activities.return_value = [garmin_activity(activity_id=1, name="Updated")]
    result = sync_activities(db, SINCE)

    assert result == {"created": 0, "updated": 1, "skipped": 0}
    assert db.exec(select(Activity)).first().name == "Updated"


def test_skips_non_cycling(garmin_client, db):
    garmin_client.get_activities.return_value = [
        garmin_activity(activity_id=1, type_key="running", parent_type_id=1),
    ]

    result = sync_activities(db, SINCE)

    assert result == {"created": 0, "updated": 0, "skipped": 1}
    assert db.exec(select(Activity)).first() is None


def test_stops_at_cutoff(garmin_client, db):
    garmin_client.get_activities.return_value = [
        garmin_activity(activity_id=1, date="2023-12-31 10:00:00"),
    ]

    result = sync_activities(db, SINCE)

    assert result == {"created": 0, "updated": 0, "skipped": 0}


def test_empty_response(garmin_client, db):
    garmin_client.get_activities.return_value = []

    result = sync_activities(db, SINCE)

    assert result == {"created": 0, "updated": 0, "skipped": 0}


def test_mixed_batch(garmin_client, db):
    garmin_client.get_activities.return_value = [
        garmin_activity(activity_id=1),
        garmin_activity(activity_id=2, type_key="running", parent_type_id=1),
        garmin_activity(activity_id=3),
    ]

    result = sync_activities(db, SINCE)

    assert result == {"created": 2, "updated": 0, "skipped": 1}


# ---------------------------------------------------------------------------
# _map_activity
# ---------------------------------------------------------------------------

def test_map_activity_basic():
    item = garmin_activity(
        activity_id=42,
        date="2024-03-01 08:30:00",
        name="Tempo Ride",
        tss=95.0,
        movingDuration=3600.0,
        avgPower=220.0,
    )
    fields = _map_activity(item)

    assert fields["tss"] == 95.0
    assert fields["moving_time"] == 3600
    assert fields["average_watts"] == 220.0
    assert fields["start_date"] == datetime.datetime(2024, 3, 1, 8, 30)


def test_map_activity_missing_optional_fields():
    item = garmin_activity(activity_id=1)
    fields = _map_activity(item)

    assert fields["moving_time"] is None
    assert fields["average_watts"] is None
    assert fields["rpe"] is None


def test_map_activity_detail_summary():
    item = garmin_activity(activity_id=1)
    fields = _map_activity(item, detail_summary={"directWorkoutRpe": 7, "directWorkoutFeel": 3})

    assert fields["rpe"] == 7
    assert fields["feel"] == 3


def test_map_activity_max_power_int():
    item = garmin_activity(activity_id=1, maxPower=387.6)
    fields = _map_activity(item)

    assert fields["max_watts"] == 387
