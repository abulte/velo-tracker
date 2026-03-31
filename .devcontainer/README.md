# GitHub Codespaces Setup for velo-tracker

This directory contains the configuration for GitHub Codespaces development environment.

## What's included

- **Python 3.12** runtime environment
- **uv** package manager for fast dependency installation
- **PostgreSQL 17** database running in Docker
- **VS Code extensions** for Python development (Ruff, Black, etc.)
- **Port forwarding** for Flask app (5000) and PostgreSQL (5432)

## Automatic setup

When you create a new codespace, the setup script will automatically:

1. Install `uv` package manager
2. Start PostgreSQL database with Docker Compose
3. Install Python dependencies with `uv sync`
4. Run database migrations with `alembic upgrade head`
5. Create a default `.env` file

## Getting started

After the codespace is created and setup is complete:

### 1. Start the development server

```bash
uv run flask run
```

The app will be available at the forwarded port URL (VS Code will show a notification).

### 2. Authenticate with Garmin Connect (optional)

```bash
uv run python cli.py login
```

### 3. Sync cycling activities (requires authentication)

```bash
uv run python cli.py sync --since 2025-01-01
```

## Available commands

- `uv run flask run` - Start the Flask development server
- `uv run python cli.py login` - Authenticate with Garmin Connect
- `uv run python cli.py sync` - Sync recent activities (last 7 days)
- `uv run python cli.py sync --since YYYY-MM-DD` - Sync since specific date
- `uv run pytest` - Run tests
- `uv run ruff check .` - Check code quality
- `uv run ruff format .` - Format code
- `uv run pyright` - Type check

## Environment variables

The following environment variables are pre-configured:

- `FLASK_APP=app`
- `FLASK_DEBUG=1`
- `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/velodb`
- `SECRET_KEY=dev-secret-key-change-in-production`

## Database access

PostgreSQL is accessible at `localhost:5432` with:
- Username: `postgres`
- Password: `postgres`
- Database: `velodb`

## Troubleshooting

If the database isn't accessible, try:

```bash
docker compose restart db
```

If dependencies aren't installed, run:

```bash
uv sync
```