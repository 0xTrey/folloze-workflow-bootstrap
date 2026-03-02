#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OVERRIDES_ROOT="$STACK_ROOT/overrides"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/Projects}"

require_dir() {
  local path="$1"
  if [ ! -d "$path" ]; then
    echo "Missing required directory: $path" >&2
    exit 1
  fi
}

copy_override() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  echo "Applied override: $dst"
}

require_dir "$OVERRIDES_ROOT"
require_dir "$PROJECTS_ROOT/deal-research-nightly-runner"
require_dir "$PROJECTS_ROOT/watch-tomorrow-meetings"
require_dir "$PROJECTS_ROOT/granola-sync"

copy_override \
  "$OVERRIDES_ROOT/deal-research-nightly-runner/runner.py" \
  "$PROJECTS_ROOT/deal-research-nightly-runner/runner.py"
copy_override \
  "$OVERRIDES_ROOT/deal-research-nightly-runner/README.md" \
  "$PROJECTS_ROOT/deal-research-nightly-runner/README.md"
copy_override \
  "$OVERRIDES_ROOT/watch-tomorrow-meetings/watch_tomorrow_meetings.py" \
  "$PROJECTS_ROOT/watch-tomorrow-meetings/watch_tomorrow_meetings.py"
copy_override \
  "$OVERRIDES_ROOT/granola-sync/granola_email_drafter.py" \
  "$PROJECTS_ROOT/granola-sync/granola_email_drafter.py"
copy_override \
  "$OVERRIDES_ROOT/granola-sync/email_draft_config.example.json" \
  "$PROJECTS_ROOT/granola-sync/email_draft_config.example.json"
copy_override \
  "$OVERRIDES_ROOT/granola-sync/TOOL_CONTRACT.md" \
  "$PROJECTS_ROOT/granola-sync/TOOL_CONTRACT.md"
copy_override \
  "$OVERRIDES_ROOT/granola-sync/launchd/com.user.granola-email-drafter.template.plist" \
  "$PROJECTS_ROOT/granola-sync/launchd/com.user.granola-email-drafter.template.plist"

echo "Repo overrides applied."
