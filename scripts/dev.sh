#!/usr/bin/env bash
#
# dev.sh — start the TradingAgents WebUI backend (FastAPI :8000) and
# frontend (Next.js :3000) together. Frees the ports first if anything
# is already listening on them, so re-running never collides with a
# stale server.
#
# Usage:
#   scripts/dev.sh            # start both, stream logs, Ctrl-C stops both
#   scripts/dev.sh --api      # backend only
#   scripts/dev.sh --web      # frontend only
#
set -euo pipefail

API_PORT=8000
WEB_PORT=3000
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- arg parsing -------------------------------------------------------------
START_API=1
START_WEB=1
case "${1:-}" in
  --api) START_WEB=0 ;;
  --web) START_API=0 ;;
  "" )   ;;
  * ) echo "usage: $0 [--api|--web]" >&2; exit 2 ;;
esac

# --- free a port if occupied -------------------------------------------------
# lsof is the most reliable way to find the listener on macOS.
free_port() {
  local port="$1" pids
  pids=$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ' || true)
  pids="${pids% }"
  if [ -n "$pids" ]; then
    echo "port ${port} in use by PID(s): ${pids} — killing"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    # escalate if anything survived
    pids=$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

# --- child process tracking + cleanup ---------------------------------------
PIDS=()
cleanup() {
  echo
  echo "shutting down…"
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  # also reclaim the ports in case a child spawned its own listener
  [ "$START_API" = 1 ] && free_port "$API_PORT"
  [ "$START_WEB" = 1 ] && free_port "$WEB_PORT"
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- start backend -----------------------------------------------------------
if [ "$START_API" = 1 ]; then
  # Resolve a Python interpreter explicitly. The project's .venv is required
  # (requires-python >=3.10); the shell's `python3`/`uvicorn` on PATH may be an
  # unrelated env (e.g. a Framework/conda Python with NumPy-1.x-compiled wheels
  # that crash against this project's NumPy 2.x). Prefer .venv, never bare PATH.
  if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
  elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PY="$VIRTUAL_ENV/bin/python"
  else
    echo "error: no project virtualenv found at .venv/. Create it and install dev deps:" >&2
    echo "       python3.10 -m venv .venv && .venv/bin/pip install -e \".[dev]\"" >&2
    exit 1
  fi
  if ! "$PY" -c "import uvicorn" >/dev/null 2>&1; then
    echo "error: uvicorn not installed in $PY. Run: $PY -m pip install -e \".[dev]\"" >&2
    exit 1
  fi
  free_port "$API_PORT"
  echo "starting backend  → http://localhost:${API_PORT}  ($PY -m uvicorn api.main:app --reload)"
  ( cd "$ROOT" && exec "$PY" -m uvicorn api.main:app --reload --port "$API_PORT" ) &
  PIDS+=($!)
fi

# --- start frontend ----------------------------------------------------------
if [ "$START_WEB" = 1 ]; then
  if [ ! -d "$ROOT/webui/node_modules" ]; then
    echo "error: webui/node_modules missing. Run: cd webui && npm install" >&2
    exit 1
  fi
  # Next.js 16 requires Node >=20.9. Some machines have an old /usr/local/bin/node
  # (v16) ahead of a homebrew node 26 on PATH. Prefer a >=20 node if the current
  # one is too old, by putting common homebrew/nvm bin dirs first.
  NODE_MAJOR="$(node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/' || echo 0)"
  if [ "${NODE_MAJOR:-0}" -lt 20 ] 2>/dev/null; then
    for d in /opt/homebrew/bin /usr/local/opt/node/bin "$HOME/.nvm/versions/node"/*/bin; do
      if [ -x "$d/node" ]; then
        _m="$("$d/node" -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/')"
        if [ "${_m:-0}" -ge 20 ] 2>/dev/null; then export PATH="$d:$PATH"; break; fi
      fi
    done
  fi
  free_port "$WEB_PORT"
  echo "starting frontend → http://localhost:${WEB_PORT}  (next dev, node $(node -v 2>/dev/null))"
  ( cd "$ROOT/webui" && exec npm run dev -- --port "$WEB_PORT" ) &
  PIDS+=($!)
fi

echo "both servers up. Press Ctrl-C to stop."
wait
