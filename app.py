import datetime
import os

import click
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request
from sqlmodel import Session, create_engine, select

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")

database_url = os.getenv("DATABASE_URL", "")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["DATABASE_URL"] = database_url

engine = create_engine(app.config["DATABASE_URL"], echo=False)


def get_session():
    return Session(engine)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@app.cli.command("sync")
@click.option("--since", default=None, help="Start date YYYY-MM-DD (default: 7 days ago)")
def cli_sync(since: str):
    """Sync activities from intervals.icu into the local DB."""
    from sync import sync_activities
    oldest = since or (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    click.echo(f"Syncing from {oldest}…")
    with get_session() as session:
        result = sync_activities(session, oldest)
    click.echo(f"Done — synced: {result['synced']}, skipped (Strava): {result['skipped']}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _stats(activities):
    rides = len(activities)
    distance = sum(a.distance or 0 for a in activities) / 1000
    time = sum(a.moving_time or 0 for a in activities)
    elevation = sum(a.total_elevation_gain or 0 for a in activities)
    tss = sum(a.tss or 0 for a in activities)
    rpe_vals = [a.icu_rpe for a in activities if a.icu_rpe]
    avg_rpe = sum(rpe_vals) / len(rpe_vals) if rpe_vals else None
    return dict(rides=rides, distance=distance, time=time,
                elevation=elevation, tss=tss, avg_rpe=avg_rpe)


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    with get_session() as session:
        activities = session.exec(
            select(Activity).order_by(Activity.start_date.desc())
        ).all()

    by_week = {}
    by_month = {}
    for a in activities:
        iso = a.start_date.isocalendar()
        wk = (iso[0], iso[1])
        mo = (a.start_date.year, a.start_date.month)
        by_week.setdefault(wk, []).append(a)
        by_month.setdefault(mo, []).append(a)

    def _week_label(year, week):
        mon = datetime.date.fromisocalendar(year, week, 1)
        sun = datetime.date.fromisocalendar(year, week, 7)
        if mon.month == sun.month:
            return f"{mon.strftime('%b %-d')}–{sun.day} {sun.strftime('%Y')}"
        return f"{mon.strftime('%b %-d')} – {sun.strftime('%b %-d %Y')}"

    weeks = [{"key": k, "label": _week_label(*k), "stats": _stats(v)}
             for k, v in sorted(by_week.items(), reverse=True)]
    months = [{"key": k, "label": datetime.date(k[0], k[1], 1).strftime("%B %Y"), "stats": _stats(v)}
              for k, v in sorted(by_month.items(), reverse=True)]

    return render_template("dashboard.html", weeks=weeks, months=months)


@app.route("/activities")
def list_activities():
    with get_session() as session:
        activities = session.exec(
            select(Activity).order_by(Activity.start_date.desc())
        ).all()
    return render_template(
        "activities/list.html",
        activities=activities,
        today=datetime.date.today(),
        timedelta=datetime.timedelta,
    )


@app.route("/activities/sync", methods=["POST"])
def sync_activities_route():
    from sync import sync_activities
    oldest = request.form.get("since") or (
        datetime.date.today() - datetime.timedelta(days=7)
    ).isoformat()
    with get_session() as session:
        result = sync_activities(session, oldest)
    return render_template("activities/_sync_result.html", **result)


@app.route("/activities/<string:icu_id>")
def show_activity(icu_id: str):
    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.icu_id == icu_id)
        ).first()
        if not activity:
            return "Not found", 404
    return render_template("activities/show.html", activity=activity)



@app.route("/activities/<string:icu_id>/streams")
def activity_streams(icu_id: str):
    import intervals
    from flask import jsonify
    raw = intervals.get_streams(icu_id, types=["latlng"])
    # latlng stream: latitudes in 'data', longitudes in 'data2'
    stream = next((s for s in raw if s["type"] == "latlng"), None)
    if not stream:
        return jsonify([])
    lats = stream.get("data") or []
    lngs = stream.get("data2") or []
    pairs = [
        [lat, lng]
        for lat, lng in zip(lats, lngs)
        if lat is not None and lng is not None
    ]
    return jsonify(pairs)


@app.route("/activities/<string:icu_id>/notes", methods=["POST"])
def save_notes(icu_id: str):
    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.icu_id == icu_id)
        ).first()
        if not activity:
            return "Not found", 404
        activity.notes = request.form.get("notes", "").strip() or None
        activity.updated_at = datetime.datetime.utcnow()
        session.add(activity)
        session.commit()
        session.refresh(activity)
    return render_template("activities/_notes.html", activity=activity)


@app.route("/health")
def health():
    try:
        with get_session() as session:
            session.exec(select(Activity).limit(1)).first()
        return {"status": "healthy"}, 200
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 500


# Import models after engine is set up so Alembic can detect them
from models import Activity  # noqa: E402, F401
