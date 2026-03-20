#!/usr/bin/env python3
"""CLI for velo-tracker: login & sync against Garmin Connect."""

import base64
import datetime
import json
import sys
from getpass import getpass
from pathlib import Path

import click
from dotenv import load_dotenv
from sqlmodel import Session, create_engine, select

load_dotenv()

TOKEN_DIR = Path(__file__).parent / "garmin_tokens"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _engine():
    import os

    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, echo=False)


def _map_activity(item: dict, detail_summary: dict | None = None) -> dict:
    """Map a Garmin Connect activity dict to our model fields.

    `item` comes from get_activities (list endpoint).
    `detail_summary` is the summaryDTO from get_activity (detail endpoint),
    used for fields only available there (RPE, feel).
    """
    at = item.get("activityType", {})
    ds = detail_summary or {}
    return dict(
        garmin_id=str(item["activityId"]),
        name=item.get("activityName", ""),
        activity_type=at.get("typeKey", ""),
        start_date=datetime.datetime.fromisoformat(
            item["startTimeGMT"].replace(" ", "T")
        ),
        distance=item.get("distance"),
        moving_time=int(item["movingDuration"]) if item.get("movingDuration") else None,
        elapsed_time=int(item["elapsedDuration"]) if item.get("elapsedDuration") else None,
        total_elevation_gain=item.get("elevationGain"),
        average_watts=item.get("avgPower"),
        normalized_watts=item.get("normPower"),
        max_watts=int(item["maxPower"]) if item.get("maxPower") else None,
        average_heartrate=item.get("averageHR"),
        max_heartrate=int(item["maxHR"]) if item.get("maxHR") else None,
        average_cadence=item.get("averageBikingCadenceInRevPerMinute"),
        average_speed=item.get("averageSpeed"),
        max_speed=item.get("maxSpeed"),
        tss=item.get("trainingStressScore"),
        intensity_factor=item.get("intensityFactor"),
        training_load=item.get("activityTrainingLoad"),
        rpe=ds.get("directWorkoutRpe"),
        feel=ds.get("directWorkoutFeel"),
        description=item.get("description"),
    )


def sync_activities(session: Session, since: datetime.date) -> dict[str, int]:
    """Fetch activities from Garmin Connect since `since` and upsert into DB."""
    from garmin import get_client
    from models import Activity

    client = get_client()

    # Garmin uses start/limit pagination, not date filters on the list endpoint.
    # We paginate until we pass the cutoff date.
    created = 0
    updated = 0
    skipped = 0
    batch_size = 50
    offset = 0
    cutoff = datetime.datetime.combine(since, datetime.time.min)

    while True:
        batch = client.get_activities(start=offset, limit=batch_size)
        if not batch:
            break

        past_cutoff = False
        for item in batch:
            start_str = item.get("startTimeGMT", "")
            start_dt = datetime.datetime.fromisoformat(start_str.replace(" ", "T"))
            if start_dt < cutoff:
                past_cutoff = True
                break

            # Only sync cycling activities
            at = item.get("activityType", {})
            parent = at.get("parentTypeId")
            if parent != 2:  # 2 = cycling
                skipped += 1
                continue

            name = item.get("activityName", "?")[:40]
            type_key = at.get("typeKey", "?")
            click.echo(f"  [{created + updated + 1}] {start_dt:%Y-%m-%d} {name} ({type_key})… ", nl=False)

            # Fetch detail for RPE/feel (only in summaryDTO)
            detail = client.get_activity(item["activityId"])
            detail_summary = detail.get("summaryDTO", {}) if detail else {}

            # Fetch polyline for map
            pairs = []
            try:
                details = client.get_activity_details(item["activityId"])
                poly = details.get("geoPolylineDTO", {})
                points = poly.get("polyline", []) if poly else []
                pairs = [
                    [p["lat"], p["lon"]]
                    for p in points
                    if p.get("lat") is not None and p.get("lon") is not None
                ]
            except Exception:
                pass  # no polyline for this activity

            fields = _map_activity(item, detail_summary)
            fields["polyline"] = pairs if pairs else None
            garmin_id = fields.pop("garmin_id")

            existing = session.exec(
                select(Activity).where(Activity.garmin_id == garmin_id)
            ).first()
            is_new = existing is None
            activity = existing or Activity(garmin_id=garmin_id)

            for k, v in fields.items():
                setattr(activity, k, v)
            activity.updated_at = datetime.datetime.utcnow()

            session.add(activity)
            if is_new:
                created += 1
            else:
                updated += 1
            click.echo("✓")

        if past_cutoff or len(batch) < batch_size:
            break
        offset += batch_size

    session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """velo-tracker CLI."""
    pass


@cli.command()
def login():
    """Authenticate with Garmin Connect and store tokens."""
    from garminconnect import Garmin, GarminConnectAuthenticationError

    email = input("Garmin Connect email: ").strip()
    password = getpass("Garmin Connect password: ")

    click.echo("Authenticating…")
    try:
        client = Garmin(email, password)
        client.login()
    except GarminConnectAuthenticationError as e:
        click.echo(f"Authentication failed: {e}", err=True)
        sys.exit(1)

    # Save tokens locally
    TOKEN_DIR.mkdir(exist_ok=True)
    client.garth.dump(str(TOKEN_DIR))
    click.echo(f"✅ Tokens saved to {TOKEN_DIR}/")

    # Print dokku config:set command
    oauth1 = base64.b64encode(
        (TOKEN_DIR / "oauth1_token.json").read_bytes()
    ).decode()
    oauth2 = base64.b64encode(
        (TOKEN_DIR / "oauth2_token.json").read_bytes()
    ).decode()
    click.echo()
    click.echo("To deploy to Dokku, run:")
    click.echo(
        f"  dokku config:set velo-tracker "
        f"GARMIN_OAUTH1_TOKEN='{oauth1}' "
        f"GARMIN_OAUTH2_TOKEN='{oauth2}'"
    )

    # Quick verification
    click.echo()
    click.echo("Verifying…")
    activities = client.get_activities(start=0, limit=1)
    if activities:
        a = activities[0]
        at = a.get("activityType", {})
        click.echo(
            f"  Latest: {a.get('activityName')} ({at.get('typeKey')})"
        )
    click.echo("Done.")


@cli.command()
@click.option("--since", default=None, help="Start date YYYY-MM-DD (default: 1 year ago)")
def sync(since: str | None):
    """Sync cycling activities from Garmin Connect."""
    cutoff = (
        datetime.date.fromisoformat(since)
        if since
        else datetime.date.today() - datetime.timedelta(days=7)
    )

    click.echo(f"Syncing activities since {cutoff}…")
    engine = _engine()
    with Session(engine) as session:
        result = sync_activities(session, cutoff)
    click.echo(f"Done — new: {result['created']}, updated: {result['updated']}, skipped (non-cycling): {result['skipped']}")


if __name__ == "__main__":
    cli()
