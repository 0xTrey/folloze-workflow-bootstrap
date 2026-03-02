# deal-context-manager

Index and manage all deal documents for fast lookups and context retrieval.

## What It Does

- **Scans Drive** for all "Deal Notes" documents
- **Extracts company names** from filenames
- **Maps domains** to deal docs (e.g., `amazon.com` → Amazon Deal Notes)
- **Maintains local index** for fast lookups (~milliseconds vs Drive API calls)
- **Provides query interface** for other skills

## Usage

### Build Index (Run once, then periodically)

```bash
cd /Users/treyharnden/.openclaw/workspace/skills/deal-context-manager

# Scan entire Drive
python3 deal_context_manager.py refresh

# Scan specific folder only
python3 deal_context_manager.py refresh --folder-id YOUR_FOLDER_ID
```

### Query Index

```bash
# List all deals
python3 deal_context_manager.py list

# Search for specific deal
python3 deal_context_manager.py search "Amazon"
python3 deal_context_manager.py search "amazon.com"

# Get doc ID (for scripting)
python3 deal_context_manager.py get-doc-id "amazon.com"
```

## Index Storage

Saved locally at: `~/.openclaw/deal-index.json`

```json
{
  "updated_at": "2026-02-10T20:45:00",
  "deal_count": 42,
  "deals": {
    "amazon.com": {
      "doc_id": "18fQc39roHG...",
      "name": "Amazon",
      "domain": "amazon.com",
      "folder_id": "...",
      "folder_path": "My Drive/Customers/AWS",
      "created_time": "...",
      "modified_time": "..."
    }
  }
}
```

## Python API

```python
from deal_context_manager import DealContextManager

manager = DealContextManager()

# Find deal by domain
deal = manager.find_deal("amazon.com")
if deal:
    print(f"Doc ID: {deal.doc_id}")
    print(f"Folder: {deal.folder_path}")

# Find by email
deal = manager.get_deal_by_email("john@amazon.com")

# Get all deals
deals = manager.list_deals()

# Get full context
context = manager.get_deal_context("amazon.com")
# Returns: deal metadata + doc URL + folder URL
```

## Integration with email-scanner

Instead of searching Drive for each email, email-scanner can use the index:

```python
from deal_context_manager import DealContextManager

manager = DealContextManager()

# In email processing loop
deal = manager.get_deal_by_email(email['from'])
if deal:
    append_to_doc(deal.doc_id, email_summary)
else:
    print(f"No deal doc for {domain}")
```

## Integration with nightly-sync

Add deal context to daily recaps:

```python
# For each company engaged today
for domain in companies:
    deal = manager.find_deal(domain)
    if deal:
        recap.add_deal_activity(deal)
```

## Refresh Strategy

**Option 1: Manual refresh**
Run when you create new deal docs

**Option 2: Nightly cron**
Add to nightly-sync to refresh index daily

**Option 3: On-demand**
Skills check index age and refresh if stale (>24h)

## Files

- `deal_context_manager.py` — Core module with DealContextManager class

## Future Enhancements

- [ ] Track deal stage changes over time
- [ ] Auto-extract next actions from deal docs
- [ ] Deal health scoring based on activity
- [ ] Alert when deal docs are stale (>7 days)
- [ ] Link related deals (same parent company)
