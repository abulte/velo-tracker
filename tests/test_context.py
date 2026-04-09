"""Tests for coach._build_context."""
import datetime
import pytest
from coach import _build_context
from tests.factories import goal, profile

TODAY = datetime.date(2024, 6, 1)
START = datetime.date(2024, 6, 3)  # 2 days from today
PMC = {"ctl": 55.0, "atl": 60.0, "tsb": -5.0}


def ctx(g=None, p=None, pmc=None, start=START, week_type="a"):
    """Shorthand: build context and return the string."""
    return _build_context(g or goal(), p or profile(), pmc or PMC, start, week_type, _today=TODAY)[0]


def plan_weeks(g=None, start=START, week_type="a"):
    return _build_context(g or goal(), profile(), PMC, start, week_type, _today=TODAY)[1]


# ---------------------------------------------------------------------------
# plan_weeks calculation
# ---------------------------------------------------------------------------

def test_plan_weeks_uses_weeks_to_goal():
    g = goal(target_date=TODAY + datetime.timedelta(weeks=8))
    assert plan_weeks(g, start=TODAY) == 8


def test_plan_weeks_capped_at_20():
    g = goal(target_date=TODAY + datetime.timedelta(weeks=30))
    assert plan_weeks(g, start=TODAY) == 20


def test_plan_weeks_minimum_one():
    g = goal(target_date=TODAY + datetime.timedelta(days=3))
    assert plan_weeks(g, start=TODAY) >= 1


# ---------------------------------------------------------------------------
# goal type descriptions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("goal_type,expected_fragment", [
    ("race",      "prepare for a race/event"),
    ("ftp",       "build FTP to 300W"),
    ("endurance", "build endurance"),
])
def test_goal_type_description(goal_type, expected_fragment):
    g = goal(goal_type=goal_type, target_ftp=300)
    assert expected_fragment in ctx(g)


# ---------------------------------------------------------------------------
# athlete profile display
# ---------------------------------------------------------------------------

def test_wpkg_shown_when_both_set():
    p = profile(ftp=280, weight_kg=70.0)
    assert "4.00 W/kg" in ctx(p=p)


def test_wpkg_hidden_when_no_weight():
    p = profile(ftp=280, weight_kg=None)
    assert "W/kg" not in ctx(p=p)


def test_peak_ctl_shown_when_set():
    p = profile(peak_ctl=90.0)
    assert "peak CTL 90" in ctx(p=p)


def test_peak_ctl_hidden_when_none():
    p = profile(peak_ctl=None)
    assert "peak CTL" not in ctx(p=p)


def test_unknown_ftp_when_none():
    p = profile(ftp=None)
    assert "FTP: unknown" in ctx(p=p)


# ---------------------------------------------------------------------------
# start note
# ---------------------------------------------------------------------------

def test_start_note_shown_when_future():
    future_start = TODAY + datetime.timedelta(days=10)
    result = ctx(start=future_start)
    assert "plan starts in 10 days" in result


def test_start_note_hidden_when_today():
    result = ctx(start=TODAY)
    assert "plan starts in" not in result


# ---------------------------------------------------------------------------
# weekly availability lines
# ---------------------------------------------------------------------------

def test_avail_lines_count_matches_plan_weeks():
    g = goal(target_date=TODAY + datetime.timedelta(weeks=6))
    p = profile(week_a={"sat": 3.0, "sun": 2.0}, week_b={"sat": 2.0})
    result, weeks = _build_context(g, p, PMC, TODAY, "a", _today=TODAY)
    assert weeks == 6
    assert result.count("Week ") == 6


def test_avail_lines_show_hours():
    p = profile(week_a={"sat": 3.5, "sun": 2.0})
    result = ctx(p=p)
    assert "5.5h total" in result


def test_no_riding_when_empty_week():
    p = profile(week_a=None, week_b=None)
    result = ctx(p=p)
    assert "no riding" in result
