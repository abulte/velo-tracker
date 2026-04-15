"""intervals.icu API sync — fetch athlete metrics and classify level."""
import base64
import datetime
import json
import logging

import requests

from fit_export import session_to_fit

log = logging.getLogger(__name__)

_BASE = "https://intervals.icu/api/v1"


def _get(athlete_id: str, api_key: str, path: str, **params) -> dict:
    url = f"{_BASE}/athlete/{athlete_id}/{path}"
    r = requests.get(url, auth=("API_KEY", api_key), params=params, timeout=15)
    r.raise_for_status()
    return r.json()  # type: ignore[no-any-return]


def _get_list(athlete_id: str, api_key: str, path: str, **params) -> list:
    url = f"{_BASE}/athlete/{athlete_id}/{path}"
    r = requests.get(url, auth=("API_KEY", api_key), params=params, timeout=15)
    r.raise_for_status()
    return r.json()  # type: ignore[no-any-return]


def _post(athlete_id: str, api_key: str, path: str, payload: object) -> object:
    url = f"{_BASE}/athlete/{athlete_id}/{path}"
    r = requests.post(url, auth=("API_KEY", api_key), data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, timeout=15)
    if not r.ok:
        log.error("ICU POST %s → %s: %s", path, r.status_code, r.text)
    r.raise_for_status()
    return r.json()  # type: ignore[no-any-return]


def _del(athlete_id: str, api_key: str, path: str) -> None:
    url = f"{_BASE}/athlete/{athlete_id}/{path}"
    r = requests.delete(url, auth=("API_KEY", api_key), timeout=15)
    if r.status_code != 404:
        r.raise_for_status()


def _classify_level(peak_ctl: float, watts_per_kg: float | None) -> str:
    ctl_level = (
        "elite" if peak_ctl >= 100 else
        "competitive" if peak_ctl >= 70 else
        "amateur" if peak_ctl >= 40 else
        "recreational"
    )
    if watts_per_kg is None:
        return ctl_level
    wpkg_level = (
        "elite" if watts_per_kg >= 4.5 else
        "competitive" if watts_per_kg >= 3.5 else
        "amateur" if watts_per_kg >= 2.5 else
        "recreational"
    )
    # Take the higher of the two signals
    order = ["recreational", "amateur", "competitive", "elite"]
    return order[max(order.index(ctl_level), order.index(wpkg_level))]


def sync_athlete(athlete_id: str, api_key: str) -> dict:
    """
    Fetch key metrics from intervals.icu and return a dict of profile fields to update.
    """
    # Current athlete profile: weight
    athlete = _get(athlete_id, api_key, "")
    weight_kg = athlete.get("icu_weight")

    # Peak CTL over last 3 years
    oldest = (datetime.date.today() - datetime.timedelta(days=365 * 3)).isoformat()
    wellness = _get(athlete_id, api_key, "wellness", oldest=oldest)
    peak_ctl = max((w.get("ctl") or 0 for w in wellness), default=0)

    athlete_level = _classify_level(peak_ctl, None)

    log.info("icu sync: weight=%s peak_ctl=%.1f level=%s", weight_kg, peak_ctl, athlete_level)

    return {
        "weight_kg": weight_kg,
        "peak_ctl": peak_ctl,
        "athlete_level": athlete_level,
        "icu_synced_at": datetime.datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# Workout calendar event push
# ---------------------------------------------------------------------------

def push_workout_event(
    athlete_id: str,
    api_key: str,
    session_date: datetime.date,
    title: str,
    steps: list[dict],
    tss_target: int,
    duration_min: int,
    ftp: int,
    activity_id: object = None,
    old_icu_event_id: str | None = None,
) -> str | None:
    """
    Create a workout calendar event in intervals.icu. Returns the event id, or None if skipped.

    Skips if:
    - session_date is in the past (already happened)
    - activity_id is set (session already paired with an activity)

    If pushing a new event and old_icu_event_id exists, deletes the old orphaned event first.
    """
    # Skip if session is in the past
    if session_date < datetime.date.today():
        log.info("icu push skipped: session %s is in the past", title)
        return None

    # Skip if session is already linked to an activity
    if activity_id is not None:
        log.info("icu push skipped: session %s already linked to activity", title)
        return None

    # Delete old orphaned event if one exists
    if old_icu_event_id:
        delete_workout_event(athlete_id, api_key, old_icu_event_id)

    fit_b64 = base64.b64encode(session_to_fit(title, steps, ftp)).decode()
    event = {
        "category": "WORKOUT",
        "start_date_local": f"{session_date.isoformat()}T00:00:00",
        "name": title,
        "file_contents_base64": fit_b64,
        "filename": "workout.fit",
        "type": "Ride",
        "moving_time": duration_min * 60,
        "icu_training_load": tss_target,
    }
    # POST /events takes a single EventEx object (not array — use /events/bulk for batch)
    resp = _post(athlete_id, api_key, "events", event)
    assert isinstance(resp, dict)
    log.info("icu push: event %s → %s on %s", resp.get("id"), title, session_date)
    return str(resp["id"])


def delete_workout_event(athlete_id: str, api_key: str, event_id: str) -> None:
    """Delete a workout calendar event from intervals.icu. Silently ignores 404."""
    _del(athlete_id, api_key, f"events/{event_id}")
    log.info("icu delete: event %s", event_id)


# ---------------------------------------------------------------------------
# Compliance sync
# ---------------------------------------------------------------------------

def fetch_compliance(
    athlete_id: str,
    api_key: str,
    event_ids: set[str],
    oldest: datetime.date,
    newest: datetime.date,
) -> dict[str, tuple[float, str]]:
    """
    Return a mapping of icu_event_id → (compliance%, garmin_activity_id) for activities
    paired to one of the given event IDs.  Unpaired or missing activities are omitted.
    """
    activities = _get_list(
        athlete_id, api_key, "activities",
        oldest=oldest.isoformat(),
        newest=newest.isoformat(),
        fields="id,paired_event_id,compliance,external_id",
    )
    result: dict[str, tuple[float, str]] = {}
    for act in activities:
        paired = act.get("paired_event_id")
        compliance = act.get("compliance")
        garmin_id = act.get("external_id")  # external_id is the Garmin activity ID
        if paired is not None and compliance is not None and garmin_id is not None:
            eid = str(paired)
            if eid in event_ids:
                result[eid] = (float(compliance), str(garmin_id))
                log.info("icu compliance: event %s → %.0f%% (activity %s)", eid, compliance, garmin_id)
    return result
