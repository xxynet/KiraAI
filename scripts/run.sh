#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root (one level up from this script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "$REPO_ROOT"

# Python executable selection
PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

# Step 1: Create venv if missing
if [ ! -d .venv ]; then
  echo "[1/3] Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
else
  echo "Virtual environment already exists."
fi

# Step 2: Activate venv
echo "[2/3] Activating virtual environment..."
# shellcheck disable=SC1091
source .venv/bin/activate

# Step 3: Install dependencies
echo "[3/3] Installing dependencies..."
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
else
  echo "requirements.txt not found, skipping dependency installation."
fi

# Step 4: Run the app
echo "=============================="
echo " Launching application..."
echo "=============================="

if [ -f launch.py ]; then
  exec python launch.py
else
  echo "Error: launch.py not found."
  exit 1
fi
