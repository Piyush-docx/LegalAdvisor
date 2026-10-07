#!/usr/bin/env bash
# Start the Legal Help backend (FastAPI :8000) and frontend (Vite :5173).
# Usage: ./run.sh   — stop both with Ctrl+C.
set -e
cd "$(dirname "$0")"

kill_tree() {
  local pid=$1
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

PYTHON_BIN="python3"
for py in "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" "/usr/local/bin/python3" "$(command -v python3 2>/dev/null)"; do
  if [ -n "$py" ] && [ -x "$py" ] && "$py" -c "import fastapi" 2>/dev/null; then
    PYTHON_BIN="$py"
    break
  fi
done

"$PYTHON_BIN" -m uvicorn src.api:app --reload --port 8000 --env-file .env &
BACKEND_PID=$!

(cd frontend && npm run dev) &
FRONTEND_PID=$!

cleanup() {
  trap - INT TERM EXIT
  kill_tree "$BACKEND_PID"
  kill_tree "$FRONTEND_PID"
}
trap cleanup INT TERM EXIT
wait
