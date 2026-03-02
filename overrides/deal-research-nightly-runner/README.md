# deal-research-nightly-runner

Nightly pipeline that watches tomorrow's calendar for external meetings and auto-generates deal research Google Docs for net-new companies.

## What it does

1. Calls `watch_tomorrow_meetings.py` to scan tomorrow's Google Calendar
2. Identifies unique external companies (non-folloze.com attendees)
3. Skips any domain already in the seen-companies ledger
4. Runs `deal_research.py` for each net-new company (Apollo data, tech stack, LinkedIn contacts, news, Google Doc)
5. Records each researched domain in the ledger so it's never duplicated

## Schedule

Runs nightly at **21:30** via `<label-prefix>.deal-research-nightly-runner` LaunchAgent.

## Setup

Register the Launch Agent (one-time):
```bash
launchctl load ~/Library/LaunchAgents/com.<your-user>.deal-research-nightly-runner.plist
```

Unregister:
```bash
launchctl unload ~/Library/LaunchAgents/com.<your-user>.deal-research-nightly-runner.plist
```

Check status:
```bash
launchctl list | grep deal-research-nightly
```

## Run manually

```bash
cd ~/Projects/deal-research-nightly-runner
python3 runner.py
```

## Seen-companies ledger

`~/.local/share/deal-research-nightly-runner/seen_companies.json`

Tracks every domain that has been researched. Remove an entry to trigger a fresh research run for that company.

## Logs

`~/Library/Logs/deal-research-nightly-runner/runner.log`
`~/Library/Logs/deal-research-nightly-runner/runner.err.log`

## Dependencies

- `~/Projects/watch-tomorrow-meetings/watch_tomorrow_meetings.py`
- `~/Projects/deal-research/deal_research.py`
- `APOLLO_API_KEY`, `GEMINI_API_KEY`, `TAVILY_API_KEY` — loaded from `~/.zshrc` via Keychain
- `GOOGLE_DRIVE_FOLDER_ID` — loaded from `~/.zshrc`

## Path overrides (optional)

If your repos live outside `~/Projects`, set:

- `FOLLOZE_PROJECTS_ROOT`
- `WATCH_TOMORROW_MEETINGS_SCRIPT`
- `DEAL_RESEARCH_SCRIPT`
- `WATCH_TOMORROW_MEETINGS_JSON`
- `OPENCLAW_DEAL_INDEX_PATH`

## Development log

- 2026-02-25: Initial build. Wrote runner.py and Launch Agent plist. Patched deal_research.py with SKIP_BROWSER env check.
