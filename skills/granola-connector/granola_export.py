#!/usr/bin/env python3
"""
granola-export: Export Granola notes using the granola CLI.

Uses the already-installed `granola` CLI to read from local cache
and export to markdown files or Google Docs.

Usage:
    python granola_export.py [--days N] [--output-dir PATH] [--to-drive]
"""

import os
import re
import json
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# Google imports (optional)
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "openclaw" / "google" / "token.json"


def run_granola_cli(args: list) -> Optional[Dict]:
    """Run granola CLI and parse JSON output."""
    try:
        result = subprocess.run(
            ['granola'] + args,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            print(f"❌ granola CLI error: {result.stderr}")
            return None
        return json.loads(result.stdout)
    except FileNotFoundError:
        print("❌ granola CLI not found. Install with: brew install granola")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse granola output: {e}")
        return None
    except Exception as e:
        print(f"❌ Error running granola: {e}")
        return None


def get_meetings(since: Optional[datetime] = None) -> List[Dict]:
    """Get meetings from granola CLI."""
    data = run_granola_cli(['meetings', '--json'])
    if not data:
        return []
    
    # Handle both list and dict formats
    if isinstance(data, list):
        meetings = data
    else:
        meetings = data.get('meetings', [])
    
    # Filter by date if specified
    if since:
        # Make since timezone-aware (UTC) for comparison
        from datetime import timezone
        since_utc = since.replace(tzinfo=timezone.utc)
        
        filtered = []
        for meeting in meetings:
            created = meeting.get('created_at', '')
            if created:
                try:
                    meeting_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if meeting_date >= since_utc:
                        filtered.append(meeting)
                except Exception as e:
                    # If date parsing fails, include it anyway
                    filtered.append(meeting)
            else:
                filtered.append(meeting)
        meetings = filtered
    
    return meetings


def get_full_meeting(meeting_id: str) -> Optional[Dict]:
    """Get full meeting details including transcript."""
    return run_granola_cli(['full', meeting_id, '--json'])


def slugify(text: str) -> str:
    """Convert text to filename-safe slug."""
    text = re.sub(r'[^\w\s-]', '', text).strip()
    return re.sub(r'[-\s]+', '-', text).lower()[:50]


def extract_summary_from_panels(meeting: Dict) -> str:
    """Extract summary from Granola panels."""
    panels = meeting.get('panels', [])
    for panel in panels:
        if panel.get('template') == 'meeting-summary-consolidated':
            return panel.get('content', '')
        if 'summary' in panel.get('title', '').lower():
            return panel.get('content', '')
    return meeting.get('summary', '')


def format_meeting_as_markdown(meeting: Dict) -> str:
    """Format a meeting as markdown."""
    created = meeting.get('created_at', '')
    if created:
        try:
            date_str = datetime.fromisoformat(created.replace('Z', '+00:00')).strftime('%Y-%m-%d')
        except:
            date_str = created[:10]
    else:
        date_str = 'unknown'
    
    title = meeting.get('title', 'Untitled')
    
    # Extract summary from panels if available
    summary = extract_summary_from_panels(meeting) or meeting.get('summary', '(No summary)')
    
    lines = [
        f"# {title}",
        "",
        f"**Date:** {date_str}",
        f"**Duration:** {meeting.get('duration_minutes', 'Unknown')} minutes",
        "",
        "## Summary",
        "",
        summary,
        "",
    ]
    
    # Attendees
    attendees = meeting.get('attendees', [])
    if attendees:
        lines.extend(["## Attendees", ""])
        for attendee in attendees:
            name = attendee.get('name', 'Unknown')
            email = attendee.get('email', '')
            if email:
                lines.append(f"- {name} <{email}>")
            else:
                lines.append(f"- {name}")
        lines.append("")
    
    # Key points
    key_points = meeting.get('key_points', [])
    if key_points:
        lines.extend(["## Key Points", ""])
        for point in key_points:
            if isinstance(point, str):
                lines.append(f"- {point}")
            elif isinstance(point, dict):
                # Handle dict format
                point_text = point.get('text', str(point))
                lines.append(f"- {point_text}")
            else:
                lines.append(f"- {str(point)}")
        lines.append("")
    
    # Action items
    action_items = meeting.get('action_items', [])
    if action_items:
        lines.extend(["## Action Items", ""])
        for item in action_items:
            if isinstance(item, dict):
                text = item.get('text', '')
                assignee = item.get('assignee', '')
                done = item.get('done', False)
                status = "[x]" if done else "[ ]"
                if assignee:
                    lines.append(f"- {status} {text} (@{assignee})")
                else:
                    lines.append(f"- {status} {text}")
            else:
                # Handle string items
                lines.append(f"- {item}")
        lines.append("")
    
    # Full transcript
    transcript = meeting.get('transcript', '')
    if transcript:
        lines.extend(["## Transcript", "", "```"])
        
        if isinstance(transcript, list):
            # Handle transcript as list of entries
            transcript_text = []
            for entry in transcript[:50]:  # Limit entries
                speaker = entry.get('speaker', '')
                text = entry.get('text', '')
                if speaker:
                    transcript_text.append(f"{speaker}: {text}")
                else:
                    transcript_text.append(text)
            lines.append("\n".join(transcript_text))
            if len(transcript) > 50:
                lines.append(f"\n... ({len(transcript) - 50} more entries)")
        else:
            # Handle transcript as string
            lines.append(str(transcript)[:3000])
            if len(str(transcript)) > 3000:
                lines.append("...")
        
        lines.extend(["```", ""])
    
    return "\n".join(lines)


def export_to_folder(meetings: List[Dict], output_dir: Path):
    """Export meetings as markdown files to folder."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for meeting in meetings:
        created = meeting.get('created_at', datetime.now().isoformat())[:10]
        title_slug = slugify(meeting.get('title', 'untitled'))
        filename = f"{created}-{title_slug}.md"
        filepath = output_dir / filename
        
        # Get full meeting details
        meeting_id = meeting.get('id')
        if meeting_id:
            full_meeting = get_full_meeting(meeting_id)
            if full_meeting:
                meeting = full_meeting
        
        content = format_meeting_as_markdown(meeting)
        filepath.write_text(content, encoding='utf-8')
        print(f"  📄 {filepath.name}")
    
    print(f"\n✅ Exported {len(meetings)} meetings to {output_dir}")


def upload_to_drive(docs_service, drive_service, meeting: Dict, folder_id: Optional[str] = None) -> str:
    """Upload meeting as Google Doc."""
    title = meeting.get('title', 'Untitled')
    created = meeting.get('created_at', datetime.now().isoformat())[:10]
    doc_title = f"{created} - {title}"
    
    content = format_meeting_as_markdown(meeting)
    
    # Create document
    doc = docs_service.documents().create(body={'title': doc_title}).execute()
    doc_id = doc.get('documentId')
    
    # Insert content
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={
            'requests': [{
                'insertText': {
                    'location': {'index': 1},
                    'text': content
                }
            }]
        }
    ).execute()
    
    # Move to folder if specified
    if folder_id:
        try:
            drive_service.files().update(
                fileId=doc_id,
                addParents=folder_id,
                removeParents='root',
                fields='id, parents'
            ).execute()
        except Exception as e:
            print(f"  Warning: Could not move to folder: {e}")
    
    return doc_id


def export_to_drive(meetings: List[Dict], folder_id: Optional[str] = None):
    """Export meetings to Google Drive as Docs."""
    if not GOOGLE_AVAILABLE:
        print("❌ Google libraries not installed")
        return
    
    if not DEFAULT_TOKEN_PATH.exists():
        print(f"❌ OAuth token not found at {DEFAULT_TOKEN_PATH}")
        return
    
    creds = Credentials.from_authorized_user_file(
        str(DEFAULT_TOKEN_PATH),
        ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"]
    )
    
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    
    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    
    print(f"📤 Uploading {len(meetings)} meetings to Google Drive...")
    
    for meeting in meetings:
        # Get full details
        meeting_id = meeting.get('id')
        if meeting_id:
            full_meeting = get_full_meeting(meeting_id)
            if full_meeting:
                meeting = full_meeting
        
        doc_id = upload_to_drive(docs_service, drive_service, meeting, folder_id)
        title = meeting.get('title', 'Untitled')[:40]
        print(f"  ✅ {title}...")
    
    print(f"\n✅ Uploaded {len(meetings)} meetings to Drive")


def main():
    parser = argparse.ArgumentParser(description='Export Granola meetings')
    parser.add_argument('--days', type=int, default=7,
                        help='Days to export (default: 7)')
    parser.add_argument('--output-dir', type=Path,
                        default=Path.home() / "Documents" / "Granola-Exports",
                        help='Output folder for markdown files')
    parser.add_argument('--to-drive', action='store_true',
                        help='Upload to Google Drive instead of local folder')
    parser.add_argument('--drive-folder-id', type=str,
                        help='Google Drive folder ID for uploads')
    
    args = parser.parse_args()
    
    # Calculate date range
    since = datetime.now() - timedelta(days=args.days)
    print(f"🔍 Fetching meetings since {since.date()}...")
    
    # Get meetings
    meetings = get_meetings(since)
    
    if not meetings:
        print("❌ No meetings found")
        return 0
    
    print(f"✅ Found {len(meetings)} meetings\n")
    
    # Export
    if args.to_drive:
        export_to_drive(meetings, args.drive_folder_id)
    else:
        export_to_folder(meetings, args.output_dir)
    
    return 0


if __name__ == "__main__":
    exit(main())
