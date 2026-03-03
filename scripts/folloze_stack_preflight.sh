#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_STACK_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

STACK_ROOT="${STACK_ROOT:-$DEFAULT_STACK_ROOT}"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/Projects}"
SKILLS_ROOT="${SKILLS_ROOT:-$STACK_ROOT/skills}"

FAILURES=0
WARNINGS=0

ok() { printf 'OK    %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf 'FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

check_file() {
  local path="$1"
  if [ -f "$path" ]; then
    ok "file exists: $path"
  else
    fail "missing file: $path"
  fi
}

check_dir() {
  local path="$1"
  if [ -d "$path" ]; then
    ok "directory exists: $path"
  else
    fail "missing directory: $path"
  fi
}

check_optional_file() {
  local path="$1"
  if [ -f "$path" ]; then
    ok "optional file exists: $path"
  else
    warn "optional file missing: $path"
  fi
}

check_env_required() {
  local var_name="$1"
  if [ -n "${!var_name:-}" ]; then
    ok "env set: $var_name"
  else
    fail "env missing: $var_name"
  fi
}

check_env_any() {
  local first="$1"
  local second="$2"
  if [ -n "${!first:-}" ] || [ -n "${!second:-}" ]; then
    ok "env set: $first/$second"
  else
    fail "env missing: $first or $second"
  fi
}

check_keychain_secret() {
  local service="$1"
  if security find-generic-password -s "$service" -w >/dev/null 2>&1; then
    ok "keychain secret present: $service"
  else
    warn "keychain secret missing: $service"
  fi
}

check_launch_suffix() {
  local suffix="$1"
  if launchctl list | rg -q "com\\..*\\.${suffix}$"; then
    ok "LaunchAgent loaded: *.${suffix}"
  else
    fail "LaunchAgent not loaded: *.${suffix}"
  fi
}

check_help_invocation() {
  local label="$1"
  shift
  if "$@" --help >/dev/null 2>&1; then
    ok "cli imports OK: $label"
  else
    fail "cli failed --help: $label"
  fi
}

printf 'Folloze Stack Preflight (%s)\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
printf 'STACK_ROOT=%s\n' "$STACK_ROOT"
printf 'PROJECTS_ROOT=%s\n' "$PROJECTS_ROOT"
printf 'SKILLS_ROOT=%s\n' "$SKILLS_ROOT"
printf -- '--------------------------------------------------\n'

check_dir "$STACK_ROOT"
check_dir "$PROJECTS_ROOT"
check_dir "$SKILLS_ROOT"

printf '\n# Core scripts\n'
check_file "$SKILLS_ROOT/granola-to-deals/granola_to_deals.py"
check_file "$SKILLS_ROOT/granola-to-deals/run_orchestrator.sh"
check_file "$SKILLS_ROOT/deal-context-manager/deal_context_manager.py"
check_file "$STACK_ROOT/scripts/install_folloze_launchagents.sh"
check_file "$PROJECTS_ROOT/deal-research-nightly-runner/runner.py"
check_file "$PROJECTS_ROOT/deal-research/deal_research.py"
check_file "$PROJECTS_ROOT/watch-tomorrow-meetings/watch_tomorrow_meetings.py"
check_file "$PROJECTS_ROOT/granola-sync/granola_sync.py"
check_file "$PROJECTS_ROOT/granola-sync/granola_email_drafter.py"
check_file "$PROJECTS_ROOT/google-workspace/google_workspace/auth.py"
check_file "$PROJECTS_ROOT/granola-reader/granola_reader.py"

printf '\n# Optional index-backed workflow\n'
check_optional_file "$PROJECTS_ROOT/deal-notes-index/deal_notes_index.py"

printf '\n# OAuth and local state\n'
check_file "$HOME/.config/openclaw/google/token.json"
if [ -f "$HOME/.config/google-workspace/credentials.json" ] || [ -f "$HOME/.config/openclaw/google/credentials.json" ]; then
  ok "google oauth credentials found (.config/google-workspace or .config/openclaw/google)"
else
  warn "google oauth credentials missing (.config/google-workspace/credentials.json or .config/openclaw/google/credentials.json)"
fi
check_optional_file "$HOME/.config/granola-email-drafter/token.json"
check_file "$HOME/.openclaw/deal-index.json"

printf '\n# Required env vars\n'
check_env_required "APOLLO_API_KEY"
check_env_any "GEMINI_API_KEY" "AI_GEMINI_KEY"
check_env_required "GOOGLE_DRIVE_FOLDER_ID"
if [ -n "${TAVILY_API_KEY:-}" ]; then
  ok "env set: TAVILY_API_KEY"
else
  warn "env missing: TAVILY_API_KEY (recommended for research quality)"
fi

printf '\n# Keychain secrets used by automations\n'
check_keychain_secret "gemini-api"

printf '\n# LaunchAgents\n'
check_launch_suffix "deal-research-nightly-runner"
check_launch_suffix "granola-to-deals"
check_launch_suffix "granola-sync"
check_launch_suffix "granola-email-drafter"

printf '\n# CLI import smoke checks\n'
check_help_invocation "granola_to_deals" python3 "$SKILLS_ROOT/granola-to-deals/granola_to_deals.py"
check_help_invocation "watch_tomorrow_meetings" python3 "$PROJECTS_ROOT/watch-tomorrow-meetings/watch_tomorrow_meetings.py"
check_help_invocation "granola_sync" python3 "$PROJECTS_ROOT/granola-sync/granola_sync.py"
check_help_invocation "granola_email_drafter" python3 "$PROJECTS_ROOT/granola-sync/granola_email_drafter.py"

printf '\nSummary: failures=%d warnings=%d\n' "$FAILURES" "$WARNINGS"
if [ "$FAILURES" -gt 0 ]; then
  exit 1
fi
exit 0
