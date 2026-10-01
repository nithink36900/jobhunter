#!/usr/bin/env bash
# Mac / Linux:  ./start.sh      (first run sets everything up automatically)
cd "$(dirname "$0")" || exit 1
if [ ! -f .venv/ready.txt ]; then
  echo "First-time setup (only once)..."
  command -v python3 >/dev/null || { echo "Please install Python 3 first."; exit 1; }
  rm -rf .venv
  python3 -m venv .venv || exit 1
  .venv/bin/python -m pip install --upgrade pip -q
  .venv/bin/python -m pip install -r requirements.txt || exit 1
  .venv/bin/python -m playwright install chromium || echo "Warning: browser download failed; applying will not work."
  echo ready > .venv/ready.txt
fi
exec .venv/bin/python run.py "${@:-dashboard}"
