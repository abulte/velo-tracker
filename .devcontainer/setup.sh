#!/bin/bash
set -e

echo "🚀 Setting up velo-tracker development environment..."

# Install uv package manager
echo "📦 Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
source /home/vscode/.cargo/env

# Wait for PostgreSQL to be ready (started by feature)
echo "⏳ Waiting for PostgreSQL to start..."
until pg_isready -h localhost -p 5432 -U postgres; do
  echo "Waiting for PostgreSQL..."
  sleep 2
done

# Create the database if it doesn't exist
echo "🗃️  Creating database..."
createdb -h localhost -U postgres velodb 2>/dev/null || echo "Database already exists"

# Install Python dependencies
echo "🐍 Installing Python dependencies..."
uv sync

# Run database migrations
echo "🗃️  Running database migrations..."
uv run alembic upgrade head

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
  echo "📝 Creating .env file..."
  cat > .env << EOF
FLASK_APP=app
FLASK_DEBUG=1
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/velodb
SECRET_KEY=dev-secret-key-change-in-production
EOF
fi

echo "✅ Setup complete! You can now:"
echo "   1. Run 'uv run flask run' to start the development server"
echo "   2. Run 'uv run python cli.py login' to authenticate with Garmin Connect"
echo "   3. Run 'uv run python cli.py sync' to sync activities"
echo ""
echo "The Flask app will be available at http://localhost:5000"