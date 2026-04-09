import datetime
import math
import pytest
from app import _compute_pmc
from tests.factories import activity

D = datetime.date


def test_empty():
    assert _compute_pmc([]) == []


def test_single_day():
    result = _compute_pmc([activity(D(2024, 1, 1), tss=100)], _end=D(2024, 1, 1))
    assert len(result) == 1
    row = result[0]
    assert row["date"] == "2024-01-01"
    assert row["tss"] == 100
    assert row["ctl"] == pytest.approx(100 * (1 - math.exp(-1 / 42)), abs=0.05)
    assert row["atl"] == pytest.approx(100 * (1 - math.exp(-1 / 7)), abs=0.05)
    assert row["tsb"] == 0.0  # form is computed from yesterday (zero)


def test_zero_tss_decays():
    # seed one day of TSS, then let it decay over two rest days
    acts = [activity(D(2024, 1, 1), tss=100)]
    result = _compute_pmc(acts, _end=D(2024, 1, 3))
    assert len(result) == 3
    ctl_day1 = result[0]["ctl"]
    ctl_day2 = result[1]["ctl"]
    ctl_day3 = result[2]["ctl"]
    assert ctl_day3 < ctl_day2 < ctl_day1


def test_multi_day_tss_accumulates():
    acts = [activity(D(2024, 1, d), tss=80) for d in range(1, 8)]
    result = _compute_pmc(acts, _end=D(2024, 1, 7))
    # CTL should be strictly increasing over 7 days of consistent load
    ctls = [r["ctl"] for r in result]
    assert ctls == sorted(ctls)


def test_same_day_activities_sum():
    acts = [activity(D(2024, 1, 1), tss=60), activity(D(2024, 1, 1), tss=40)]
    result = _compute_pmc(acts, _end=D(2024, 1, 1))
    assert result[0]["tss"] == 100
