#!/usr/bin/env python3
"""
granola-to-deals: Sync Granola meeting notes to Deal Docs.

Queries Granola for recent meetings, extracts domains from attendees,
matches to deal docs, and appends structured call notes.

Usage:
    python granola_to_deals.py --today          # Process today's meetings
    python granola_to_deals.py --days 1         # Process last N days
    python granola_to_deals.py --since 2026-02-15  # Process since date
    python granola_to_deals.py --dry-run        # Preview without writing
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "granola-connector"))
sys.path.insert(0, str(Path(__file__).parent.parent / "deal-context-manager"))

from granola_tool import GranolaTool
from deal_context_manager import DealContextManager

# Google imports
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "openclaw" / "google" / "token.json"
DEALS_DATA_DIR = Path.home() / ".openclaw" / "deals"


def get_docs_service(token_path: Optional[Path] = None):
    """Initialize Docs API service."""
    token_path = token_path or DEFAULT_TOKEN_PATH
    creds = Credentials.from_authorized_user_file(
        str(token_path),
        ["https://www.googleapis.com/auth/documents"]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('docs', 'v1', credentials=creds)


def parse_meeting_date(meeting: Dict) -> datetime:
    """Extract meeting date."""
    date_str = meeting.get('date') or meeting.get('created_at', '')[:10]
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return datetime.now()


def parse_summary_structure(text: str) -> list:
    """
    Parse Granola summary into structured parts for proper formatting.
    Returns list of dicts: {'type': 'header'|'bullet'|'text', 'content': str}
    """
    if not text:
        return []

    lines = text.split('\n')
    parts = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Remove all markdown bold markers first
        stripped = re.sub(r'\*\*?(.*?)\*\*?', r'\1', stripped)
        stripped = re.sub(r'__(.*?)__', r'\1', stripped)

        # Section headers (### in markdown) - these become bold text (not H2)
        if re.match(r'^#{1,6}\s+', stripped):
            content = re.sub(r'^#{1,6}\s*', '', stripped).strip()
            if content:
                # Headers from markdown become bold text, not document headers
                parts.append({'type': 'subheader', 'content': content})
        # Bullet points - convert to bullets (remove the dash/asterisk and any checkbox)
        elif re.match(r'^[\-\*\•]\s+', stripped):
            # Also strip checkboxes like [ ] or [x]
            content = re.sub(r'^[\-\*\•]\s*(?:\[[\sx]\])?\s*', '', stripped).strip()
            if content:
                parts.append({'type': 'bullet', 'content': content})
        # Numbered lists - treat as bullets too
        elif re.match(r'^\d+[\.\)]\s+', stripped):
            content = re.sub(r'^\d+[\.\)]\s+', '', stripped).strip()
            if content:
                parts.append({'type': 'bullet', 'content': content})
        # Regular text
        else:
            if stripped:
                parts.append({'type': 'text', 'content': stripped})

    return parts


def format_date_with_weekday(date: datetime) -> str:
    """Format date as 'Wednesday, January 21st'."""
    # Add ordinal suffix
    day = date.day
    if 11 <= day <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    
    return date.strftime(f'%A, %B %-d{suffix}')


def format_call_note(meeting: Dict, tool: GranolaTool) -> Tuple[str, Dict]:
    """
    Format meeting as call note for Google Doc.
    Matches existing formatting: weekday date, bold headers, bullet points, compact spacing.
    Returns: (formatted_text, structured_data)
    """
    date = parse_meeting_date(meeting)
    date_str = format_date_with_weekday(date)

    # Parse summary into structured parts (headers, bullets, text)
    raw_summary = tool.extract_summary(meeting)
    summary_parts = parse_summary_structure(raw_summary.strip() if raw_summary else "")

    # Extract action items
    action_items = tool.extract_action_items(meeting)

    # Get attendees - use EMAIL addresses, not display names
    attendees = meeting.get('attendees', [])
    attendee_emails = []
    for a in attendees:
        email = a.get('email', '')
        if email:
            attendee_emails.append(email)

    # Build preview text for dry-run display
    preview_lines = [f"{date_str}\n"]
    if attendee_emails:
        preview_lines.append(f"Attendees: {', '.join(attendee_emails)}\n")
    if summary_parts:
        preview_lines.append("Summary:\n")
        for part in summary_parts:
            if part['type'] in ('header', 'subheader'):
                preview_lines.append(f"{part['content']}\n")  # Subheader (bold in actual doc)
            elif part['type'] == 'bullet':
                preview_lines.append(f"• {part['content']}\n")  # Bullet character for preview
            else:
                preview_lines.append(f"{part['content']}\n")
    preview_text = "".join(preview_lines)

    # Structured data for local JSON
    structured = {
        "date": date_str,
        "timestamp": meeting.get('created_at', datetime.now().isoformat()),
        "granola_id": meeting.get('id'),
        "attendees": attendee_emails,
        "external_domains": tool.get_external_domains(meeting),
        "summary": raw_summary,  # Keep raw for JSON
        "summary_parts": summary_parts,  # Structured for potential API use
        "action_items": [{"text": i.get('text', str(i)), "done": i.get('done', False)}
                        for i in action_items] if action_items else [],
        "meeting_title": meeting.get('title', ''),
    }

    return preview_text, structured, summary_parts, attendee_emails, action_items


def find_call_notes_section(docs_service, doc_id: str) -> Optional[int]:
    """
    Find the 'Call Notes' section in a Google Doc.
    Returns the index after the H1 heading, or None if not found.
    """
    doc = docs_service.documents().get(documentId=doc_id).execute()
    content = doc.get('body', {}).get('content', [])

    for i, element in enumerate(content):
        if 'paragraph' in element:
            para = element['paragraph']
            # Check if it's a heading
            para_style = para.get('paragraphStyle', {}).get('namedStyleType', '')
            if 'HEADING_1' in para_style or 'HEADING' in para_style:
                # Get text content
                text = ""
                for elem in para.get('elements', []):
                    if 'textRun' in elem:
                        text += elem['textRun'].get('content', '')

                if 'call notes' in text.lower() or 'callnotes' in text.lower():
                    # Found the Call Notes heading, return index after it
                    return element.get('endIndex', 1)

    return None


def insert_formatted_note(docs_service, doc_id: str, heading_index: int, date_str: str, attendee_emails: list, summary_parts: list, action_items: list):
    """
    Insert formatted note with proper structure:
    - Date as H2
    - Labels (Attendees:, Summary:) in bold
    - Section headers in bold
    - Real bullet lists (not dash text)
    - Single spacing
    """
    requests = []
    current_index = heading_index

    # Helper to add text and return new index
    def add_text(text):
        nonlocal current_index
        requests.append({
            "insertText": {
                "location": {"index": current_index},
                "text": text
            }
        })
        start = current_index
        current_index += len(text)
        return start, current_index

    # Helper to make range bold
    def make_bold(start, end):
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {"bold": True},
                "fields": "bold"
            }
        })

    # Helper to ensure text is NOT bold (for bullets after bold headers)
    def make_normal(start, end):
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {"bold": False},
                "fields": "bold"
            }
        })

    # Helper to apply bullet list
    def apply_bullets(start, end):
        requests.append({
            "createParagraphBullets": {
                "range": {"startIndex": start, "endIndex": end},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"
            }
        })

    # Insert date and make it H2
    date_start, date_end = add_text(f"{date_str}\n\n")
    requests.append({
        "updateParagraphStyle": {
            "range": {"startIndex": date_start, "endIndex": date_end - 2},
            "paragraphStyle": {"namedStyleType": "HEADING_2"},
            "fields": "namedStyleType"
        }
    })

    # Attendees with bold label
    if attendee_emails:
        label_start, label_end = add_text("Attendees:")
        make_bold(label_start, label_end)
        add_text(f" {', '.join(attendee_emails)}\n\n")

    # Summary section
    if summary_parts:
        label_start, label_end = add_text("Summary:\n")
        make_bold(label_start, label_end - 1)  # Exclude the newline

        # Track bullet ranges
        bullet_start = None
        bullet_end = None

        for part in summary_parts:
            if part['type'] in ('header', 'subheader'):
                # End any previous bullet list
                if bullet_start is not None:
                    apply_bullets(bullet_start, bullet_end)
                    bullet_start = None
                # Add subheader with bold (normal text, just bolded - not a heading)
                h_start, h_end = add_text(f"{part['content']}\n")
                make_bold(h_start, h_end - 1)

            elif part['type'] == 'bullet':
                # Track bullet range
                if bullet_start is None:
                    bullet_start = current_index
                b_start, b_end = add_text(f"{part['content']}\n")
                # Ensure bullet text is NOT bold
                make_normal(b_start, b_end - 1)  # Exclude newline
                bullet_end = b_end

            else:  # text - normal text, no special styling
                # End any previous bullet list
                if bullet_start is not None:
                    apply_bullets(bullet_start, bullet_end)
                    bullet_start = None
                # Normal text - no bold, no heading style
                add_text(f"{part['content']}\n")

        # End final bullet list if any
        if bullet_start is not None:
            apply_bullets(bullet_start, bullet_end)

        add_text("\n")

    # Action Items section
    if action_items:
        label_start, label_end = add_text("Action Items:\n")
        make_bold(label_start, label_end - 1)

        bullet_start = current_index
        for item in action_items:
            text = item.get('text', item) if isinstance(item, dict) else str(item)
            done = item.get('done', False) if isinstance(item, dict) else False
            checkbox = "[x]" if done else "[ ]"
            b_start, b_end = add_text(f"{checkbox} {text}\n")
            # Ensure action item text is NOT bold
            make_normal(b_start, b_end - 1)  # Exclude newline
        bullet_end = current_index
        apply_bullets(bullet_start, bullet_end)
        add_text("\n")

    # Separator
    sep_start, sep_end = add_text("---\n\n")

    # Final formatting pass: ensure everything except date is NORMAL_TEXT
    # This prevents style inheritance from the insertion point
    final_requests = []

    # Track ranges that should be normal text (everything after the date)
    # Date ends at date_end - 2 (excluding the \n\n), content starts right after
    content_start = date_end
    content_end = current_index

    if content_end > content_start:
        final_requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": content_start, "endIndex": content_end},
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "fields": "namedStyleType"
            }
        })

    # Re-apply H2 to the date (ensure it stays H2)
    final_requests.append({
        "updateParagraphStyle": {
            "range": {"startIndex": date_start, "endIndex": date_end - 2},
            "paragraphStyle": {"namedStyleType": "HEADING_2"},
            "fields": "namedStyleType"
        }
    })

    # Combine initial requests with final formatting pass
    requests.extend(final_requests)

    # Apply all requests
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()


def insert_after_heading(docs_service, doc_id: str, heading_index: int, note_text: str):
    """
    Legacy function - kept for compatibility.
    """
    requests = [{
        "insertText": {
            "location": {"index": heading_index},
            "text": note_text
        }
    }]

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()


def append_to_call_notes(docs_service, doc_id: str, date_str: str, attendee_emails: list, summary_parts: list, action_items: list) -> bool:
    """
    Append a call note to the Call Notes section of a deal doc.
    Inserts after the Call Notes H1 heading (most recent first).
    Date is formatted as H2, rest as normal text.
    """
    try:
        heading_index = find_call_notes_section(docs_service, doc_id)

        if heading_index:
            # Insert right after the H1 heading with proper formatting
            insert_formatted_note(docs_service, doc_id, heading_index, date_str, attendee_emails, summary_parts, action_items)
        else:
            # Fallback: append to end of doc
            doc = docs_service.documents().get(documentId=doc_id).execute()
            end_index = doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1)

            # Build simple text for fallback from summary_parts (no markdown, plain text only)
            attendees_text = f"Attendees: {', '.join(attendee_emails)}\n\n" if attendee_emails else ""

            summary_lines = ["Summary:\n"]
            for part in summary_parts:
                if part['type'] in ('header', 'subheader'):
                    summary_lines.append(f"{part['content']}\n")  # Subheaders as bold would need API calls
                elif part['type'] == 'bullet':
                    summary_lines.append(f"{part['content']}\n")  # No dash prefix - bullets added via API
                else:
                    summary_lines.append(f"{part['content']}\n")
            summary_text = "".join(summary_lines) + "\n" if summary_parts else ""

            action_items_text = ""
            if action_items:
                action_items_text = "Action Items:\n"
                for item in action_items:
                    text = item.get('text', item) if isinstance(item, dict) else str(item)
                    done = item.get('done', False) if isinstance(item, dict) else False
                    checkbox = "[x]" if done else "[ ]"
                    action_items_text += f"{checkbox} {text}\n"  # No dash prefix
                action_items_text += "\n"

            note_text = f"{date_str}\n\n{attendees_text}{summary_text}{action_items_text}---\n\n"

            requests = [{
                "insertText": {
                    "location": {"index": end_index - 1},
                    "text": f"\n{note_text}"
                }
            }]

            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests}
            ).execute()

        return True

    except Exception as e:
        print(f"  ❌ Failed to append to doc: {e}")
        return False


def update_local_deal_json(domain: str, meeting_data: Dict, force: bool = False):
    """
    Update local JSON store for a deal.
    Append-only meeting log for machine queries.
    """
    DEALS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Sanitize domain for filename
    safe_domain = re.sub(r'[^\w\.-]', '_', domain)
    json_path = DEALS_DATA_DIR / f"{safe_domain}.json"

    # Load existing or create new
    if json_path.exists():
        with open(json_path, 'r') as f:
            data = json.load(f)
    else:
        data = {
            "domain": domain,
            "meetings": [],
            "last_activity": None,
            "flags": [],
            "objections_raised": [],
            "stakeholders": [],
        }

    # Check for duplicate (same date + granola_id)
    existing_ids = {m.get('granola_id') for m in data['meetings']}
    if meeting_data.get('granola_id') in existing_ids and not force:
        print(f"  ⚠️  Meeting already recorded, skipping")
        return False

    # Append meeting
    data['meetings'].append(meeting_data)
    data['last_activity'] = meeting_data.get('timestamp') or datetime.now().isoformat()

    # Extract insights for flags
    summary_lower = meeting_data.get('summary', '').lower()

    # Check for objections
    objection_keywords = ['pricing', 'budget', 'cost', 'expensive', 'cheaper', 'competitor',
                         'alternative', 'not ready', 'timeline', 'delay', 'push back']
    for keyword in objection_keywords:
        if keyword in summary_lower and keyword not in data['objections_raised']:
            data['objections_raised'].append(keyword)

    # Check for pricing flag
    if 'pricing' in summary_lower or 'budget' in summary_lower:
        if 'pricing_discussed' not in data['flags']:
            data['flags'].append('pricing_discussed')

    # Track stakeholders
    for attendee in meeting_data.get('attendees', []):
        if attendee not in data['stakeholders']:
            data['stakeholders'].append(attendee)

    # Save
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    return True


def is_meeting_recorded(domain: str, granola_id: Optional[str]) -> bool:
    """Return True if a meeting ID is already present in local per-domain state."""
    if not granola_id:
        return False

    safe_domain = re.sub(r'[^\w\.-]', '_', domain)
    json_path = DEALS_DATA_DIR / f"{safe_domain}.json"
    if not json_path.exists():
        return False

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except Exception:
        return False

    existing_ids = {m.get('granola_id') for m in data.get('meetings', [])}
    return granola_id in existing_ids


def process_meeting(meeting: Dict, tool: GranolaTool, deal_manager: DealContextManager,
                   docs_service, dry_run: bool = False, force: bool = False) -> Dict:
    """
    Process a single meeting: match to deal, append to doc, update JSON.
    """
    result = {
        "meeting_title": meeting.get('title', 'Untitled'),
        "date": meeting.get('date', 'Unknown'),
        "matched": False,
        "appended": False,
        "json_updated": False,
        "domain": None,
        "doc_id": None,
    }

    # Extract domains from attendees
    domains = tool.get_external_domains(meeting)

    if not domains:
        print(f"  ⚠️  No external domains found, skipping")
        return result

    # Try to match each domain to a deal
    matched_deal = None
    matched_domain = None

    for domain in domains:
        deal = deal_manager.find_deal(domain)
        if deal:
            matched_deal = deal
            matched_domain = domain
            break

    if not matched_deal:
        print(f"  ⚠️  No matching deal for domains: {domains}")
        result['domain'] = domains[0] if domains else None
        return result

    result['matched'] = True
    result['domain'] = matched_domain
    result['doc_id'] = matched_deal.doc_id

    print(f"  ✅ Matched to deal: {matched_deal.name} ({matched_domain})")

    # Format the note data
    preview_text, structured_data, summary_parts, attendee_emails, action_items = format_call_note(meeting, tool)
    date_str = structured_data['date']
    granola_id = structured_data.get('granola_id')

    # Dedupe before any document writes to avoid duplicate call-note appends.
    if not force and is_meeting_recorded(matched_domain, granola_id):
        print(f"  ⚠️  Meeting already recorded locally, skipping doc append")
        return result

    if dry_run:
        print(f"  📝 Would append:\n{preview_text[:200]}...")
        result['appended'] = True  # Simulate success
    else:
        # Append to Google Doc with proper formatting
        success = append_to_call_notes(docs_service, matched_deal.doc_id, date_str, attendee_emails, summary_parts, action_items)
        result['appended'] = success

        if success:
            print(f"  ✅ Appended to Google Doc")

    # Update local JSON (even in dry-run, show what would happen)
    if not dry_run and result['appended']:
        json_updated = update_local_deal_json(matched_domain, structured_data, force)
        result['json_updated'] = json_updated
        if json_updated:
            print(f"  ✅ Updated local JSON: {DEALS_DATA_DIR}/{matched_domain}.json")

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Sync Granola meetings to Deal Docs')
    parser.add_argument('--today', action='store_true', help='Process today only')
    parser.add_argument('--days', type=int, help='Process last N days')
    parser.add_argument('--since', help='Process since date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing')
    parser.add_argument('--force', action='store_true', help='Force re-sync even if already recorded')
    parser.add_argument('--target', help='Only process meetings matching this domain (for testing)')

    args = parser.parse_args()

    # Determine date range
    if args.today:
        since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    elif args.days:
        since = datetime.now() - timedelta(days=args.days)
    elif args.since:
        since = datetime.strptime(args.since, '%Y-%m-%d')
    else:
        since = datetime.now() - timedelta(days=1)  # Default: last 24h

    print(f"🔄 Syncing Granola meetings since {since.date()}")
    if args.dry_run:
        print("   (DRY RUN - no changes will be made)")

    # Initialize tools
    try:
        tool = GranolaTool()
        deal_manager = DealContextManager()
        docs_service = get_docs_service() if not args.dry_run else None
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        return 1

    # Get meetings with full details (includes panels/summaries)
    print(f"\n📅 Fetching meetings from Granola...")
    meetings = tool.get_meetings_with_details(since=since)
    print(f"   Found {len(meetings)} meetings")

    if not meetings:
        print("   No meetings to process")
        return 0

    # Process each meeting
    print(f"\n📝 Processing meetings...\n")
    results = []

    for meeting in meetings:
        title = meeting.get('title', 'Untitled')
        date = meeting.get('date', 'Unknown')
        
        # Check target filter if specified
        if args.target:
            domains = tool.get_external_domains(meeting)
            if args.target not in domains:
                continue
        
        print(f"• {date}: {title}")

        result = process_meeting(meeting, tool, deal_manager, docs_service, args.dry_run, args.force)
        results.append(result)
        print()

    # Summary
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)

    matched = sum(1 for r in results if r['matched'])
    appended = sum(1 for r in results if r['appended'])
    json_updated = sum(1 for r in results if r['json_updated'])

    print(f"Total meetings: {len(results)}")
    print(f"Matched to deals: {matched}")
    print(f"Appended to docs: {appended}")
    print(f"Local JSON updated: {json_updated}")

    return 0


if __name__ == "__main__":
    exit(main())
