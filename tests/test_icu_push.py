"""Tests for intervals.icu workout push/delete."""
import datetime
from unittest.mock import MagicMock, patch

from icu import delete_workout_event, push_workout_event


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


def test_push_sends_correct_fields():
    with _mock_post({"id": 1}) as mock:
        push_workout_event(
            "i123", "key", datetime.date(2026, 5, 1),
            "Test session", STEPS, tss_target=80, duration_min=40, ftp=220,
        )
    import json
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
    import base64
    with _mock_post({"id": 1}) as mock:
        push_workout_event(
            "i123", "key", datetime.date(2026, 5, 1),
            "Test", STEPS, tss_target=50, duration_min=30, ftp=200,
        )
    import json
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
