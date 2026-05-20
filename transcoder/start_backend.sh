#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV="$BACKEND_DIR/.venv"

cd "$BACKEND_DIR"

# Create venv if not exists
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q -r requirements.txt
fi

# Check if already running
if pgrep -f "app.py" > /dev/null; then
    echo "Backend already running"
    exit 0
fi

echo "Starting Transcoder Backend on port 5001..."
"$VENV/bin/python" app.py
