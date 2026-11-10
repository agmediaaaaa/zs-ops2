#!/usr/bin/env python3
"""CSLB Contractor Domain Enrichment Script

Find and verify company website domains for CSLB contractors.

Two-phase workflow:
  1. Candidate discovery (free): Query Clearbit/Hunter, save all to codicen_domain_candidates
  2. Verification (paid, opt-in): Fetch pages, check identity, run Jev classifier

Usage:
  # Phase 1: Find candidates (free)
  python scripts/enrich_cslb_domains.py --limit 10 --dry-run
  python scripts/enrich_cslb_domains.py --limit 100
  python scripts/enrich_cslb_domains.py  # All CLEAR companies in 90-day window
  
  # Phase 2: Verify candidates (paid, requires --max-spend-usd)
  python scripts/enrich_cslb_domains.py --verify --max-spend-usd 5.00 --limit 100
  python scripts/enrich_cslb_domains.py --verify --max-spend-usd 50.00 --dry-run

Environment Variables:
  SUPABASE_URL       - Supabase project URL (defaults to ZS Lead Database)
  SUPABASE_KEY       - Supabase service role key (required)
  TREG_API_KEY       - Treg API key (required for discovery and verify)
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

# Rate limiting (requests per minute)
CLEARBIT_RPM = 300  # Clearbit autocomplete is generous
HUNTER_RPM = 10  # Free tier is limited

# Generic/low-quality domain patterns to exclude (directory/social sites)
EXCLUDED_DOMAINS = {
    "yelp.com", "facebook.com", "bbb.org", "houzz.com", "angi.com", "angieslist.com",
    "linkedin.com", "yellowpages.com", "buildzoom.com", "mapquest.com", "google.com",
    "thumbtack.com", "homeadvisor.com", "porch.com", "nextdoor.com", "manta.com",
    "bizjournals.com", "whitepages.com", "superpages.com", "dexknows.com",
    "instagram.com",
}

# Treg API configuration
TREG_API_URL = "https://api.treg.ai/v2"
JEV_ACTOR_ID = "typesafe/jev-1.13"

# Real costs (measured):
# - Jev via Treg: ~$0.00008 per check ($0.042/M input tokens)
# - Crawl4AI page fetch: ~$0.00015 per page (or $0 if plain HTTP)
# - $0.0005 reserve held per Jev request, settled after response
JEV_RESERVE_PER_CALL = 0.0005  # Reserved before call, released after settlement
JEV_TYPICAL_COST = 0.00008  # Typical settled cost per Jev check
PAGE_FETCH_COST = 0.0  # Using plain HTTP (free), not Crawl4AI

# Verification thresholds (calibrated on 200 companies)
VERIFICATION_THRESHOLDS = {
    'license_match': {'contractor': 0.65, 'california': 0.60, 'identity': 0.65},
    'phone_match': {'contractor': 0.70, 'california': 0.80, 'identity': 0.82},
    'city_ca_match': {'contractor': 0.80, 'california': 0.90, 'identity': 0.90},
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


def calculate_ranking_score(
    company_name: str,
    candidate_name: str,
    candidate_domain: str,
) -> float:
    """Calculate ranking score for a domain candidate
    
    Returns: match_score (0.0 to 1.0+, with .com bonus for ranking)
    """
    # Check if domain is in excluded list
    domain_lower = candidate_domain.lower()
    for excluded in EXCLUDED_DOMAINS:
        if excluded in domain_lower:
            return 0.0
    
    # Calculate name similarity
    similarity = calculate_name_similarity(company_name, candidate_name)
    
    # .com domain gets +0.05 bonus for ranking purposes only
    is_com = candidate_domain.endswith('.com')
    ranking_score = similarity + (0.05 if is_com else 0)
    
    return ranking_score


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


def query_treg_hunter(
    company_name: str,
    city: Optional[str],
    state: Optional[str],
    treg_api_key: str,
    rate_limiter: RateLimiter
) -> List[Dict]:
    """Query free Treg Hunter domain finder for company domains
    
    Uses hunter.x.domain-finder via Treg API (free).
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
    
    company_query = " ".join(query_parts)
    
    url = f"{TREG_API_URL}/call/hunter.x.domain-finder"
    
    payload = {
        'input': {
            'company': company_query,
        }
    }
    
    headers = {
        'Authorization': f'Bearer {treg_api_key}',
        'Content-Type': 'application/json',
    }
    
    try:
        req = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        
        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        results = []
        
        # Extract domain from Treg response
        if 'output' in result and isinstance(result['output'], dict):
            output = result['output']
            domain = output.get('domain')
            org_name = output.get('organization') or output.get('name') or company_name
            
            if domain:
                results.append({
                    'domain': domain.lower(),
                    'name': org_name,
                })
        
        return results
    
    except Exception as e:
        return []


def fetch_webpage_content(domain: str, path: str = '') -> Optional[str]:
    """Fetch webpage content from domain
    
    Tries https:// first, falls back to http://
    Follows simple redirects once (3xx status)
    
    Returns: Page text content or None if fetch fails
    """
    protocols = ['https', 'http']
    
    for protocol in protocols:
        url = f"{protocol}://{domain}{path}"
        
        try:
            req = Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (compatible; CSLB-Domain-Enrichment/1.0)')
            
            response = urlopen(req, timeout=15)
            
            # Follow simple redirects once (meta refresh or 3xx that urllib didn't handle)
            final_url = response.geturl()
            if final_url != url:
                # Simple meta refresh check
                html = response.read().decode('utf-8', errors='ignore')
                meta_match = re.search(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\']0;\s*url=([^"\']+)', html, re.IGNORECASE)
                if meta_match:
                    redirect_url = meta_match.group(1)
                    try:
                        req2 = Request(redirect_url)
                        req2.add_header('User-Agent', 'Mozilla/5.0 (compatible; CSLB-Domain-Enrichment/1.0)')
                        response = urlopen(req2, timeout=15)
                        html = response.read().decode('utf-8', errors='ignore')
                    except:
                        pass  # Use original response
            else:
                html = response.read().decode('utf-8', errors='ignore')
            
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type and 'text/plain' not in content_type:
                continue  # Try next protocol
            
            # Simple text extraction (remove HTML tags)
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            return text[:50000]  # Limit to 50KB of text
        
        except Exception as e:
            continue  # Try next protocol
    
    return None


def find_contact_about_path(domain: str) -> Optional[str]:
    """Find a contact or about page path
    
    Returns: Path like '/contact' or '/about' if found, else None
    """
    common_paths = ['/contact', '/about', '/contact-us', '/about-us', '/contactus', '/aboutus']
    
    for path in common_paths:
        try:
            url = f"https://{domain}{path}"
            req = Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (compatible; CSLB-Domain-Enrichment/1.0)')
            
            with urlopen(req, timeout=5) as response:
                if response.status == 200:
                    return path
        except:
            continue
    
    return None


def check_identity_markers(
    page_texts: List[str],
    license_no: str,
    business_phone: Optional[str],
    city: Optional[str],
) -> Dict[str, bool]:
    """Check for identity markers in page text
    
    Returns: Dict with license_match, phone_match, city_ca_match flags
    """
    combined_text = ' '.join(page_texts).lower()
    
    markers = {
        'license_match': False,
        'phone_match': False,
        'city_ca_match': False,
    }
    
    # Check for CSLB license number (exact match)
    if license_no and license_no.lower() in combined_text:
        markers['license_match'] = True
    
    # Check for business phone (exact match, multiple formats)
    if business_phone:
        # Normalize phone: remove all non-digits
        phone_digits = re.sub(r'\D', '', business_phone)
        if len(phone_digits) >= 10:
            # Check various formats
            formats = [
                phone_digits[-10:],  # Last 10 digits
                f"{phone_digits[-10:-7]}-{phone_digits[-7:-4]}-{phone_digits[-4:]}",
                f"({phone_digits[-10:-7]}) {phone_digits[-7:-4]}-{phone_digits[-4:]}",
                f"{phone_digits[-10:-7]}.{phone_digits[-7:-4]}.{phone_digits[-4:]}",
            ]
            for fmt in formats:
                if fmt in combined_text:
                    markers['phone_match'] = True
                    break
    
    # Check for city + explicit "California" or "CA"
    if city:
        city_lower = city.lower()
        if city_lower in combined_text:
            # Look for explicit California markers nearby (within 50 chars)
            city_positions = [m.start() for m in re.finditer(re.escape(city_lower), combined_text)]
            for pos in city_positions:
                context = combined_text[max(0, pos-50):pos+50]
                if 'california' in context or ' ca ' in context or ',ca' in context:
                    markers['city_ca_match'] = True
                    break
    
    return markers


def call_treg_jev(
    domain: str,
    page_texts: List[str],
    treg_api_key: str,
) -> Tuple[Optional[Dict], float]:
    """Call Treg Jev classifier for contractor/california/identity probabilities
    
    Returns: (probabilities_dict or None, actual_cost_usd)
    """
    combined_text = ' '.join(page_texts)[:10000]  # Limit to 10KB for API
    
    url = f"{TREG_API_URL}/call/{JEV_ACTOR_ID}"
    
    payload = {
        'input': {
            'domain': domain,
            'text': combined_text,
        }
    }
    
    headers = {
        'Authorization': f'Bearer {treg_api_key}',
        'Content-Type': 'application/json',
    }
    
    try:
        req = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        # Extract actual cost from Treg response metadata
        actual_cost = 0.0
        if 'metadata' in result and 'cost' in result['metadata']:
            actual_cost = float(result['metadata']['cost'])
        elif 'cost' in result:
            actual_cost = float(result['cost'])
        else:
            # Fallback to typical cost if not provided
            actual_cost = JEV_TYPICAL_COST
        
        # Extract probabilities from result
        if 'output' in result and isinstance(result['output'], dict):
            output = result['output']
            probs = {
                'contractor': output.get('contractor', 0.0),
                'california': output.get('california', 0.0),
                'identity': output.get('identity', 0.0),
            }
            return probs, actual_cost
        
        return None, actual_cost
    
    except Exception as e:
        print(f"  Treg Jev error for {domain}: {e}")
        return None, 0.0


def verify_candidate(
    candidate: Dict,
    company: Dict,
    treg_api_key: str,
    dry_run: bool = False,
) -> Tuple[str, str, Optional[Dict], float]:
    """Verify a domain candidate with web scraping and Jev classification
    
    Returns: (status, reason, jev_result, actual_cost)
      status: 'confirmed', 'rejected', or 'error'
      reason: Human-readable explanation
      jev_result: Jev probabilities dict or None
      actual_cost: Actual settled cost in USD
    """
    domain = candidate['candidate_domain']
    license_no = company.get('license_no', '')
    business_phone = company.get('business_phone', '')
    city = company.get('city', '')
    
    # Fetch homepage
    homepage_text = fetch_webpage_content(domain)
    if not homepage_text:
        return 'jev_rejected', 'homepage_fetch_failed', None, 0.0
    
    page_texts = [homepage_text]
    
    # Fetch one contact/about page
    contact_path = find_contact_about_path(domain)
    if contact_path:
        contact_text = fetch_webpage_content(domain, contact_path)
        if contact_text:
            page_texts.append(contact_text)
    
    # Check for identity markers
    markers = check_identity_markers(page_texts, license_no, business_phone, city)
    
    # Must have at least one identity marker
    if not any(markers.values()):
        return 'jev_rejected', 'no_identity_markers', None, 0.0
    
    # Call Jev classifier (this costs money!)
    if dry_run:
        # In dry run, stop here and report what would happen
        marker_type = 'license' if markers['license_match'] else \
                      'phone' if markers['phone_match'] else \
                      'city_ca' if markers['city_ca_match'] else 'unknown'
        print(f"  [DRY RUN] Would call Jev with {marker_type} marker (typical cost: ~${JEV_TYPICAL_COST:.5f})")
        return 'dry_run_pending', f'would_verify_{marker_type}_marker', None, 0.0
    else:
        jev_result, actual_cost = call_treg_jev(domain, page_texts, treg_api_key)
        if not jev_result:
            return 'error', 'jev_call_failed', None, actual_cost
    
    # Check against thresholds based on which marker(s) matched
    if markers['license_match']:
        thresholds = VERIFICATION_THRESHOLDS['license_match']
        if (jev_result['contractor'] >= thresholds['contractor'] and
            jev_result['california'] >= thresholds['california'] and
            jev_result['identity'] >= thresholds['identity']):
            return 'jev_confirmed', 'license_match+jev', jev_result, actual_cost
        else:
            return 'jev_rejected', f"license_match_but_jev_below_threshold", jev_result, actual_cost
    
    elif markers['phone_match']:
        thresholds = VERIFICATION_THRESHOLDS['phone_match']
        if (jev_result['contractor'] >= thresholds['contractor'] and
            jev_result['california'] >= thresholds['california'] and
            jev_result['identity'] >= thresholds['identity']):
            return 'jev_confirmed', 'phone_match+jev', jev_result, actual_cost
        else:
            return 'jev_rejected', f"phone_match_but_jev_below_threshold", jev_result, actual_cost
    
    elif markers['city_ca_match']:
        thresholds = VERIFICATION_THRESHOLDS['city_ca_match']
        if (jev_result['contractor'] >= thresholds['contractor'] and
            jev_result['california'] >= thresholds['california'] and
            jev_result['identity'] >= thresholds['identity']):
            return 'jev_confirmed', 'city_ca_match+jev', jev_result, actual_cost
        else:
            return 'jev_rejected', f"city_ca_but_jev_below_threshold", jev_result, actual_cost
    
    return 'jev_rejected', 'no_matching_criteria', jev_result, actual_cost


def discover_candidates(
    supabase: Client,
    limit: Optional[int] = None,
    dry_run: bool = False,
    refresh: bool = False,
    treg_api_key: Optional[str] = None,
) -> Dict:
    """Phase 1: Discover domain candidates (free)
    
    Returns: Statistics dictionary with counts
    """
    stats = {
        'companies_processed': 0,
        'companies_with_new_candidates': 0,
        'total_new_candidates': 0,
        'clearbit_calls': 0,
        'hunter_calls': 0,
        'errors': 0,
    }
    
    # Initialize rate limiters
    clearbit_limiter = RateLimiter(CLEARBIT_RPM)
    hunter_limiter = RateLimiter(HUNTER_RPM)
    
    print("\n=== CSLB Domain Candidate Discovery (Free) ===")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Limit: {limit if limit else 'None (process all CLEAR + 90-day)'}")
    print(f"Refresh: {'Yes (reprocess companies with candidates)' if refresh else 'No (skip companies with candidates)'}")
    print(f"Hunter: {'SKIPPED (dry-run)' if dry_run else 'Treg free hunter.x.domain-finder'}")
    print()
    
    # Build query: CLEAR status + 90-day window + no domain
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    ninety_days_out = today + timedelta(days=90)
    
    print("Fetching CLEAR companies in 90-day window without domains...")
    
    # Paginate to get exactly N eligible companies
    companies = []
    page_size = 1000
    offset = 0
    target_count = limit if limit else 999999
    
    while len(companies) < target_count:
        # Fetch a batch
        query = supabase.table('cslb_companies').select(
            'license_no, business_name, city, state'
        ).eq('primary_status', 'CLEAR') \
         .gte('expiration_date_iso', today.isoformat()) \
         .lte('expiration_date_iso', ninety_days_out.isoformat()) \
         .is_('company_domain', 'null') \
         .order('license_no') \
         .range(offset, offset + page_size - 1)
        
        response = query.execute()
        batch = response.data
        
        if not batch:
            break  # No more companies
        
        # Filter out companies that already have candidates (unless refresh mode)
        if not refresh:
            license_nos = [c['license_no'] for c in batch]
            existing_license_nos = set()
            
            # Chunk the lookup to avoid URL length issues
            chunk_size = 100
            for i in range(0, len(license_nos), chunk_size):
                chunk = license_nos[i:i + chunk_size]
                chunk_response = supabase.table('codicen_domain_candidates').select('license_no') \
                    .in_('license_no', chunk).execute()
                existing_license_nos.update(row['license_no'] for row in chunk_response.data)
            
            eligible = [c for c in batch if c['license_no'] not in existing_license_nos]
        else:
            eligible = batch
        
        companies.extend(eligible)
        offset += page_size
        
        # Stop if we have enough
        if len(companies) >= target_count:
            companies = companies[:target_count]
            break
        
        # Stop if we got fewer than page_size (last page)
        if len(batch) < page_size:
            break
    
    print(f"Processing {len(companies)} eligible companies\n")
    
    # Track all candidates for bulk insert
    all_candidates = []
    
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
        
        # Query Hunter (skip in dry-run to avoid spending credits)
        if not dry_run:
            try:
                hunter_results = query_treg_hunter(
                    business_name, city, state, treg_api_key or '', hunter_limiter
                )
                stats['hunter_calls'] += 1
                
                for result in hunter_results:
                    candidates.append({
                        'source': 'hunter',
                        'domain': result['domain'],
                        'name': result['name'],
                    })
            except Exception as e:
                print(f"  Error querying Treg Hunter for {license_no}: {e}")
                stats['errors'] += 1
        
        # Process candidates - save ALL to codicen_domain_candidates
        if candidates:
            stats['companies_with_new_candidates'] += 1
            
            for candidate in candidates:
                # Calculate ranking score (similarity + .com bonus)
                ranking_score = calculate_ranking_score(
                    business_name,
                    candidate['name'],
                    candidate['domain']
                )
                
                # Calculate pure name similarity (no bonus) for storage
                name_similarity = calculate_name_similarity(business_name, candidate['name'])
                
                # Save ALL candidates to codicen_domain_candidates
                all_candidates.append({
                    'license_no': license_no,
                    'company_name': business_name,
                    'city': city,
                    'principal': None,
                    'candidate_domain': candidate['domain'],
                    'source': candidate['source'],
                    'candidate_name': candidate['name'],
                    'name_match_score': name_similarity,  # Store pure similarity, not ranking score
                    'verification_status': 'pending',
                    'verification_evidence': {},
                })
                
                stats['total_new_candidates'] += 1
        
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
    
    return stats


def extract_domain_tokens(domain: str) -> List[str]:
    """Extract tokens from domain for similarity matching
    
    Examples:
        'martinsheetmetal.com' → ['martinsheetmetal']
        'jazz-blues.com' → ['jazz', 'blues']
        'abc-roofing-inc.net' → ['abc', 'roofing', 'inc']
    """
    # Remove TLD
    domain_lower = domain.lower()
    for tld in ['.com', '.net', '.org', '.us', '.edu', '.gov', '.co', '.io', '.biz', '.info']:
        if domain_lower.endswith(tld):
            domain_lower = domain_lower[:-len(tld)]
            break
    
    # Remove www prefix
    if domain_lower.startswith('www.'):
        domain_lower = domain_lower[4:]
    
    # Split on hyphens, underscores, dots, numbers
    parts = re.split(r'[-_.\d]+', domain_lower)
    
    # Return non-empty parts of reasonable length
    tokens = [p for p in parts if len(p) >= 2]
    
    return tokens


def calculate_domain_token_similarity(company_name: str, domain: str) -> float:
    """Calculate similarity between company name tokens and domain tokens
    
    Returns: score from 0.0 to 1.0 based on token overlap
    """
    # Normalize company name to tokens
    company_normalized = normalize_business_name(company_name).lower()
    company_tokens = set(re.findall(r'\b\w{2,}\b', company_normalized))
    
    # Extract domain tokens
    domain_tokens = set(extract_domain_tokens(domain))
    
    if not company_tokens or not domain_tokens:
        return 0.0
    
    # Calculate Jaccard similarity (intersection over union)
    intersection = company_tokens & domain_tokens
    union = company_tokens | domain_tokens
    
    if not union:
        return 0.0
    
    return len(intersection) / len(union)


def is_us_tld(domain: str) -> bool:
    """Check if domain has a US TLD"""
    # Prefer .com, .us, .org, .net
    # Deprioritize non-US ccTLDs like .com.do, .com.co, .co.uk
    domain_lower = domain.lower()
    
    # Non-US ccTLDs to deprioritize
    non_us_patterns = [
        '.com.do', '.com.co', '.co.uk', '.com.mx', '.com.br',
        '.com.ar', '.co.nz', '.co.za', '.com.au', '.co.in',
    ]
    
    for pattern in non_us_patterns:
        if domain_lower.endswith(pattern):
            return False
    
    # US TLDs
    us_tlds = ['.com', '.org', '.net', '.us', '.edu', '.gov']
    for tld in us_tlds:
        if domain_lower.endswith(tld):
            return True
    
    return False


def calculate_verification_rank(candidate: Dict, company: Dict) -> Tuple[float, float, str]:
    """Calculate ranking score for verification priority
    
    Returns (total_score, domain_score, source) for sorting:
    - Domain token similarity (weighted 0.6, range 0.0-0.6)
    - Candidate name similarity (weighted 0.3, range 0.0-0.3)
    - .com bonus (+0.05)
    - US TLD bonus (+0.05)
    - Total range: 0.0 to 1.0
    
    Returns tuple for deterministic tie-breaking:
    (total_score, domain_score_for_tiebreak, source_for_tiebreak)
    """
    company_name = company.get('business_name', '')
    candidate_name = candidate.get('candidate_name', '')
    domain = candidate.get('candidate_domain', '')
    source = candidate.get('source', '')
    
    # Domain token similarity (weighted higher, 60%)
    domain_similarity = calculate_domain_token_similarity(company_name, domain)
    domain_score = domain_similarity * 0.6
    
    # Candidate name similarity (weighted lower, 30%)
    name_similarity = calculate_name_similarity(company_name, candidate_name)
    name_score = name_similarity * 0.3
    
    # TLD bonuses (10% total available)
    tld_bonus = 0.0
    if domain.endswith('.com'):
        tld_bonus += 0.05
    if is_us_tld(domain):
        tld_bonus += 0.05
    
    total_score = domain_score + name_score + tld_bonus
    
    # Return tuple for deterministic sorting:
    # 1st: total score (higher better)
    # 2nd: domain score for tie-break (higher better)
    # 3rd: source for final tie-break (clearbit before hunter alphabetically)
    return (total_score, domain_similarity, source)


def verify_candidates(
    supabase: Client,
    limit: Optional[int] = None,
    max_spend_usd: float = 0.0,
    dry_run: bool = False,
    treg_api_key: Optional[str] = None,
    per_company: int = 1,
) -> Dict:
    """Phase 2: Verify pending candidates (paid)
    
    Returns: Statistics dictionary with counts
    """
    if not dry_run and not treg_api_key:
        print("Error: TREG_API_KEY required for verification (not dry run)")
        sys.exit(1)
    
    stats = {
        'candidates_processed': 0,
        'candidates_confirmed': 0,
        'candidates_rejected': 0,
        'domains_written_to_cslb': 0,
        'jev_calls': 0,
        'spend_usd': 0.0,
        'errors': 0,
    }
    
    print("\n=== CSLB Domain Verification (Paid) ===")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Max spend: ${max_spend_usd:.2f}")
    print(f"Limit: {limit if limit else 'None'}")
    print(f"Per-company cap: {per_company}")
    print(f"Jev typical cost: ~${JEV_TYPICAL_COST:.5f} per check")
    print(f"Jev reserve per call: ${JEV_RESERVE_PER_CALL:.5f} (released after settlement)")
    print()
    
    # Smart pagination: stream pages until we have enough strong candidates
    # For small --limit, this avoids loading all 78k rows
    print("Streaming pending candidates...")
    
    target_candidates = limit * 5 if limit else 999999  # Fetch 5x limit for ranking buffer
    page_size = 1000
    offset = 0
    streamed_candidates = []
    seen_licenses = set()
    
    while len(streamed_candidates) < target_candidates:
        batch_response = supabase.table('codicen_domain_candidates').select(
            'license_no, candidate_domain, candidate_name, source'
        ).eq('verification_status', 'pending') \
         .order('license_no') \
         .range(offset, offset + page_size - 1).execute()
        
        batch = batch_response.data
        if not batch:
            break
        
        # Collect unique license_nos from this batch for company lookup
        batch_licenses = {c['license_no'] for c in batch if c['license_no'] not in seen_licenses}
        seen_licenses.update(batch_licenses)
        
        # Fetch company data for new licenses in this batch (chunked)
        if batch_licenses:
            companies_batch = {}
            licenses_list = list(batch_licenses)
            chunk_size = 100
            
            for i in range(0, len(licenses_list), chunk_size):
                chunk = licenses_list[i:i + chunk_size]
                chunk_response = supabase.table('cslb_companies').select(
                    'license_no, business_name, business_phone, city, state, company_domain'
                ).in_('license_no', chunk).execute()
                
                for company in chunk_response.data:
                    companies_batch[company['license_no']] = company
            
            # Add eligible candidates from this batch
            for candidate in batch:
                company = companies_batch.get(candidate['license_no'])
                if company and not company.get('company_domain'):
                    streamed_candidates.append((candidate, company))
        
        offset += page_size
        
        if len(batch) < page_size:
            break
    
    print(f"Streamed {len(streamed_candidates)} eligible candidates (companies without domains)")
    
    if not streamed_candidates:
        print("No eligible candidates")
        return stats
    
    # Rank using domain + name similarity
    print("Ranking by domain tokens + name similarity...")
    ranked = []
    for candidate, company in streamed_candidates:
        rank_tuple = calculate_verification_rank(candidate, company)
        ranked.append((rank_tuple, candidate, company))
    
    # Sort by rank tuple (total_score desc, domain_score desc, source asc)
    ranked.sort(key=lambda x: (-x[0][0], -x[0][1], x[0][2]))
    
    # Apply per-company cap: keep at most N candidates per company
    if per_company:
        company_counts = {}
        capped_ranked = []
        for rank_tuple, candidate, company in ranked:
            license_no = candidate['license_no']
            count = company_counts.get(license_no, 0)
            if count < per_company:
                capped_ranked.append((rank_tuple, candidate, company))
                company_counts[license_no] = count + 1
        ranked = capped_ranked
    
    # Apply overall limit
    if limit:
        ranked = ranked[:limit]
    
    print(f"Processing top {len(ranked)} candidates (max spend: ${max_spend_usd:.2f})...\n")
    
    # Track confirmed companies to skip remaining candidates
    confirmed_companies = set()
    
    for idx, (rank_tuple, candidate, company) in enumerate(ranked, 1):
        license_no = candidate['license_no']
        domain = candidate['candidate_domain']
        total_score = rank_tuple[0]
        
        # Skip if this company already has a confirmed candidate
        if license_no in confirmed_companies:
            continue
        
        # Check spend limit before verification (reserve cost)
        reserved_cost = JEV_RESERVE_PER_CALL if not dry_run else 0.0
        if stats['spend_usd'] + reserved_cost > max_spend_usd:
            print(f"\nSpend limit reached: ${stats['spend_usd']:.5f} / ${max_spend_usd:.2f}")
            print(f"Processed {stats['candidates_processed']} candidates")
            break
        
        print(f"[{idx}/{len(ranked)}] Verifying {domain} for {license_no} (score: {total_score:.3f})...")
        
        # Verify candidate
        try:
            status, reason, jev_result, actual_cost = verify_candidate(
                candidate, company, treg_api_key or '', dry_run
            )
            
            stats['candidates_processed'] += 1
            
            if jev_result or status == 'dry_run_pending':
                stats['jev_calls'] += 1
                if not dry_run:
                    stats['spend_usd'] += actual_cost
            
            if status == 'jev_confirmed':
                stats['candidates_confirmed'] += 1
                print(f"  ✓ CONFIRMED: {reason}")
                
                # Mark company as confirmed (skip remaining candidates)
                confirmed_companies.add(license_no)
                
                # Update candidate status
                if not dry_run:
                    supabase.table('codicen_domain_candidates').update({
                        'verification_status': 'jev_confirmed',
                        'verification_evidence': {
                            'reason': reason,
                            'jev_scores': jev_result,
                            'verified_at': datetime.now(timezone.utc).isoformat(),
                        }
                    }).eq('license_no', license_no).eq('candidate_domain', domain).execute()
                    
                    # Update cslb_companies (only if no existing domain)
                    update_result = supabase.table('cslb_companies').update({
                        'company_domain': domain,
                        'domain_source': candidate['source'],
                        'domain_confidence': 'jev_confirmed',
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                    }).eq('license_no', license_no).is_('company_domain', 'null').execute()
                    
                    if update_result.data:
                        stats['domains_written_to_cslb'] += 1
            
            elif status == 'jev_rejected':
                stats['candidates_rejected'] += 1
                print(f"  ✗ REJECTED: {reason}")
                
                # Update candidate status
                if not dry_run:
                    supabase.table('codicen_domain_candidates').update({
                        'verification_status': 'jev_rejected',
                        'verification_evidence': {
                            'reason': reason,
                            'jev_scores': jev_result if jev_result else {},
                            'verified_at': datetime.now(timezone.utc).isoformat(),
                        }
                    }).eq('license_no', license_no).eq('candidate_domain', domain).execute()
            
            elif status == 'dry_run_pending':
                # In dry run, just report
                print(f"  [DRY RUN] {reason}")
            
            else:  # error
                stats['errors'] += 1
                print(f"  ! ERROR: {reason}")
        
        except Exception as e:
            print(f"  ! Exception: {e}")
            stats['errors'] += 1
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='CSLB domain enrichment: discover candidates (free) or verify them (paid)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover candidates (free, default mode)
  python scripts/enrich_cslb_domains.py --limit 10 --dry-run
  python scripts/enrich_cslb_domains.py --limit 100
  
  # Verify candidates (paid, requires --max-spend-usd)
  python scripts/enrich_cslb_domains.py --verify --max-spend-usd 5.00 --limit 50
  python scripts/enrich_cslb_domains.py --verify --max-spend-usd 50.00 --dry-run
        """
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Run verification step (paid) instead of discovery (free)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of items to process',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without writing to database or making paid API calls',
    )
    parser.add_argument(
        '--refresh',
        action='store_true',
        help='Reprocess companies that already have candidates (discovery only)',
    )
    parser.add_argument(
        '--max-spend-usd',
        type=float,
        help='Max spend in USD (required for --verify, not dry run)',
    )
    parser.add_argument(
        '--per-company',
        type=int,
        default=1,
        help='Max candidates to check per company per pass (default: 1)',
    )
    parser.add_argument(
        '--supabase-url',
        default=os.environ.get('SUPABASE_URL', DEFAULT_SUPABASE_URL),
        help='Supabase project URL',
    )
    parser.add_argument(
        '--supabase-key',
        default=os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY'),
        help='Supabase service role key (or set SUPABASE_KEY/SUPABASE_SERVICE_ROLE_KEY)',
    )
    parser.add_argument(
        '--treg-api-key',
        default=os.environ.get('TREG_API_KEY') or os.environ.get('TREG_TOKEN'),
        help='Treg API key (or set TREG_API_KEY/TREG_TOKEN)',
    )
    
    args = parser.parse_args()
    
    # Validate required arguments
    if not args.supabase_key:
        print("Error: Supabase key required. Set SUPABASE_KEY env var or use --supabase-key")
        sys.exit(1)
    
    if args.verify and not args.dry_run and not args.max_spend_usd:
        print("Error: --max-spend-usd required for --verify (unless --dry-run)")
        sys.exit(1)
    
    if args.verify and not args.dry_run and not args.treg_api_key:
        print("Error: Treg API key required for --verify. Set TREG_API_KEY env var or use --treg-api-key")
        sys.exit(1)
    
    # Create Supabase client
    try:
        supabase = create_client(args.supabase_url, args.supabase_key)
    except Exception as e:
        print(f"Error creating Supabase client: {e}")
        sys.exit(1)
    
    # Run appropriate workflow
    start_time = time.time()
    
    try:
        if args.verify:
            # Phase 2: Verification
            stats = verify_candidates(
                supabase=supabase,
                limit=args.limit,
                max_spend_usd=args.max_spend_usd or 0.0,
                dry_run=args.dry_run,
                treg_api_key=args.treg_api_key,
                per_company=args.per_company,
            )
        else:
            # Phase 1: Discovery
            stats = discover_candidates(
                supabase=supabase,
                limit=args.limit,
                dry_run=args.dry_run,
                refresh=args.refresh,
                treg_api_key=args.treg_api_key,
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
    print("\n" + "="*70)
    print("FINAL REPORT")
    print("="*70)
    
    if args.verify:
        # Verification report
        print(f"Candidates processed:             {stats['candidates_processed']:,}")
        print(f"Candidates confirmed:             {stats['candidates_confirmed']:,}")
        print(f"Candidates rejected:              {stats['candidates_rejected']:,}")
        print(f"Domains written to cslb_companies: {stats['domains_written_to_cslb']:,}")
        print()
        print(f"Jev API calls:                    {stats['jev_calls']:,}")
        print(f"Spend (USD):                      ${stats['spend_usd']:.2f}")
        print(f"Errors:                           {stats['errors']:,}")
    else:
        # Discovery report
        print(f"Companies processed:              {stats['companies_processed']:,}")
        print(f"Companies with new candidates:    {stats['companies_with_new_candidates']:,}")
        print(f"Total new candidate pairs:        {stats['total_new_candidates']:,}")
        print()
        print(f"Clearbit API calls:               {stats['clearbit_calls']:,}")
        print(f"Hunter API calls:                 {stats['hunter_calls']:,}")
        print(f"Errors:                           {stats['errors']:,}")
    
    print()
    print(f"Elapsed time:                     {elapsed_time:.1f}s")
    print("="*70)
    
    if args.dry_run:
        print("\nDRY RUN - No data was written to the database")
        if args.verify:
            print("DRY RUN - No paid API calls were made")


if __name__ == '__main__':
    main()
