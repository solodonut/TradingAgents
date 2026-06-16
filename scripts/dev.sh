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
  if ! command -v uvicorn >/dev/null 2>&1; then
    echo "error: uvicorn not found. Install dev deps: pip install -e \".[dev]\"" >&2
    exit 1
  fi
  free_port "$API_PORT"
  echo "starting backend  → http://localhost:${API_PORT}  (uvicorn api.main:app --reload)"
  ( cd "$ROOT" && exec uvicorn api.main:app --reload --port "$API_PORT" ) &
  PIDS+=($!)
fi

# --- start frontend ----------------------------------------------------------
if [ "$START_WEB" = 1 ]; then
  if [ ! -d "$ROOT/webui/node_modules" ]; then
    echo "error: webui/node_modules missing. Run: cd webui && npm install" >&2
    exit 1
  fi
  free_port "$WEB_PORT"
  echo "starting frontend → http://localhost:${WEB_PORT}  (next dev)"
  ( cd "$ROOT/webui" && exec npm run dev -- --port "$WEB_PORT" ) &
  PIDS+=($!)
fi

echo "both servers up. Press Ctrl-C to stop."
wait
