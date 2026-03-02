#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/.openclaw/logs"
LOG_FILE="$LOG_DIR/deal-docs-ingestion.log"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x "/opt/homebrew/opt/python@3.13/libexec/bin/python3" ]; then
    PYTHON_BIN="/opt/homebrew/opt/python@3.13/libexec/bin/python3"
  elif [ -x "/opt/homebrew/bin/python3.13" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.13"
  else
    PYTHON_BIN="python3"
  fi
fi

mkdir -p "$LOG_DIR"

# Non-fatal helper for any downstream consumers that inspect Gemini/Google keys.
if GEMINI_API_KEY="$(security find-generic-password -s "gemini-api" -w 2>/dev/null)"; then
  export GEMINI_API_KEY
  export GOOGLE_API_KEY="$GEMINI_API_KEY"
fi

RUN_START_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
CMD=("$PYTHON_BIN" "$SCRIPT_DIR/granola_to_deals.py" --days 4)

{
  echo "=== ${RUN_START_UTC} granola nightly sync start ==="
  echo "command: ${CMD[*]}"
} >>"$LOG_FILE"

if OUTPUT="$("${CMD[@]}" 2>&1)"; then
  {
    printf '%s\n' "$OUTPUT"
    echo "{\"status\":\"ok\",\"source\":\"granola_to_deals_nightly\",\"script\":\"granola_to_deals.py\",\"args\":[\"--days\",\"4\"],\"finished_at\":\"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"}"
    echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') granola nightly sync end ==="
  } >>"$LOG_FILE"
else
  RC=$?
  {
    printf '%s\n' "$OUTPUT"
    echo "{\"status\":\"error\",\"source\":\"granola_to_deals_nightly\",\"script\":\"granola_to_deals.py\",\"args\":[\"--days\",\"4\"],\"exit_code\":${RC},\"finished_at\":\"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"}"
    echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') granola nightly sync end ==="
  } >>"$LOG_FILE"
  exit "$RC"
fi
