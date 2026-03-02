#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/Projects}"
LABEL_PREFIX="${LABEL_PREFIX:-com.${USER:-$(id -un)}}"
AUTO_LOAD="${AUTO_LOAD:-1}"
RUN_PREFLIGHT="${RUN_PREFLIGHT:-1}"
VENV_PATH="${VENV_PATH:-$HOME/.venvs/folloze-stack}"

mkdir -p "$PROJECTS_ROOT"

clone_or_pull() {
  local name="$1"
  local url="$2"
  local dest="$PROJECTS_ROOT/$name"
  if [ -d "$dest/.git" ]; then
    echo "[repo] Updating $name"
    if git -C "$dest" remote get-url origin >/dev/null 2>&1; then
      local branch
      branch="$(git -C "$dest" rev-parse --abbrev-ref HEAD)"
      git -C "$dest" fetch origin >/dev/null 2>&1 || true
      git -C "$dest" pull --ff-only origin "$branch" || {
        echo "[repo] pull failed for $name (continuing)"
      }
    else
      echo "[repo] no origin remote for $name (skipping pull)"
    fi
  elif [ -d "$dest" ]; then
    echo "[repo] Directory exists but is not a git repo: $dest" >&2
    exit 1
  else
    echo "[repo] Cloning $name"
    git clone "$url" "$dest"
  fi
}

echo "== Folloze Fresh-Mac Setup =="
echo "STACK_ROOT=$STACK_ROOT"
echo "PROJECTS_ROOT=$PROJECTS_ROOT"
echo

clone_or_pull "deal-research-nightly-runner" "https://github.com/0xTrey/deal-research-nightly-runner.git"
clone_or_pull "deal-research" "https://github.com/0xTrey/deal-research.git"
clone_or_pull "watch-tomorrow-meetings" "https://github.com/0xTrey/watch-tomorrow-meetings.git"
clone_or_pull "granola-sync" "https://github.com/0xTrey/granola-sync.git"
clone_or_pull "weekly-report" "https://github.com/0xTrey/weekly-report.git"
clone_or_pull "google-workspace" "https://github.com/0xTrey/google-workspace.git"
clone_or_pull "granola-reader" "https://github.com/0xTrey/granola-reader.git"
clone_or_pull "llm-gateway" "https://github.com/0xTrey/llm-gateway.git"

echo
echo "[override] Applying portable code overrides"
PROJECTS_ROOT="$PROJECTS_ROOT" "$STACK_ROOT/scripts/apply_repo_overrides.sh"

echo
echo "[python] Preparing virtualenv at $VENV_PATH"
python3 -m venv "$VENV_PATH"
# shellcheck disable=SC1090
source "$VENV_PATH/bin/activate"
pip install --upgrade pip
pip install -e "$PROJECTS_ROOT/google-workspace"
pip install -e "$PROJECTS_ROOT/llm-gateway"
pip install -e "$PROJECTS_ROOT/granola-reader"
pip install -r "$PROJECTS_ROOT/deal-research/requirements.txt"
pip install -r "$PROJECTS_ROOT/watch-tomorrow-meetings/requirements.txt"

echo
echo "[config] Writing Gemini-only drafter config"
cat > "$PROJECTS_ROOT/granola-sync/email_draft_config.json" <<'JSON'
{
  "llm_profiles": ["strategic"],
  "llm_model": null
}
JSON

echo
echo "[launchd] Installing LaunchAgents"
chmod +x "$STACK_ROOT/scripts/install_folloze_launchagents.sh"
PROJECTS_ROOT="$PROJECTS_ROOT" STACK_ROOT="$STACK_ROOT" LABEL_PREFIX="$LABEL_PREFIX" AUTO_LOAD="$AUTO_LOAD" \
  "$STACK_ROOT/scripts/install_folloze_launchagents.sh"

if [ "$RUN_PREFLIGHT" = "1" ]; then
  echo
  echo "[verify] Running preflight"
  chmod +x "$STACK_ROOT/scripts/folloze_stack_preflight.sh"
  if PROJECTS_ROOT="$PROJECTS_ROOT" STACK_ROOT="$STACK_ROOT" "$STACK_ROOT/scripts/folloze_stack_preflight.sh"; then
    echo "[verify] Preflight passed"
  else
    echo "[verify] Preflight reported issues (see output above)"
  fi
fi

cat <<'EOF'

Manual steps still required:
1. Set env vars in ~/.zshrc:
   - APOLLO_API_KEY
   - GEMINI_API_KEY (or AI_GEMINI_KEY)
   - TAVILY_API_KEY (recommended)
   - GOOGLE_DRIVE_FOLDER_ID
2. Ensure keychain secret exists:
   security find-generic-password -s gemini-api -w
3. Run OAuth setup:
   source ~/.venvs/folloze-stack/bin/activate
   python -m google_workspace.setup_auth
   python3 ~/Projects/granola-sync/granola_email_drafter.py auth
4. Smoke tests:
   python3 $STACK_ROOT/skills/granola-to-deals/granola_to_deals.py --days 4 --dry-run --target zilliant.com
   python3 ~/Projects/watch-tomorrow-meetings/watch_tomorrow_meetings.py --json --dry-run
   python3 ~/Projects/granola-sync/granola_email_drafter.py status --json
EOF
