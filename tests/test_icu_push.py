"""Tests for intervals.icu workout push/delete."""
import base64
import datetime
import json
import os
import tempfile
from typing import Any, cast
from unittest.mock import MagicMock, patch

from fitparse import FitFile

from icu import delete_workout_event, fetch_compliance, push_workout_event


STEPS = [
    {"type": "warmup",   "duration_sec": 300,  "zone": "z1", "description": "Warmup"},
    {"type": "active",   "duration_sec": 1800, "zone": "z3", "description": "Main"},
    {"type": "cooldown", "duration_sec": 300,  "zone": "z1", "description": "Cooldown"},
]


def _mock_post(return_value):
    return patch("icu.requests.post", return_value=MagicMock(
        ok=True, json=lambda: return_value, raise_for_status=lambda: None,
    ))


def _mock_delete(status_code=200):
    return patch("icu.requests.delete", return_value=MagicMock(
        status_code=status_code, raise_for_status=lambda: None,
    ))


def test_push_returns_event_id():
    with _mock_post({"id": 42, "name": "Test"}):
        event_id = push_workout_event(
            "i123", "key", datetime.date(2026, 5, 1),
            "Test session", STEPS, tss_target=80, duration_min=40, ftp=220,
        )
    assert event_id == "42"


def test_push_skips_past_sessions():
    """Sessions in the past should not be pushed."""
    with _mock_post({"id": 42}) as mock:
        event_id = push_workout_event(
            "i123", "key", datetime.date(2025, 12, 31),  # past date
            "Test session", STEPS, tss_target=80, duration_min=40, ftp=220,
        )
    assert event_id is None
    mock.assert_not_called()


def test_push_skips_linked_activities():
    """Sessions already linked to activities should not be pushed."""
    with _mock_post({"id": 42}) as mock:
        event_id = push_workout_event(
            "i123", "key", datetime.date(2026, 5, 1),
            "Test session", STEPS, tss_target=80, duration_min=40, ftp=220,
            activity_id=123,  # linked to an activity
        )
    assert event_id is None
    mock.assert_not_called()


def test_push_deletes_old_orphaned_event():
    """When pushing a new event, delete the old orphaned one if it exists."""
    with _mock_post({"id": 99}):
        with _mock_delete() as mock_del:
            event_id = push_workout_event(
                "i123", "key", datetime.date(2026, 5, 1),
                "Test session", STEPS, tss_target=80, duration_min=40, ftp=220,
                old_icu_event_id="old-event-42",
            )
    assert event_id == "99"
    mock_del.assert_called_once()
    assert "events/old-event-42" in mock_del.call_args.args[0]


def test_push_sends_correct_fields():
    with _mock_post({"id": 1}) as mock:
        push_workout_event(
            "i123", "key", datetime.date(2026, 5, 1),
            "Test session", STEPS, tss_target=80, duration_min=40, ftp=220,
        )
    payload = json.loads(mock.call_args.kwargs["data"].decode())
    assert payload["category"] == "WORKOUT"
    assert payload["start_date_local"] == "2026-05-01T00:00:00"
    assert payload["name"] == "Test session"
    assert payload["type"] == "Ride"
    assert payload["moving_time"] == 40 * 60
    assert payload["icu_training_load"] == 80
    assert "file_contents_base64" in payload
    assert payload["filename"] == "workout.fit"


def test_push_fit_is_valid_base64():
    with _mock_post({"id": 1}) as mock:
        push_workout_event(
            "i123", "key", datetime.date(2026, 5, 1),
            "Test", STEPS, tss_target=50, duration_min=30, ftp=200,
        )
    payload = json.loads(mock.call_args.kwargs["data"].decode())
    decoded = base64.b64decode(payload["file_contents_base64"])
    assert decoded[0] == 14           # header size
    assert decoded[1] == 0x10         # protocol version
    assert decoded[8:12] == b".FIT"


def test_delete_calls_correct_url():
    with _mock_delete() as mock:
        delete_workout_event("i123", "key", "event-99")
    assert "events/event-99" in mock.call_args.args[0]


def test_delete_ignores_404():
    with _mock_delete(status_code=404):
        delete_workout_event("i123", "key", "missing-event")  # must not raise


def test_push_set_produces_repeat_step():
    """A set in the steps list must produce a REPEAT_UNTIL_STEPS_CMPLT step in the FIT file."""
    steps = [
        {"type": "set", "repeat": 3, "steps": [
            {"type": "active", "duration_sec": 300, "zone": "z4", "description": "On"},
            {"type": "rest",   "duration_sec": 120, "zone": "z1", "description": "Off"},
        ]},
    ]
    with _mock_post({"id": 1}) as mock:
        push_workout_event("i123", "key", datetime.date(2026, 5, 1),
                           "Intervals", steps, tss_target=60, duration_min=30, ftp=220)
    payload = json.loads(mock.call_args.kwargs["data"].decode())
    fit_bytes = base64.b64decode(payload["file_contents_base64"])

    with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as f:
        f.write(fit_bytes)
        path = f.name
    try:
        workout_steps = [cast(Any, m).get_values()
                         for m in FitFile(path).get_messages("workout_step")]
    finally:
        os.unlink(path)

    assert len(workout_steps) == 3  # active + rest + repeat marker
    repeat = workout_steps[2]
    assert repeat["duration_type"] == "repeat_until_steps_cmplt"
    assert repeat["repeat_steps"] == 3


# ---------------------------------------------------------------------------
# sync_plan_compliance_impl
# ---------------------------------------------------------------------------

def test_sync_compliance_links_activities(db):
    """Syncing compliance should link Activity records to TrainingSession."""
    import datetime
    from models import UserProfile, Goal, TrainingPlan, TrainingWeek, TrainingSession, Activity
    from app import _sync_plan_compliance_impl

    # Setup
    profile = UserProfile(icu_athlete_id="i123", icu_api_key="key")
    db.add(profile)
    goal = Goal(title="Test", goal_type="race", target_date=datetime.date(2026, 6, 1))
    db.add(goal)
    db.flush()
    assert goal.id is not None
    plan = TrainingPlan(goal_id=goal.id, summary="test")
    db.add(plan)
    db.flush()
    assert plan.id is not None
    week = TrainingWeek(plan_id=plan.id, week_number=1, phase="base", tss_target=100, description="", week_start=datetime.date(2026, 5, 4))
    db.add(week)
    db.flush()
    assert week.id is not None
    session = TrainingSession(week_id=week.id, day_of_week="mon", session_type="threshold", tss_target=80, duration_min=60, title="Workout", icu_event_id="event-42")
    db.add(session)
    activity = Activity(garmin_id="garmin-123", name="Done", activity_type="cycling", start_date=datetime.datetime(2026, 5, 4))
    db.add(activity)
    db.commit()

    with patch("app._fetch_icu_compliance") as mock_fetch:
        mock_fetch.return_value = {"event-42": (85.5, "garmin-123")}
        updated = _sync_plan_compliance_impl(db, plan.id)

    assert updated == 1
    db.refresh(session)
    assert session.icu_compliance == 85.5
    assert session.activity_id == activity.id


def test_sync_compliance_no_pushed_sessions(db):
    """Sync returns 0 when no sessions have been pushed."""
    import datetime
    from models import UserProfile, Goal, TrainingPlan, TrainingWeek, TrainingSession
    from app import _sync_plan_compliance_impl

    profile = UserProfile(icu_athlete_id="i123", icu_api_key="key")
    db.add(profile)
    goal = Goal(title="Test", goal_type="race", target_date=datetime.date(2026, 6, 1))
    db.add(goal)
    db.flush()
    assert goal.id is not None
    plan = TrainingPlan(goal_id=goal.id, summary="test")
    db.add(plan)
    db.flush()
    assert plan.id is not None
    week = TrainingWeek(plan_id=plan.id, week_number=1, phase="base", tss_target=100, description="", week_start=datetime.date(2026, 5, 4))
    db.add(week)
    db.flush()
    assert week.id is not None
    session = TrainingSession(week_id=week.id, day_of_week="mon", session_type="threshold", tss_target=80, duration_min=60, title="Workout", icu_event_id=None)
    db.add(session)
    db.commit()

    updated = _sync_plan_compliance_impl(db, plan.id)

    assert updated == 0


def test_sync_compliance_no_credentials(db):
    """Sync returns 0 when ICU credentials are not set."""
    import datetime
    from models import Goal, TrainingPlan, TrainingWeek, TrainingSession
    from app import _sync_plan_compliance_impl

    goal = Goal(title="Test", goal_type="race", target_date=datetime.date(2026, 6, 1))
    db.add(goal)
    db.flush()
    assert goal.id is not None
    plan = TrainingPlan(goal_id=goal.id, summary="test")
    db.add(plan)
    db.flush()
    assert plan.id is not None
    week = TrainingWeek(plan_id=plan.id, week_number=1, phase="base", tss_target=100, description="", week_start=datetime.date(2026, 5, 4))
    db.add(week)
    db.flush()
    assert week.id is not None
    session = TrainingSession(week_id=week.id, day_of_week="mon", session_type="threshold", tss_target=80, duration_min=60, title="Workout", icu_event_id="event-42")
    db.add(session)
    db.commit()

    updated = _sync_plan_compliance_impl(db, plan.id)

    assert updated == 0


# ---------------------------------------------------------------------------
# fetch_compliance
# ---------------------------------------------------------------------------

def _mock_activities(activities):
    return patch("icu.requests.get", return_value=MagicMock(
        raise_for_status=lambda: None,
        json=lambda: activities,
    ))


def test_fetch_compliance_returns_matched():
    activities = [
        {"id": "i1", "paired_event_id": 42, "compliance": 95.5, "external_id": "22533552380"},
        {"id": "i2", "paired_event_id": 99, "compliance": 80.0, "external_id": "22533552381"},
    ]
    with _mock_activities(activities):
        result = fetch_compliance("i123", "key", {"42"}, datetime.date(2026, 5, 1), datetime.date(2026, 5, 7))
    assert result == {"42": (95.5, "22533552380")}


def test_fetch_compliance_ignores_unmatched():
    activities = [
        {"id": "i1", "paired_event_id": 99, "compliance": 80.0, "external_id": "22533552381"},
    ]
    with _mock_activities(activities):
        result = fetch_compliance("i123", "key", {"42"}, datetime.date(2026, 5, 1), datetime.date(2026, 5, 7))
    assert result == {}


def test_fetch_compliance_ignores_missing_fields():
    activities = [
        {"id": "i1", "paired_event_id": 42, "compliance": None, "external_id": "22533552380"},
        {"id": "i2", "paired_event_id": 42, "compliance": 80.0, "external_id": None},
        {"id": "i3", "paired_event_id": None, "compliance": 80.0, "external_id": "22533552382"},
    ]
    with _mock_activities(activities):
        result = fetch_compliance("i123", "key", {"42"}, datetime.date(2026, 5, 1), datetime.date(2026, 5, 7))
    assert result == {}
