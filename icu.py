"""intervals.icu API sync — fetch athlete metrics and classify level."""
import datetime
import logging

import requests

log = logging.getLogger(__name__)

_BASE = "https://intervals.icu/api/v1"


def _get(athlete_id: str, api_key: str, path: str, **params):
    url = f"{_BASE}/athlete/{athlete_id}/{path}"
    r = requests.get(url, auth=("API_KEY", api_key), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


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
