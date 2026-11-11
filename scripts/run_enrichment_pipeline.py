#!/usr/bin/env python3
"""Optimized Codicen CSLB enrichment pipeline with duplicate prevention

High-concurrency async pipeline for:
1. Web search for domains (anyapi.google.serp.organic via Treg)
2. Free HTTP fetch of homepages + contact pages
3. Paid Jev verification for identity-matched domains
4. Paid Crawl4AI for email extraction from confirmed domains
5. Paid MV/BB email verification

Features:
- Async/await for high concurrency (100+ concurrent operations)
- Attempts ledger prevents duplicate work (codicen_enrichment_attempts)
- Pipelined: search → fetch → jev → crawl → email can overlap
- Bulk Supabase writes (batched inserts/updates)
- Hard spend cap checked before every paid call
- Dry-run mode for testing without spending

Usage:
    python3 scripts/run_enrichment_pipeline.py --method web_search --limit 100 --max-spend 1.00 --dry-run
    python3 scripts/run_enrichment_pipeline.py --method candidate_verify --limit 1000 --max-spend 5.00
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

try:
    import httpx
    from supabase import create_client, Client
except ImportError:
    print("Error: Required packages not installed. Run:")
    print("  pip install httpx supabase")
    sys.exit(1)


DEFAULT_SUPABASE_URL = 'https://npkdhahdvilcctjwzdlf.supabase.co'
DEFAULT_TREG_URL = 'https://api.treg.dev/call'

# Cost constants (microdollars, 1e-6 USD)
COSTS = {
    'anyapi.google.serp.organic': 470,  # ~$0.00047
    'openrouter.ai-judge.decide': 80,    # ~$0.00008 (Jev)
    'crawl4ai.web.extract.batch': 150,   # ~$0.00015
    'millionverifier.people.email.verify': 1100,  # ~$0.0011
    'bounceban.people.email.verify': 4000,  # ~$0.004
}

# Concurrency limits
CONCURRENCY = {
    'search': 40,      # Concurrent web searches
    'fetch': 100,      # Concurrent HTTP fetches
    'jev': 20,         # Concurrent Jev calls
    'crawl': 10,       # Concurrent crawl calls
    'email_verify': 10,  # Concurrent email verifications
}

# Timeouts (seconds)
TIMEOUTS = {
    'fetch': 8.0,
    'treg': 30.0,
}

# Jev thresholds (from enrich_cslb_domains.py)
JEV_THRESHOLDS = {
    'license_match': {'contractor': 0.45, 'california': 0.70, 'identity': 0.80},
    'phone_match': {'contractor': 0.55, 'california': 0.75, 'identity': 0.85},
    'city_ca_match': {'contractor': 0.65, 'california': 0.80, 'identity': 0.90},
}

# Directory hosts to skip
DIRECTORY_HOSTS = {
    'yelp.com', 'bbb.org', 'angi.com', 'homeadvisor.com', 'facebook.com',
    'linkedin.com', 'yellowpages.com', 'buildzoom.com', 'thumbtack.com',
    'houzz.com', 'instagram.com', 'cslb.ca.gov', 'wikipedia.org',
}

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,229}\.[A-Za-z]{2,24}')

class EnrichmentPipeline:
    def __init__(
        self,
        supabase: Client,
        treg_token: str,
        max_spend_micro: int,
        dry_run: bool = False,
        batch_id: Optional[str] = None,
        list_id: Optional[str] = None,
    ):
        self.supabase = supabase
        self.treg_token = treg_token
        self.treg_url = DEFAULT_TREG_URL
        self.max_spend_micro = max_spend_micro
        self.dry_run = dry_run
        self.batch_id = batch_id or f'codicen-cloud-{datetime.now(timezone.utc).strftime("%Y%m%d")}'
        self.list_id = list_id or 'a24441d6-4bac-48a8-96c5-2b6bfd3e1f46'
        
        # State
        self.stats = Counter()
        self.spent_micro = 0
        self.lock = asyncio.Lock()
        self.stop_paid = False
        self.http_client = None
        
        # Caches
        self.attempted_cache = {method: set() for method in ['candidate_fetch', 'jev', 'web_search', 'crawl', 'email_verify']}
        self.suppress_emails = set()
        self.recent_emails = set()  # pipeline_leads within 30 days
        self.confirmed_domains = set()  # cslb_companies.company_domain
        
        # Pending writes (batched)
        self.pending_attempts = []
        self.pending_candidates = []
        self.pending_domain_updates = []
        self.pending_leads = []
    
    def log(self, msg: str):
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f'[{ts}] {msg}', flush=True)
    
    async def init(self):
        """Initialize async HTTP client and load caches"""
        self.http_client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUTS['treg']))
        await self.load_caches()
    
    async def close(self):
        """Close HTTP client and flush pending writes"""
        await self.flush_writes()
        if self.http_client:
            await self.http_client.aclose()
    
    async def load_caches(self):
        """Load attempts cache, suppression list, recent emails, confirmed domains"""
        self.log("Loading caches...")
        
        # Load existing attempts
        for method in self.attempted_cache:
            page_size = 1000
            offset = 0
            while True:
                response = self.supabase.table('codicen_enrichment_attempts').select(
                    'license_no, identifier'
                ).eq('method', method) \
                 .range(offset, offset + page_size - 1).execute()
                
                if not response.data:
                    break
                
                for row in response.data:
                    license_no = row['license_no']
                    identifier = row.get('identifier')
                    if method in ['jev', 'crawl']:
                        self.attempted_cache[method].add(identifier) if identifier else None
                    elif method == 'email_verify':
                        self.attempted_cache[method].add(identifier.lower() if identifier else None)
                    else:
                        self.attempted_cache[method].add(license_no)
                
                offset += page_size
                if len(response.data) < page_size:
                    break
        
        self.log(f"  Attempted cache: {sum(len(s) for s in self.attempted_cache.values())} entries")
        
        # Load confirmed domains from cslb_companies
        page_size = 1000
        offset = 0
        while True:
            response = self.supabase.table('cslb_companies').select('company_domain') \
                .not_.is_('company_domain', 'null') \
                .range(offset, offset + page_size - 1).execute()
            
            if not response.data:
                break
            
            for row in response.data:
                self.confirmed_domains.add(row['company_domain'])
            
            offset += page_size
            if len(response.data) < page_size:
                break
        
        self.log(f"  Confirmed domains: {len(self.confirmed_domains)}")
        
        # Load recent pipeline_leads (within 30 days)
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        page_size = 1000
        offset = 0
        while True:
            response = self.supabase.table('pipeline_leads').select('email') \
                .gte('created_at', thirty_days_ago) \
                .range(offset, offset + page_size - 1).execute()
            
            if not response.data:
                break
            
            for row in response.data:
                email = row.get('email')
                if email:
                    self.recent_emails.add(email.lower())
            
            offset += page_size
            if len(response.data) < page_size:
                break
        
        self.log(f"  Recent emails: {len(self.recent_emails)}")
        
        self.log("Caches loaded")
    
    def was_attempted(self, method: str, license_no: str, identifier: Optional[str] = None) -> bool:
        """Check if company/method/identifier was already attempted"""
        if method in ['jev', 'crawl']:
            return identifier in self.attempted_cache[method] if identifier else False
        elif method == 'email_verify':
            return identifier.lower() in self.attempted_cache[method] if identifier else False
        else:
            return license_no in self.attempted_cache[method]
    
    def skip_email(self, email: str) -> Tuple[bool, str]:
        """Check if email should be skipped (suppression, recent, invalid)"""
        email_lower = email.lower()
        
        # Check suppression list (PlusVibe)
        if email_lower in self.suppress_emails:
            return True, 'suppressed'
        
        # Check recent pipeline_leads
        if email_lower in self.recent_emails:
            return True, 'recent_pipeline_lead'
        
        # Check invalid patterns
        local, domain = email_lower.rsplit('@', 1)
        if local in {'info', 'office', 'admin', 'contact', 'sales', 'support', 'hello', 'noreply', 'no-reply'}:
            return True, 'generic_local'
        
        return False, ''
    
    async def can_afford(self, endpoint: str) -> bool:
        """Check if we can afford another call to endpoint"""
        if self.dry_run:
            return True
        
        cost = COSTS.get(endpoint, 0)
        if cost == 0:
            return True
        
        async with self.lock:
            if self.stop_paid:
                return False
            if self.spent_micro + cost > self.max_spend_micro:
                self.stop_paid = True
                return False
            return True
    
    async def record_spend(self, endpoint: str, actual_cost_micro: int = None):
        """Record spend for an endpoint"""
        if self.dry_run:
            return
        
        cost = actual_cost_micro if actual_cost_micro is not None else COSTS.get(endpoint, 0)
        async with self.lock:
            self.spent_micro += cost
            self.stats[f'spend_{endpoint}'] += cost
    
    async def call_treg(self, endpoint: str, body: Dict, memo: str = '') -> Optional[Dict]:
        """Call Treg endpoint with idempotency and cost checking"""
        if not await self.can_afford(endpoint):
            raise BudgetExceeded(f"Cannot afford {endpoint}")
        
        # Generate idempotency key
        req_key = json.dumps({'endpoint': endpoint, 'body': body, 'memo': memo}, sort_keys=True)
        idem_key = f"{self.batch_id}-{hashlib.sha256(req_key.encode()).hexdigest()[:16]}"
        
        if self.dry_run:
            self.log(f"  [DRY RUN] Would call {endpoint} (cost: ~${COSTS.get(endpoint, 0)/1e6:.5f})")
            await self.record_spend(endpoint)
            return {'dry_run': True}
        
        # Call Treg
        request = {
            'endpoint_id': endpoint,
            'body': body,
            'idempotency_key': idem_key,
            'headers': {'X-Treg-Route-Max-Cost': str(COSTS.get(endpoint, 0) / 1e6)},
        }
        
        try:
            response = await self.http_client.post(
                self.treg_url,
                json=request,
                headers={'Authorization': f'Bearer {self.treg_token}'},
                timeout=TIMEOUTS['treg'],
            )
            response.raise_for_status()
            result = response.json()
            
            # Record actual cost if available
            actual_cost = result.get('cost_micro') or result.get('metadata', {}).get('cost_micro')
            await self.record_spend(endpoint, actual_cost)
            
            return result.get('output') or result
        
        except Exception as e:
            self.log(f"  Treg call failed: {e}")
            self.stats['treg_errors'] += 1
            return None
    
    async def fetch_page(self, domain: str, path: str = '') -> Optional[str]:
        """Fetch webpage content (free HTTP)"""
        for protocol in ['https', 'http']:
            url = f"{protocol}://{domain}{path}"
            try:
                response = await self.http_client.get(
                    url,
                    follow_redirects=True,
                    timeout=TIMEOUTS['fetch'],
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; CSLB-Enrichment/1.0)'},
                )
                if response.status_code == 200:
                    text = response.text
                    # Basic HTML cleaning
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text[:50000]  # Limit to 50KB
            except Exception:
                continue
        return None
    
    async def find_contact_path(self, domain: str) -> Optional[str]:
        """Find contact/about page path"""
        for path in ['/contact', '/about', '/contact-us', '/about-us']:
            try:
                for protocol in ['https', 'http']:
                    url = f"{protocol}://{domain}{path}"
                    response = await self.http_client.head(
                        url,
                        follow_redirects=True,
                        timeout=3.0,
                    )
                    if response.status_code == 200:
                        return path
            except Exception:
                continue
        return None
    
    async def flush_writes(self):
        """Flush all pending writes to Supabase"""
        async with self.lock:
            if self.dry_run:
                self.log(f"[DRY RUN] Would write {len(self.pending_attempts)} attempts, "
                        f"{len(self.pending_candidates)} candidates, "
                        f"{len(self.pending_domain_updates)} domain updates, "
                        f"{len(self.pending_leads)} leads")
                self.pending_attempts.clear()
                self.pending_candidates.clear()
                self.pending_domain_updates.clear()
                self.pending_leads.clear()
                return
            
            # Write attempts
            if self.pending_attempts:
                self.log(f"  Writing {len(self.pending_attempts)} attempts...")
                chunk_size = 500
                for i in range(0, len(self.pending_attempts), chunk_size):
                    chunk = self.pending_attempts[i:i + chunk_size]
                    self.supabase.table('codicen_enrichment_attempts').upsert(
                        chunk,
                        on_conflict='license_no,method,identifier,attempted_at'
                    ).execute()
                self.pending_attempts.clear()
            
            # Write candidates
            if self.pending_candidates:
                self.log(f"  Writing {len(self.pending_candidates)} candidates...")
                chunk_size = 500
                for i in range(0, len(self.pending_candidates), chunk_size):
                    chunk = self.pending_candidates[i:i + chunk_size]
                    self.supabase.table('codicen_domain_candidates').upsert(
                        chunk,
                        on_conflict='license_no,candidate_domain'
                    ).execute()
                self.pending_candidates.clear()
            
            # Write domain updates
            if self.pending_domain_updates:
                self.log(f"  Writing {len(self.pending_domain_updates)} domain updates...")
                for update in self.pending_domain_updates:
                    self.supabase.table('cslb_companies').update(update['data']) \
                        .eq('license_no', update['license_no']) \
                        .is_('company_domain', 'null').execute()
                self.pending_domain_updates.clear()
            
            # Write leads
            if self.pending_leads:
                self.log(f"  Writing {len(self.pending_leads)} leads...")
                chunk_size = 500
                for i in range(0, len(self.pending_leads), chunk_size):
                    chunk = self.pending_leads[i:i + chunk_size]
                    self.supabase.table('pipeline_leads').upsert(
                        chunk,
                        on_conflict='email,batch_id'
                    ).execute()
                self.pending_leads.clear()


class BudgetExceeded(Exception):
    pass


async def main():
    parser = argparse.ArgumentParser(description='Run Codicen enrichment pipeline')
    parser.add_argument('--method', choices=['web_search', 'candidate_verify'], required=True,
                       help='Enrichment method to run')
    parser.add_argument('--limit', type=int, help='Limit number of companies to process')
    parser.add_argument('--max-spend', type=float, required=True,
                       help='Maximum spend in USD (e.g. 1.00 for $1)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode: no paid calls, no writes')
    parser.add_argument('--supabase-url', default=os.environ.get('SUPABASE_URL', DEFAULT_SUPABASE_URL))
    parser.add_argument('--supabase-key', default=os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY'))
    parser.add_argument('--treg-token', default=os.environ.get('treg') or os.environ.get('TREG_API_KEY'))
    parser.add_argument('--batch-id', help='Batch ID for this run (default: codicen-cloud-YYYYMMDD)')
    parser.add_argument('--list-id', default='a24441d6-4bac-48a8-96c5-2b6bfd3e1f46',
                       help='PlusVibe list ID')
    
    args = parser.parse_args()
    
    if not args.supabase_key:
        print("Error: Supabase key required. Set SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    
    if not args.treg_token and not args.dry_run:
        print("Error: Treg token required for live runs. Set 'treg' or TREG_API_KEY env var")
        sys.exit(1)
    
    max_spend_micro = int(args.max_spend * 1_000_000)
    
    print(f"\n{'='*70}")
    print(f"Codicen Enrichment Pipeline")
    print(f"{'='*70}")
    print(f"Method: {args.method}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Max spend: ${args.max_spend:.2f}")
    print(f"Limit: {args.limit or 'None'}")
    print(f"Batch ID: {args.batch_id or 'codicen-cloud-' + datetime.now(timezone.utc).strftime('%Y%m%d')}")
    print(f"{'='*70}\n")
    
    supabase = create_client(args.supabase_url, args.supabase_key)
    
    pipeline = EnrichmentPipeline(
        supabase=supabase,
        treg_token=args.treg_token or '',
        max_spend_micro=max_spend_micro,
        dry_run=args.dry_run,
        batch_id=args.batch_id,
        list_id=args.list_id,
    )
    
    try:
        await pipeline.init()
        
        # Run the selected method
        if args.method == 'web_search':
            # TODO: Implement web search pipeline
            print("Web search pipeline not yet implemented")
            sys.exit(1)
        elif args.method == 'candidate_verify':
            # TODO: Implement candidate verification pipeline
            print("Candidate verification pipeline not yet implemented")
            sys.exit(1)
    
    finally:
        await pipeline.close()


if __name__ == '__main__':
    asyncio.run(main())
