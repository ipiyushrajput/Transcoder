#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV="$BACKEND_DIR/.venv"

cd "$BACKEND_DIR"

# Detect Python executable
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "ERROR: Python not found. Install Python 3.10+ and try again."
    exit 1
fi

# Create venv if not present
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV"
fi

# Always install / sync requirements
echo "Installing requirements..."
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r requirements.txt

# Guard against double-start
if pgrep -f "app.py" > /dev/null 2>&1; then
    echo "Backend already running."
    exit 0
fi

echo "Starting Transcoder Backend on port 5001..."
"$VENV/bin/python" app.py
