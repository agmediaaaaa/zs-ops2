#!/usr/bin/env python3
"""CSLB Contractor Domain Enrichment Script

Find company website domains for CSLB contractors using Clearbit and Hunter APIs.

Usage:
  python scripts/enrich_cslb_domains.py --limit 100 --dry-run  # Test mode
  python scripts/enrich_cslb_domains.py --limit 1000           # Process 1000 companies
  python scripts/enrich_cslb_domains.py                        # Process all companies without domains

Features:
  - Uses free Clearbit autocomplete API
  - Uses Hunter domain search (free tier)
  - Bulk operations for efficiency
  - Rate limiting and retries
  - High-confidence domain verification
  - Progress tracking and reporting

Environment Variables:
  SUPABASE_URL       - Supabase project URL (defaults to ZS Lead Database)
  SUPABASE_KEY       - Supabase service role key (required)
  HUNTER_API_KEY     - Hunter.io API key (optional, uses free tier if not provided)
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from supabase import create_client, Client
except ImportError:
    print("Error: supabase package not found. Install with: pip install supabase")
    sys.exit(1)

# Configuration
DEFAULT_SUPABASE_URL = "https://npkdhahdvilcctjwzdlf.supabase.co"
CLEARBIT_AUTOCOMPLETE_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"
HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"

# Rate limiting (requests per minute)
CLEARBIT_RPM = 300  # Clearbit autocomplete is generous
HUNTER_RPM = 10  # Free tier is limited

# Generic/low-quality domain patterns to exclude
EXCLUDED_DOMAINS = {
    "yelp.com", "facebook.com", "bbb.org", "houzz.com", "angi.com", "angieslist.com",
    "linkedin.com", "yellowpages.com", "buildzoom.com", "mapquest.com", "google.com",
    "thumbtack.com", "homeadvisor.com", "porch.com", "nextdoor.com", "manta.com",
    "bizjournals.com", "whitepages.com", "superpages.com", "dexknows.com",
}


class RateLimiter:
    """Simple rate limiter for API calls"""
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request = 0.0

    def wait(self):
        """Wait if necessary to respect rate limit"""
        now = time.time()
        time_since_last = now - self.last_request
        if time_since_last < self.min_interval:
            time.sleep(self.min_interval - time_since_last)
        self.last_request = time.time()


def normalize_business_name(name: str) -> str:
    """Normalize business name for domain search
    
    Remove common business suffixes, punctuation, and extra whitespace.
    """
    if not name:
        return ""
    
    # Convert to uppercase for consistent processing
    normalized = name.upper()
    
    # Remove common business type suffixes
    suffixes = [
        r'\s+INC\.?$', r'\s+INCORPORATED$', r'\s+LLC\.?$', r'\s+L\.L\.C\.?$',
        r'\s+CORP\.?$', r'\s+CORPORATION$', r'\s+LTD\.?$', r'\s+LIMITED$',
        r'\s+CO\.?$', r'\s+COMPANY$', r'\s+DBA\s+.*$', r'\s+&\s+CO\.?$',
    ]
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized)
    
    # Remove punctuation except spaces
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    
    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized


def calculate_name_similarity(name1: str, name2: str) -> float:
    """Calculate similarity between two company names (0.0 to 1.0)"""
    if not name1 or not name2:
        return 0.0
    
    # Normalize both names
    n1 = normalize_business_name(name1).lower()
    n2 = normalize_business_name(name2).lower()
    
    # Use SequenceMatcher for similarity
    return SequenceMatcher(None, n1, n2).ratio()


def is_high_confidence_match(
    company_name: str,
    candidate_name: str,
    candidate_domain: str,
) -> Tuple[bool, float]:
    """Determine if a domain candidate is high confidence
    
    Returns: (is_high_confidence, match_score)
    """
    # Check if domain is in excluded list
    domain_lower = candidate_domain.lower()
    for excluded in EXCLUDED_DOMAINS:
        if excluded in domain_lower:
            return False, 0.0
    
    # Calculate name similarity
    similarity = calculate_name_similarity(company_name, candidate_name)
    
    # High confidence criteria:
    # - Name similarity > 0.7 (70% match)
    # - .com domain preferred (slight bonus)
    is_com = candidate_domain.endswith('.com')
    adjusted_score = similarity + (0.05 if is_com else 0)
    
    is_high_confidence = adjusted_score >= 0.75
    
    return is_high_confidence, similarity


def query_clearbit(company_name: str, rate_limiter: RateLimiter) -> List[Dict]:
    """Query Clearbit autocomplete API for company domains
    
    Returns list of candidates with domain and name.
    """
    normalized = normalize_business_name(company_name)
    if not normalized:
        return []
    
    rate_limiter.wait()
    
    url = f"{CLEARBIT_AUTOCOMPLETE_URL}?query={quote_plus(normalized)}"
    
    try:
        req = Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; CSLB-Domain-Enrichment/1.0)')
        
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        results = []
        for item in data:
            if item.get('domain') and item.get('name'):
                results.append({
                    'domain': item['domain'].lower(),
                    'name': item['name'],
                })
        
        return results
    
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"  Clearbit error for '{company_name}': {e}")
        return []
    except Exception as e:
        print(f"  Clearbit unexpected error for '{company_name}': {e}")
        return []


def query_hunter(
    company_name: str,
    city: Optional[str],
    state: Optional[str],
    hunter_api_key: Optional[str],
    rate_limiter: RateLimiter
) -> List[Dict]:
    """Query Hunter.io domain search API for company domains
    
    Returns list of candidates with domain and name.
    """
    normalized = normalize_business_name(company_name)
    if not normalized:
        return []
    
    rate_limiter.wait()
    
    # Build query with location if available
    query_parts = [normalized]
    if city and state == "CA":
        query_parts.append(city)
        query_parts.append("California")
    
    query = " ".join(query_parts)
    
    url = f"{HUNTER_DOMAIN_SEARCH_URL}?company={quote_plus(query)}"
    
    # Add API key if provided (otherwise use free tier)
    if hunter_api_key:
        url += f"&api_key={hunter_api_key}"
    
    try:
        req = Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; CSLB-Domain-Enrichment/1.0)')
        
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        results = []
        
        # Hunter returns a single domain result
        domain_data = data.get('data', {})
        if domain_data.get('domain'):
            results.append({
                'domain': domain_data['domain'].lower(),
                'name': domain_data.get('organization', company_name),
            })
        
        return results
    
    except HTTPError as e:
        if e.code == 429:
            print(f"  Hunter rate limit hit for '{company_name}'")
        elif e.code == 403:
            print(f"  Hunter API key invalid or quota exceeded")
        else:
            print(f"  Hunter HTTP error {e.code} for '{company_name}'")
        return []
    except (URLError, TimeoutError) as e:
        print(f"  Hunter error for '{company_name}': {e}")
        return []
    except Exception as e:
        print(f"  Hunter unexpected error for '{company_name}': {e}")
        return []


def enrich_company_domains(
    supabase: Client,
    limit: Optional[int] = None,
    dry_run: bool = False,
    use_90_day_window: bool = True,
    hunter_api_key: Optional[str] = None,
) -> Dict:
    """Main enrichment function
    
    Returns: Statistics dictionary with counts
    """
    stats = {
        'companies_processed': 0,
        'companies_with_new_candidates': 0,
        'total_new_candidates': 0,
        'domains_written_to_cslb': 0,
        'companies_still_without_domain': 0,
        'clearbit_calls': 0,
        'hunter_calls': 0,
        'errors': 0,
    }
    
    # Initialize rate limiters
    clearbit_limiter = RateLimiter(CLEARBIT_RPM)
    hunter_limiter = RateLimiter(HUNTER_RPM)
    
    print("\n=== CSLB Domain Enrichment ===")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"90-day window filter: {'ON' if use_90_day_window else 'OFF'}")
    print(f"Limit: {limit if limit else 'None (process all)'}")
    print(f"Hunter API key: {'Provided' if hunter_api_key else 'Not provided (using free tier)'}")
    print()
    
    # Build query for companies without domains
    query = supabase.table('cslb_companies').select(
        'license_no, business_name, city, state'
    ).is_('company_domain', 'null')
    
    if use_90_day_window:
        query = query.gte('expiration_date_iso', 'now()') \
                     .lte('expiration_date_iso', 'now() + interval \'90 days\'')
    
    if limit:
        query = query.limit(limit)
    
    print("Fetching companies without domains...")
    response = query.execute()
    companies = response.data
    
    print(f"Found {len(companies)} companies to process\n")
    
    # Track all candidates for bulk insert
    all_candidates = []
    companies_to_update = []
    
    for idx, company in enumerate(companies, 1):
        license_no = company['license_no']
        business_name = company['business_name']
        city = company.get('city')
        state = company.get('state')
        
        if idx % 10 == 0:
            print(f"Processing {idx}/{len(companies)}...")
        
        # Skip if no business name
        if not business_name or business_name.strip() == '':
            continue
        
        candidates = []
        
        # Query Clearbit
        try:
            clearbit_results = query_clearbit(business_name, clearbit_limiter)
            stats['clearbit_calls'] += 1
            
            for result in clearbit_results:
                candidates.append({
                    'source': 'clearbit',
                    'domain': result['domain'],
                    'name': result['name'],
                })
        except Exception as e:
            print(f"  Error querying Clearbit for {license_no}: {e}")
            stats['errors'] += 1
        
        # Query Hunter
        try:
            hunter_results = query_hunter(
                business_name, city, state, hunter_api_key, hunter_limiter
            )
            stats['hunter_calls'] += 1
            
            for result in hunter_results:
                candidates.append({
                    'source': 'hunter',
                    'domain': result['domain'],
                    'name': result['name'],
                })
        except Exception as e:
            print(f"  Error querying Hunter for {license_no}: {e}")
            stats['errors'] += 1
        
        # Process candidates
        if candidates:
            stats['companies_with_new_candidates'] += 1
            
            # Find best candidate
            best_candidate = None
            best_score = 0.0
            
            for candidate in candidates:
                is_high_conf, score = is_high_confidence_match(
                    business_name,
                    candidate['name'],
                    candidate['domain']
                )
                
                # Store all candidates for codicen_domain_candidates
                all_candidates.append({
                    'license_no': license_no,
                    'company_name': business_name,
                    'city': city,
                    'principal': None,  # We don't have principal info in this context
                    'candidate_domain': candidate['domain'],
                    'source': candidate['source'],
                    'candidate_name': candidate['name'],
                    'name_match_score': score,
                    'verification_status': 'pending',
                    'verification_evidence': {},
                })
                
                stats['total_new_candidates'] += 1
                
                # Track best high-confidence candidate for cslb_companies update
                if is_high_conf and score > best_score:
                    best_candidate = candidate
                    best_score = score
            
            # If we have a high-confidence match, prepare to update cslb_companies
            if best_candidate:
                companies_to_update.append({
                    'license_no': license_no,
                    'company_domain': best_candidate['domain'],
                    'domain_source': best_candidate['source'],
                    'domain_confidence': 'high',
                })
                stats['domains_written_to_cslb'] += 1
        
        stats['companies_processed'] += 1
    
    # Bulk insert candidates to codicen_domain_candidates
    if all_candidates and not dry_run:
        print(f"\nInserting {len(all_candidates)} candidates into codicen_domain_candidates...")
        
        # Insert in batches of 1000
        batch_size = 1000
        for i in range(0, len(all_candidates), batch_size):
            batch = all_candidates[i:i + batch_size]
            try:
                supabase.table('codicen_domain_candidates').upsert(
                    batch,
                    on_conflict='license_no,candidate_domain'
                ).execute()
            except Exception as e:
                print(f"  Error inserting batch {i//batch_size + 1}: {e}")
                stats['errors'] += 1
    
    # Bulk update cslb_companies with high-confidence domains
    if companies_to_update and not dry_run:
        print(f"\nUpdating {len(companies_to_update)} companies in cslb_companies...")
        
        for company_update in companies_to_update:
            try:
                supabase.table('cslb_companies').update({
                    'company_domain': company_update['company_domain'],
                    'domain_source': company_update['domain_source'],
                    'domain_confidence': company_update['domain_confidence'],
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                }).eq('license_no', company_update['license_no']).execute()
            except Exception as e:
                print(f"  Error updating {company_update['license_no']}: {e}")
                stats['errors'] += 1
    
    # Calculate companies still without domain
    stats['companies_still_without_domain'] = (
        stats['companies_processed'] - stats['domains_written_to_cslb']
    )
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Enrich CSLB contractor companies with domain data from Clearbit and Hunter',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of companies to process (default: process all)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without writing to database',
    )
    parser.add_argument(
        '--all-companies',
        action='store_true',
        help='Process all companies, not just 90-day window',
    )
    parser.add_argument(
        '--supabase-url',
        default=os.environ.get('SUPABASE_URL', DEFAULT_SUPABASE_URL),
        help='Supabase project URL',
    )
    parser.add_argument(
        '--supabase-key',
        default=os.environ.get('SUPABASE_KEY'),
        help='Supabase service role key (or set SUPABASE_KEY env var)',
    )
    parser.add_argument(
        '--hunter-api-key',
        default=os.environ.get('HUNTER_API_KEY'),
        help='Hunter.io API key (optional, or set HUNTER_API_KEY env var)',
    )
    
    args = parser.parse_args()
    
    # Validate required arguments
    if not args.supabase_key:
        print("Error: Supabase key required. Set SUPABASE_KEY env var or use --supabase-key")
        sys.exit(1)
    
    # Create Supabase client
    try:
        supabase = create_client(args.supabase_url, args.supabase_key)
    except Exception as e:
        print(f"Error creating Supabase client: {e}")
        sys.exit(1)
    
    # Run enrichment
    start_time = time.time()
    
    try:
        stats = enrich_company_domains(
            supabase=supabase,
            limit=args.limit,
            dry_run=args.dry_run,
            use_90_day_window=not args.all_companies,
            hunter_api_key=args.hunter_api_key,
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    elapsed_time = time.time() - start_time
    
    # Print final report
    print("\n" + "="*60)
    print("FINAL REPORT")
    print("="*60)
    print(f"Companies processed:              {stats['companies_processed']:,}")
    print(f"Companies with new candidates:    {stats['companies_with_new_candidates']:,}")
    print(f"Total new candidate pairs:        {stats['total_new_candidates']:,}")
    print(f"Domains written to cslb_companies: {stats['domains_written_to_cslb']:,}")
    print(f"Companies still without domain:   {stats['companies_still_without_domain']:,}")
    print()
    print(f"Clearbit API calls:               {stats['clearbit_calls']:,}")
    print(f"Hunter API calls:                 {stats['hunter_calls']:,}")
    print(f"Errors:                           {stats['errors']:,}")
    print()
    print(f"Elapsed time:                     {elapsed_time:.1f}s")
    print("="*60)
    
    if args.dry_run:
        print("\nDRY RUN - No data was written to the database")


if __name__ == '__main__':
    main()
