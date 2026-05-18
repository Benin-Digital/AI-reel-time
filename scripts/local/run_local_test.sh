#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   API_BASE=http://localhost:8000 CV_DIR=$HOME/RH/CV JOB_DIR=$HOME/RH/JOB ./scripts/local/run_local_test.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
API_BASE="${API_BASE:-http://localhost:8000}"
CV_DIR="${CV_DIR:-$HOME/RH/CV}"
JOB_DIR="${JOB_DIR:-$HOME/RH/JOB}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

mkdir -p "$CV_DIR" "$JOB_DIR"

if ! command -v python >/dev/null 2>&1; then
  echo "python not found on PATH" >&2
  exit 1
fi

if ! command -v open >/dev/null 2>&1; then
  echo "open command not found (macOS expected)" >&2
  exit 1
fi

# Start frontend
pushd "$ROOT_DIR/frontend" >/dev/null
python -m http.server "$FRONTEND_PORT" >/tmp/ai-realtime-frontend.log 2>&1 &
FRONTEND_PID=$!
popd >/dev/null

# Start RH agent
pushd "$ROOT_DIR" >/dev/null
python agent/sync_agent.py \
  --cv-dir "$CV_DIR" \
  --job-dir "$JOB_DIR" \
  --api-base "$API_BASE" \
  >/tmp/ai-realtime-agent.log 2>&1 &
AGENT_PID=$!
popd >/dev/null

# Open UI
open "http://localhost:$FRONTEND_PORT"

echo "Frontend PID: $FRONTEND_PID"
echo "Agent PID: $AGENT_PID"
echo "API_BASE: $API_BASE"
echo "CV_DIR: $CV_DIR"
echo "JOB_DIR: $JOB_DIR"
echo "Logs: /tmp/ai-realtime-frontend.log /tmp/ai-realtime-agent.log"

echo "Press Ctrl+C to stop (frontend and agent will keep running)."
wait
