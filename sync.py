"""Shared sync logic — used by both the webapp and the CLI."""
import datetime
from sqlmodel import Session, select

import intervals
from models import Activity


def sync_activities(session: Session, oldest: str) -> dict[str, int]:
    """
    Fetch activities from intervals.icu since `oldest` (YYYY-MM-DD) and
    upsert them into the DB. Returns {"synced": n, "skipped": n}.
    """
    raw = intervals.get_activities(oldest=oldest)

    synced = 0
    skipped = 0
    for item in raw:
        if "_note" in item:
            skipped += 1
            continue

        existing = session.exec(
            select(Activity).where(Activity.icu_id == item["id"])
        ).first()
        activity = existing or Activity(icu_id=item["id"])

        activity.athlete_id = item.get("icu_athlete_id", "")
        activity.name = item.get("name", "")
        activity.sport = item.get("type", "")
        activity.start_date = datetime.datetime.fromisoformat(item["start_date_local"])
        activity.distance = item.get("distance")
        activity.moving_time = item.get("moving_time")
        activity.elapsed_time = item.get("elapsed_time")
        activity.total_elevation_gain = item.get("total_elevation_gain")
        activity.average_watts = item.get("icu_average_watts")
        activity.normalized_watts = item.get("icu_weighted_avg_watts")
        activity.max_watts = item.get("max_watts")
        activity.average_heartrate = item.get("average_heartrate")
        activity.max_heartrate = item.get("max_heartrate")
        activity.average_cadence = item.get("average_cadence")
        activity.average_speed = item.get("average_speed")
        activity.max_speed = item.get("max_speed")
        activity.tss = item.get("icu_training_load")
        activity.intensity_factor = item.get("icu_intensity")
        activity.icu_training_load = item.get("icu_training_load")
        activity.icu_rpe = item.get("icu_rpe")
        activity.feel = item.get("feel")
        activity.description = item.get("description")
        activity.updated_at = datetime.datetime.utcnow()

        session.add(activity)
        synced += 1

    session.commit()
    return {"synced": synced, "skipped": skipped}
