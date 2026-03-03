#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Low-storage defaults suitable for 16GB Macs.
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/Projects}"
VENV_PATH="${VENV_PATH:-$HOME/.venvs/folloze-stack}"

LOW_STORAGE_MODE=1 \
SKIP_WEEKLY_REPORT=1 \
PROJECTS_ROOT="$PROJECTS_ROOT" \
VENV_PATH="$VENV_PATH" \
"$STACK_ROOT/scripts/setup_fresh_mac.sh"
