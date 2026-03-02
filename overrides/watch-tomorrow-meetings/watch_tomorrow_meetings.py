#!/usr/bin/env python3
"""Watch tomorrow's meetings and output external account targets as JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

GOOGLE_WORKSPACE_PATH = Path(
    os.environ.get("GOOGLE_WORKSPACE_PATH", str(Path.home() / "Projects" / "google-workspace"))
).expanduser()
if GOOGLE_WORKSPACE_PATH.exists():
    sys.path.insert(0, str(GOOGLE_WORKSPACE_PATH))

try:
    from google_workspace.auth import build_service
except Exception as exc:  # pragma: no cover - runtime environment dependent
    print(
        "Failed to import google_workspace.auth. "
        f"Install with: pip install -e {GOOGLE_WORKSPACE_PATH}",
        file=sys.stderr,
    )
    raise

DEFAULT_OUTPUT = Path("~/.local/share/watch-tomorrow-meetings/tomorrow_meetings.json").expanduser()
PERSONAL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "protonmail.com",
    "proton.me",
}
SYSTEM_DOMAINS = {
    "resource.calendar.google.com",
    "group.calendar.google.com",
}


def extract_domain(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].strip().lower()


def normalize_company_name_from_domain(domain: str) -> str:
    if not domain:
        return ""
    base = domain.split(".")[0]
    base = re.sub(r"[^a-zA-Z0-9\- ]", " ", base)
    base = base.replace("-", " ").strip()
    return re.sub(r"\s+", " ", base).title()


def parse_iso_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_external_domain(domain: str, internal_domain: str, ignored: set[str]) -> bool:
    if not domain:
        return False
    if domain in ignored:
        return False
    if domain in SYSTEM_DOMAINS:
        return False
    if domain == internal_domain:
        return False
    return True


def choose_account_domain(external_domains: set[str]) -> str:
    if not external_domains:
        return ""

    non_personal = sorted(d for d in external_domains if d not in PERSONAL_DOMAINS)
    if non_personal:
        return non_personal[0]
    return sorted(external_domains)[0]


def choose_champion_name(
    attendees: list[dict[str, Any]],
    account_domain: str,
    internal_domain: str,
    ignored: set[str],
) -> str:
    scored: list[tuple[int, str]] = []

    for attendee in attendees:
        email = attendee.get("email", "")
        domain = extract_domain(email)
        if not is_external_domain(domain, internal_domain, ignored):
            continue
        if attendee.get("self"):
            continue

        display_name = attendee.get("displayName") or attendee.get("name") or ""
        if not display_name and email:
            display_name = email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()

        if not display_name:
            continue

        score = 0
        if domain == account_domain:
            score += 2
        if attendee.get("responseStatus") == "accepted":
            score += 1
        if attendee.get("optional") is False:
            score += 1

        scored.append((score, display_name))

    if not scored:
        return ""

    scored.sort(key=lambda x: (-x[0], x[1].lower()))
    return scored[0][1]


def fetch_events_for_date(
    target_date: date,
    calendar_id: str,
    max_results: int,
) -> tuple[list[dict[str, Any]], datetime, datetime]:
    service = build_service("calendar", "v3")

    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        raise RuntimeError("Could not determine local timezone")

    start_local = datetime.combine(target_date, time.min, tzinfo=local_tz)
    end_local = start_local + timedelta(days=1)

    all_events: list[dict[str, Any]] = []
    page_token = None

    while True:
        kwargs = {
            "calendarId": calendar_id,
            "timeMin": start_local.isoformat(),
            "timeMax": end_local.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        response = service.events().list(**kwargs).execute()
        all_events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return all_events, start_local, end_local


def to_output_event(
    event: dict[str, Any],
    internal_domain: str,
    ignored_domains: set[str],
    include_internal: bool,
) -> dict[str, Any] | None:
    if event.get("status") == "cancelled":
        return None

    start = event.get("start", {})
    end = event.get("end", {})

    start_dt = start.get("dateTime")
    end_dt = end.get("dateTime")

    # Skip all-day events
    if not start_dt:
        return None

    parsed_start = parse_iso_datetime(start_dt)
    parsed_end = parse_iso_datetime(end_dt)

    attendees = event.get("attendees", []) or []

    normalized_attendees = []
    external_domains: set[str] = set()

    for attendee in attendees:
        email = attendee.get("email", "")
        domain = extract_domain(email)
        if is_external_domain(domain, internal_domain, ignored_domains):
            external_domains.add(domain)

        normalized_attendees.append(
            {
                "email": email,
                "name": attendee.get("displayName") or "",
                "self": bool(attendee.get("self", False)),
                "response": attendee.get("responseStatus", ""),
            }
        )

    if not include_internal and not external_domains:
        return None

    account_domain = choose_account_domain(external_domains)
    account_name_guess = normalize_company_name_from_domain(account_domain)
    champion_name_guess = choose_champion_name(
        attendees,
        account_domain,
        internal_domain,
        ignored_domains,
    )

    return {
        "event_id": event.get("id", ""),
        "status": event.get("status", ""),
        "summary": event.get("summary", "(no title)"),
        "start_time": parsed_start.isoformat() if parsed_start else start_dt,
        "end_time": parsed_end.isoformat() if parsed_end else end_dt,
        "calendar_link": event.get("htmlLink", ""),
        "location": event.get("location", ""),
        "attendees": normalized_attendees,
        "external_domains": sorted(external_domains),
        "account_domain": account_domain,
        "account_name_guess": account_name_guess,
        "champion_name_guess": champion_name_guess,
    }


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch tomorrow meetings and emit JSON")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD (default: tomorrow local time)")
    parser.add_argument("--calendar-id", default="primary", help="Google Calendar ID")
    parser.add_argument("--internal-domain", default="folloze.com", help="Internal company domain")
    parser.add_argument(
        "--ignore-domain",
        action="append",
        default=[],
        help="Domain to ignore (repeatable)",
    )
    parser.add_argument("--max-results", type=int, default=500, help="Max events per page")
    parser.add_argument("--include-internal", action="store_true", help="Include internal-only events")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output file")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = (datetime.now().astimezone() + timedelta(days=1)).date()

    ignored_domains = {d.strip().lower() for d in args.ignore_domain if d.strip()}
    ignored_domains.update(SYSTEM_DOMAINS)

    raw_events, start_local, end_local = fetch_events_for_date(
        target_date=target_date,
        calendar_id=args.calendar_id,
        max_results=args.max_results,
    )

    output_events = []
    for event in raw_events:
        out = to_output_event(
            event,
            internal_domain=args.internal_domain.lower(),
            ignored_domains=ignored_domains,
            include_internal=args.include_internal,
        )
        if out:
            output_events.append(out)

    output_events.sort(key=lambda e: e.get("start_time", ""))

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "target_date": target_date.isoformat(),
        "window_start": start_local.isoformat(),
        "window_end": end_local.isoformat(),
        "calendar_id": args.calendar_id,
        "internal_domain": args.internal_domain.lower(),
        "event_count": len(output_events),
        "events": output_events,
    }

    if not args.dry_run:
        write_output(args.output.expanduser(), payload)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"Found {len(output_events)} external meeting(s) for {target_date.isoformat()} "
            f"(written to {args.output.expanduser()})"
        )
        for event in output_events:
            domain = event.get("account_domain") or "(no domain)"
            name = event.get("account_name_guess") or "(no account guess)"
            print(f"- {event['start_time']} | {event['summary']} | {name} [{domain}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
