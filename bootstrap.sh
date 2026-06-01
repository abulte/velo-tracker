#!/bin/bash
set -e

echo "🚀 velo-tracker Bootstrap Script"
echo "================================="
echo
echo "This script will bootstrap your velo-tracker environment with:"
echo "  1. Garmin Connect authentication" 
echo "  2. Sample cycling data (1 month of activities)"
echo "  3. Application verification"
echo
echo "Prerequisites: Development environment should already be set up"
echo "(dependencies installed, database running, migrations applied)"
echo
echo "You'll need your Garmin Connect credentials to proceed."
echo

# Confirm user wants to proceed
read -p "Continue? (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo
echo "🔐 Step 1: Garmin Connect Authentication"
echo "========================================"
echo
echo "You'll now be prompted for your Garmin Connect credentials."
echo "These are needed to sync your cycling activities."
echo

# Authenticate with Garmin Connect
echo "Note: You'll need to enter your Garmin Connect email and password."
echo "Your credentials are only used to generate authentication tokens."
echo
if ! uv run python cli.py login; then
    echo "❌ Garmin Connect authentication failed."
    echo "   You can retry later with: uv run python cli.py login"
    echo "   Continuing with basic setup..."
    SKIP_SYNC=true
fi

echo
echo "📊 Step 2: Syncing cycling activities"
echo "====================================="

if [ "$SKIP_SYNC" = true ]; then
    echo "⏭️  Skipping activity sync due to authentication failure."
    echo "   You can sync activities later with:"
    echo "   uv run python cli.py sync --since $(date +%Y-%m-%d)"
else
    echo "Syncing the last 30 days of cycling activities..."
    
    # Sync 30 days of activities
    # Handle both GNU date (Linux) and BSD date (macOS)
    if date -v-30d >/dev/null 2>&1; then
        # BSD date (macOS)
        SINCE_DATE=$(date -v-30d +%Y-%m-%d)
    else
        # GNU date (Linux)
        SINCE_DATE=$(date -d "30 days ago" +%Y-%m-%d)
    fi
    
    if ! uv run python cli.py sync --since "$SINCE_DATE"; then
        echo "⚠️  Activity sync encountered issues, but you can retry later."
        echo "   Try: uv run python cli.py sync --since $SINCE_DATE"
    fi
fi

echo
echo "🎯 Step 3: Final verification"
echo "======================"

# Test the Flask app can start
echo "🧪 Testing Flask application..."
timeout 10s uv run flask run --host 0.0.0.0 --port 5000 &
FLASK_PID=$!
sleep 5

if kill -0 $FLASK_PID 2>/dev/null; then
    echo "✅ Flask app started successfully"
    kill $FLASK_PID
    wait $FLASK_PID 2>/dev/null || true
else
    echo "⚠️  Flask app test failed, but setup should still work"
fi

echo
echo "🎉 Bootstrap Complete!"
echo "====================="
echo
echo "Your velo-tracker environment is now ready! Here's what you can do:"
echo
echo "📱 Start the development server:"
echo "   uv run flask run"
echo "   (or 'uv run flask run --host 0.0.0.0' to bind to all interfaces)"
echo
echo "🔄 Sync more activities:"
echo "   uv run python cli.py sync                    # Last 7 days"
echo "   uv run python cli.py sync --since 2025-01-01 # Since specific date"
echo
echo "🧪 Run tests:"
echo "   uv run pytest"
echo
echo "🔍 Check code quality:"
echo "   uv run ruff check ."
echo "   uv run pyright"
echo
echo "📚 View your cycling dashboard:"
echo "   Start the Flask server and visit the provided URL"
echo
echo "Happy cycling! 🚴‍♂️"