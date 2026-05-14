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

# Step 1: Migrate .venv -> venv (backward compatibility)
if [ -d .venv ] && [ ! -d venv ]; then
  echo "[compat] Renaming .venv to venv..."
  mv .venv venv
fi

# Step 1: Create venv if missing
if [ ! -d venv ]; then
  echo "[1/3] Creating virtual environment..."
  "$PYTHON_BIN" -m venv venv
else
  echo "Virtual environment already exists."
fi

# Step 2: Activate venv
echo "[2/3] Activating virtual environment..."
# shellcheck disable=SC1091
source venv/bin/activate

# Step 3: Test pip mirrors and select fastest
echo "[3/3] Testing pip mirrors..."

MIRROR=""
BEST_SPEED=0

test_mirror() {
  local name="$1" url="$2"
  local result
  result=$(curl -s -o /dev/null -r 0-32767 -w "%{http_code} %{time_connect} %{speed_download}" -m 5 "$url" 2>/dev/null) || true
  local http=$(echo "$result" | awk '{print $1}')
  local connect_time=$(echo "$result" | awk '{print $2}')
  local speed=$(echo "$result" | awk '{print $3}')

  if [[ "$http" == "200" || "$http" == "206" ]]; then
    local ms
    ms=$(echo "$connect_time" | awk -F. '{sec=$1; frac=substr($2"000",1,3); print sec*1000+frac}')
    local speed_int=${speed%%.*}
    local fmt_speed
    if (( speed_int >= 1048576 )); then
      fmt_speed="$(( speed_int / 1048576 )) MB/s"
    elif (( speed_int >= 1024 )); then
      fmt_speed="$(( speed_int / 1024 )) KB/s"
    else
      fmt_speed="${speed_int} B/s"
    fi
    echo "    $name ... ${ms}ms, $fmt_speed"
    if (( speed_int > BEST_SPEED )); then
      BEST_SPEED=$speed_int
      MIRROR="-i $url"
    fi
  else
    echo "    $name ... unreachable"
  fi
}

test_mirror "pypi.org" "https://pypi.org/simple/"
test_mirror "pypi.tuna.tsinghua.edu.cn" "https://pypi.tuna.tsinghua.edu.cn/simple/"
test_mirror "mirrors.aliyun.com" "https://mirrors.aliyun.com/pypi/simple/"
test_mirror "mirrors.cloud.tencent.com" "https://mirrors.cloud.tencent.com/pypi/simple/"

echo
if [ -n "$MIRROR" ]; then
  echo "  Selected: $MIRROR"
else
  echo "  All mirrors unreachable, using default PyPI."
  MIRROR="-i https://pypi.org/simple/"
fi

python -m pip install --upgrade pip $MIRROR
if [ -f requirements.txt ]; then
  pip install -r requirements.txt $MIRROR
else
  echo "requirements.txt not found, skipping dependency installation."
fi

# Step 4: Run the app
echo "=============================="
echo " Launching application..."
echo "=============================="

if [ -f main.py ]; then
  exec python main.py "$@"
else
  echo "Error: main.py not found."
  exit 1
fi
