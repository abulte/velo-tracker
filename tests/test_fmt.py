import pytest
from app import fmt_dur_filter
from coach import _fmt_zone


@pytest.mark.parametrize("seconds,expected", [
    (0,    "0min"),
    (60,   "1min"),
    (3600, "1h"),
    (3660, "1h01"),
    (5400, "1h30"),
    (7200, "2h"),
    (7320, "2h02"),
])
def test_fmt_dur(seconds, expected):
    assert fmt_dur_filter(seconds) == expected


@pytest.mark.parametrize("name,lo,hi,expected", [
    ("z1", None, 0.55, "Z1 <55%"),
    ("z2", 0.55, 0.75, "Z2 55%–75%"),
    ("z4", 0.90, 1.05, "Z4 90%–105%"),
    ("z6", 1.20, None, "Z6 >120%"),
])
def test_fmt_zone(name, lo, hi, expected):
    assert _fmt_zone(name, lo, hi) == expected
