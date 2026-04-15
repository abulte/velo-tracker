"""Tests for FIT workout file generation."""
import os
import tempfile
from typing import Any, cast

import pytest
from fitparse import FitFile

from fit_export import _flatten, _zone_watts, session_to_fit


# ---------------------------------------------------------------------------
# _zone_watts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("zone,ftp,expected_lo,expected_hi", [
    ("z1", 200,   1, 110),   # no lower bound → 1W sentinel, hi = 0.55*200
    ("z2", 200, 110, 150),   # 0.55–0.75 * 200
    ("z3", 200, 150, 180),   # 0.75–0.90 * 200
    ("z4", 200, 180, 210),   # 0.90–1.05 * 200
    ("z5", 200, 210, 240),   # 1.05–1.20 * 200
    ("z6", 200, 240, 300),   # no upper bound → 1.5 * 200
])
def test_zone_watts(zone, ftp, expected_lo, expected_hi):
    lo, hi = _zone_watts(zone, ftp)
    assert lo == expected_lo
    assert hi == expected_hi


def test_zone_watts_z1_avoids_sentinel():
    """Z1 lower bound must not be 0 (raw value 1000 is the FIT watts_offset sentinel)."""
    lo, _ = _zone_watts("z1", 220)
    assert lo != 0, "0W (raw 1000) is a FIT sentinel; use 1W instead"


# ---------------------------------------------------------------------------
# _flatten
# ---------------------------------------------------------------------------

def test_flatten_simple():
    steps = [
        {"type": "warmup", "duration_sec": 300, "zone": "z1"},
        {"type": "active", "duration_sec": 600, "zone": "z3"},
    ]
    assert _flatten(steps) == steps


def test_flatten_set():
    steps = [
        {"type": "set", "repeat": 3, "steps": [
            {"type": "active", "duration_sec": 240, "zone": "z4"},
            {"type": "rest",   "duration_sec": 120, "zone": "z1"},
        ]},
    ]
    flat = _flatten(steps)
    assert len(flat) == 6
    assert flat[0]["zone"] == "z4"
    assert flat[1]["zone"] == "z1"
    assert flat[4]["zone"] == "z4"


# ---------------------------------------------------------------------------
# session_to_fit — structural checks via fitparse
# ---------------------------------------------------------------------------

def _parse_fit(data: bytes) -> list[dict]:
    """Parse workout_step messages from a FIT byte string."""
    with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        steps = []
        for msg in FitFile(path).get_messages("workout_step"):
            steps.append(cast(Any, msg).get_values())
        return steps
    finally:
        os.unlink(path)


def test_fit_step_count():
    steps = [
        {"type": "warmup",   "duration_sec": 300,  "zone": "z1", "description": "Warmup"},
        {"type": "active",   "duration_sec": 1200, "zone": "z3", "description": "Intervals"},
        {"type": "cooldown", "duration_sec": 300,  "zone": "z1", "description": "Cooldown"},
    ]
    parsed = _parse_fit(session_to_fit("Test", steps, ftp=220))
    assert len(parsed) == 3


def test_fit_set_has_repeat_step():
    steps = [
        {"type": "set", "repeat": 4, "steps": [
            {"type": "active", "duration_sec": 300, "zone": "z4", "description": "On"},
            {"type": "rest",   "duration_sec": 120, "zone": "z1", "description": "Off"},
        ]},
    ]
    parsed = _parse_fit(session_to_fit("Intervals", steps, ftp=220))
    # 2 inner steps + 1 REPEAT_UNTIL_STEPS_CMPLT marker (not 4×2 unrolled)
    assert len(parsed) == 3
    repeat = parsed[2]
    assert repeat["duration_type"] == "repeat_until_steps_cmplt"
    assert repeat["duration_step"] == 0    # loop back to step 0
    assert repeat["repeat_steps"] == 4     # 4 repetitions


def test_fit_power_targets_no_sentinel():
    """No custom_target_power_low should decode as the watts_offset sentinel."""
    steps = [
        {"type": "active", "duration_sec": 600, "zone": "z2", "description": "Z2"},
        {"type": "warmup", "duration_sec": 300, "zone": "z1", "description": "Z1"},
    ]
    parsed = _parse_fit(session_to_fit("Test", steps, ftp=220))
    for step in parsed:
        assert step.get("custom_target_power_low") != "watts_offset", (
            f"Step '{step.get('wkt_step_name')}' has watts_offset sentinel for low power"
        )


def test_fit_duration_in_seconds():
    steps = [{"type": "active", "duration_sec": 900, "zone": "z2", "description": "15min"}]
    parsed = _parse_fit(session_to_fit("Test", steps, ftp=200))
    assert parsed[0]["duration_time"] == 900.0


def test_fit_z2_power_range():
    """Z2 at FTP=200 → 110–150W stored as 1110–1150 (raw)."""
    steps = [{"type": "active", "duration_sec": 600, "zone": "z2", "description": "Z2"}]
    parsed = _parse_fit(session_to_fit("Test", steps, ftp=200))
    assert parsed[0]["custom_target_power_low"]  == 1110
    assert parsed[0]["custom_target_power_high"] == 1150
