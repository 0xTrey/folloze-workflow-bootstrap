---
name: granola-to-deals
alias: g2d
description: |
  Sync Granola meeting notes to Deal Docs automatically.
  
  Queries Granola for recent meetings, extracts domains from attendees,
  matches to existing deal docs, and appends structured call notes.
  Also maintains local JSON for machine-readable deal queries.
  
  Use when: Processing daily meetings, updating deal docs with call notes,
  or building institutional memory from sales calls.
  
  Triggers: "sync my meetings", "update deal notes from Granola", 
  "process today's calls", "append meeting to deal doc"
---

# Granola to Deals

Sync Granola meeting notes to your Deal Docs automatically.

## What It Does

1. **Queries Granola** for meetings (today, last N days, or since date)
2. **Extracts domains** from attendee emails to identify the company
3. **Matches to deal docs** using deal-index.json
4. **Appends to Google Doc** in the "Call Notes" section (most recent first)
5. **Updates local JSON** with structured meeting data for queries

## Output Format

**Google Doc (human-readable):**
```markdown
## 2026-02-15

**Attendees:** Trey, Jane Smith, Bob Jones

**Summary:**
Discussed personalization strategy. Jane concerned about integration timeline. 
Bob pushing for ROI metrics. Folloze case study resonated.

**Action Items:**
- [ ] Send case study by Friday
- [ ] Schedule technical deep-dive
```

**Local JSON (machine-readable):**
```json
{
  "domain": "acme.com",
  "meetings": [...],
  "last_activity": "2026-02-15T14:30:00Z",
  "flags": ["pricing_discussed"],
  "objections_raised": ["integration", "timeline"],
  "stakeholders": ["Jane Smith", "Bob Jones"]
}
```

## Usage

### CLI

```bash
# Process today's meetings
cd /Users/treyharnden/.openclaw/workspace/skills/granola-to-deals
python3 granola_to_deals.py --today

# Process last 3 days
python3 granola_to_deals.py --days 3

# Process specific date range
python3 granola_to_deals.py --since 2026-02-10

# Preview without writing (dry run)
python3 granola_to_deals.py --today --dry-run
```

### Cron (Daily)

Add to `~/.openclaw/cron/`:
```json
{
  "name": "granola-daily-sync",
  "schedule": {"kind": "cron", "expr": "0 9 * * *", "tz": "America/Chicago"},
  "command": "python3 /Users/treyharnden/.openclaw/workspace/skills/granola-to-deals/granola_to_deals.py --today"
}
```

## Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌─────────────┐
│  Granola    │────→│  Extract     │────→│  Match to   │────→│  Append to  │
│  Meetings   │     │  Domains     │     │  Deal Doc   │     │  Google Doc │
└─────────────┘     └──────────────┘     └─────────────┘     └─────────────┘
                                                                  │
                                                                  ↓
                                                           ┌─────────────┐
                                                           │ Update JSON │
                                                           │  (~/.openclaw/deals/)
                                                           └─────────────┘
```

## File Locations

- **Script:** `skills/granola-to-deals/granola_to_deals.py`
- **Local deal data:** `~/.openclaw/deals/{domain}.json`
- **Deal index:** `~/.openclaw/deal-index.json`

## Integration

### With deal-research
After creating a new deal doc, run granola-to-deals to backfill any recent meetings:
```bash
python3 granola_to_deals.py --days 7
```

### With nightly-sync
Add to daily recaps: meetings synced, deals updated, flags raised

### Query local deal data
```python
import json
from pathlib import Path

deals_dir = Path.home() / ".openclaw" / "deals"
for json_file in deals_dir.glob("*.json"):
    with open(json_file) as f:
        data = json.load(f)
        if "pricing_discussed" in data.get("flags", []):
            print(f"{data['domain']}: pricing was discussed")
```

## Requirements

- Granola CLI installed (`brew install granola`)
- Google OAuth token (`~/.config/openclaw/google/token.json`)
- Deal index built (`deal-context-manager refresh`)
- Python dependencies: `google-auth`, `google-api-python-client`

## Future Enhancements

- [ ] Slack notification on new meeting synced
- [ ] Weekly stale deal report (no meetings in 14 days)
- [ ] Auto-extract competitor mentions
- [ ] Sentiment analysis on meeting tone
- [ ] Deal health scoring based on meeting frequency
