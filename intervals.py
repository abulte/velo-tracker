"""intervals.icu API client."""
import os
import requests

BASE_URL = "https://intervals.icu/api/v1"


def _auth() -> tuple[str, str]:
    return ("API_KEY", os.environ["INTERVALS_API_KEY"])


def _athlete_id() -> str:
    return os.environ["INTERVALS_ATHLETE_ID"]


def get_activities(oldest: str = None, newest: str = None) -> list[dict]:
    """Fetch activity list. Dates as YYYY-MM-DD strings."""
    params = {}
    if oldest:
        params["oldest"] = oldest
    if newest:
        params["newest"] = newest

    resp = requests.get(
        f"{BASE_URL}/athlete/{_athlete_id()}/activities",
        auth=_auth(),
        params=params,
    )
    resp.raise_for_status()
    return resp.json()


def get_activity(activity_id: str) -> dict:
    """Fetch a single activity by its intervals.icu ID."""
    resp = requests.get(
        f"{BASE_URL}/activity/{activity_id}",
        auth=_auth(),
    )
    resp.raise_for_status()
    return resp.json()


def get_streams(activity_id: str, types: list[str] = None) -> dict:
    """Fetch time-series streams for an activity."""
    params = {}
    if types:
        params["types"] = ",".join(types)

    resp = requests.get(
        f"{BASE_URL}/activity/{activity_id}/streams.json",
        auth=_auth(),
        params=params,
    )
    resp.raise_for_status()
    return resp.json()
