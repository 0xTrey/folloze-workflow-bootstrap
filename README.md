# Folloze Workflow Bootstrap

Single-repo bootstrap for bringing a fresh Mac to a working Folloze sales workflow stack with Codex.

This repo includes:
- Production skill code for Granola -> Deal Docs sync
- Installers for launchd automations
- Preflight verification checks
- Portable overrides for dependent repos
- A copy/paste Codex setup prompt for a new teammate

## Fresh-Mac one command

```bash
cd ~/Projects
git clone https://github.com/0xTrey/folloze-workflow-bootstrap.git
cd folloze-workflow-bootstrap
bash ./scripts/setup_fresh_mac.sh
```

## Low-storage Mac (16GB) mode

If the machine is space-constrained, run:

```bash
cd ~/Projects/folloze-workflow-bootstrap
bash ./scripts/setup_low_storage_mac.sh
```

This mode:
- uses shallow clones (`--depth 1 --filter=blob:none`)
- skips `weekly-report` by default
- installs Python deps with no pip cache

If local disk is still too tight, put repos + venv on external/cloud-backed volume:

```bash
PROJECTS_ROOT=/Volumes/WorkDrive/Projects \
VENV_PATH=/Volumes/WorkDrive/.venvs/folloze-stack \
bash ./scripts/setup_low_storage_mac.sh
```

## Codex handoff

If Candace is using Codex directly, have her paste:
- `CANDACE_CODEX_SETUP_PROMPT.md`

## What setup script does

1. Clones/pulls required dependent repos into `~/Projects`.
2. Applies portable overrides to remove Trey-specific path assumptions.
3. Creates `~/.venvs/folloze-stack` and installs required Python deps.
4. Writes Gemini-only config for `granola_email_drafter.py`.
5. Installs and loads LaunchAgents via `scripts/install_folloze_launchagents.sh`.
6. Runs `scripts/folloze_stack_preflight.sh`.

## Manual steps still required

These cannot be fully automated from a clean machine:
- API keys in env (`APOLLO_API_KEY`, `GEMINI_API_KEY`/`AI_GEMINI_KEY`, `GOOGLE_DRIVE_FOLDER_ID`, `TAVILY_API_KEY`)
- macOS Keychain secret `gemini-api`
- OAuth browser flows:
  - `python -m google_workspace.setup_auth`
  - `python3 ~/Projects/granola-sync/granola_email_drafter.py auth`

## Primary scripts

- `scripts/setup_fresh_mac.sh`
- `scripts/setup_low_storage_mac.sh`
- `scripts/install_folloze_launchagents.sh`
- `scripts/folloze_stack_preflight.sh`
- `scripts/apply_repo_overrides.sh`

## Skills bundled here

- `skills/granola-to-deals`
- `skills/granola-connector`
- `skills/deal-context-manager`

## Granola -> Deal Docs watchdog

Current runtime behavior for the meeting-sync stack:

- `granola-sync` prefers Granola's local cache when it is fresh, and falls back to the live Granola API when the cache is stale or unavailable.
- `granola-to-deals` prefers the live API path through `granola-connector`, and repairs missing deal `doc_id` values by searching Google Drive before appending call notes.
- `granola-to-deals` treats `missing_doc_id` as a tracked non-fatal failure, so one incomplete deal record should not flip the whole sync to `status:"error"`.
- Both pipelines now write structured status artifacts in addition to plain logs:
  - `~/Library/Logs/granola-sync/sync.status.json`
  - `~/Library/Logs/granola-sync/sync-runs.jsonl`
  - `~/.openclaw/logs/deal-docs-ingestion.status.json`
  - `~/.openclaw/logs/deal-docs-ingestion.jsonl`
  - `~/.openclaw/logs/deal-index-health.status.json`
- Failures raise local macOS notifications and remote watchdog alerts:
  - Mason Discord: `channel:1480676983041167541`
  - Email to `trey.harnden@folloze.com` from `mason@elevationengine.co`

Optional alert overrides:

- `GRANOLA_ALERT_DISCORD_TARGET`
- `GRANOLA_ALERT_EMAIL_TO`
- `GRANOLA_ALERT_EMAIL_FROM`
- `GRANOLA_ALERTS_DRY_RUN=1` to exercise alert code without sending live notifications

### Troubleshooting alert semantics

- If `~/.openclaw/logs/deal-docs-ingestion.status.json` ends with `status:"ok"`, the Granola sync completed even if the summary still contains a non-fatal `missing_doc_id`.
- If Mason says `Granola sync error: unavailable`, check `~/.openclaw/logs/gateway.err.log` for `required secrets are unavailable` before changing the Granola sync code.
- The `required secrets are unavailable` message comes from OpenClaw gateway startup, usually because a configured provider secret such as `AI_DEEPSEEK_KEY` or `AI_GEMINI_KEY` is missing. That is a gateway/config issue, not a Granola meeting-ingestion bug.
- For historical context: the April 3, 2026 Mason alerts were a combination of the older wrapper returning exit code `1` for `missing_doc_id` and simultaneous OpenClaw secret failures during gateway restart.

## Manual account sync

Run the same wrapper the scheduler uses, but target one account:

```bash
GRANOLA_TO_DEALS_ARGS='--since 2026-03-16 --target selector.ai' \
/bin/bash ~/Projects/folloze-workflow-bootstrap/skills/granola-to-deals/run_orchestrator.sh
```

Preview without writing:

```bash
GRANOLA_TO_DEALS_ARGS='--since 2026-03-16 --target selector.ai --dry-run' \
/bin/bash ~/Projects/folloze-workflow-bootstrap/skills/granola-to-deals/run_orchestrator.sh
```

This is the preferred repair/backfill path for one company because it preserves the same logs, status files, and alert behavior as the scheduled job.
