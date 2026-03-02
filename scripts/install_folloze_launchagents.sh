#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_STACK_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOME_DIR="${HOME}"
USER_NAME="${USER:-$(id -un)}"
LABEL_PREFIX="${LABEL_PREFIX:-com.${USER_NAME}}"
STACK_ROOT="${STACK_ROOT:-$DEFAULT_STACK_ROOT}"
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME_DIR/Projects}"
SKILLS_ROOT="${SKILLS_ROOT:-$STACK_ROOT/skills}"
LAUNCH_AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME_DIR/Library/LaunchAgents}"

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

AUTO_LOAD="${AUTO_LOAD:-1}"
PATH_VALUE="${PATH_VALUE:-/opt/homebrew/opt/python@3.13/libexec/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin}"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$HOME_DIR/.openclaw/logs"
mkdir -p "$HOME_DIR/Library/Logs/granola-sync"
mkdir -p "$HOME_DIR/Library/Logs/deal-research-nightly-runner"

write_plist_deal_research() {
  local label="${LABEL_PREFIX}.deal-research-nightly-runner"
  local path="${LAUNCH_AGENTS_DIR}/${label}.plist"
  cat >"$path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>source ${HOME_DIR}/.zshrc >/dev/null 2>/dev/null; cd ${PROJECTS_ROOT}/deal-research-nightly-runner; ${PYTHON_BIN} runner.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>21</integer>
    <key>Minute</key><integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${HOME_DIR}/Library/Logs/deal-research-nightly-runner/runner.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME_DIR}/Library/Logs/deal-research-nightly-runner/runner.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>${HOME_DIR}</string>
    <key>PATH</key><string>${PATH_VALUE}</string>
  </dict>
</dict>
</plist>
EOF
  plutil -lint "$path" >/dev/null
}

write_plist_granola_to_deals() {
  local label="${LABEL_PREFIX}.granola-to-deals"
  local path="${LAUNCH_AGENTS_DIR}/${label}.plist"
  cat >"$path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SKILLS_ROOT}/granola-to-deals/run_orchestrator.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SKILLS_ROOT}/granola-to-deals</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>1</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>${HOME_DIR}/.openclaw/logs/granola-to-deals.launchd.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME_DIR}/.openclaw/logs/granola-to-deals.launchd.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>${HOME_DIR}</string>
    <key>PATH</key><string>${PATH_VALUE}</string>
  </dict>
</dict>
</plist>
EOF
  plutil -lint "$path" >/dev/null
}

write_plist_granola_sync() {
  local label="${LABEL_PREFIX}.granola-sync"
  local path="${LAUNCH_AGENTS_DIR}/${label}.plist"
  cat >"$path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${PROJECTS_ROOT}/granola-sync/granola_sync.py</string>
    <string>sync</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>${HOME_DIR}/Library/Logs/granola-sync/sync.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME_DIR}/Library/Logs/granola-sync/sync.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>${HOME_DIR}</string>
    <key>PATH</key><string>${PATH_VALUE}</string>
  </dict>
</dict>
</plist>
EOF
  plutil -lint "$path" >/dev/null
}

write_plist_email_drafter() {
  local label="${LABEL_PREFIX}.granola-email-drafter"
  local path="${LAUNCH_AGENTS_DIR}/${label}.plist"
  cat >"$path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>GEMINI_KEY=\$(security find-generic-password -s 'gemini-api' -w 2>/dev/null); if [ -z "\$GEMINI_KEY" ]; then echo 'Missing keychain secret: gemini-api' 1>/dev/stderr; exit 1; fi; export AI_GEMINI_KEY="\$GEMINI_KEY" GEMINI_API_KEY="\$GEMINI_KEY"; exec ${PYTHON_BIN} ${PROJECTS_ROOT}/granola-sync/granola_email_drafter.py run --json</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>1800</integer>
  <key>StandardOutPath</key>
  <string>${HOME_DIR}/Library/Logs/granola-sync/email-drafter.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME_DIR}/Library/Logs/granola-sync/email-drafter.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>${HOME_DIR}</string>
    <key>PATH</key><string>${PATH_VALUE}</string>
  </dict>
</dict>
</plist>
EOF
  plutil -lint "$path" >/dev/null
}

write_plist_deal_research
write_plist_granola_to_deals
write_plist_granola_sync
write_plist_email_drafter

if [ "$AUTO_LOAD" = "1" ]; then
  for suffix in deal-research-nightly-runner granola-to-deals granola-sync granola-email-drafter; do
    label="${LABEL_PREFIX}.${suffix}"
    plist="${LAUNCH_AGENTS_DIR}/${label}.plist"
    launchctl unload "$plist" >/dev/null 2>&1 || true
    launchctl load "$plist"
  done
fi

echo "Installed LaunchAgents with prefix: ${LABEL_PREFIX}"
echo "Stack root: ${STACK_ROOT}"
echo "LaunchAgents dir: ${LAUNCH_AGENTS_DIR}"
echo "Auto load: ${AUTO_LOAD}"
