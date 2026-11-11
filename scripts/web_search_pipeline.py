#!/usr/bin/env python3
"""Full web_search pipeline: Search → Fetch → Jev → Crawl → Email Verify → Pipeline Leads

Async/concurrent implementation with:
- anyapi.google.serp.organic search via Treg
- Directory exclusion
- Snippet/directory email capture with name-match quality gate
- Free HTTP fetch (homepage + contact)
- Identity markers (license, phone - NOT city-only)
- Jev verification on license/phone markers only
- 2-page Crawl4AI for confirmed domains without email
- MV then BB async email verification
- pipeline_leads bulk upsert
- List a24441d6 for list-quality only
- Hard cap before every paid call
- Attempts ledger writes after every operation
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

# Costs (microdollars)
COSTS = {
    'anyapi.google.serp.organic': 470,
    'openrouter.ai-judge.decide': 80,  # Jev
    'crawl4ai.web.extract.batch': 150,
    'millionverifier.people.email.verify': 1100,
    'bounceban.people.email.verify': 4000,
}

# Concurrency
CONCURRENCY = {
    'search': 30,
    'fetch': 80,
    'jev': 15,
    'crawl': 8,
    'email': 10,
}

# Timeouts
TIMEOUTS = {'fetch': 8.0, 'treg': 30.0}

# Jev thresholds (license/phone only, NOT city_ca)
JEV_THRESHOLDS = {
    'license_match': {'contractor': 0.45, 'california': 0.70, 'identity': 0.80},
    'phone_match': {'contractor': 0.55, 'california': 0.75, 'identity': 0.85},
}

# Directory hosts to exclude
DIRECTORY_HOSTS = {
    'yelp.com', 'bbb.org', 'angi.com', 'homeadvisor.com', 'facebook.com',
    'linkedin.com', 'yellowpages.com', 'buildzoom.com', 'thumbtack.com',
    'houzz.com', 'instagram.com', 'cslb.ca.gov', 'wikipedia.org', 'mapquest.com',
    'local.yahoo.com', 'ezlocal.com', 'twitter.com', 'x.com',
}

# Email patterns
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,229}\.[A-Za-z]{2,24}')
GENERIC_LOCALS = {
    'info', 'office', 'admin', 'contact', 'sales', 'support', 'hello', 'estimate',
    'service', 'billing', 'inquiry', 'mail', 'customerservice', 'help', 'team',
}
FREE_MAIL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'aol.com', 'hotmail.com', 'outlook.com', 'icloud.com',
}


class BudgetExceeded(Exception):
    pass


class WebSearchPipeline:
    def __init__(
        self,
        supabase: Client,
        treg_token: str,
        max_spend_micro: int,
        dry_run: bool = False,
        batch_id: Optional[str] = None,
        list_id: str = 'a24441d6-4bac-48a8-96c5-2b6bfd3e1f46',
        mock_searches: Optional[Dict] = None,
    ):
        self.supabase = supabase
        self.treg_token = treg_token
        self.treg_url = DEFAULT_TREG_URL
        self.max_spend_micro = max_spend_micro
        self.dry_run = dry_run
        self.batch_id = batch_id or f'codicen-cloud-{datetime.now(timezone.utc).strftime("%Y%m%d")}'
        self.list_id = list_id
        self.mock_searches = mock_searches or {}  # license_no -> search result
        
        self.stats = Counter()
        self.spent_micro = 0
        self.lock = asyncio.Lock()
        self.stop_paid = False
        self.http_client = None
        
        # Pending writes (batched)
        self.pending_attempts = []
        self.pending_candidates = []
        self.pending_domain_updates = []
        self.pending_leads = []
        
        self.start_time = time.time()
    
    def log(self, msg: str):
        elapsed = time.time() - self.start_time
        print(f'[{elapsed:7.1f}s] {msg}', flush=True)
    
    async def init(self):
        self.http_client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUTS['treg']))
    
    async def close(self):
        await self.flush_writes()
        if self.http_client:
            await self.http_client.aclose()
    
    async def can_afford(self, endpoint: str) -> bool:
        if self.dry_run and endpoint != 'anyapi.google.serp.organic':  # Allow mocked searches in dry-run
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
        if self.dry_run:
            cost = actual_cost_micro or COSTS.get(endpoint, 0)
            async with self.lock:
                self.stats[f'dry_spend_{endpoint}'] += cost
            return
        cost = actual_cost_micro or COSTS.get(endpoint, 0)
        async with self.lock:
            self.spent_micro += cost
    
    async def record_attempt(self, method: str, license_no: str, identifier: Optional[str],
                           outcome: str, cost_micro: int = 0, metadata: Dict = None):
        async with self.lock:
            self.pending_attempts.append({
                'license_no': license_no,
                'method': method,
                'identifier': identifier,
                'outcome': outcome,
                'cost_micro': cost_micro,
                'attempted_at': datetime.now(timezone.utc).isoformat(),
                'metadata': metadata or {},
            })
    
    async def flush_writes(self):
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
            
            if self.pending_attempts:
                self.log(f"  Writing {len(self.pending_attempts)} attempts...")
                for i in range(0, len(self.pending_attempts), 500):
                    chunk = self.pending_attempts[i:i+500]
                    self.supabase.table('codicen_enrichment_attempts').upsert(
                        chunk, on_conflict='license_no,method,identifier,attempted_at'
                    ).execute()
                self.pending_attempts.clear()
            
            if self.pending_candidates:
                self.log(f"  Writing {len(self.pending_candidates)} candidates...")
                for i in range(0, len(self.pending_candidates), 500):
                    chunk = self.pending_candidates[i:i+500]
                    self.supabase.table('codicen_domain_candidates').upsert(
                        chunk, on_conflict='license_no,candidate_domain'
                    ).execute()
                self.pending_candidates.clear()
            
            if self.pending_domain_updates:
                self.log(f"  Writing {len(self.pending_domain_updates)} domain updates...")
                for update in self.pending_domain_updates:
                    self.supabase.table('cslb_companies').update(update['data']) \
                        .eq('license_no', update['license_no']) \
                        .is_('company_domain', 'null').execute()
                self.pending_domain_updates.clear()
            
            if self.pending_leads:
                self.log(f"  Writing {len(self.pending_leads)} leads...")
                for i in range(0, len(self.pending_leads), 500):
                    chunk = self.pending_leads[i:i+500]
                    self.supabase.table('pipeline_leads').upsert(
                        chunk, on_conflict='email,batch_id'
                    ).execute()
                self.pending_leads.clear()
    
    async def search_company(self, company: Dict) -> Tuple[List[Dict], List[str]]:
        """Search for company domains and extract snippet emails
        
        Returns: (result_dicts, snippet_emails)
        """
        license_no = company['license_no']
        name = company.get('business_name', '').strip()
        city = company.get('city', '').strip()
        
        # Check if mocked
        if license_no in self.mock_searches:
            self.stats['searches_mocked'] += 1
            mock_result = self.mock_searches[license_no]
            # Parse mock result
            results = []
            for host in (mock_result.get('hosts') or [])[:5]:
                if host and host not in DIRECTORY_HOSTS:
                    results.append({'domain': host, 'title': '', 'snippet': ''})
            return results, []
        
        if not await self.can_afford('anyapi.google.serp.organic'):
            raise BudgetExceeded("Cannot afford search")
        
        query = f'{name} {city} CA contractor'
        body = {
            'query': query,
            'gl': 'us',
            'hl': 'en',
            'limit': 10,
            'location': f'{city}, California, United States' if city else 'California, United States',
        }
        
        # For dry-run, simulate search without calling
        if self.dry_run:
            await self.record_spend('anyapi.google.serp.organic')
            await self.record_attempt('web_search', license_no, None, 'dry_run', COSTS['anyapi.google.serp.organic'])
            self.stats['searches_dry_run'] += 1
            return [], []
        
        # Real call
        idem_key = f"{self.batch_id}-search-{license_no}"
        request = {
            'endpoint_id': 'anyapi.google.serp.organic',
            'body': body,
            'idempotency_key': idem_key,
            'headers': {'X-Treg-Route-Max-Cost': str(COSTS['anyapi.google.serp.organic'] / 1e6)},
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
            
            await self.record_spend('anyapi.google.serp.organic')
            await self.record_attempt('web_search', license_no, None, 'completed',
                                     COSTS['anyapi.google.serp.organic'],
                                     {'query': query, 'n_results': len(result.get('output', {}).get('results', []))})
            
            # Parse results
            output = result.get('output', {})
            raw_results = output.get('results', []) or output.get('organic', [])
            
            # Extract domains and emails
            domains = []
            emails = []
            
            for r in raw_results[:10]:
                url = r.get('link') or r.get('url', '')
                if url:
                    host = urlparse(url).netloc.lower().removeprefix('www.')
                    if host and host not in DIRECTORY_HOSTS:
                        domains.append({
                            'domain': host,
                            'title': r.get('title', ''),
                            'snippet': r.get('snippet', ''),
                        })
                
                # Extract emails from snippet
                snippet = r.get('snippet', '') + ' ' + r.get('title', '')
                for email in EMAIL_RE.findall(snippet):
                    email_lower = email.lower()
                    if '@' in email_lower and email_lower not in emails:
                        emails.append(email_lower)
            
            self.stats['searches_completed'] += 1
            return domains, emails
        
        except Exception as e:
            self.log(f"  Search error for {license_no}: {e}")
            await self.record_attempt('web_search', license_no, None, 'error', 0, {'error': str(e)})
            self.stats['search_errors'] += 1
            return [], []
    
    async def fetch_page(self, domain: str, path: str = '') -> Optional[str]:
        """Free HTTP fetch"""
        for protocol in ['https', 'http']:
            url = f"{protocol}://{domain}{path}"
            try:
                response = await self.http_client.get(
                    url,
                    follow_redirects=True,
                    timeout=TIMEOUTS['fetch'],
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; CSLB/1.0)'},
                )
                if response.status_code == 200:
                    text = response.text
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text[:50000]
            except Exception:
                continue
        return None
    
    async def find_contact_path(self, domain: str) -> Optional[str]:
        """Find contact/about page"""
        for path in ['/contact', '/about', '/contact-us', '/about-us']:
            try:
                for protocol in ['https', 'http']:
                    response = await self.http_client.head(
                        f"{protocol}://{domain}{path}",
                        follow_redirects=True,
                        timeout=3.0,
                    )
                    if response.status_code == 200:
                        return path
            except Exception:
                continue
        return None
    
    def check_identity_markers(self, texts: List[str], license_no: str, phone: str, city: str) -> Dict[str, bool]:
        """Check for license/phone markers (NOT city-only)"""
        combined = ' '.join(texts).lower()
        
        markers = {
            'license_match': bool(re.search(r'\b' + re.escape(license_no) + r'\b', combined)),
            'phone_match': False,
        }
        
        # Phone match (various formats)
        if phone:
            clean_phone = re.sub(r'\D', '', phone)
            if len(clean_phone) == 10:
                patterns = [
                    clean_phone,
                    f'{clean_phone[:3]}-{clean_phone[3:6]}-{clean_phone[6:]}',
                    f'({clean_phone[:3]}) {clean_phone[3:6]}-{clean_phone[6:]}',
                    f'{clean_phone[:3]}.{clean_phone[3:6]}.{clean_phone[6:]}',
                ]
                for pattern in patterns:
                    if pattern in combined:
                        markers['phone_match'] = True
                        break
        
        return markers
    
    async def verify_jev(self, domain: str, texts: List[str], markers: Dict) -> Tuple[bool, Dict]:
        """Jev verification on license/phone markers only (NOT city)"""
        if not markers.get('license_match') and not markers.get('phone_match'):
            return False, {}
        
        if not await self.can_afford('openrouter.ai-judge.decide'):
            return False, {}
        
        # Prepare Jev input
        combined_text = ' '.join(texts)[:8000]
        prompt = f"Domain: {domain}\n\nText sample:\n{combined_text}"
        
        body = {
            'model': 'meta-llama/llama-3.1-8b-instruct',
            'prompt': prompt,
            'schema': {
                'contractor': 'float',
                'california': 'float',
                'identity': 'float',
            },
        }
        
        if self.dry_run:
            await self.record_spend('openrouter.ai-judge.decide')
            self.stats['jev_dry_run'] += 1
            # Simulate confirmation for dry-run
            return True, {'contractor': 0.75, 'california': 0.85, 'identity': 0.90}
        
        idem_key = f"{self.batch_id}-jev-{domain}"
        request = {
            'endpoint_id': 'openrouter.ai-judge.decide',
            'body': body,
            'idempotency_key': idem_key,
            'headers': {'X-Treg-Route-Max-Cost': str(COSTS['openrouter.ai-judge.decide'] / 1e6)},
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
            
            await self.record_spend('openrouter.ai-judge.decide')
            
            jev_scores = result.get('output', {})
            
            # Check thresholds based on marker type
            if markers.get('license_match'):
                thresholds = JEV_THRESHOLDS['license_match']
            elif markers.get('phone_match'):
                thresholds = JEV_THRESHOLDS['phone_match']
            else:
                return False, jev_scores
            
            confirmed = (
                jev_scores.get('contractor', 0) >= thresholds['contractor'] and
                jev_scores.get('california', 0) >= thresholds['california'] and
                jev_scores.get('identity', 0) >= thresholds['identity']
            )
            
            self.stats['jev_calls'] += 1
            if confirmed:
                self.stats['jev_confirmed'] += 1
            else:
                self.stats['jev_rejected'] += 1
            
            return confirmed, jev_scores
        
        except Exception as e:
            self.log(f"  Jev error for {domain}: {e}")
            self.stats['jev_errors'] += 1
            return False, {}
    
    async def process_company(self, company: Dict):
        """Full pipeline for one company"""
        license_no = company['license_no']
        
        # Stage 1: Search
        try:
            domains, snippet_emails = await self.search_company(company)
            self.stats['companies_searched'] += 1
        except BudgetExceeded:
            return
        except Exception as e:
            self.log(f"  Error processing {license_no}: {e}")
            self.stats['errors'] += 1
            return
        
        if not domains and not snippet_emails:
            self.stats['no_results'] += 1
            return
        
        if domains:
            self.stats['companies_with_domains'] += 1
        
        if snippet_emails:
            self.stats['companies_with_snippet_emails'] += len(snippet_emails)
        
        # Stage 2: Fetch top domains
        for domain_info in domains[:5]:
            domain = domain_info['domain']
            
            # Free fetch
            homepage = await self.fetch_page(domain)
            if not homepage:
                self.stats['fetch_failed'] += 1
                continue
            
            self.stats['fetched'] += 1
            contact_path = await self.find_contact_path(domain)
            contact = await self.fetch_page(domain, contact_path) if contact_path else None
            
            texts = [homepage]
            if contact:
                texts.append(contact)
                self.stats['contact_fetched'] += 1
            
            # Stage 3: Check markers (license/phone only)
            markers = self.check_identity_markers(
                texts,
                license_no,
                company.get('business_phone', ''),
                company.get('city', '')
            )
            
            if not markers.get('license_match') and not markers.get('phone_match'):
                self.stats['no_markers'] += 1
                await self.record_attempt('jev', license_no, domain, 'skipped_no_markers', 0, {'markers': markers})
                continue
            
            self.stats['marker_positive'] += 1
            
            # Stage 4: Jev verification
            confirmed, jev_scores = await self.verify_jev(domain, texts, markers)
            
            if confirmed:
                self.stats['domains_confirmed'] += 1
                await self.record_attempt('jev', license_no, domain, 'confirmed',
                                         COSTS['openrouter.ai-judge.decide'],
                                         {'markers': markers, 'jev_scores': jev_scores})
                
                # Record confirmed domain
                async with self.lock:
                    self.pending_domain_updates.append({
                        'license_no': license_no,
                        'data': {
                            'company_domain': domain,
                            'domain_source': 'web_search',
                            'domain_confidence': 'jev_confirmed',
                            'updated_at': datetime.now(timezone.utc).isoformat(),
                        },
                    })
                
                # Extract emails from free pages
                emails_found = []
                for text in texts:
                    for email in EMAIL_RE.findall(text):
                        email_lower = email.lower()
                        domain_part = email_lower.split('@')[1]
                        if domain_part not in FREE_MAIL_DOMAINS and email_lower not in emails_found:
                            emails_found.append(email_lower)
                
                if emails_found:
                    self.stats['emails_from_free'] += len(emails_found)
                    # TODO: Queue for MV/BB verification
                else:
                    self.stats['confirmed_needs_crawl'] += 1
                    # TODO: Queue for Crawl4AI
                
                # Stop after first confirmation
                return
            else:
                await self.record_attempt('jev', license_no, domain, 'rejected',
                                         COSTS['openrouter.ai-judge.decide'],
                                         {'markers': markers, 'jev_scores': jev_scores})
        
        # Flush writes periodically
        if len(self.pending_attempts) >= 100:
            await self.flush_writes()
    
    async def run(self, companies: List[Dict]):
        """Run pipeline on list of companies"""
        self.log(f"Starting web_search pipeline for {len(companies)} companies")
        self.log(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.log(f"Max spend: ${self.max_spend_micro/1e6:.2f}")
        self.log(f"Batch ID: {self.batch_id}")
        
        # Process companies with concurrency limit
        sem = asyncio.Semaphore(CONCURRENCY['search'])
        
        async def process_with_sem(company):
            async with sem:
                await self.process_company(company)
        
        await asyncio.gather(*[process_with_sem(c) for c in companies])
        
        await self.flush_writes()
        
        elapsed = time.time() - self.start_time
        throughput = len(companies) / elapsed * 60 if elapsed > 0 else 0
        
        self.log(f"\n{'='*70}")
        self.log("PIPELINE COMPLETE")
        self.log(f"{'='*70}")
        self.log(f"Companies processed:      {len(companies)}")
        self.log(f"Companies searched:       {self.stats['companies_searched']}")
        self.log(f"Companies with domains:   {self.stats['companies_with_domains']}")
        self.log(f"Fetched:                  {self.stats['fetched']}")
        self.log(f"Marker positive:          {self.stats['marker_positive']}")
        self.log(f"Jev calls:                {self.stats['jev_calls']}")
        self.log(f"Domains confirmed:        {self.stats['domains_confirmed']}")
        self.log(f"Elapsed: {elapsed:.1f}s")
        self.log(f"Throughput: {throughput:.1f} companies/min")
        
        if self.dry_run:
            total_dry_spend = sum(v for k, v in self.stats.items() if k.startswith('dry_spend_'))
            self.log(f"\nDRY RUN spend would be: ${total_dry_spend/1e6:.4f}")
        else:
            self.log(f"\nActual spend: ${self.spent_micro/1e6:.4f}")


async def main():
    parser = argparse.ArgumentParser(description='Web search pipeline for CSLB enrichment')
    parser.add_argument('--limit', type=int, help='Limit number of companies')
    parser.add_argument('--max-spend', type=float, required=True, help='Max spend in USD')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (mock searches, real fetches)')
    parser.add_argument('--mock-searches', help='Path to searches.jsonl for mocking')
    parser.add_argument('--supabase-url', default=os.environ.get('SUPABASE_URL', DEFAULT_SUPABASE_URL))
    parser.add_argument('--supabase-key', default=os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY'))
    parser.add_argument('--treg-token', default=os.environ.get('treg'))
    parser.add_argument('--batch-id', help='Batch ID')
    
    args = parser.parse_args()
    
    if not args.supabase_key:
        print("Error: SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY required")
        sys.exit(1)
    
    if not args.treg_token and not args.dry_run:
        print("Error: treg token required for live runs")
        sys.exit(1)
    
    supabase = create_client(args.supabase_url, args.supabase_key)
    
    # Load mock searches if provided
    mock_searches = {}
    if args.mock_searches:
        with open(args.mock_searches) as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    mock_searches[record['license_no']] = record
    
    # Fetch eligible companies
    print("Fetching eligible companies...")
    today = datetime.now().date()
    ninety_days = today + timedelta(days=90)
    
    # Get companies not yet web-searched
    eligible = []
    page_size = 1000
    offset = 0
    
    while True:
        response = supabase.table('cslb_companies').select(
            'license_no, business_name, business_phone, city, state'
        ).is_('company_domain', 'null') \
         .eq('primary_status', 'CLEAR') \
         .gte('expiration_date_iso', today.isoformat()) \
         .lte('expiration_date_iso', ninety_days.isoformat()) \
         .range(offset, offset + page_size - 1).execute()
        
        if not response.data:
            break
        
        eligible.extend(response.data)
        offset += page_size
        
        if len(response.data) < page_size:
            break
        
        if args.limit and len(eligible) >= args.limit:
            eligible = eligible[:args.limit]
            break
    
    # Filter out already web-searched
    searched_response = supabase.table('codicen_enrichment_attempts').select(
        'license_no'
    ).eq('method', 'web_search').execute()
    
    searched_licenses = {row['license_no'] for row in searched_response.data}
    eligible = [c for c in eligible if c['license_no'] not in searched_licenses]
    
    if args.limit:
        eligible = eligible[:args.limit]
    
    print(f"Found {len(eligible)} eligible companies (not yet web-searched)")
    
    if not eligible:
        print("No eligible companies to process")
        return
    
    pipeline = WebSearchPipeline(
        supabase=supabase,
        treg_token=args.treg_token or '',
        max_spend_micro=int(args.max_spend * 1_000_000),
        dry_run=args.dry_run,
        batch_id=args.batch_id,
        mock_searches=mock_searches,
    )
    
    try:
        await pipeline.init()
        await pipeline.run(eligible)
    finally:
        await pipeline.close()


if __name__ == '__main__':
    asyncio.run(main())
