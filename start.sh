#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/backend"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10 or newer." >&2
  exit 1
fi

if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
. venv/bin/activate

echo "Installing packages (first run only takes a minute)..."
pip install -q -r requirements.txt

if [ ! -f ../frontend/dist/index.html ]; then
  echo "The built dashboard is missing. Run 'npm install && npm run build' inside the frontend folder." >&2
  exit 1
fi

echo
echo "Starting Outage Command Center at http://localhost:8000 (Ctrl+C to stop)"
( sleep 2; (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || (command -v open >/dev/null && open http://localhost:8000) || true ) >/dev/null 2>&1 &
exec python -m uvicorn app.main:app --port 8000
