"""Factory functions for building test data."""
import datetime
from types import SimpleNamespace
from typing import cast

from cli import GarminActivity


def step(type: str = "interval", duration_sec: int = 300, zone: str = "z4", **kwargs) -> dict:
    return {"type": type, "duration_sec": duration_sec, "zone": zone, **kwargs}


def set_(steps: list, repeat: int = 3) -> dict:
    return {"type": "set", "repeat": repeat, "steps": steps}


def activity(date: datetime.date, tss: float) -> SimpleNamespace:
    return SimpleNamespace(start_date=date, tss=tss)


def goal(
    title: str = "Race Goal",
    goal_type: str = "race",
    target_date: datetime.date = datetime.date(2025, 6, 1),
    target_ftp: int | None = None,
    notes: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(title=title, goal_type=goal_type, target_date=target_date, target_ftp=target_ftp, notes=notes)


def profile(
    ftp: int | None = 280,
    weight_kg: float | None = 70.0,
    athlete_level: str | None = "amateur",
    peak_ctl: float | None = 75.0,
    week_a: dict | None = None,
    week_b: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(ftp=ftp, weight_kg=weight_kg, athlete_level=athlete_level, peak_ctl=peak_ctl, week_a=week_a, week_b=week_b)


def garmin_activity(
    activity_id: int = 1,
    date: str = "2024-01-15 10:00:00",
    name: str = "Morning Ride",
    type_key: str = "cycling",
    parent_type_id: int = 2,
    tss: float = 80.0,
    **kwargs,
) -> GarminActivity:
    return cast(GarminActivity, {
        "activityId": activity_id,
        "startTimeGMT": date,
        "activityName": name,
        "activityType": {"typeKey": type_key, "parentTypeId": parent_type_id},
        "trainingStressScore": tss,
        **kwargs,
    })
