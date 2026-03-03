# Granola Email Drafter Tool Contract

Tool source of truth:
- `~/Projects/granola-sync/granola_email_drafter.py`

Input data source:
- `~/Documents/granola-exports/*.md`
- `~/Documents/granola-exports/.sync-state.json`

Output/state:
- Gmail drafts (live mode)
- `~/Documents/granola-exports/.email-draft-state.json`
- `~/Documents/granola-email-drafts/*.md` (dry-run mode)

## Runtime Prerequisites

- Python 3.11+
- Granola export pipeline already running (`granola-sync`)
- Google auth client libraries available (typically via `google-workspace` install)

### Gemini-only runtime

Use direct Gemini API auth:

- `AI_GEMINI_KEY=<your key>` (or `GEMINI_API_KEY`)
- optional model override: `GEMINI_MODEL=gemini-2.0-flash`

No `llm-gateway` dependency is required in this bootstrap variant.

## Responsibilities

- Generate follow-up draft email subject/body from Granola exports.
- Apply delay/eligibility logic (`delay_minutes`, lookback window, external attendee filtering).
- Keep idempotent state so unchanged meetings are skipped and changed meetings update existing drafts.
- Never send email. Draft-only.

## Auth Model

- Dedicated Gmail compose token (write-scope isolation):
  - default token: `~/.config/granola-email-drafter/token.json`
  - default scopes requested: `https://www.googleapis.com/auth/gmail.compose`
- Run once (or when token expires):  
  `python3 ~/Projects/granola-sync/granola_email_drafter.py auth`

This avoids mutating the shared read-oriented token used by `google-workspace`.

## CLI Commands

- Status:
  - human: `python3 ~/Projects/granola-sync/granola_email_drafter.py status`
  - machine: `python3 ~/Projects/granola-sync/granola_email_drafter.py status --json`

- Dry-run previews:
  - `python3 ~/Projects/granola-sync/granola_email_drafter.py run --dry-run --json`

- Live drafts:
  - `python3 ~/Projects/granola-sync/granola_email_drafter.py run --json`

- Single meeting:
  - `python3 ~/Projects/granola-sync/granola_email_drafter.py run --doc-id 188c5af3 --json`

- Optional batching:
  - `python3 ~/Projects/granola-sync/granola_email_drafter.py run --max-meetings 10 --json`

## JSON Output Contract

`run --json` emits:
- `ok` (bool)
- `mode` (`dry_run` or `live`)
- `counts` (processed, drafted, previewed, skipped_*, errors)
- `meetings[]` with `doc_id`, `outcome`, and when drafted/previewed also `subject`, `recipients`, `output_ref`, `llm_profile`

`status --json` emits:
- `ok`
- `state_path`
- `last_run`
- `tracked_meetings`
- `statuses`

## Exit Codes

- `0`: success (`ok=true`)
- `2`: run completed but had one or more per-meeting errors
- `1`: configuration/auth/runtime failure before successful completion

## Orchestration Pattern (OpenClaw/Codex/Claude)

1. Ensure `granola-sync` has run recently.
2. Execute dry-run and inspect `counts.errors` plus a sample of `meetings[].subject/body` previews.
3. Execute live run.
4. Persist stdout JSON and logs as artifacts.
5. Alert only on non-zero exit code or `counts.errors > 0`.

## launchd Notes

- If scheduled with `launchd`, ensure the job environment includes required `AI_*` variables for cloud profiles.
- For Gemini-only automation, set `llm_profiles` to `["gemini"]` and provide `AI_GEMINI_KEY`.
- Portable plist template: `launchd/com.user.granola-email-drafter.template.plist`
