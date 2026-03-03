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
