# GitHub Codespaces Setup for velo-tracker

This directory contains the configuration for GitHub Codespaces development environment.

## What's included

- **Python 3.12** runtime environment
- **uv** package manager for fast dependency installation
- **PostgreSQL 17** database service
- **VS Code extensions** for Python development (Ruff, Black, etc.)
- **Port forwarding** for Flask app (5000) and PostgreSQL (5432)

## Automatic setup

When you create a new codespace, the setup script will automatically:

1. Install `uv` package manager
2. Wait for PostgreSQL database service to be ready
3. Install Python dependencies with `uv sync`
4. Run database migrations with `alembic upgrade head`
5. Create a default `.env` file

## Getting started

After the codespace is created and setup is complete, you have two options:

### Option A: Complete Bootstrap (Recommended)

Run the bootstrap script for a fully configured environment with sample data:

```bash
./bootstrap.sh
```

This will:
1. 🔐 Guide you through Garmin Connect authentication
2. 📊 Sync 30 days of your cycling activities
3. 🧪 Test the Flask application
4. 📚 Provide usage instructions

**This is the fastest way to get a working environment with real data!**

### Option B: Manual Setup

For more control over the setup process:

#### 1. Start the development server

```bash
uv run flask run
```

The app will be available at the forwarded port URL (VS Code will show a notification).

#### 2. Authenticate with Garmin Connect (optional)

```bash
uv run python cli.py login
```

#### 3. Sync cycling activities (requires authentication)

```bash
uv run python cli.py sync --since 2025-01-01
```

## Available commands

**Bootstrap:**
- `./bootstrap.sh` - Complete environment setup with Garmin auth and sample data

**Development:**
- `uv run flask run` - Start the Flask development server
- `uv run python cli.py login` - Authenticate with Garmin Connect
- `uv run python cli.py sync` - Sync recent activities (last 7 days)
- `uv run python cli.py sync --since YYYY-MM-DD` - Sync since specific date

**Code Quality:**
- `uv run pytest` - Run tests
- `uv run ruff check .` - Check code quality
- `uv run ruff format .` - Format code
- `uv run pyright` - Type check

## Environment variables

The following environment variables are pre-configured:

- `FLASK_APP=app`
- `FLASK_DEBUG=1`
- `DATABASE_URL=postgresql://postgres:postgres@db:5432/velodb`
- `SECRET_KEY=dev-secret-key-change-in-production`

## Database access

PostgreSQL is accessible at `db:5432` (or `localhost:5432` via port forwarding) with:
- Username: `postgres`
- Password: `postgres`
- Database: `velodb`

## Troubleshooting

If the database isn't accessible, restart the codespace or check that the PostgreSQL service is running.

If dependencies aren't installed, run:

```bash
uv sync
```