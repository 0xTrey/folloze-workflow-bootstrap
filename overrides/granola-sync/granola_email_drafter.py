#!/usr/bin/env python3
"""
Granola Email Drafter.

Generate Gmail draft follow-up emails from Granola markdown exports.

Usage:
    granola-email-drafter auth [--token-path PATH] [--credentials-path PATH]
    granola-email-drafter run [--dry-run] [--force] [--doc-id ID] [--config PATH]
    granola-email-drafter status [--state PATH]
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import requests

DEFAULT_CONFIG_PATH = Path(__file__).parent / "email_draft_config.json"
EXPORT_DIR = Path.home() / "Documents" / "granola-exports"
DEFAULT_STATE_PATH = EXPORT_DIR / ".email-draft-state.json"
DEFAULT_TOOL_CONFIG_DIR = Path.home() / ".config" / "granola-email-drafter"
DEFAULT_TOKEN_PATH = DEFAULT_TOOL_CONFIG_DIR / "token.json"
DEFAULT_CREDENTIALS_PATH = Path.home() / ".config" / "google-workspace" / "credentials.json"
DEFAULT_DRY_RUN_DIR = Path.home() / "Documents" / "granola-email-drafts"
SYNC_STATE_PATH = EXPORT_DIR / ".sync-state.json"
STATE_VERSION = 1

REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
]

COMPOSE_SCOPES = {
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://mail.google.com/",
}

DEFAULT_CONFIG = {
    "internal_domains": ["folloze.com"],
    "ignore_domains": ["resource.calendar.google.com"],
    "delay_minutes": 60,
    "lookback_days": 7,
    "min_context_chars": 180,
    "max_context_chars": 12000,
    "llm_profiles": ["gemini"],
    "llm_model": None,
    "temperature": 0.2,
    "max_tokens": 1400,
    "sender_name": "Trey",
    "signature": "Best,\nTrey",
    "tone": "Warm, concise, action-oriented, and professional.",
    "to_mode": "all_external",
    "max_external_recipients": 4,
    "dry_run_dir": str(DEFAULT_DRY_RUN_DIR),
}

log = logging.getLogger("granola-email-drafter")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    log.setLevel(level)

    if log.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(handler)


def _print_json(data: dict):
    print(json.dumps(data, indent=2, sort_keys=True))


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)[:60]


def parse_frontmatter(filepath: Path | str) -> dict:
    filepath = Path(filepath)
    text = filepath.read_text()

    if not text.startswith("---"):
        return {}

    end = text.find("\n---", 3)
    if end == -1:
        return {}

    fm_block = text[4:end]
    result = {}
    for line in fm_block.split("\n"):
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        key = key.strip()
        value = value.strip()
        if key == "attendees_json":
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        elif value == "true":
            value = True
        elif value == "false":
            value = False
        result[key] = value
    return result


def _atomic_write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        json.dump(data, tmp, indent=2)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        log.warning("Invalid JSON in %s, using defaults", path)
        return default


def load_config(path: Path) -> dict:
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        user_cfg = _load_json(path, {})
        if isinstance(user_cfg, dict):
            config.update(user_cfg)
    else:
        if path == DEFAULT_CONFIG_PATH:
            log.info("No config file at %s, using built-in defaults", path)
        else:
            raise FileNotFoundError(f"Config not found: {path}")
    return config


def load_state(path: Path) -> dict:
    default = {"version": STATE_VERSION, "last_run": None, "meetings": {}}
    state = _load_json(path, default)
    if state.get("version") != STATE_VERSION:
        return default
    if "meetings" not in state or not isinstance(state["meetings"], dict):
        state["meetings"] = {}
    return state


def save_state(path: Path, state: dict):
    state["last_run"] = datetime.now().astimezone().isoformat()
    _atomic_write_json(path, state)


def load_sync_state(path: Path) -> dict:
    default = {"version": 1, "last_run": None, "meetings": {}}
    return _load_json(path, default)


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _strip_frontmatter(md_text: str) -> str:
    if not md_text.startswith("---\n"):
        return md_text
    idx = md_text.find("\n---\n", 4)
    if idx == -1:
        return md_text
    return md_text[idx + 5 :]


def _section(md_text: str, heading: str) -> str:
    body = _strip_frontmatter(md_text)
    pattern = rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, body)
    if not match:
        return ""
    return match.group(1).strip()


def _context_from_markdown(md_text: str, max_chars: int) -> tuple[str, str, str]:
    summary = _section(md_text, "Summary")
    notes = _section(md_text, "Notes")

    if not summary and not notes:
        fallback = _strip_frontmatter(md_text)
        fallback = re.sub(r"(?ms)^##\s+Transcript\s*$.*$", "", fallback).strip()
        context = fallback
    else:
        parts = []
        if summary:
            parts.append("Summary:\n" + summary)
        if notes:
            parts.append("Notes:\n" + notes)
        context = "\n\n".join(parts)

    if len(context) > max_chars:
        context = context[:max_chars]

    return summary, notes, context


def _external_recipients(
    frontmatter: dict,
    internal_domains: set[str],
    ignore_domains: set[str],
    to_mode: str,
    max_external: int,
) -> list[str]:
    attendees = frontmatter.get("attendees_json") or []
    if isinstance(attendees, str):
        try:
            attendees = json.loads(attendees)
        except json.JSONDecodeError:
            attendees = []

    recipients: list[str] = []
    seen: set[str] = set()

    for attendee in attendees:
        if not isinstance(attendee, dict):
            continue
        email = (attendee.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        domain = email.split("@", 1)[1]
        if domain in internal_domains or domain in ignore_domains:
            continue
        if email in seen:
            continue
        seen.add(email)
        recipients.append(email)

    if to_mode == "first_external":
        return recipients[:1]
    return recipients[:max_external]


def _meeting_end(frontmatter: dict, fallback_iso: str) -> Optional[datetime]:
    for key in ("end_time", "start_time", "exported_at"):
        dt = _parse_iso(frontmatter.get(key, ""))
        if dt:
            if key == "start_time":
                return dt + timedelta(minutes=30)
            return dt
    return _parse_iso(fallback_iso)


def _clean_json_block(text: str) -> str:
    stripped = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def _parse_llm_json(text: str) -> dict:
    cleaned = _clean_json_block(text)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _build_prompts(
    *,
    sender_name: str,
    tone: str,
    meeting_title: str,
    meeting_date: str,
    recipients: list[str],
    context: str,
) -> tuple[str, str]:
    system_prompt = (
        "You write high-quality sales follow-up emails after meetings.\n"
        "Use only the provided context.\n"
        "Do not invent commitments, timelines, or pricing.\n"
        "Return only valid JSON with keys: subject, body."
    )

    user_prompt = (
        f"Sender name: {sender_name}\n"
        f"Tone: {tone}\n"
        f"Meeting title: {meeting_title}\n"
        f"Meeting date: {meeting_date}\n"
        f"Recipients: {', '.join(recipients)}\n\n"
        "Meeting context:\n"
        f"{context}\n\n"
        "Instructions:\n"
        "- Keep it concise.\n"
        "- Include clear next steps and owners if present in context.\n"
        "- If details are uncertain, use soft language instead of inventing facts.\n"
        "- Body should be plain text.\n\n"
        'Output JSON schema: {"subject":"...", "body":"..."}'
    )
    return system_prompt, user_prompt


def _gemini_key() -> str:
    for key_name in ("GEMINI_API_KEY", "AI_GEMINI_KEY", "GOOGLE_API_KEY"):
        value = (os.environ.get(key_name) or "").strip()
        if value:
            return value
    raise RuntimeError(
        "Missing Gemini API key. Set GEMINI_API_KEY or AI_GEMINI_KEY (or GOOGLE_API_KEY)."
    )


def _gemini_text(*, model: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
    api_key = _gemini_key()
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(endpoint, json=payload, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:300]}")

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"Gemini response was not JSON: {exc}") from exc

    candidates = data.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = (part.get("text") or "").strip()
            if text:
                return text
    raise RuntimeError("Gemini returned no text content")


def _llm_json(config: dict, system_prompt: str, user_prompt: str) -> tuple[dict, str]:
    model = (config.get("llm_model") or os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash").strip()
    temperature = float(config.get("temperature", 0.2))
    max_tokens = int(config.get("max_tokens", 1400))

    text = _gemini_text(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    parsed = _parse_llm_json(text)
    subject = (parsed.get("subject") or "").strip() if isinstance(parsed, dict) else ""
    body = (parsed.get("body") or "").strip() if isinstance(parsed, dict) else ""
    if not subject or not body:
        raise RuntimeError("Gemini response missing required JSON fields: subject/body")
    return {"subject": subject, "body": body}, "gemini"


def _has_compose_scope(scopes: list[str]) -> bool:
    return any(scope in COMPOSE_SCOPES for scope in scopes)


def _load_google_creds(token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not token_path.exists():
        raise FileNotFoundError(
            f"Token not found at {token_path}. Run: granola-email-drafter auth"
        )

    creds = Credentials.from_authorized_user_file(str(token_path))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())

    scopes = list(creds.scopes or [])
    if not _has_compose_scope(scopes):
        raise PermissionError(
            "Token is missing Gmail compose scope. Run: granola-email-drafter auth"
        )

    return creds


def _gmail_service(token_path: Path):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=_load_google_creds(token_path))


def _draft_raw_message(to_emails: list[str], subject: str, body: str) -> str:
    message = MIMEText(body, "plain", "utf-8")
    message["To"] = ", ".join(to_emails)
    message["Subject"] = subject
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def _upsert_gmail_draft(
    service,
    *,
    to_emails: list[str],
    subject: str,
    body: str,
    draft_id: Optional[str] = None,
) -> str:
    raw = _draft_raw_message(to_emails, subject, body)
    payload = {"message": {"raw": raw}}

    if draft_id:
        updated = service.users().drafts().update(
            userId="me",
            id=draft_id,
            body=payload,
        ).execute()
        return updated["id"]

    created = service.users().drafts().create(userId="me", body=payload).execute()
    return created["id"]


def run_auth(token_path: Path, credentials_path: Path):
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {credentials_path}"
        )
    token_path.parent.mkdir(parents=True, exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), REQUIRED_SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())

    scope_count = len(creds.scopes or [])
    log.info("OAuth complete. Saved token to %s (%d scopes)", token_path, scope_count)


def _resolve_doc_id(sync_state: dict, doc_hint: Optional[str]) -> Optional[str]:
    if not doc_hint:
        return None
    meetings = sync_state.get("meetings", {})
    if doc_hint in meetings:
        return doc_hint
    matches = [doc_id for doc_id in meetings if doc_id.startswith(doc_hint)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous doc ID prefix '{doc_hint}'")
    raise ValueError(f"No meeting found for doc ID '{doc_hint}'")


def _write_preview(
    preview_dir: Path,
    *,
    meeting_date: str,
    meeting_title: str,
    doc_id: str,
    recipients: list[str],
    subject: str,
    body: str,
) -> Path:
    preview_dir.mkdir(parents=True, exist_ok=True)
    name = f"{meeting_date}-{slugify(meeting_title)}-{doc_id[:8]}-draft.md"
    path = preview_dir / name

    lines = [
        f"# Draft Preview: {meeting_title}",
        "",
        f"- Doc ID: `{doc_id}`",
        f"- To: {', '.join(recipients)}",
        f"- Subject: {subject}",
        "",
        "## Body",
        "",
        body.strip(),
        "",
    ]
    path.write_text("\n".join(lines))
    return path


def _already_signed(body: str, sender_name: str) -> bool:
    tail = "\n".join(body.strip().splitlines()[-4:]).lower()
    return sender_name.lower() in tail


def run_pipeline(args):
    config_path = Path(args.config).expanduser()
    state_path = Path(args.state).expanduser()
    token_path = Path(args.token_path).expanduser()

    config = load_config(config_path)
    if args.delay_minutes is not None:
        config["delay_minutes"] = args.delay_minutes

    state = load_state(state_path)
    sync_state = load_sync_state(SYNC_STATE_PATH)
    meetings = sync_state.get("meetings", {})

    target_doc_id = _resolve_doc_id(sync_state, args.doc_id)
    now = datetime.now().astimezone()

    internal_domains = {d.lower() for d in config.get("internal_domains", [])}
    ignore_domains = {d.lower() for d in config.get("ignore_domains", [])}

    delay_minutes = int(config.get("delay_minutes", 60))
    lookback_days = int(config.get("lookback_days", 7))
    min_context_chars = int(config.get("min_context_chars", 180))
    max_context_chars = int(config.get("max_context_chars", 12000))
    max_external = int(config.get("max_external_recipients", 4))
    to_mode = str(config.get("to_mode", "all_external"))
    signature = str(config.get("signature", "")).strip()
    sender_name = str(config.get("sender_name", "Trey")).strip() or "Trey"
    tone = str(config.get("tone", DEFAULT_CONFIG["tone"]))
    dry_run_dir = Path(str(config.get("dry_run_dir", str(DEFAULT_DRY_RUN_DIR)))).expanduser()

    service = None if args.dry_run else _gmail_service(token_path)

    counters = {
        "processed": 0,
        "drafted": 0,
        "previewed": 0,
        "skipped_unchanged": 0,
        "skipped_no_external": 0,
        "skipped_delay": 0,
        "skipped_old": 0,
        "skipped_low_context": 0,
        "errors": 0,
    }
    records = []

    sorted_items = sorted(
        meetings.items(),
        key=lambda item: item[1].get("exported_at", ""),
        reverse=True,
    )

    if args.max_meetings is not None and not target_doc_id:
        sorted_items = sorted_items[: args.max_meetings]

    for doc_id, entry in sorted_items:
        if target_doc_id and doc_id != target_doc_id:
            continue

        counters["processed"] += 1
        export_path = EXPORT_DIR / entry.get("export_path", "")
        content_hash = entry.get("content_hash", "")
        prior = state["meetings"].get(doc_id, {})

        record = {
            "doc_id": doc_id,
            "title": entry.get("title", ""),
            "export_path": str(export_path),
            "content_hash": content_hash,
            "outcome": "unknown",
        }

        try:
            if not export_path.exists():
                raise FileNotFoundError(f"Export file missing: {export_path}")

            if not args.force and prior.get("content_hash") == content_hash:
                prior_status = prior.get("status")
                should_skip = False
                if args.dry_run and prior_status in ("draft_created", "preview_written"):
                    should_skip = True
                if (not args.dry_run) and prior_status == "draft_created":
                    should_skip = True

                if should_skip:
                    counters["skipped_unchanged"] += 1
                    record["outcome"] = "skipped_unchanged"
                    records.append(record)
                    continue

            fm = parse_frontmatter(export_path)
            recipients = _external_recipients(
                fm,
                internal_domains=internal_domains,
                ignore_domains=ignore_domains,
                to_mode=to_mode,
                max_external=max_external,
            )
            if not recipients:
                counters["skipped_no_external"] += 1
                record["outcome"] = "skipped_no_external"
                records.append(record)
                continue

            end_dt = _meeting_end(fm, entry.get("exported_at", ""))
            if end_dt:
                if end_dt + timedelta(minutes=delay_minutes) > now:
                    counters["skipped_delay"] += 1
                    record["outcome"] = "skipped_delay"
                    records.append(record)
                    continue
                if end_dt < now - timedelta(days=lookback_days):
                    counters["skipped_old"] += 1
                    record["outcome"] = "skipped_old"
                    records.append(record)
                    continue

            md_text = export_path.read_text()
            _, _, context = _context_from_markdown(md_text, max_chars=max_context_chars)
            if len(context) < min_context_chars:
                counters["skipped_low_context"] += 1
                record["outcome"] = "skipped_low_context"
                records.append(record)
                continue

            meeting_title = str(fm.get("title", entry.get("title", "Meeting"))).strip() or "Meeting"
            meeting_date = str(fm.get("date", "")) or (end_dt.date().isoformat() if end_dt else "")
            system_prompt, user_prompt = _build_prompts(
                sender_name=sender_name,
                tone=tone,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                recipients=recipients,
                context=context,
            )

            llm_result, llm_profile = _llm_json(config, system_prompt, user_prompt)
            subject = llm_result["subject"].strip()
            body = llm_result["body"].strip()

            if signature and not _already_signed(body, sender_name):
                body = body.rstrip() + "\n\n" + signature

            if args.dry_run:
                preview_path = _write_preview(
                    dry_run_dir,
                    meeting_date=meeting_date or "unknown-date",
                    meeting_title=meeting_title,
                    doc_id=doc_id,
                    recipients=recipients,
                    subject=subject,
                    body=body,
                )
                counters["previewed"] += 1
                status = "preview_written"
                draft_id = prior.get("draft_id")
                output_ref = str(preview_path)
                record["outcome"] = "previewed"
            else:
                draft_id = _upsert_gmail_draft(
                    service,
                    to_emails=recipients,
                    subject=subject,
                    body=body,
                    draft_id=prior.get("draft_id"),
                )
                counters["drafted"] += 1
                status = "draft_created"
                output_ref = draft_id
                record["outcome"] = "drafted"

            state["meetings"][doc_id] = {
                "title": meeting_title,
                "export_path": entry.get("export_path", ""),
                "content_hash": content_hash,
                "status": status,
                "draft_id": draft_id,
                "output_ref": output_ref,
                "recipients": recipients,
                "subject": subject,
                "llm_profile": llm_profile,
                "updated_at": now.isoformat(),
                "last_error": None,
            }

            record["status"] = status
            record["output_ref"] = output_ref
            record["recipients"] = recipients
            record["subject"] = subject
            record["llm_profile"] = llm_profile
            records.append(record)
        except Exception as exc:
            counters["errors"] += 1
            log.exception("Failed on meeting %s (%s)", doc_id[:8], entry.get("title", ""))
            state["meetings"][doc_id] = {
                "title": entry.get("title", ""),
                "export_path": entry.get("export_path", ""),
                "content_hash": content_hash,
                "status": "error",
                "draft_id": prior.get("draft_id"),
                "output_ref": prior.get("output_ref"),
                "recipients": prior.get("recipients", []),
                "subject": prior.get("subject", ""),
                "llm_profile": prior.get("llm_profile", ""),
                "updated_at": now.isoformat(),
                "last_error": str(exc),
            }

            record["outcome"] = "error"
            record["error"] = str(exc)
            records.append(record)

    save_state(state_path, state)
    log.info(
        (
            "Processed=%d drafted=%d previewed=%d skipped_unchanged=%d "
            "skipped_no_external=%d skipped_delay=%d skipped_old=%d "
            "skipped_low_context=%d errors=%d"
        ),
        counters["processed"],
        counters["drafted"],
        counters["previewed"],
        counters["skipped_unchanged"],
        counters["skipped_no_external"],
        counters["skipped_delay"],
        counters["skipped_old"],
        counters["skipped_low_context"],
        counters["errors"],
    )

    return {
        "ok": counters["errors"] == 0,
        "timestamp": datetime.now().astimezone().isoformat(),
        "mode": "dry_run" if args.dry_run else "live",
        "config_path": str(config_path),
        "state_path": str(state_path),
        "token_path": str(token_path),
        "sync_state_path": str(SYNC_STATE_PATH),
        "counts": counters,
        "meetings": records,
    }


def show_status(state_path: Path):
    state = load_state(state_path)
    meetings = state.get("meetings", {})
    statuses: dict[str, int] = {}
    for item in meetings.values():
        key = item.get("status", "unknown")
        statuses[key] = statuses.get(key, 0) + 1

    return {
        "ok": True,
        "state_path": str(state_path),
        "last_run": state.get("last_run", "never"),
        "tracked_meetings": len(meetings),
        "statuses": dict(sorted(statuses.items())),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate Gmail follow-up drafts from Granola exports")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p_auth = sub.add_parser("auth", help="Run OAuth flow with Gmail compose scope")
    p_auth.add_argument("--token-path", default=str(DEFAULT_TOKEN_PATH))
    p_auth.add_argument("--credentials-path", default=str(DEFAULT_CREDENTIALS_PATH))
    p_auth.add_argument("--json", action="store_true", help="Emit JSON output to stdout")

    p_run = sub.add_parser("run", help="Generate drafts from recent exported meetings")
    p_run.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    p_run.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    p_run.add_argument("--token-path", default=str(DEFAULT_TOKEN_PATH))
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--force", action="store_true")
    p_run.add_argument("--doc-id", help="Specific Granola document ID (or prefix)")
    p_run.add_argument("--max-meetings", type=int, help="Process at most N meetings after sorting")
    p_run.add_argument("--delay-minutes", type=int, help="Override delay before drafting")
    p_run.add_argument("--json", action="store_true", help="Emit JSON output to stdout")

    p_status = sub.add_parser("status", help="Show drafter status")
    p_status.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    p_status.add_argument("--json", action="store_true", help="Emit JSON output to stdout")

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        if args.command == "auth":
            run_auth(
                token_path=Path(args.token_path).expanduser(),
                credentials_path=Path(args.credentials_path).expanduser(),
            )
            result = {
                "ok": True,
                "token_path": str(Path(args.token_path).expanduser()),
                "scopes_requested": REQUIRED_SCOPES,
            }
            if args.json:
                _print_json(result)
            else:
                print(f"Token ready at: {result['token_path']}")
        elif args.command == "run":
            result = run_pipeline(args)
            if args.json:
                _print_json(result)
            if not result.get("ok", False):
                raise SystemExit(2)
        elif args.command == "status":
            result = show_status(Path(args.state).expanduser())
            if args.json:
                _print_json(result)
            else:
                print(f"State file: {result['state_path']}")
                print(f"Last run: {result['last_run']}")
                print(f"Tracked meetings: {result['tracked_meetings']}")
                for status, count in result["statuses"].items():
                    print(f"  {status}: {count}")
        else:
            parser.print_help()
            raise SystemExit(1)
    except Exception as exc:
        log.error("%s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
