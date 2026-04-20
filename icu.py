"""intervals.icu API sync — fetch athlete metrics and classify level."""
import datetime
import json
import logging

import requests

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

