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


@app.route("/api/performance-insights")
def performance_insights():
    from flask import jsonify, g
    from flask_fenrir import require_auth
    from collections import defaultdict
    import calendar

    # Ensure user is authenticated
    require_auth()
    
    try:
        with get_session() as session:
            # Limit to last 2 years of data for performance
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=730)
            activities = session.exec(
                select(Activity)
                .where(Activity.start_date >= cutoff_date)
                .order_by(Activity.start_date)
            ).all()

        # Group activities by month
        by_month = defaultdict(list)
        for activity in activities:
            month_key = f"{activity.start_date.year}-{activity.start_date.month:02d}"
            by_month[month_key].append(activity)

        insights = []
        for month_key in sorted(by_month.keys()):
            activities_in_month = by_month[month_key]
            year, month = map(int, month_key.split('-'))
            month_name = f"{calendar.month_abbr[month]} {year}"
            
            # Calculate metrics with better error handling
            total_distance = sum(a.distance or 0 for a in activities_in_month) / 1000  # km
            total_time = sum(a.moving_time or 0 for a in activities_in_month) / 3600  # hours
            total_tss = sum(a.tss or 0 for a in activities_in_month)
            
            # Average power (weighted by time) - fix division by zero
            power_activities = [(a.average_watts, a.moving_time) for a in activities_in_month 
                              if a.average_watts and a.average_watts > 0 and a.moving_time and a.moving_time > 0]
            
            if power_activities:
                power_time_sum = sum(power * time for power, time in power_activities)
                total_power_time = sum(time for _, time in power_activities)
                avg_power = power_time_sum / total_power_time if total_power_time > 0 else None
            else:
                avg_power = None
            
            # Average RPE - handle Garmin's 0-100 scale
            rpe_values = [a.rpe / 10.0 for a in activities_in_month 
                         if a.rpe is not None and a.rpe > 0]  # Convert from 0-100 to 0-10 scale
            avg_rpe = sum(rpe_values) / len(rpe_values) if rpe_values else None
            
            insights.append({
                'month': month_name,
                'distance': round(total_distance, 1) if total_distance > 0 else 0,
                'time': round(total_time, 1) if total_time > 0 else 0,
                'tss': round(total_tss) if total_tss > 0 else 0,
                'avgPower': round(avg_power) if avg_power and avg_power > 0 else None,
                'avgRpe': round(avg_rpe, 1) if avg_rpe and avg_rpe > 0 else None,
                'activities': len(activities_in_month)
            })

        return jsonify(insights)
    
    except Exception as e:
        app.logger.error(f"Error in performance_insights: {str(e)}")
        return jsonify({'error': 'Failed to load performance insights'}), 500


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
