#!/usr/bin/env python3
"""Nightly deal research runner.

Pipeline:
  1. Run watch_tomorrow_meetings.py → ~/.local/share/watch-tomorrow-meetings/tomorrow_meetings.json
  2. Parse unique external companies from the JSON
  3. Skip any domain already in the seen-companies ledger
  4. Run deal_research.py for each net-new company
  5. Record domain + doc URL in the ledger
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------

PROJECTS_ROOT = Path(
    os.environ.get("FOLLOZE_PROJECTS_ROOT", str(Path.home() / "Projects"))
).expanduser()
WATCH_SCRIPT = Path(
    os.environ.get(
        "WATCH_TOMORROW_MEETINGS_SCRIPT",
        str(PROJECTS_ROOT / "watch-tomorrow-meetings" / "watch_tomorrow_meetings.py"),
    )
).expanduser()
DEAL_RESEARCH_SCRIPT = Path(
    os.environ.get(
        "DEAL_RESEARCH_SCRIPT",
        str(PROJECTS_ROOT / "deal-research" / "deal_research.py"),
    )
).expanduser()
MEETINGS_JSON = Path(
    os.environ.get(
        "WATCH_TOMORROW_MEETINGS_JSON",
        str(Path("~/.local/share/watch-tomorrow-meetings/tomorrow_meetings.json").expanduser()),
    )
).expanduser()
LEDGER_PATH = Path("~/.local/share/deal-research-nightly-runner/seen_companies.json").expanduser()
LOG_DIR = Path("~/.local/share/deal-research-nightly-runner/runs").expanduser()
DEAL_INDEX_PATH = Path(
    os.environ.get("OPENCLAW_DEAL_INDEX_PATH", str(Path("~/.openclaw/deal-index.json").expanduser()))
).expanduser()

INTERNAL_DOMAIN = "folloze.com"
PYTHON = sys.executable


def validate_paths() -> bool:
    """Validate required script paths before starting work."""
    missing: list[Path] = []
    for path in (WATCH_SCRIPT, DEAL_RESEARCH_SCRIPT):
        if not path.exists():
            missing.append(path)
    if missing:
        print("ERROR: required script paths are missing:")
        for path in missing:
            print(f"  - {path}")
        print("Set FOLLOZE_PROJECTS_ROOT or explicit *_SCRIPT environment overrides.")
        return False
    return True


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class Tee:
    """Write to both stdout and a log file simultaneously."""

    def __init__(self, log_path: Path) -> None:
        self._stdout = sys.stdout
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logfile = open(log_path, "w", buffering=1, encoding="utf-8")

    def write(self, msg: str) -> None:
        self._stdout.write(msg)
        self._logfile.write(msg)

    def flush(self) -> None:
        self._stdout.flush()
        self._logfile.flush()

    def close(self) -> None:
        self._logfile.close()
        sys.stdout = self._stdout


# ---------------------------------------------------------------------------
# Deal index helpers
# ---------------------------------------------------------------------------

def _register_in_deal_index(domain: str, company_name: str, doc_url: str) -> None:
    """Register a newly created doc in the OpenClaw deal index.

    granola-to-deals reads deal-index.json to resolve domain → doc.
    Without this, call notes never land in docs created by this runner.
    """
    if not doc_url:
        return
    m = re.search(r"/document/d/([^/]+)", doc_url)
    if not m:
        print(f"  WARNING: could not extract doc_id from {doc_url}")
        return
    doc_id = m.group(1)

    if DEAL_INDEX_PATH.exists():
        try:
            index = json.loads(DEAL_INDEX_PATH.read_text())
        except Exception:
            index = {"updated_at": "", "deal_count": 0, "deals": {}}
    else:
        DEAL_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        index = {"updated_at": "", "deal_count": 0, "deals": {}}

    deals = index.setdefault("deals", {})
    if domain in deals:
        return  # already registered

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    deals[domain] = {
        "doc_id": doc_id,
        "name": company_name,
        "domain": domain,
        "folder_id": "",
        "folder_path": "My Drive/Deal Research Initial Folder",
        "created_time": now,
        "modified_time": now,
        "last_accessed": None,
        "status": "active",
    }
    index["updated_at"] = now
    index["deal_count"] = len(deals)
    DEAL_INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")
    print(f"  Registered in deal index: {domain} → {doc_id[:20]}...")


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------

def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_ledger(ledger: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Step 1: Refresh tomorrow's meetings
# ---------------------------------------------------------------------------

def run_watch_script() -> bool:
    """Run watch_tomorrow_meetings.py. Returns True on success."""
    print(f"[1/3] Scanning tomorrow's calendar...")
    result = subprocess.run(
        [PYTHON, str(WATCH_SCRIPT), "--internal-domain", INTERNAL_DOMAIN],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"  ERROR: watch_tomorrow_meetings exited {result.returncode}")
        if result.stderr.strip():
            print(result.stderr.strip())
        return False
    return True


# ---------------------------------------------------------------------------
# Step 2: Parse + deduplicate
# ---------------------------------------------------------------------------

def load_meetings() -> list[dict]:
    if not MEETINGS_JSON.exists():
        print(f"  WARNING: {MEETINGS_JSON} not found")
        return []
    try:
        data = json.loads(MEETINGS_JSON.read_text())
        return data.get("events", [])
    except Exception as exc:
        print(f"  ERROR reading meetings JSON: {exc}")
        return []


def unique_targets(events: list[dict]) -> list[dict]:
    """One entry per external domain, first occurrence wins."""
    seen: set[str] = set()
    targets = []
    for event in events:
        domain = (event.get("account_domain") or "").strip().lower()
        if not domain or domain in seen:
            continue
        seen.add(domain)
        company_name = (
            event.get("account_name_guess")
            or domain.split(".")[0].replace("-", " ").title()
        )
        targets.append({
            "domain": domain,
            "company_name": company_name,
            "champion_name": event.get("champion_name_guess") or "",
            "event_summary": event.get("summary", ""),
        })
    return targets


# ---------------------------------------------------------------------------
# Step 3: Run deal research
# ---------------------------------------------------------------------------

def extract_doc_url(output: str) -> str | None:
    match = re.search(r"Google Doc: (https://docs\.google\.com/[^\s]+)", output)
    return match.group(1) if match else None


def run_deal_research(
    company_name: str, domain: str, champion_name: str | None
) -> tuple[str | None, str]:
    """Run deal_research.py. Returns (doc_url, combined_output)."""
    cmd = [PYTHON, str(DEAL_RESEARCH_SCRIPT), company_name, domain]
    if champion_name:
        cmd.append(champion_name)

    env = {**os.environ, "SKIP_BROWSER": "1"}

    print(f"  Running deal_research.py for {company_name} [{domain}]...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print(f"  ERROR: deal_research timed out for {company_name}")
        return None, ""

    combined_output = result.stdout + result.stderr

    # Forward output indented for readability
    for line in combined_output.splitlines():
        print(f"    {line}")

    if result.returncode != 0:
        print(f"  ERROR: deal_research exited {result.returncode} for {company_name}")
        return None, combined_output

    return extract_doc_url(result.stdout), combined_output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _infer_run_status(doc_url: str | None, output: str) -> tuple[str, list[str]]:
    """Infer status and failed sections from the subprocess output."""
    if not doc_url:
        return "error", []

    sections_failed = []
    gemini_empty = "[Company Research] Gemini grounded returned empty" in output
    brave_ok = "[Company Research] Brave fallback succeeded" in output
    if gemini_empty and not brave_ok:
        sections_failed.append("company_research")

    status = "partial" if sections_failed else "success"
    return status, sections_failed


def main() -> int:
    if not validate_paths():
        return 1

    # Set up file logging — all print() output goes to stdout AND the log file.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / datetime.now().strftime("%Y-%m-%d_%H%M%S.log")
    summary_path = LOG_DIR / "run_summary.json"

    tee = Tee(log_path)
    sys.stdout = tee

    run_summary: list[dict] = []

    try:
        print(f"\n{'='*60}")
        print(f"Deal Research Nightly Runner")
        print(f"Started: {datetime.now().astimezone().isoformat()}")
        print(f"Log: {log_path}")
        print(f"{'='*60}\n")

        # Step 1
        if not run_watch_script():
            print("Aborting: could not get tomorrow's meetings.")
            return 1

        # Step 2
        events = load_meetings()
        targets = unique_targets(events)
        print(f"\n[2/3] {len(targets)} unique external company/companies for tomorrow")
        for t in targets:
            champ = t["champion_name"] or "(none)"
            print(f"  - {t['company_name']} [{t['domain']}]  champion: {champ}")

        if not targets:
            print("\nNothing to research. Done.")
            return 0

        # Step 3
        ledger = load_ledger()
        new_count = 0
        skipped_count = 0
        net_new_targets = [t for t in targets if t["domain"] not in ledger]

        print(f"\n[3/3] Running deal research for net-new companies...")
        for target in targets:
            domain = target["domain"]

            if domain in ledger:
                prev = ledger[domain]
                print(
                    f"\n  SKIP {target['company_name']} [{domain}]"
                    f" — already researched {prev.get('researched_at', '?')}"
                    f" ({prev.get('doc_url') or 'no doc URL recorded'})"
                )
                skipped_count += 1
                continue

            print(f"\n  RESEARCH: {target['company_name']} [{domain}]")
            doc_url, run_output = run_deal_research(
                company_name=target["company_name"],
                domain=domain,
                champion_name=target["champion_name"] or None,
            )

            status, sections_failed = _infer_run_status(doc_url, run_output)

            ledger[domain] = {
                "company_name": target["company_name"],
                "champion_name": target["champion_name"],
                "researched_at": date.today().isoformat(),
                "doc_url": doc_url or "",
            }
            save_ledger(ledger)
            if doc_url:
                _register_in_deal_index(domain, target["company_name"], doc_url)
            new_count += 1

            run_summary.append({
                "company": target["company_name"],
                "domain": domain,
                "status": status,
                "sections_failed": sections_failed,
                "doc_url": doc_url or "",
            })
            summary_path.write_text(json.dumps(run_summary, indent=2) + "\n")

            if doc_url:
                print(f"  → {doc_url}")
            if sections_failed:
                print(f"  WARNING: sections with issues: {', '.join(sections_failed)}")

            # Pause between companies to let Gemini quota partially recover.
            if target is not net_new_targets[-1]:
                print(f"  Waiting 20s before next company...")
                time.sleep(20)

        print(f"\n{'='*60}")
        print(f"Done. {new_count} new research doc(s) created, {skipped_count} skipped.")
        print(f"Finished: {datetime.now().astimezone().isoformat()}")
        print(f"{'='*60}\n")
        return 0

    finally:
        tee.close()


if __name__ == "__main__":
    raise SystemExit(main())
