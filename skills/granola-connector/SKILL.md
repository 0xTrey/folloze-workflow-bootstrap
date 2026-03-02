# granola-connector

Structured access to Granola meeting data for automation workflows.

## Files

- **`granola_tool.py`** — Core Python module for accessing Granola data
- **`granola_export.py`** — Export meetings to markdown or Google Drive

## Quick Start

```python
from granola_tool import GranolaTool
from datetime import datetime, timedelta

tool = GranolaTool()

# Get today's meetings
meetings = tool.get_meetings_for_date(datetime.now())

# Get meetings with full transcripts
meetings = tool.get_meetings_with_details(
    since=datetime.now() - timedelta(days=1)
)

# Extract structured data
for meeting in meetings:
    summary = tool.extract_summary(meeting)
    action_items = tool.extract_action_items(meeting)
    domains = tool.get_external_domains(meeting)
```

## API Reference

### GranolaTool

#### `get_meetings(since=None, limit=None)`
Get list of meetings.

#### `get_meeting(meeting_id)`
Get full meeting details including transcript.

#### `get_meetings_with_details(since=None)`
Get meetings with full transcripts (slower).

#### `get_meetings_for_date(date)`
Get all meetings for a specific date.

#### `search_meetings(query, limit=10)`
Search meetings by keyword.

#### `extract_summary(meeting)`
Extract AI summary from meeting panels.

#### `extract_action_items(meeting)`
Extract action items from meeting.

#### `get_external_domains(meeting)`
Get external company domains from attendees.

## CLI Usage

### Test the tool
```bash
python3 granola_tool.py --days 1
python3 granola_tool.py --days 1 --details
python3 granola_tool.py --days 1 --json
```

### Export to files
```bash
# Export to ~/Documents/Granola-Exports/
python3 granola_export.py --days 1

# Export to Google Drive
python3 granola_export.py --days 1 --to-drive
```

## Integration

### In nightly-sync
```python
import sys
sys.path.insert(0, '/Users/treyharnden/.openclaw/workspace/skills/granola-connector')
from granola_tool import GranolaTool

tool = GranolaTool()
meetings = tool.get_meetings_for_date(target_date)
for meeting in meetings:
    recap.add_call_notes(meeting)
```

### In weekly report
```python
meetings = tool.get_meetings(since=datetime.now() - timedelta(days=7))
for meeting in meetings:
    summary = tool.extract_summary(meeting)
    # Add to report
```

## Prerequisites

The `granola` CLI must be installed:
```bash
brew install granola
```

This provides the `granola` command that reads from the local cache.

## Why This Approach?

- **No MCP needed** — reads directly from local cache
- **No export folders** — accesses data programmatically  
- **Structured data** — clean Python API for all workflows
- **Always available** — works offline, no authentication needed
