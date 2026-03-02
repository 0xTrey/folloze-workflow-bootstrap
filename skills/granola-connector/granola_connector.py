#!/usr/bin/env python3
"""
granola-connector: Extract call notes from Granola exports.

Granola exports meeting summaries to a folder. This skill parses those
files and extracts structured data for integration with deal context.

Usage:
    python granola_connector.py [--folder PATH] [--since DATE] [--json]

Environment:
    GRANOLA_EXPORT_FOLDER: Path to Granola notes folder
    GRANOLA_DEAL_FOLDER_ID: Google Drive folder for call notes
"""

import os
import re
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

# Try to import Google libs for optional Drive upload
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "openclaw" / "google" / "token.json"

# Default locations to check for Granola exports
DEFAULT_GRANOLA_PATHS = [
    Path.home() / "Documents" / "Granola",
    Path.home() / "Documents" / "Granola Notes",
    Path.home() / "Library" / "Application Support" / "Granola" / "Exports",
    Path.home() / ".granola",
]


@dataclass
class GranolaNote:
    """Structured representation of a Granola call note."""
    filename: str
    date: Optional[datetime]
    title: str
    attendees: List[str]
    summary: str
    key_points: List[str]
    action_items: List[str]
    raw_content: str
    domain: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'date': self.date.isoformat() if self.date else None,
        }


def find_granola_folder(custom_path: Optional[Path] = None) -> Optional[Path]:
    """Find Granola export folder."""
    paths_to_check = [custom_path] if custom_path else DEFAULT_GRANOLA_PATHS
    
    for path in paths_to_check:
        if path and path.exists() and path.is_dir():
            return path
    
    return None


def extract_date_from_filename(filename: str) -> Optional[datetime]:
    """Try to extract date from filename."""
    # Common patterns: "2026-02-10 Meeting Title.md" or "Meeting Title 2026-02-10.md"
    patterns = [
        r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
        r'(\d{2}-\d{2}-\d{4})',  # MM-DD-YYYY
        r'(\d{2}/\d{2}/\d{4})',  # MM/DD/YYYY
    ]
    
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            date_str = match.group(1)
            for fmt in ['%Y-%m-%d', '%m-%d-%Y', '%m/%d/%Y']:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
    
    return None


def extract_date_from_content(content: str) -> Optional[datetime]:
    """Try to extract date from note content."""
    # Look for lines like "Date: 2026-02-10" or "February 10, 2026"
    patterns = [
        (r'Date[:\s]+(\d{4}-\d{2}-\d{2})', '%Y-%m-%d'),
        (r'Date[:\s]+(\d{2}/\d{2}/\d{4})', '%m/%d/%Y'),
        (r'(\d{4}-\d{2}-\d{2})', '%Y-%m-%d'),
    ]
    
    for pattern, fmt in patterns:
        match = re.search(pattern, content)
        if match:
            try:
                return datetime.strptime(match.group(1), fmt)
            except ValueError:
                continue
    
    return None


def extract_attendees(content: str) -> List[str]:
    """Extract attendee list from note content."""
    attendees = []
    
    # Look for "Attendees:" or "Participants:" sections
    patterns = [
        r'Attendees?[:\s]+(.+?)(?:\n\n|\n#|$)',
        r'Participants?[:\s]+(.+?)(?:\n\n|\n#|$)',
        r'(?:^|\n)([A-Z][a-z]+ [A-Z][a-z]+)(?:\s+-|\s*\(|\s*<|\n)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
        for match in matches:
            # Split by commas or newlines
            names = re.split(r'[,\n]+', match)
            for name in names:
                name = name.strip()
                if name and len(name) > 2 and not name.lower().startswith('http'):
                    attendees.append(name)
    
    return list(set(attendees))  # Remove duplicates


def extract_domain_from_attendees(attendees: List[str]) -> Optional[str]:
    """Try to extract company domain from attendee names/emails."""
    for attendee in attendees:
        # Check for email format
        email_match = re.search(r'[\w\.-]+@([\w\.-]+\.\w+)', attendee)
        if email_match:
            return email_match.group(1).lower()
    
    return None


def extract_action_items(content: str) -> List[str]:
    """Extract action items from note content."""
    action_items = []
    
    # Look for "Action Items:" or "To-Do:" sections
    patterns = [
        r'Action Items?[:\s]+(.+?)(?:\n\n|\n#|$)',
        r'To-Do[s:]?(.+?)(?:\n\n|\n#|$)',
        r'Tasks?[:\s]+(.+?)(?:\n\n|\n#|$)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            items_text = match.group(1)
            # Split by newlines or bullets
            items = re.split(r'\n|•|\-', items_text)
            for item in items:
                item = item.strip()
                if item and len(item) > 5:
                    action_items.append(item)
    
    # Also look for [ ] or [x] checkboxes
    checkbox_pattern = r'\[([ x])\]\s*(.+?)(?:\n|$)'
    for match in re.finditer(checkbox_pattern, content):
        status = "Done" if match.group(1) == 'x' else "Todo"
        action_items.append(f"[{status}] {match.group(2).strip()}")
    
    return action_items


def extract_key_points(content: str) -> List[str]:
    """Extract key points from note content."""
    key_points = []
    
    # Look for "Key Points:" or "Highlights:" sections
    patterns = [
        r'Key Points?[:\s]+(.+?)(?:\n\n|\n#|$)',
        r'Highlights?[:\s]+(.+?)(?:\n\n|\n#|$)',
        r'(?:^|\n)([-•])\s*(.+?)(?:\n|$)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
        for match in matches:
            if isinstance(match, tuple):
                point = match[1]
            else:
                point = match
            point = point.strip()
            if point and len(point) > 10 and len(point) < 200:
                key_points.append(point)
    
    return key_points[:10]  # Limit to 10


def parse_granola_note(filepath: Path) -> Optional[GranolaNote]:
    """Parse a single Granola note file."""
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}")
        return None
    
    # Extract date
    date = extract_date_from_filename(filepath.stem) or extract_date_from_content(content)
    
    # Extract title (first line or filename)
    lines = content.split('\n')
    title = lines[0].strip('# ') if lines else filepath.stem
    if not title or title == filepath.stem:
        # Try to extract from content patterns
        title_match = re.search(r'(?:Meeting|Call)[:\s]+(.+?)(?:\n|$)', content, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
    
    # Extract attendees
    attendees = extract_attendees(content)
    
    # Extract domain
    domain = extract_domain_from_attendees(attendees)
    
    # Extract summary (first substantial paragraph)
    summary = ""
    for line in lines[1:]:
        line = line.strip()
        if len(line) > 50:
            summary = line[:500]  # Limit length
            break
    
    # Extract key points and action items
    key_points = extract_key_points(content)
    action_items = extract_action_items(content)
    
    return GranolaNote(
        filename=filepath.name,
        date=date,
        title=title,
        attendees=attendees,
        summary=summary,
        key_points=key_points,
        action_items=action_items,
        raw_content=content,
        domain=domain
    )


def scan_granola_folder(folder: Path, since: Optional[datetime] = None) -> List[GranolaNote]:
    """Scan folder for Granola notes and parse them."""
    notes = []
    
    # Look for markdown and text files
    extensions = ['*.md', '*.txt', '*.markdown']
    files = []
    for ext in extensions:
        files.extend(folder.glob(ext))
    
    # Also check subdirectories one level deep
    for subdir in folder.iterdir():
        if subdir.is_dir():
            for ext in extensions:
                files.extend(subdir.glob(ext))
    
    print(f"Found {len(files)} potential note files")
    
    for filepath in files:
        note = parse_granola_note(filepath)
        if note:
            # Filter by date if specified
            if since and note.date and note.date < since:
                continue
            notes.append(note)
    
    # Sort by date (newest first)
    notes.sort(key=lambda x: x.date or datetime.min, reverse=True)
    
    return notes


def upload_to_drive(doc_title: str, content: str, folder_id: Optional[str] = None) -> Optional[str]:
    """Upload note as Google Doc."""
    if not GOOGLE_AVAILABLE:
        print("Google libraries not available. Install with: pip install google-auth google-auth-oauthlib google-api-python-client")
        return None
    
    if not DEFAULT_TOKEN_PATH.exists():
        print(f"OAuth token not found at {DEFAULT_TOKEN_PATH}")
        return None
    
    creds = Credentials.from_authorized_user_file(
        str(DEFAULT_TOKEN_PATH),
        ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"]
    )
    
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    
    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    
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
            print(f"Warning: Could not move to folder: {e}")
    
    return doc_id


def format_note_as_doc(note: GranolaNote) -> str:
    """Format a Granola note as document content."""
    lines = [
        f"# {note.title}",
        "",
        f"**Date:** {note.date.strftime('%Y-%m-%d') if note.date else 'Unknown'}",
        f"**Domain:** {note.domain or 'Unknown'}",
        "",
        "---",
        "",
        "## Attendees",
        "",
    ]
    
    if note.attendees:
        for attendee in note.attendees:
            lines.append(f"- {attendee}")
    else:
        lines.append("(No attendees identified)")
    
    lines.extend([
        "",
        "## Summary",
        "",
        note.summary or "(No summary extracted)",
        "",
    ])
    
    if note.key_points:
        lines.extend([
            "## Key Points",
            "",
        ])
        for point in note.key_points:
            lines.append(f"- {point}")
        lines.append("")
    
    if note.action_items:
        lines.extend([
            "## Action Items",
            "",
        ])
        for item in note.action_items:
            lines.append(f"- {item}")
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "## Raw Notes",
        "",
        "```",
        note.raw_content[:2000],  # Truncate for doc
        "```" if len(note.raw_content) > 2000 else "",
    ])
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Extract Granola call notes')
    parser.add_argument('--folder', type=Path,
                        help='Path to Granola export folder')
    parser.add_argument('--since', type=str,
                        help='Only process notes since date (YYYY-MM-DD)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--upload', action='store_true',
                        help='Upload to Google Drive')
    parser.add_argument('--folder-id', type=str,
                        help='Google Drive folder ID for uploads')
    parser.add_argument('--limit', type=int, default=10,
                        help='Maximum notes to process')
    
    args = parser.parse_args()
    
    # Find Granola folder
    folder = find_granola_folder(args.folder)
    if not folder:
        print("❌ Could not find Granola export folder")
        print("\nChecked locations:")
        for path in DEFAULT_GRANOLA_PATHS:
            print(f"  - {path}")
        print("\nSpecify with --folder or set GRANOLA_EXPORT_FOLDER env var")
        return 1
    
    print(f"📁 Found Granola folder: {folder}")
    
    # Parse since date
    since = None
    if args.since:
        since = datetime.strptime(args.since, '%Y-%m-%d')
    
    # Scan for notes
    print(f"🔍 Scanning for notes...")
    notes = scan_granola_folder(folder, since)
    print(f"✅ Found {len(notes)} notes")
    
    if not notes:
        print("No notes found matching criteria")
        return 0
    
    # Limit results
    notes = notes[:args.limit]
    
    # Output
    if args.json:
        print(json.dumps([n.to_dict() for n in notes], indent=2))
        return 0
    
    # Display and optionally upload
    for note in notes:
        print(f"\n{'='*60}")
        print(f"📞 {note.title}")
        print(f"   📅 {note.date.strftime('%Y-%m-%d') if note.date else 'Unknown date'}")
        print(f"   🏢 {note.domain or 'Unknown domain'}")
        print(f"   👥 {len(note.attendees)} attendees")
        print(f"   ✅ {len(note.action_items)} action items")
        
        if args.upload:
            doc_title = f"Call Notes - {note.title} ({note.date.strftime('%Y-%m-%d') if note.date else 'unknown'})"
            content = format_note_as_doc(note)
            doc_id = upload_to_drive(doc_title, content, args.folder_id)
            if doc_id:
                print(f"   📄 Uploaded: https://docs.google.com/document/d/{doc_id}/edit")
    
    return 0


if __name__ == "__main__":
    exit(main())
