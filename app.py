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


def _compute_pmc(activities):
    """Compute daily CTL, ATL, TSB (Performance Management Chart)."""
    import math

    if not activities:
        return []

    daily_tss: dict[datetime.date, float] = {}
    for a in activities:
        d = a.start_date.date() if isinstance(a.start_date, datetime.datetime) else a.start_date
        daily_tss[d] = daily_tss.get(d, 0) + (a.tss or 0)

    start = min(daily_tss)
    end = datetime.date.today()

    ctl_k = math.exp(-1 / 42)
    atl_k = math.exp(-1 / 7)
    ctl_f = 1 - ctl_k
    atl_f = 1 - atl_k

    ctl = atl = 0.0
    result = []
    d = start
    while d <= end:
        tss = daily_tss.get(d, 0)
        tsb = round(ctl - atl, 1)   # yesterday's balance = today's form
        ctl = ctl * ctl_k + tss * ctl_f
        atl = atl * atl_k + tss * atl_f
        result.append({
            "date": d.isoformat(),
            "tss": round(tss, 0),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": tsb,
        })
        d += datetime.timedelta(days=1)

    return result


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

    pmc = _compute_pmc(list(activities))
    current = pmc[-1] if pmc else {"ctl": 0, "atl": 0, "tsb": 0}

    return render_template("dashboard.html", weeks=weeks, months=months, pmc=pmc, current=current)


@app.route("/activities")
def list_activities():
    from models import Route

    dist_min = request.args.get("dist_min", type=float)
    dist_max = request.args.get("dist_max", type=float)
    dur_min = request.args.get("dur_min", type=int)   # minutes
    dur_max = request.args.get("dur_max", type=int)   # minutes
    route_id = request.args.get("route_id", type=int)

    query = select(Activity).order_by(Activity.start_date.desc())
    if dist_min is not None:
        query = query.where(Activity.distance >= dist_min * 1000)
    if dist_max is not None:
        query = query.where(Activity.distance <= dist_max * 1000)
    if dur_min is not None:
        query = query.where(Activity.moving_time >= dur_min * 60)
    if dur_max is not None:
        query = query.where(Activity.moving_time <= dur_max * 60)
    if route_id is not None:
        query = query.where(Activity.route_id == route_id)

    with get_session() as session:
        all_activities = session.exec(select(Activity)).all()
        activities = session.exec(query).all()
        routes = session.exec(select(Route).order_by(Route.name)).all()

    distances = [a.distance / 1000 for a in all_activities if a.distance]
    durations = [a.moving_time // 60 for a in all_activities if a.moving_time]
    bounds = dict(
        dist_min_bound=int(min(distances, default=0)),
        dist_max_bound=int(max(distances, default=300)),
        dur_min_bound=int(min(durations, default=0)),
        dur_max_bound=int(max(durations, default=360)),
    )

    filters = dict(dist_min=dist_min, dist_max=dist_max, dur_min=dur_min, dur_max=dur_max, route_id=route_id)
    return render_template(
        "activities/list.html",
        activities=activities,
        filters=filters,
        routes=routes,
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
    from climbs import detect_climbs

    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.garmin_id == garmin_id)
        ).first()
        if not activity:
            return "Not found", 404
    climbs = detect_climbs(activity.polyline) if activity.polyline else []
    return render_template("activities/show.html", activity=activity, climbs=climbs)


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


@app.route("/routes")
def list_routes():
    from models import Route
    from sqlalchemy import func

    with get_session() as session:
        routes = session.exec(select(Route).order_by(Route.name)).all()
        counts = dict(
            session.exec(
                select(Activity.route_id, func.count(Activity.id))
                .where(Activity.route_id.isnot(None))
                .group_by(Activity.route_id)
            ).all()
        )
        ref_ids = [r.reference_activity_id for r in routes]
        ref_activities = {
            a.garmin_id: a
            for a in session.exec(
                select(Activity).where(Activity.garmin_id.in_(ref_ids))
            ).all()
        } if ref_ids else {}

    map_data = [
        {"id": r.id, "name": r.name, "pts": ref_activities[r.reference_activity_id].polyline}
        for r in routes
        if r.reference_activity_id in ref_activities and ref_activities[r.reference_activity_id].polyline
    ]

    return render_template("routes/list.html", routes=routes, counts=counts, map_data=map_data)


@app.route("/routes", methods=["POST"])
def create_route():
    from models import Route
    from routes import assign_route_to_all

    name = request.form.get("name", "").strip()
    garmin_id = request.form.get("garmin_id", "").strip()
    if not name or not garmin_id:
        return "Missing name or activity id", 400

    with get_session() as session:
        route = Route(name=name, reference_activity_id=garmin_id)
        session.add(route)
        session.commit()
        session.refresh(route)
        route_id = route.id
        count = assign_route_to_all(session, route)
        session.commit()

    is_htmx = request.headers.get("HX-Request")
    if is_htmx:
        matched = f"{count} activit{'y' if count == 1 else 'ies'} matched"
        return (
            f'<div id="route-save-area" class="mt-4 pt-4 border-t border-base-300 text-sm">'
            f'<span class="text-base-content/50">Route:</span> '
            f'<a href="/routes/{route_id}" class="link">{name}</a>'
            f'<span class="text-base-content/40 ml-2">({matched})</span>'
            f'</div>'
        )
    return redirect(url_for("show_route", route_id=route_id))


@app.route("/routes/<int:route_id>")
def show_route(route_id: int):
    from models import Route

    with get_session() as session:
        route = session.get(Route, route_id)
        if not route:
            return "Not found", 404
        activities = session.exec(
            select(Activity)
            .where(Activity.route_id == route_id)
            .order_by(Activity.start_date.desc())
        ).all()
        ref_activity = session.exec(
            select(Activity).where(Activity.garmin_id == route.reference_activity_id)
        ).first()

    distances = [a.distance / 1000 for a in activities if a.distance]
    tsses = [a.tss for a in activities if a.tss]
    stats = dict(
        count=len(activities),
        avg_distance=sum(distances) / len(distances) if distances else None,
        best_distance=max(distances) if distances else None,
        avg_tss=sum(tsses) / len(tsses) if tsses else None,
        best_tss=max(tsses) if tsses else None,
    )

    polylines = [
        {"pts": a.polyline, "garmin_id": a.garmin_id, "name": a.name, "date": a.start_date.strftime("%Y-%m-%d")}
        for a in activities if a.polyline and a.garmin_id != route.reference_activity_id
    ]
    ref_polyline = {"pts": ref_activity.polyline, "garmin_id": ref_activity.garmin_id, "name": ref_activity.name, "date": ref_activity.start_date.strftime("%Y-%m-%d")} if ref_activity and ref_activity.polyline else None

    return render_template("routes/show.html", route=route, activities=activities, stats=stats, polylines=polylines, ref_polyline=ref_polyline, ref_activity=ref_activity)


@app.route("/routes/<int:route_id>/edit", methods=["POST"])
def edit_route(route_id: int):
    from models import Route

    name = request.form.get("name", "").strip()
    if not name:
        return "Name required", 400

    with get_session() as session:
        route = session.get(Route, route_id)
        if not route:
            return "Not found", 404
        route.name = name
        session.add(route)
        session.commit()

    return f'<h1 id="route-title" class="text-xl font-bold">{name}</h1>'


@app.route("/routes/<int:route_id>/delete", methods=["POST"])
def delete_route(route_id: int):
    with get_session() as session:
        activities = session.exec(
            select(Activity).where(Activity.route_id == route_id)
        ).all()
        for a in activities:
            a.route_id = None
        session.commit()

        from models import Route
        route = session.get(Route, route_id)
        if route:
            session.delete(route)
            session.commit()

    return redirect(url_for("list_routes"))


@app.route("/routes/<int:route_id>/course", methods=["POST"])
def save_course_url(route_id: int):
    from models import Route

    with get_session() as session:
        route = session.get(Route, route_id)
        if not route:
            return "Not found", 404
        route.garmin_course_url = request.form.get("garmin_course_url", "").strip() or None
        session.add(route)
        session.commit()
        session.refresh(route)

    return render_template("routes/_course_url.html", route=route)


@app.route("/activities/<string:garmin_id>/gpx")
def activity_gpx(garmin_id: str):
    from flask import Response

    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.garmin_id == garmin_id)
        ).first()
        if not activity:
            return "Not found", 404
        if not activity.polyline:
            return "No polyline for this activity", 404

    name = request.args.get("name", activity.name)
    pts = []
    for p in activity.polyline:
        lat, lon = p[0], p[1]
        ele = p[2] if len(p) > 2 and p[2] is not None else None
        ele_tag = f"<ele>{ele}</ele>" if ele is not None else ""
        pts.append(f'    <trkpt lat="{lat}" lon="{lon}">{ele_tag}</trkpt>\n')
    points = "".join(pts)
    gpx = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="velo-tracker"'
        ' xmlns="http://www.topografix.com/GPX/1/1">\n'
        f'  <trk><name>{name}</name><trkseg>\n'
        f'{points}'
        '  </trkseg></trk>\n'
        '</gpx>'
    )
    return Response(
        gpx,
        mimetype="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{name}.gpx"'},
    )


@app.route("/health")
def health():
    try:
        with get_session() as session:
            session.exec(select(Activity).limit(1)).first()
        return {"status": "healthy"}, 200
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 500


# Import models after engine is set up so Alembic can detect them
from models import Activity, Route  # noqa: E402, F401
