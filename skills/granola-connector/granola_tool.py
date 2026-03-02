#!/usr/bin/env python3
"""
granola_tool: Structured access to Granola meeting data.

This module provides a clean interface for accessing Granola call notes,
summaries, and transcripts. Used by nightly-sync, weekly reports, and
other automation pipelines.

Usage:
    from granola_tool import GranolaTool
    
    tool = GranolaTool()
    meetings = tool.get_meetings(since=datetime.now() - timedelta(days=1))
    for meeting in meetings:
        print(meeting['title'], meeting['summary'])
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any


class GranolaTool:
    """Tool for accessing Granola meeting data."""
    
    def __init__(self):
        self._check_cli()
    
    def _check_cli(self):
        """Verify granola CLI is available."""
        try:
            result = subprocess.run(
                ['granola', '--help'],
                capture_output=True,
                timeout=5
            )
            if result.returncode != 0:
                raise RuntimeError("granola CLI not working properly")
        except FileNotFoundError:
            raise RuntimeError(
                "granola CLI not found. Install with: brew install granola"
            )
    
    def _run(self, args: List[str]) -> Optional[Any]:
        """Run granola CLI and return parsed JSON."""
        try:
            result = subprocess.run(
                ['granola'] + args + ['--json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                print(f"granola CLI error: {result.stderr}")
                return None
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"Failed to parse granola output: {e}")
            return None
        except Exception as e:
            print(f"Error running granola: {e}")
            return None
    
    def get_meetings(self, since: Optional[datetime] = None, 
                     limit: Optional[int] = None) -> List[Dict]:
        """
        Get meetings from Granola.
        
        Args:
            since: Only return meetings after this datetime
            limit: Maximum number of meetings to return
            
        Returns:
            List of meeting dictionaries
        """
        data = self._run(['meetings'])
        if not data:
            return []
        
        # Handle both list and dict formats
        meetings = data if isinstance(data, list) else data.get('meetings', [])
        
        # Filter by date if specified
        if since:
            from datetime import timezone
            since_utc = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
            
            filtered = []
            for meeting in meetings:
                created = meeting.get('created_at', '')
                if created:
                    try:
                        meeting_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        if meeting_date >= since_utc:
                            filtered.append(meeting)
                    except:
                        filtered.append(meeting)  # Include if date parsing fails
                else:
                    filtered.append(meeting)
            meetings = filtered
        
        # Apply limit
        if limit:
            meetings = meetings[:limit]
            
        return meetings
    
    def get_meeting(self, meeting_id: str) -> Optional[Dict]:
        """
        Get full meeting details including transcript.
        
        Args:
            meeting_id: The Granola meeting ID
            
        Returns:
            Full meeting dictionary or None if not found
        """
        return self._run(['full', meeting_id])
    
    def get_meetings_with_details(self, since: Optional[datetime] = None) -> List[Dict]:
        """
        Get meetings with full details (slower, includes transcripts).
        
        Args:
            since: Only return meetings after this datetime
            
        Returns:
            List of full meeting dictionaries
        """
        meetings = self.get_meetings(since=since)
        detailed = []
        
        for meeting in meetings:
            meeting_id = meeting.get('id')
            if meeting_id:
                full = self.get_meeting(meeting_id)
                if full:
                    detailed.append(full)
                else:
                    detailed.append(meeting)  # Fallback to basic
            else:
                detailed.append(meeting)
        
        return detailed
    
    def search_meetings(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search meetings by keyword.
        
        Args:
            query: Search query string
            limit: Maximum results
            
        Returns:
            List of matching meetings
        """
        data = self._run(['search', query])
        if not data:
            return []
        
        meetings = data if isinstance(data, list) else data.get('meetings', [])
        return meetings[:limit]
    
    def get_meetings_for_date(self, date: datetime) -> List[Dict]:
        """
        Get all meetings for a specific date.
        
        Args:
            date: The date to query
            
        Returns:
            List of meetings on that date
        """
        date_str = date.strftime('%Y-%m-%d')
        meetings = self.get_meetings()
        
        return [
            m for m in meetings 
            if m.get('date') == date_str or m.get('created_at', '').startswith(date_str)
        ]
    
    def extract_summary(self, meeting: Dict) -> str:
        """
        Extract the best summary from a meeting.
        
        Args:
            meeting: Meeting dictionary
            
        Returns:
            Summary text or empty string
        """
        # Try panels first (Granola's AI summary)
        panels = meeting.get('panels', [])
        for panel in panels:
            if panel.get('template') == 'meeting-summary-consolidated':
                return panel.get('content', '')
            if 'summary' in panel.get('title', '').lower():
                return panel.get('content', '')
        
        # Fallback to user notes
        return meeting.get('user_notes', '') or meeting.get('summary', '')
    
    def extract_action_items(self, meeting: Dict) -> List[Dict]:
        """
        Extract action items from a meeting.
        
        Args:
            meeting: Meeting dictionary
            
        Returns:
            List of action item dictionaries
        """
        # Try to extract from panels
        panels = meeting.get('panels', [])
        for panel in panels:
            content = panel.get('content', '')
            if 'action item' in content.lower():
                # Simple extraction - could be improved with regex
                lines = content.split('\n')
                items = []
                for line in lines:
                    if line.strip().startswith('-') or line.strip().startswith('•'):
                        items.append({
                            'text': line.strip('- •'),
                            'done': '[x]' in line.lower() or 'done' in line.lower()
                        })
                return items
        
        return meeting.get('action_items', [])
    
    def get_external_domains(self, meeting: Dict) -> List[str]:
        """
        Extract external company domains from meeting attendees.
        
        Args:
            meeting: Meeting dictionary
            
        Returns:
            List of unique external domains
        """
        attendees = meeting.get('attendees', [])
        domains = set()
        
        ignored = {
            'folloze.com', 'gmail.com', 'yahoo.com', 'hotmail.com',
            'outlook.com', 'icloud.com', 'me.com', 'resource.calendar.google.com'
        }
        
        for attendee in attendees:
            email = attendee.get('email', '')
            if '@' in email:
                domain = email.split('@')[1].lower()
                if domain not in ignored:
                    domains.add(domain)
        
        return sorted(list(domains))


# Simple CLI for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Granola Tool')
    parser.add_argument('--days', type=int, default=1, help='Days to fetch')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--details', action='store_true', help='Include full details')
    
    args = parser.parse_args()
    
    tool = GranolaTool()
    since = datetime.now() - timedelta(days=args.days)
    
    if args.details:
        meetings = tool.get_meetings_with_details(since=since)
    else:
        meetings = tool.get_meetings(since=since)
    
    if args.json:
        print(json.dumps(meetings, indent=2, default=str))
    else:
        print(f"\n📅 Meetings since {since.date()}:\n")
        for m in meetings:
            date = m.get('date', 'Unknown')
            title = m.get('title', 'Untitled')
            domains = tool.get_external_domains(m)
            print(f"  • {date}: {title}")
            if domains:
                print(f"    Domains: {', '.join(domains)}")
            if args.details:
                summary = tool.extract_summary(m)[:100]
                if summary:
                    print(f"    Summary: {summary}...")
        print(f"\n✅ Total: {len(meetings)} meetings")
