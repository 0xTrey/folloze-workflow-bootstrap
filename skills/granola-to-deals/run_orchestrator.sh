#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/.openclaw/logs"
LOG_FILE="$LOG_DIR/deal-docs-ingestion.log"
RUNS_FILE="$LOG_DIR/deal-docs-ingestion.jsonl"
STATUS_FILE="$LOG_DIR/deal-docs-ingestion.status.json"
MAX_LOG_BYTES=$((5 * 1024 * 1024))
ALERT_DISCORD_TARGET="${GRANOLA_ALERT_DISCORD_TARGET:-channel:1480676983041167541}"
ALERT_EMAIL_TO="${GRANOLA_ALERT_EMAIL_TO:-trey.harnden@folloze.com}"
ALERT_EMAIL_FROM="${GRANOLA_ALERT_EMAIL_FROM:-mason@elevationengine.co}"

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

rotate_file_if_large() {
  local file="$1"
  [ -f "$file" ] || return 0
  local size
  size=$(wc -c <"$file" | tr -d ' ')
  if [ "$size" -ge "$MAX_LOG_BYTES" ]; then
    mv "$file" "$file.$(date -u +'%Y%m%dT%H%M%SZ')"
  fi
}

extract_summary_line() {
  local output="$1"
  "$PYTHON_BIN" - "$output" <<'PY'
import json
import sys

for line in reversed(sys.argv[1].splitlines()):
    try:
        payload = json.loads(line)
    except Exception:
        continue
    if payload.get("event") == "run_summary":
        print(json.dumps(payload, sort_keys=True))
        break
PY
}

write_status_files() {
  local summary_line="$1"
  [ -z "$summary_line" ] && return 0
  rotate_file_if_large "$RUNS_FILE"
  printf '%s\n' "$summary_line" >"$STATUS_FILE"
  printf '%s\n' "$summary_line" >>"$RUNS_FILE"
}

notify_failure() {
  local summary_line="$1"
  [ -z "$summary_line" ] && return 0
  ALERT_DISCORD_TARGET="$ALERT_DISCORD_TARGET" ALERT_EMAIL_TO="$ALERT_EMAIL_TO" ALERT_EMAIL_FROM="$ALERT_EMAIL_FROM" \
  "$PYTHON_BIN" - "$summary_line" "$STATUS_FILE" "$RUNS_FILE" "$LOG_FILE" <<'PY'
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

payload = json.loads(sys.argv[1])
if payload.get("dry_run"):
    raise SystemExit(0)

status_file, runs_file, log_file = sys.argv[2:5]
message = f"{payload.get('failure_total', 0)} failure(s) across {payload.get('meetings_total', 0)} meeting(s)"
failures = payload.get("failures") or []
if failures:
    first = failures[0]
    detail = first.get("meeting_title") or first.get("domain") or first.get("error") or "unknown failure"
    message = f"{message}: {detail}"

script = f"display notification {json.dumps(message[:220])} with title \"Granola to Deal Docs\""
subprocess.run(["/usr/bin/osascript", "-e", script], check=False)

subject = "[Mason] Granola to deal docs error"
body = "\n".join(
    [
        subject,
        "",
        f"Detail: {message}",
        f"Finished: {payload.get('finished_at', 'unknown')}",
        f"Status file: {status_file}",
        f"Runs log: {runs_file}",
        f"Main log: {log_file}",
    ]
)

discord_cmd = [
    os.getenv("OPENCLAW_BIN", "openclaw"),
    "message",
    "send",
    "--channel",
    "discord",
    "--target",
    os.getenv("GRANOLA_ALERT_DISCORD_TARGET", "channel:1480676983041167541"),
    "--message",
    body[:1900],
]
if os.getenv("GRANOLA_ALERTS_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}:
    discord_cmd.extend(["--dry-run", "--json"])
try:
    subprocess.run(discord_cmd, capture_output=True, text=True, timeout=20, check=True)
except (OSError, subprocess.CalledProcessError):
    pass

if os.getenv("GRANOLA_ALERTS_DRY_RUN", "").strip().lower() not in {"1", "true", "yes", "on"}:
    api_key = os.getenv("AGENTMAIL_API_KEY", "").strip()
    if not api_key:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "agentmail-api", "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            api_key = result.stdout.strip()
    if api_key:
        inbox_id = urllib.parse.quote(
            os.getenv("GRANOLA_ALERT_EMAIL_FROM", "mason@elevationengine.co"),
            safe="",
        )
        request = urllib.request.Request(
            f"https://api.agentmail.to/inboxes/{inbox_id}/messages/send",
            data=json.dumps(
                {
                    "to": [os.getenv("GRANOLA_ALERT_EMAIL_TO", "trey.harnden@folloze.com")],
                    "subject": subject,
                    "body": body,
                    "reply_to": os.getenv("GRANOLA_ALERT_EMAIL_FROM", "mason@elevationengine.co"),
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20):
                pass
        except Exception:
            pass
PY
}

# Non-fatal helper for any downstream consumers that inspect Gemini/Google keys.
if GEMINI_API_KEY="$(security find-generic-password -s "gemini-api" -w 2>/dev/null)"; then
  export GEMINI_API_KEY
  export GOOGLE_API_KEY="$GEMINI_API_KEY"
fi

rotate_file_if_large "$LOG_FILE"

RUN_START_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
if [ -n "${GRANOLA_TO_DEALS_ARGS:-}" ]; then
  read -r -a EXTRA_ARGS <<<"$GRANOLA_TO_DEALS_ARGS"
else
  EXTRA_ARGS=(--days 4)
fi
CMD=("$PYTHON_BIN" "$SCRIPT_DIR/granola_to_deals.py" "${EXTRA_ARGS[@]}")
ARGS_JSON="$("$PYTHON_BIN" - "${EXTRA_ARGS[@]}" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]))
PY
)"

{
  echo "=== ${RUN_START_UTC} granola nightly sync start ==="
  echo "command: ${CMD[*]}"
} >>"$LOG_FILE"

if OUTPUT="$("${CMD[@]}" 2>&1)"; then
  SUMMARY_LINE="$(extract_summary_line "$OUTPUT")"
  write_status_files "$SUMMARY_LINE"
  {
    printf '%s\n' "$OUTPUT"
    echo "{\"status\":\"ok\",\"source\":\"granola_to_deals_nightly\",\"script\":\"granola_to_deals.py\",\"args\":${ARGS_JSON},\"finished_at\":\"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"}"
    echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') granola nightly sync end ==="
  } >>"$LOG_FILE"
else
  RC=$?
  SUMMARY_LINE="$(extract_summary_line "$OUTPUT")"
  if [ -z "$SUMMARY_LINE" ]; then
    SUMMARY_LINE="{\"event\":\"run_summary\",\"failure_total\":1,\"failures\":[{\"error\":\"script_failed\"}],\"meetings_total\":0}"
  fi
  write_status_files "$SUMMARY_LINE"
  notify_failure "$SUMMARY_LINE"
  {
    printf '%s\n' "$OUTPUT"
    echo "{\"status\":\"error\",\"source\":\"granola_to_deals_nightly\",\"script\":\"granola_to_deals.py\",\"args\":${ARGS_JSON},\"exit_code\":${RC},\"finished_at\":\"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"}"
    echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') granola nightly sync end ==="
  } >>"$LOG_FILE"
  exit "$RC"
fi
