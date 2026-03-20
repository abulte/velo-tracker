import datetime
import os

import click
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request
from flask_fenrir import create_fenrir_bp, secure_app
from sqlmodel import Session, create_engine, select

load_dotenv()

app = Flask("velo-tracker")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")

database_url = os.getenv("DATABASE_URL", "")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["DATABASE_URL"] = database_url

engine = create_engine(app.config["DATABASE_URL"], echo=False)

# Fenrir
app.register_blueprint(create_fenrir_bp(engine))
secure_app(app)

def get_session():
    return Session(engine)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@app.cli.command("sync")
@click.option("--since", default=None, help="Start date YYYY-MM-DD (default: 1 year ago)")
def cli_sync(since: str):
    """Sync cycling activities from Garmin Connect."""
    from cli import sync_activities

    cutoff = (
        datetime.date.fromisoformat(since)
        if since
        else datetime.date.today() - datetime.timedelta(days=7)
    )
    click.echo(f"Syncing from {cutoff}…")
    with get_session() as session:
        result = sync_activities(session, cutoff)
    click.echo(f"Done — synced: {result['synced']}, skipped (non-cycling): {result['skipped']}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _stats(activities):
    rides = len(activities)
    distance = sum(a.distance or 0 for a in activities) / 1000
    time = sum(a.moving_time or 0 for a in activities)
    elevation = sum(a.total_elevation_gain or 0 for a in activities)
    tss = sum(a.tss or 0 for a in activities)
    rpe_vals = [a.rpe for a in activities if a.rpe]
    avg_rpe = sum(rpe_vals) / len(rpe_vals) if rpe_vals else None

    by_type = {}
    for a in activities:
        by_type.setdefault(a.activity_type, []).append(a)
    type_breakdown = {}
    for t, acts in sorted(by_type.items()):
        t_rpe = [a.rpe for a in acts if a.rpe]
        type_breakdown[t] = dict(
            rides=len(acts),
            distance=sum(a.distance or 0 for a in acts) / 1000,
            time=sum(a.moving_time or 0 for a in acts),
            elevation=sum(a.total_elevation_gain or 0 for a in acts),
            tss=sum(a.tss or 0 for a in acts),
            avg_rpe=sum(t_rpe) / len(t_rpe) if t_rpe else None,
        )

    return dict(rides=rides, distance=distance, time=time,
                elevation=elevation, tss=tss, avg_rpe=avg_rpe,
                by_type=type_breakdown)


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

    # Prepare chart data (reverse chronological order for display)
    sorted_weeks = sorted(by_week.items())
    chart_labels = []
    chart_distance = []
    chart_weekly_tss = []
    
    for (year, week), activities in sorted_weeks:
        # Calculate weekly distance in km
        weekly_distance = sum(a.distance or 0 for a in activities) / 1000
        # Calculate weekly TSS (not cumulative)
        weekly_tss = sum(a.tss or 0 for a in activities)
        
        chart_labels.append(_week_label(year, week))
        chart_distance.append(weekly_distance)
        chart_weekly_tss.append(weekly_tss)
    
    chart_data = {
        "labels": chart_labels,
        "distance": chart_distance,
        "weeklyTss": chart_weekly_tss
    }

    return render_template("dashboard.html", weeks=weeks, months=months, chart_data=chart_data)


@app.route("/activities")
def list_activities():
    dist_min = request.args.get("dist_min", type=float)
    dist_max = request.args.get("dist_max", type=float)
    dur_min = request.args.get("dur_min", type=int)   # minutes
    dur_max = request.args.get("dur_max", type=int)   # minutes

    query = select(Activity).order_by(Activity.start_date.desc())
    if dist_min is not None:
        query = query.where(Activity.distance >= dist_min * 1000)
    if dist_max is not None:
        query = query.where(Activity.distance <= dist_max * 1000)
    if dur_min is not None:
        query = query.where(Activity.moving_time >= dur_min * 60)
    if dur_max is not None:
        query = query.where(Activity.moving_time <= dur_max * 60)

    with get_session() as session:
        all_activities = session.exec(select(Activity)).all()
        activities = session.exec(query).all()

    distances = [a.distance / 1000 for a in all_activities if a.distance]
    durations = [a.moving_time // 60 for a in all_activities if a.moving_time]
    bounds = dict(
        dist_min_bound=int(min(distances, default=0)),
        dist_max_bound=int(max(distances, default=300)),
        dur_min_bound=int(min(durations, default=0)),
        dur_max_bound=int(max(durations, default=360)),
    )

    filters = dict(dist_min=dist_min, dist_max=dist_max, dur_min=dur_min, dur_max=dur_max)
    return render_template(
        "activities/list.html",
        activities=activities,
        filters=filters,
        **bounds,
        today=datetime.date.today(),
        timedelta=datetime.timedelta,
    )


@app.route("/activities/sync", methods=["POST"])
def sync_activities_route():
    from cli import sync_activities

    oldest = request.form.get("since") or (
        datetime.date.today() - datetime.timedelta(days=7)
    ).isoformat()
    cutoff = datetime.date.fromisoformat(oldest)
    with get_session() as session:
        result = sync_activities(session, cutoff)
    return render_template("activities/_sync_result.html", **result)


@app.route("/activities/<string:garmin_id>")
def show_activity(garmin_id: str):
    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.garmin_id == garmin_id)
        ).first()
        if not activity:
            return "Not found", 404
    return render_template("activities/show.html", activity=activity)


@app.route("/activities/<string:garmin_id>/streams")
def activity_streams(garmin_id: str):
    from flask import jsonify

    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.garmin_id == garmin_id)
        ).first()
        if activity and activity.polyline:
            return jsonify(activity.polyline)
    return jsonify([])


@app.route("/activities/<string:garmin_id>/notes", methods=["POST"])
def save_notes(garmin_id: str):
    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.garmin_id == garmin_id)
        ).first()
        if not activity:
            return "Not found", 404
        activity.notes = request.form.get("notes", "").strip() or None
        activity.updated_at = datetime.datetime.utcnow()
        session.add(activity)
        session.commit()
        session.refresh(activity)
    return render_template("activities/_notes.html", activity=activity)


@app.route("/heatmap/data")
def heatmap_data():
    from flask import jsonify

    try:
        with get_session() as session:
            activities = session.exec(
                select(Activity).where(Activity.polyline.isnot(None))
            ).all()
        
        # Build heatmap data: coordinate frequency mapping
        coord_frequency = {}
        
        for activity in activities:
            if activity.polyline and isinstance(activity.polyline, list):
                for point in activity.polyline:
                    # Validate coordinate data
                    if (isinstance(point, (list, tuple)) and len(point) >= 2 
                        and isinstance(point[0], (int, float)) and isinstance(point[1], (int, float))
                        and -90 <= point[0] <= 90 and -180 <= point[1] <= 180):
                        
                        lat, lon = point[0], point[1]
                        # Round coordinates to reduce precision for frequency counting
                        rounded_lat = round(lat, 4)  # ~11m precision
                        rounded_lon = round(lon, 4)
                        coord_key = (rounded_lat, rounded_lon)
                        coord_frequency[coord_key] = coord_frequency.get(coord_key, 0) + 1
        
        # Convert to heatmap format: [lat, lon, intensity]
        heatmap_points = [
            [coord[0], coord[1], frequency] 
            for coord, frequency in coord_frequency.items()
            if frequency > 0  # Ensure positive frequency
        ]
        
        return jsonify(heatmap_points)
    
    except Exception as e:
        app.logger.error(f"Error generating heatmap data: {str(e)}")
        return jsonify({"error": "Failed to generate heatmap data"}), 500


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
