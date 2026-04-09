"""Factory functions for building test data."""
import datetime
from types import SimpleNamespace


def step(type: str = "interval", duration_sec: int = 300, zone: str = "z4", **kwargs) -> dict:
    return {"type": type, "duration_sec": duration_sec, "zone": zone, **kwargs}


def set_(steps: list, repeat: int = 3) -> dict:
    return {"type": "set", "repeat": repeat, "steps": steps}


def activity(date: datetime.date, tss: float) -> SimpleNamespace:
    return SimpleNamespace(start_date=date, tss=tss)
