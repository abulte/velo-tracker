# velo-tracker

A personal cycling dashboard that syncs rides from Garmin Connect. Built with Flask, SQLModel, and PostgreSQL.

## Features

- **Sync** — pulls cycling activities from Garmin Connect (road, gravel, indoor, e-bike)
- **Dashboard** — weekly and monthly breakdowns: rides, distance, time, elevation, TSS, avg RPE
- **Activity detail** — per-ride stats, interactive map (from Garmin polyline data), and freeform notes
- **Activity types** — automatic classification with emoji indicators (🚴 road, 🪨 gravel, 🏠 indoor, ⚡ e-bike MTB)
- **Upsert sync** — safe to re-run; updates existing activities by Garmin ID

## Tech stack

Flask · SQLModel · PostgreSQL · Alembic · [garminconnect](https://github.com/cyberjunky/python-garminconnect) · Gunicorn · [flask-fenrir](https://github.com/badlogic/flask-fenrir)

## Setup

### Prerequisites

- Python 3.12+
- Docker (for PostgreSQL)
- A Garmin Connect account

### 1. Start the database

```bash
docker compose up -d
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Configure environment

Create a `.env` file:

```
FLASK_APP=app
FLASK_DEBUG=1
DATABASE_URL=postgres://postgres:postgres@localhost:5432/velodb
SECRET_KEY=change-me-in-production
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Authenticate with Garmin

```bash
python cli.py login
```

This saves OAuth tokens locally to `garmin_tokens/` (gitignored) and prints a `dokku config:set` command for deployment.

### 6. Sync activities

```bash
python cli.py sync                  # last 7 days
python cli.py sync --since 2025-01-01
```

### 7. Run the app

```bash
flask run
```

## Deployment (Dokku)

The app ships with a `Procfile` and `app.json` for Dokku:

```bash
# Push Garmin tokens as base64 env vars
dokku config:set velo-tracker \
  GARMIN_OAUTH1_TOKEN='...' \
  GARMIN_OAUTH2_TOKEN='...' \
  SECRET_KEY='...' \
  DATABASE_URL='...'

# Deploy
git push dokku main
```

Migrations run automatically on release (`alembic upgrade head`).

Sync can be triggered from the UI or via `flask sync` on the server.

## Data notes

- **Distance**: metres (÷1000 for km)
- **Speed**: m/s (×3.6 for km/h)
- **Time**: seconds
- **RPE/Feel**: Garmin's 0–100 scale
- Only activities with `parentTypeId == 2` (cycling) are synced; everything else is skipped

## License

MIT
