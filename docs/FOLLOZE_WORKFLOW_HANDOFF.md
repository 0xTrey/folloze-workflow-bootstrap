# Folloze Workflow Handoff (Coworker)

## Short answer

No. Pointing Codex only at `https://github.com/0xTrey/Folloze-Sales-Stack/tree/main/skills` is not enough for full workflow parity.

Your stack is cross-repo and path-sensitive. The `skills/` folder is only one layer.

## Required repos

Clone these repos under `~/Projects`:

- `https://github.com/0xTrey/deal-research-nightly-runner.git`
- `https://github.com/0xTrey/deal-research.git`
- `https://github.com/0xTrey/watch-tomorrow-meetings.git`
- `https://github.com/0xTrey/granola-sync.git`
- `https://github.com/0xTrey/weekly-report.git`
- `https://github.com/0xTrey/google-workspace.git`
- `https://github.com/0xTrey/granola-reader.git`
- `https://github.com/0xTrey/llm-gateway.git`

Clone this bootstrap repo to `~/Projects/folloze-workflow-bootstrap` and run stack scripts from that folder.

Also required for index-backed workflows:

- `deal-notes-index` (`deal_notes_index.py`) is referenced by automation contracts but is not currently available at `https://github.com/0xTrey/deal-notes-index`.

## Path contract (current scripts assume these)

- `<STACK_ROOT>/skills/granola-to-deals/granola_to_deals.py`
- `<STACK_ROOT>/skills/granola-to-deals/run_orchestrator.sh`
- `~/Projects/deal-research-nightly-runner/runner.py`
- `~/Projects/deal-research/deal_research.py`
- `~/Projects/watch-tomorrow-meetings/watch_tomorrow_meetings.py`
- `~/Projects/granola-sync/granola_sync.py`
- `~/Projects/granola-sync/granola_email_drafter.py`
- `~/Projects/google-workspace/google_workspace/auth.py`

## Python package setup

Use one virtual environment, then install shared packages editable:

```bash
python3 -m venv ~/.venvs/folloze-stack
source ~/.venvs/folloze-stack/bin/activate

pip install -e ~/Projects/google-workspace
pip install -e ~/Projects/llm-gateway
pip install -e ~/Projects/granola-reader

pip install -r ~/Projects/deal-research/requirements.txt
pip install -r ~/Projects/watch-tomorrow-meetings/requirements.txt
```

## Secrets and auth prerequisites

Required environment variables:

- `APOLLO_API_KEY`
- `GEMINI_API_KEY` (or `AI_GEMINI_KEY`)
- `TAVILY_API_KEY` (optional fallback in some paths, recommended)
- `GOOGLE_DRIVE_FOLDER_ID`

Required OAuth/token files:

- `~/.config/openclaw/google/token.json`
- `~/.config/google-workspace/credentials.json`
- `~/.config/granola-email-drafter/token.json` (after running auth)

Auth command for drafter:

```bash
python3 ~/Projects/granola-sync/granola_email_drafter.py auth
```

## Gemini-only mode

You can run Gemini for all LLM calls without NVIDIA or local Ollama, but keep `llm-gateway` installed because current scripts call its interface.

Set:

- `AI_GEMINI_KEY=<your gemini key>`
- optional mirror: `GEMINI_API_KEY=<same key>`

For email drafts, create `~/Projects/granola-sync/email_draft_config.json`:

```json
{
  "llm_profiles": ["strategic"],
  "llm_model": null
}
```

If using launchd for email drafter, remove hard dependency on `nvidia-api` in the plist command.

## Automations to install

Local LaunchAgents should exist and be loaded:

- `com.<user>.deal-research-nightly-runner` at `21:30` local
- `com.<user>.granola-to-deals` at `01:30` and `09:30` local
- `com.<user>.granola-sync` hourly `08:00` to `20:00` local
- `com.<user>.granola-email-drafter` every `30` minutes

Installer script (recommended, from stack root):

```bash
cd ~/Projects/folloze-workflow-bootstrap
PROJECTS_ROOT=~/Projects STACK_ROOT="$(pwd)" ./scripts/install_folloze_launchagents.sh
```

## Validation checklist

Run preflight:

```bash
cd ~/Projects/folloze-workflow-bootstrap
PROJECTS_ROOT=~/Projects STACK_ROOT="$(pwd)" bash ./scripts/folloze_stack_preflight.sh
```

Run functional smoke tests:

```bash
python3 ~/Projects/folloze-workflow-bootstrap/skills/granola-to-deals/granola_to_deals.py --days 4 --dry-run --target zilliant.com
python3 ~/Projects/watch-tomorrow-meetings/watch_tomorrow_meetings.py --json --dry-run
python3 ~/Projects/granola-sync/granola_email_drafter.py status --json
```

## Candace Codex prompt

Use the prepared prompt at:

- `~/Projects/folloze-workflow-bootstrap/CANDACE_CODEX_SETUP_PROMPT.md`

## Current reliability fixes (already applied)

As of `2026-03-02`:

- Restored missing `run_orchestrator.sh` used by `com.treyharnden.granola-to-deals`.
- Updated orchestrator lookback to `--days 4`.
- Fixed deal-index loader compatibility for records containing `status`.
- Fixed pre-append dedupe so already-recorded Granola meetings do not re-append to docs.
