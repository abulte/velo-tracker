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

@app.route("/")
def index():
    return redirect(url_for("list_activities"))


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


@app.route("/activities/<string:icu_id>/notes", methods=["GET"])
def get_notes(icu_id: str):
    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.icu_id == icu_id)
        ).first()
        if not activity:
            return "Not found", 404
    return render_template("activities/_notes.html", activity=activity)


@app.route("/activities/<string:icu_id>/notes/edit", methods=["GET"])
def edit_notes(icu_id: str):
    with get_session() as session:
        activity = session.exec(
            select(Activity).where(Activity.icu_id == icu_id)
        ).first()
        if not activity:
            return "Not found", 404
    return render_template("activities/_notes_form.html", activity=activity)


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
