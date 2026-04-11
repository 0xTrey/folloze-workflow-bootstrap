#!/usr/bin/env python3
"""
deal-context-manager: Index and manage all deal documents.

Maintains a live index of all deal notes docs across Drive,
providing fast lookups and deal state management.

Usage:
    python deal_context_manager.py --refresh          # Rebuild index
    python deal_context_manager.py --list             # List all deals
    python deal_context_manager.py --search "Amazon"  # Find specific deal
    python deal_context_manager.py --get-doc-id "amazon.com"  # Get doc ID

Environment:
    DEALS_ROOT_FOLDER_ID: Root folder containing customer folders
    GOOGLE_TOKEN_JSON_PATH: Path to OAuth token
"""

import os
import re
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, fields

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "openclaw" / "google" / "token.json"
INDEX_PATH = Path.home() / ".openclaw" / "deal-index.json"
ALIAS_PATH = Path.home() / ".openclaw" / "domain-aliases.json"

# Patterns to identify deal docs
DEAL_DOC_PATTERNS = [
    r'(\w+)\s*-?\s*Deal Notes',  # "Amazon - Deal Notes" or "Amazon Deal Notes"
    r'Deal Notes\s*-?\s*(\w+)',  # "Deal Notes - Amazon"
]


def _normalize_domain(value: str) -> str:
    """Normalize domain-like strings (strip scheme/path/query/port/www)."""
    if not value:
        return ""
    v = value.strip().lower()
    if '@' in v and ' ' not in v:
        v = v.split('@', 1)[1]
    v = re.sub(r'^https?://', '', v)
    v = v.split('/', 1)[0]
    v = v.split('?', 1)[0]
    v = v.split('#', 1)[0]
    v = v.split(':', 1)[0]
    if v.startswith('www.'):
        v = v[4:]
    return v.strip('.')


def _domain_root(value: str) -> str:
    """Best-effort registrable root (heuristic)."""
    d = _normalize_domain(value)
    parts = [p for p in d.split('.') if p]
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return d


def _company_tokens(value: str) -> List[str]:
    """Tokenize company text for fuzzy matching."""
    stop = {'inc', 'llc', 'ltd', 'corp', 'co', 'company', 'group', 'the', 'partner', 'partners'}
    return [t for t in re.split(r'[^a-z0-9]+', (value or '').lower()) if t and t not in stop]


def _compact_text(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (value or '').lower())


def get_drive_service(token_path: Optional[Path] = None):
    """Initialize Drive API service."""
    token_path = token_path or DEFAULT_TOKEN_PATH
    creds = Credentials.from_authorized_user_file(
        str(token_path),
        ["https://www.googleapis.com/auth/drive.readonly"]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('drive', 'v3', credentials=creds)


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


@dataclass
class Deal:
    """Represents a deal with its metadata."""
    doc_id: str
    name: str
    domain: str
    folder_id: str = ""
    folder_path: str = ""
    created_time: str = ""
    modified_time: str = ""
    status: str = "active"
    last_accessed: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Deal':
        # Ignore forward-compatible fields written by newer index builders.
        allowed = {f.name for f in fields(cls)}
        normalized = {k: v for k, v in data.items() if k in allowed}
        return cls(**normalized)


class DealContextManager:
    """Manages the deal index and provides query interface."""
    
    def __init__(self, token_path: Optional[Path] = None):
        self.token_path = token_path or DEFAULT_TOKEN_PATH
        self.drive_service = None
        self.docs_service = None
        self.index: Dict[str, Deal] = {}  # domain -> Deal
        self.alias_map: Dict[str, str] = {}
        self._load_index()
        self._load_aliases()
    
    def _get_drive(self):
        """Lazy init Drive service."""
        if self.drive_service is None:
            self.drive_service = get_drive_service(self.token_path)
        return self.drive_service
    
    def _get_docs(self):
        """Lazy init Docs service."""
        if self.docs_service is None:
            self.docs_service = get_docs_service(self.token_path)
        return self.docs_service
    
    def _load_index(self):
        """Load index from disk."""
        if INDEX_PATH.exists():
            try:
                with open(INDEX_PATH, 'r') as f:
                    data = json.load(f)
                    self.index = {
                        k: Deal.from_dict(v) for k, v in data.get('deals', {}).items()
                    }
                print(f"📚 Loaded {len(self.index)} deals from index")
            except Exception as e:
                print(f"⚠️  Failed to load index: {e}")
                self.index = {}
        else:
            self.index = {}
    
    def _save_index(self):
        """Save index to disk."""
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'updated_at': datetime.now().isoformat(),
            'deal_count': len(self.index),
            'deals': {k: v.to_dict() for k, v in self.index.items()}
        }
        with open(INDEX_PATH, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        print(f"💾 Saved {len(self.index)} deals to index")

    def _load_aliases(self):
        """Load optional domain alias map (query_domain -> canonical_domain)."""
        self.alias_map = {}
        if not ALIAS_PATH.exists():
            return
        try:
            payload = json.loads(ALIAS_PATH.read_text())
        except Exception as e:
            print(f"⚠️  Failed to load alias map: {e}")
            return

        aliases = payload.get('aliases', payload if isinstance(payload, dict) else {})
        if not isinstance(aliases, dict):
            print("⚠️  Alias map format invalid; expected dict or {'aliases': {...}}")
            return

        for src, dst in aliases.items():
            src_n = _normalize_domain(str(src))
            dst_n = _normalize_domain(str(dst))
            if src_n and dst_n:
                self.alias_map[src_n] = dst_n

        if self.alias_map:
            print(f"🧭 Loaded {len(self.alias_map)} domain alias(es)")
    
    def _extract_company_name(self, filename: str) -> Optional[str]:
        """Extract company name from deal doc filename."""
        for pattern in DEAL_DOC_PATTERNS:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None
    
    def _extract_domain_from_doc(self, doc_id: str) -> Optional[str]:
        """Try to extract domain from doc content."""
        try:
            doc = self._get_docs().documents().get(documentId=doc_id).execute()
            content = doc.get('body', {}).get('content', [])
            
            # Look for email domains in content
            text = ''
            for elem in content:
                if 'paragraph' in elem:
                    for elem2 in elem['paragraph'].get('elements', []):
                        if 'textRun' in elem2:
                            text += elem2['textRun'].get('content', '')
            
            # Find external domains
            domains = re.findall(r'[\w\.-]+@([\w\.-]+\.\w+)', text)
            for domain in domains:
                if 'folloze.com' not in domain and 'gmail.com' not in domain:
                    return domain.lower()
            
        except Exception as e:
            print(f"  Could not read doc {doc_id}: {e}")
        
        return None
    
    def _build_folder_path(self, folder_id: str, cache: Dict = None) -> str:
        """Build human-readable folder path."""
        if cache is None:
            cache = {}
        
        if folder_id in cache:
            return cache[folder_id]
        
        if folder_id == 'root':
            return 'My Drive'
        
        try:
            folder = self._get_drive().files().get(
                fileId=folder_id,
                fields='name, parents'
            ).execute()
            
            name = folder.get('name', 'Unknown')
            parents = folder.get('parents', [])
            
            if parents:
                parent_path = self._build_folder_path(parents[0], cache)
                path = f"{parent_path}/{name}"
            else:
                path = name
            
            cache[folder_id] = path
            return path
            
        except Exception as e:
            return 'Unknown'
    
    def refresh_index(self, root_folder_id: Optional[str] = None):
        """Scan Drive and rebuild deal index."""
        print("🔍 Scanning Drive for deal documents...")
        
        # Search for all Google Docs with "Deal Notes" in name
        query = "mimeType = 'application/vnd.google-apps.document' and name contains 'Deal Notes'"
        
        if root_folder_id:
            query += f" and '{root_folder_id}' in parents"
        
        deals_found = []
        page_token = None
        
        while True:
            results = self._get_drive().files().list(
                q=query,
                pageSize=100,
                pageToken=page_token,
                fields="files(id, name, parents, createdTime, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            deals_found.extend(files)
            
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        
        print(f"✅ Found {len(deals_found)} potential deal docs")
        
        # Process each file
        folder_cache = {}
        new_index = {}
        
        for file in deals_found:
            doc_id = file['id']
            name = file['name']
            
            company = self._extract_company_name(name)
            if not company:
                print(f"  ⚠️  Could not extract company from: {name}")
                continue
            
            # Try to get domain
            domain = self._extract_domain_from_doc(doc_id)
            if not domain:
                # Guess from company name
                domain = company.lower().replace(' ', '') + '.com'
            
            # Build folder path
            parents = file.get('parents', ['root'])
            folder_id = parents[0] if parents else 'root'
            folder_path = self._build_folder_path(folder_id, folder_cache)
            
            deal = Deal(
                doc_id=doc_id,
                name=company,
                domain=domain,
                folder_id=folder_id,
                folder_path=folder_path,
                created_time=file.get('createdTime', ''),
                modified_time=file.get('modifiedTime', '')
            )
            
            new_index[domain] = deal
            print(f"  ✅ {company} → {domain} ({folder_path})")
        
        self.index = new_index
        self._save_index()
        
        return len(new_index)
    
    def find_deal(self, query: str) -> Optional[Deal]:
        """Find deal by domain or company name with normalization/fuzzy matching."""
        q_raw = (query or '').strip().lower()
        q_domain = _normalize_domain(q_raw)
        q_root = _domain_root(q_domain)
        q_label = q_root.split('.', 1)[0] if q_root else ''
        q_compact = _compact_text(q_raw)

        # Optional explicit aliasing (non-exclusive): query domain -> canonical domain.
        alias_domain = self.alias_map.get(q_domain, "") if q_domain else ""
        alias_root = _domain_root(alias_domain) if alias_domain else ""

        candidates: Dict[str, Tuple[int, Deal]] = {}

        def add_candidate(deal: Deal, score: int):
            key = deal.domain
            existing = candidates.get(key)
            if not existing or score > existing[0]:
                candidates[key] = (score, deal)

        # Strong exact candidates first
        if q_raw in self.index:
            add_candidate(self.index[q_raw], 500)
        if q_domain in self.index:
            add_candidate(self.index[q_domain], 490)
        if alias_domain and alias_domain in self.index:
            add_candidate(self.index[alias_domain], 505)

        for domain, deal in self.index.items():
            domain_norm = _normalize_domain(domain)
            d_root = _domain_root(domain)
            d_label = d_root.split('.', 1)[0] if d_root else ''
            deal_name = (deal.name or '').lower()
            deal_compact = _compact_text(deal_name)

            # Normalized exact domain
            if q_domain and q_domain == domain_norm:
                add_candidate(deal, 480)

            # Root-domain matching (amazon.com -> aws.amazon.com, cbre.com -> cbre.us)
            if q_root and q_root == d_root:
                add_candidate(deal, 420)
            if alias_root and alias_root == d_root:
                add_candidate(deal, 470)

            # Prefix-domain fuzzy (nucleussecurity.com -> nucleussec.com)
            if q_label and d_label and len(q_label) >= 6 and len(d_label) >= 6:
                if q_label.startswith(d_label) or d_label.startswith(q_label):
                    add_candidate(deal, 360)

            # Company name matching
            if deal_name and deal_name == q_raw:
                add_candidate(deal, 430)
            if q_raw and deal_name and q_raw in deal_name:
                add_candidate(deal, 320)

            # Compact fuzzy name matching ("the marketing practice" ~ "themarketingpractice")
            if q_compact and deal_compact and (q_compact in deal_compact or deal_compact in q_compact):
                add_candidate(deal, 300)

            # Domain substring fallback
            if q_domain and (q_domain in domain_norm or domain_norm in q_domain):
                add_candidate(deal, 280)

        # Token overlap fallback
        q_tokens = set(_company_tokens(q_raw if q_raw else q_domain))
        if q_tokens:
            for _, deal in self.index.items():
                d_tokens = set(_company_tokens(deal.name)) | set(_company_tokens(_normalize_domain(deal.domain).split('.')[0]))
                overlap = len(q_tokens & d_tokens)
                if overlap >= 2:
                    add_candidate(deal, 240 + overlap * 10)

        if not candidates:
            return None

        # Prefer candidates with doc_id when confidence is otherwise similar.
        best_score, best_deal = max(
            candidates.values(),
            key=lambda item: (item[0] + (30 if item[1].doc_id else 0), item[0], bool(item[1].doc_id))
        )

        # If best exact match has no doc_id, prefer same-root candidate that does.
        if q_root and best_deal and not best_deal.doc_id:
            root_with_doc = [
                (score, deal)
                for score, deal in candidates.values()
                if deal.doc_id and _domain_root(deal.domain) == q_root
            ]
            if not root_with_doc and q_label:
                root_with_doc = [
                    (score, deal)
                    for score, deal in candidates.values()
                    if deal.doc_id and _domain_root(deal.domain).split('.', 1)[0] == q_label
                ]
            if root_with_doc:
                _, best_root_deal = max(root_with_doc, key=lambda item: item[0])
                best_deal = best_root_deal
                best_score = max(best_score, 300)

        # Guardrail to avoid accidental weak matches.
        if best_score < 260:
            return None

        return best_deal

    def _iter_deal_doc_files(self) -> List[Dict]:
        """List Google Docs that look like deal notes."""
        query = "mimeType = 'application/vnd.google-apps.document' and trashed = false and name contains 'Deal Notes'"
        files = []
        page_token = None
        while True:
            response = self._get_drive().files().list(
                q=query,
                pageSize=100,
                pageToken=page_token,
                fields="nextPageToken, files(id, name, parents, createdTime, modifiedTime)",
            ).execute()
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return files

    def _score_doc_candidate(self, deal: Deal, file: Dict) -> int:
        """Prefer docs whose title matches the company/domain after normalization."""
        name = (file.get("name") or "").lower()
        name_compact = _compact_text(name)
        score = 0
        if "deal notes" in name:
            score += 20

        domain_root = _domain_root(deal.domain).split('.', 1)[0]
        deal_name = (deal.name or '').lower()
        deal_name_compact = _compact_text(deal_name)
        company_tokens = _company_tokens(deal_name)

        if deal_name and deal_name in name:
            score += 100
        if deal_name_compact and deal_name_compact in name_compact:
            score += 90
        if domain_root and domain_root in name:
            score += 80
        if domain_root and _compact_text(domain_root) in name_compact:
            score += 60
        for token in company_tokens:
            if len(token) >= 3 and token in name:
                score += 15
        return score

    def ensure_doc_id(self, query: str) -> Optional[Deal]:
        """Repair a missing doc_id by searching Drive and updating the local index."""
        deal = self.find_deal(query)
        if not deal:
            return None
        if deal.doc_id:
            return deal

        candidates = []
        for file in self._iter_deal_doc_files():
            score = self._score_doc_candidate(deal, file)
            if score <= 0:
                continue
            candidates.append((score, file))

        if not candidates:
            return deal

        best_score, best_file = max(candidates, key=lambda item: item[0])
        if best_score < 60:
            return deal

        parents = best_file.get('parents', ['root'])
        folder_id = parents[0] if parents else 'root'
        deal.doc_id = best_file['id']
        deal.folder_id = folder_id
        deal.folder_path = self._build_folder_path(folder_id)
        deal.created_time = best_file.get('createdTime', deal.created_time)
        deal.modified_time = best_file.get('modifiedTime', deal.modified_time)
        self.index[deal.domain] = deal
        self._save_index()
        print(f"🔧 Repaired missing doc_id for {deal.name}: {deal.doc_id}")
        return deal
    
    def get_deal_by_email(self, email: str) -> Optional[Deal]:
        """Find deal by email address."""
        if '@' not in email:
            return None
        
        domain = email.split('@')[1].lower()
        return self.find_deal(domain)
    
    def list_deals(self) -> List[Deal]:
        """List all deals."""
        return list(self.index.values())
    
    def get_doc_id(self, query: str) -> Optional[str]:
        """Get doc ID for a deal."""
        deal = self.find_deal(query)
        return deal.doc_id if deal else None
    
    def get_deal_context(self, query: str) -> Optional[Dict]:
        """Get full context for a deal."""
        deal = self.find_deal(query)
        if not deal:
            return None
        
        # Get doc content if needed
        # For now, return metadata
        return {
            'deal': deal.to_dict(),
            'doc_url': f"https://docs.google.com/document/d/{deal.doc_id}/edit",
            'folder_url': f"https://drive.google.com/drive/folders/{deal.folder_id}"
        }


def cmd_refresh(args):
    """Refresh the deal index."""
    manager = DealContextManager()
    count = manager.refresh_index(args.folder_id)
    print(f"\n✅ Indexed {count} deals")
    return 0


def cmd_list(args):
    """List all deals."""
    manager = DealContextManager()
    deals = manager.list_deals()
    
    print(f"\n📋 {len(deals)} Deals:\n")
    for deal in sorted(deals, key=lambda x: x.name):
        print(f"  {deal.name:20} → {deal.domain:30} ({deal.folder_path.split('/')[-1]})")
    
    return 0


def cmd_search(args):
    """Search for a deal."""
    manager = DealContextManager()
    deal = manager.find_deal(args.query)
    
    if deal:
        print(f"\n✅ Found deal:\n")
        print(f"  Name:   {deal.name}")
        print(f"  Domain: {deal.domain}")
        print(f"  Doc:    https://docs.google.com/document/d/{deal.doc_id}/edit")
        print(f"  Folder: {deal.folder_path}")
        print(f"  Updated: {deal.modified_time[:10]}")
    else:
        print(f"\n❌ No deal found for: {args.query}")
        print("\nTry one of these:")
        for d in manager.list_deals()[:10]:
            print(f"  - {d.name}")
    
    return 0


def cmd_get_doc_id(args):
    """Get doc ID for a deal."""
    manager = DealContextManager()
    doc_id = manager.get_doc_id(args.query)
    
    if doc_id:
        print(doc_id)
        return 0
    else:
        print(f"Error: No deal found for {args.query}", file=__import__('sys').stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description='Deal Context Manager')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Refresh command
    refresh_parser = subparsers.add_parser('refresh', help='Rebuild deal index')
    refresh_parser.add_argument('--folder-id', help='Root folder to scan')
    
    # List command
    subparsers.add_parser('list', help='List all deals')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search for a deal')
    search_parser.add_argument('query', help='Company name or domain')
    
    # Get doc ID command
    doc_id_parser = subparsers.add_parser('get-doc-id', help='Get doc ID for deal')
    doc_id_parser.add_argument('query', help='Company name or domain')
    
    args = parser.parse_args()
    
    if args.command == 'refresh':
        return cmd_refresh(args)
    elif args.command == 'list':
        return cmd_list(args)
    elif args.command == 'search':
        return cmd_search(args)
    elif args.command == 'get-doc-id':
        return cmd_get_doc_id(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    exit(main())
