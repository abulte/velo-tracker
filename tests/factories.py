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
