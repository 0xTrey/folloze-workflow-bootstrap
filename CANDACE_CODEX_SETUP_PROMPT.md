Copy/paste this into Codex on Candace's machine:

```text
Set up this Folloze workflow repo end-to-end on a fresh Mac.

Repository root:
~/Projects/folloze-workflow-bootstrap

Goals:
1) Build all local dependencies and wiring.
2) Install automations (launchd).
3) Validate the workflow stack.

Execution requirements:
- Do not stop at planning.
- Run commands directly.
- If a step fails, fix and retry once.

Steps:
1. Ensure repo is present:
   cd ~/Projects
   if [ -d folloze-workflow-bootstrap/.git ]; then
     git -C folloze-workflow-bootstrap pull --ff-only
   else
     git clone https://github.com/0xTrey/folloze-workflow-bootstrap.git
   fi

2. Run bootstrap:
   cd ~/Projects/folloze-workflow-bootstrap
   # If local disk is tight (16GB Mac), prefer:
   bash ./scripts/setup_low_storage_mac.sh
   # Standard mode:
   # bash ./scripts/setup_fresh_mac.sh

3. If bootstrap reports missing secrets/auth, complete these:
   - Add env vars in ~/.zshrc:
     APOLLO_API_KEY, GEMINI_API_KEY (or AI_GEMINI_KEY), GOOGLE_DRIVE_FOLDER_ID, TAVILY_API_KEY
   - Ensure keychain secret:
     security find-generic-password -s gemini-api -w
   - Run OAuth:
     source ~/.venvs/folloze-stack/bin/activate
     python -m google_workspace.setup_auth
     python3 ~/Projects/granola-sync/granola_email_drafter.py auth

4. Re-run validation:
   PROJECTS_ROOT=~/Projects STACK_ROOT=~/Projects/folloze-workflow-bootstrap \
     bash ./scripts/folloze_stack_preflight.sh
   python3 ./skills/granola-to-deals/granola_to_deals.py --days 4 --dry-run --target zilliant.com
   python3 ~/Projects/watch-tomorrow-meetings/watch_tomorrow_meetings.py --json --dry-run
   python3 ~/Projects/granola-sync/granola_email_drafter.py status --json

Final output format:
- PASS/FAIL for each pipeline:
  - deal-research seeding
  - granola-to-deals append
  - granola-sync export
  - granola-email drafts
- List any blockers still requiring human action.
- List installed LaunchAgent labels and plist paths.
```
