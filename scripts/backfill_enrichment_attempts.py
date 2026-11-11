#!/usr/bin/env python3
"""Backfill codicen_enrichment_attempts from existing Supabase state and outcome files

Backfills from:
1. codicen_domain_candidates (Jev attempts: jev_confirmed, jev_rejected statuses)
2. cslb_companies.company_domain (confirmed domains)
3. Attached outcome JSON lines files (window pass, search pilot)
4. pipeline_leads batches codicen-window-1111 and codicen-search-pilot-1111 (email attempts)

Usage:
    python3 scripts/backfill_enrichment_attempts.py [--dry-run] [--outcome-files path/to/*.jsonl]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict

try:
    from supabase import create_client, Client
except ImportError:
    print("Error: supabase package not installed. Run: pip install supabase")
    sys.exit(1)


DEFAULT_SUPABASE_URL = 'https://npkdhahdvilcctjwzdlf.supabase.co'

# Cost constants (in microdollars)
COST_JEV = 80  # ~$0.00008
COST_SEARCH = 470  # ~$0.00047
COST_CRAWL = 150  # ~$0.00015
COST_MV = 1100  # ~$0.0011
COST_BB = 4000  # ~$0.004


def log(msg):
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f"[{ts}] {msg}", flush=True)


def backfill_from_domain_candidates(supabase: Client, dry_run: bool) -> int:
    """Backfill Jev attempts from codicen_domain_candidates"""
    log("Backfilling Jev attempts from codicen_domain_candidates...")
    
    # Fetch all candidates with jev_confirmed or jev_rejected status
    count = 0
    page_size = 1000
    offset = 0
    attempts = []
    
    while True:
        response = supabase.table('codicen_domain_candidates').select(
            'license_no, candidate_domain, verification_status, verification_evidence, created_at'
        ).in_('verification_status', ['jev_confirmed', 'jev_rejected']) \
         .range(offset, offset + page_size - 1).execute()
        
        batch = response.data
        if not batch:
            break
        
        for row in batch:
            license_no = row['license_no']
            domain = row['candidate_domain']
            status = row['verification_status']
            evidence = row.get('verification_evidence') or {}
            attempted_at = row.get('created_at') or datetime.now(timezone.utc).isoformat()
            
            outcome = 'confirmed' if status == 'jev_confirmed' else 'rejected'
            
            attempts.append({
                'license_no': license_no,
                'method': 'jev',
                'identifier': domain,
                'outcome': outcome,
                'cost_micro': COST_JEV,
                'attempted_at': attempted_at,
                'metadata': {
                    'source': 'backfill_domain_candidates',
                    'evidence': evidence,
                },
            })
            count += 1
        
        offset += page_size
        if len(batch) < page_size:
            break
    
    if not dry_run and attempts:
        # Bulk insert with conflict handling
        log(f"  Inserting {len(attempts)} Jev attempts...")
        chunk_size = 500
        for i in range(0, len(attempts), chunk_size):
            chunk = attempts[i:i + chunk_size]
            # Use upsert to handle duplicates gracefully
            supabase.table('codicen_enrichment_attempts').upsert(
                chunk,
                on_conflict='license_no,method,identifier,attempted_at'
            ).execute()
    
    log(f"  Found {count} Jev attempts from domain candidates")
    return count


def backfill_from_confirmed_domains(supabase: Client, dry_run: bool) -> int:
    """Backfill confirmed domain attempts from cslb_companies"""
    log("Backfilling confirmed domains from cslb_companies...")
    
    count = 0
    page_size = 1000
    offset = 0
    attempts = []
    
    while True:
        response = supabase.table('cslb_companies').select(
            'license_no, company_domain, domain_source, domain_confidence, updated_at'
        ).not_.is_('company_domain', 'null') \
         .range(offset, offset + page_size - 1).execute()
        
        batch = response.data
        if not batch:
            break
        
        for row in batch:
            license_no = row['license_no']
            domain = row['company_domain']
            source = row.get('domain_source', 'unknown')
            confidence = row.get('domain_confidence', 'unknown')
            attempted_at = row.get('updated_at') or datetime.now(timezone.utc).isoformat()
            
            # Only backfill if it looks like a Jev confirmation
            if confidence in ['jev_confirmed', 'high', 'confirmed']:
                attempts.append({
                    'license_no': license_no,
                    'method': 'jev',
                    'identifier': domain,
                    'outcome': 'confirmed',
                    'cost_micro': COST_JEV,
                    'attempted_at': attempted_at,
                    'metadata': {
                        'source': 'backfill_cslb_companies',
                        'domain_source': source,
                        'confidence': confidence,
                    },
                })
                count += 1
        
        offset += page_size
        if len(batch) < page_size:
            break
    
    if not dry_run and attempts:
        log(f"  Inserting {len(attempts)} confirmed domain attempts...")
        chunk_size = 500
        for i in range(0, len(attempts), chunk_size):
            chunk = attempts[i:i + chunk_size]
            supabase.table('codicen_enrichment_attempts').upsert(
                chunk,
                on_conflict='license_no,method,identifier,attempted_at'
            ).execute()
    
    log(f"  Found {count} confirmed domains from cslb_companies")
    return count


def backfill_from_outcome_files(supabase: Client, outcome_files: List[Path], dry_run: bool) -> Dict[str, int]:
    """Backfill from attached outcome JSONL files"""
    log(f"Backfilling from {len(outcome_files)} outcome files...")
    
    counts = {'jev': 0, 'crawl': 0, 'email': 0}
    attempts = []
    default_timestamp = datetime.now(timezone.utc).isoformat()
    
    for path in outcome_files:
        if not path.exists():
            log(f"  Warning: {path} not found, skipping")
            continue
        
        log(f"  Reading {path.name}...")
        with open(path) as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    log(f"    Warning: line {line_no} invalid JSON: {e}")
                    continue
                
                license_no = record.get('license_no')
                domain = record.get('domain')
                status = record.get('status')
                
                if not license_no:
                    continue
                
                # Jev attempts
                if domain and status in ['jev_confirmed', 'jev_rejected', 'confirmed', 'rejected']:
                    outcome_map = {
                        'jev_confirmed': 'confirmed',
                        'jev_rejected': 'rejected',
                        'confirmed': 'confirmed',
                        'rejected': 'rejected',
                    }
                    attempts.append({
                        'license_no': license_no,
                        'method': 'jev',
                        'identifier': domain,
                        'outcome': outcome_map.get(status, 'unknown'),
                        'cost_micro': COST_JEV if status in ['jev_confirmed', 'confirmed'] or record.get('jev_result') else 0,
                        'attempted_at': record.get('attempted_at') or default_timestamp,
                        'metadata': {
                            'source': f'backfill_{path.stem}',
                            'status': status,
                            'reason': record.get('reason'),
                            'markers': record.get('markers'),
                        },
                    })
                    counts['jev'] += 1
                
                # Crawl attempts (if crawled flag or emails_from_crawl)
                if domain and (record.get('crawled') or record.get('crawl_urls')):
                    attempts.append({
                        'license_no': license_no,
                        'method': 'crawl',
                        'identifier': domain,
                        'outcome': 'completed' if record.get('emails_found') else 'no_email',
                        'cost_micro': COST_CRAWL if record.get('crawl_cost_micro') is None else record.get('crawl_cost_micro', 0),
                        'attempted_at': record.get('crawl_at') or record.get('attempted_at') or default_timestamp,
                        'metadata': {
                            'source': f'backfill_{path.stem}',
                            'crawl_urls': record.get('crawl_urls'),
                            'emails_found': record.get('emails_found'),
                        },
                    })
                    counts['crawl'] += 1
    
    if not dry_run and attempts:
        log(f"  Inserting {len(attempts)} attempts from outcome files...")
        chunk_size = 500
        for i in range(0, len(attempts), chunk_size):
            chunk = attempts[i:i + chunk_size]
            supabase.table('codicen_enrichment_attempts').upsert(
                chunk,
                on_conflict='license_no,method,identifier,attempted_at'
            ).execute()
    
    log(f"  Found {counts['jev']} Jev, {counts['crawl']} crawl attempts from outcome files")
    return counts


def backfill_from_pipeline_leads(supabase: Client, batch_ids: List[str], dry_run: bool) -> int:
    """Backfill email verification attempts from pipeline_leads"""
    log(f"Backfilling email attempts from pipeline_leads batches: {', '.join(batch_ids)}...")
    
    count = 0
    page_size = 1000
    offset = 0
    attempts = []
    
    for batch_id in batch_ids:
        offset = 0
        while True:
            # pipeline_leads may not have license_no for all entries
            response = supabase.table('pipeline_leads').select(
                'email, mv_status, created_at, raw'
            ).eq('batch_id', batch_id) \
             .range(offset, offset + page_size - 1).execute()
            
            batch = response.data
            if not batch:
                break
            
            for row in batch:
                email = row.get('email')
                status = row.get('mv_status') or row.get('status')
                created_at = row.get('created_at') or datetime.now(timezone.utc).isoformat()
                raw = row.get('raw') or {}
                
                # Try to extract license_no from raw metadata if available
                license_no = raw.get('license_no') or 'unknown'
                
                if not email:
                    continue
                
                # Map status to outcome
                outcome_map = {
                    'valid': 'valid',
                    'ok': 'valid',
                    'bounceban_deliverable': 'bounceban_deliverable',
                    'invalid': 'invalid',
                    'catch_all': 'catch_all',
                    'unknown': 'unknown',
                    'risky': 'risky',
                    'undeliverable': 'undeliverable',
                }
                outcome = outcome_map.get(status, status or 'unknown')
                
                # Estimate cost based on status
                cost = 0
                if status in ['valid', 'ok', 'invalid', 'catch_all', 'unknown']:
                    cost = COST_MV
                if status in ['bounceban_deliverable', 'risky', 'undeliverable']:
                    cost = COST_BB
                
                attempts.append({
                    'license_no': license_no,
                    'method': 'email_verify',
                    'identifier': email.lower(),
                    'outcome': outcome,
                    'cost_micro': cost,
                    'attempted_at': created_at,
                    'metadata': {
                        'source': f'backfill_pipeline_leads_{batch_id}',
                        'batch_id': batch_id,
                        'raw': raw,
                    },
                })
                count += 1
            
            offset += page_size
            if len(batch) < page_size:
                break
    
    if not dry_run and attempts:
        log(f"  Inserting {len(attempts)} email attempts...")
        chunk_size = 500
        for i in range(0, len(attempts), chunk_size):
            chunk = attempts[i:i + chunk_size]
            supabase.table('codicen_enrichment_attempts').upsert(
                chunk,
                on_conflict='license_no,method,identifier,attempted_at'
            ).execute()
    
    log(f"  Found {count} email attempts from pipeline_leads")
    return count


def backfill_from_searches_file(supabase: Client, searches_file: Path, dry_run: bool) -> int:
    """Backfill web_search attempts from searches.jsonl"""
    if not searches_file.exists():
        log(f"Searches file {searches_file} not found, skipping")
        return 0
    
    log(f"Backfilling web_search attempts from {searches_file.name}...")
    
    count = 0
    attempts = []
    default_timestamp = datetime.now(timezone.utc).isoformat()
    
    with open(searches_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            license_no = record.get('license_no')
            if not license_no:
                continue
            
            attempts.append({
                'license_no': license_no,
                'method': 'web_search',
                'identifier': None,
                'outcome': 'completed',
                'cost_micro': COST_SEARCH,
                'attempted_at': record.get('at') or default_timestamp,
                'metadata': {
                    'source': 'backfill_searches',
                    'query': record.get('query'),
                    'n_results': record.get('n_results'),
                    'n_emails': record.get('n_emails'),
                    'hosts': record.get('hosts', [])[:5],  # First 5 hosts
                },
            })
            count += 1
    
    if not dry_run and attempts:
        log(f"  Inserting {len(attempts)} web_search attempts...")
        chunk_size = 500
        for i in range(0, len(attempts), chunk_size):
            chunk = attempts[i:i + chunk_size]
            supabase.table('codicen_enrichment_attempts').upsert(
                chunk,
                on_conflict='license_no,method,identifier,attempted_at'
            ).execute()
    
    log(f"  Found {count} web_search attempts from searches file")
    return count


def backfill_crawl_from_reports(supabase: Client, report_files: List[Path], dry_run: bool) -> int:
    """Backfill crawl attempts from FINAL_REPORT files"""
    log(f"Backfilling crawl attempts from {len(report_files)} report files...")
    
    # Read the reports to get crawl counts
    total_crawled = 0
    for report_file in report_files:
        if not report_file.exists():
            continue
        
        with open(report_file) as f:
            report = json.load(f)
        
        crawl_count = report.get('stats', {}).get('crawl4ai_domains', 0)
        log(f"  {report_file.name}: {crawl_count} crawl attempts")
        total_crawled += crawl_count
    
    # Note: We can't reconstruct individual crawl attempts without the detailed logs
    # The outcome files don't have crawl information
    # This would require access to the actual crawl logs from the prototypes
    log(f"  Note: Crawl attempts need detailed logs to backfill accurately")
    log(f"  Total crawl4ai_domains from reports: {total_crawled}")
    log(f"  Skipping crawl backfill (would need crawl-specific outcome files)")
    
    return 0


def main():
    parser = argparse.ArgumentParser(description='Backfill codicen_enrichment_attempts table')
    parser.add_argument('--dry-run', action='store_true', help='Print counts without inserting')
    parser.add_argument('--outcome-files', nargs='+', help='Paths to outcome JSONL files')
    parser.add_argument('--searches-file', help='Path to searches.jsonl file')
    parser.add_argument('--report-files', nargs='+', help='Paths to FINAL_REPORT.json files')
    parser.add_argument('--supabase-url', default=os.environ.get('SUPABASE_URL', DEFAULT_SUPABASE_URL))
    parser.add_argument('--supabase-key', default=os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY'))
    
    args = parser.parse_args()
    
    if not args.supabase_key:
        print("Error: Supabase key required. Set SUPABASE_KEY env var or use --supabase-key")
        sys.exit(1)
    
    log(f"Backfill starting ({'DRY RUN' if args.dry_run else 'LIVE'})")
    log(f"Supabase URL: {args.supabase_url}")
    
    supabase = create_client(args.supabase_url, args.supabase_key)
    
    total_counts = {
        'jev_from_candidates': 0,
        'jev_from_confirmed': 0,
        'jev_from_outcomes': 0,
        'crawl_from_outcomes': 0,
        'crawl_from_reports': 0,
        'web_search_from_searches': 0,
        'email_from_pipeline': 0,
    }
    
    # 1. Backfill from codicen_domain_candidates
    total_counts['jev_from_candidates'] = backfill_from_domain_candidates(supabase, args.dry_run)
    
    # 2. Backfill from cslb_companies confirmed domains
    total_counts['jev_from_confirmed'] = backfill_from_confirmed_domains(supabase, args.dry_run)
    
    # 3. Backfill from outcome files
    if args.outcome_files:
        outcome_paths = [Path(p) for p in args.outcome_files]
        outcome_counts = backfill_from_outcome_files(supabase, outcome_paths, args.dry_run)
        total_counts['jev_from_outcomes'] = outcome_counts.get('jev', 0)
        total_counts['crawl_from_outcomes'] = outcome_counts.get('crawl', 0)
    
    # 4. Backfill from searches.jsonl
    if args.searches_file:
        searches_path = Path(args.searches_file)
        total_counts['web_search_from_searches'] = backfill_from_searches_file(supabase, searches_path, args.dry_run)
    
    # 5. Backfill crawl from reports
    if args.report_files:
        report_paths = [Path(p) for p in args.report_files]
        total_counts['crawl_from_reports'] = backfill_crawl_from_reports(supabase, report_paths, args.dry_run)
    
    # 6. Backfill from pipeline_leads batches
    batch_ids = ['codicen-window-1111', 'codicen-search-pilot-1111']
    total_counts['email_from_pipeline'] = backfill_from_pipeline_leads(supabase, batch_ids, args.dry_run)
    
    log("\n" + "="*70)
    log("BACKFILL SUMMARY")
    log("="*70)
    log(f"Jev attempts from candidates:        {total_counts['jev_from_candidates']:,}")
    log(f"Jev attempts from confirmed domains: {total_counts['jev_from_confirmed']:,}")
    log(f"Jev attempts from outcome files:     {total_counts['jev_from_outcomes']:,}")
    log(f"Crawl attempts from outcome files:   {total_counts['crawl_from_outcomes']:,}")
    log(f"Web search from searches.jsonl:      {total_counts['web_search_from_searches']:,}")
    log(f"Email attempts from pipeline_leads:  {total_counts['email_from_pipeline']:,}")
    log(f"\nTotal attempts: {sum(total_counts.values()):,}")
    
    if args.dry_run:
        log("\nDRY RUN - No data was written")
    else:
        log("\nBackfill complete")
        
        # Report actual counts by method
        log("\n" + "="*70)
        log("ACTUAL COUNTS BY METHOD (from database)")
        log("="*70)
        
        for method in ['candidate_fetch', 'jev', 'web_search', 'crawl', 'email_verify']:
            count_response = supabase.table('codicen_enrichment_attempts').select(
                'id', count='exact'
            ).eq('method', method).execute()
            count = count_response.count
            log(f"{method:20s}: {count:,}")
        
        # Get total
        total_response = supabase.table('codicen_enrichment_attempts').select(
            'id', count='exact'
        ).execute()
        log(f"{'TOTAL':20s}: {total_response.count:,}")
        
        # Get eligible for web search count
        log("\n" + "="*70)
        log("ELIGIBLE FOR WEB SEARCH")
        log("="*70)
        
        # Companies in 90-day window with no domain and not yet web-searched
        eligible_response = supabase.table('cslb_companies').select(
            'license_no', count='exact'
        ).is_('company_domain', 'null') \
         .eq('primary_status', 'CLEAR') \
         .gte('expiration_date_iso', datetime.now().date().isoformat()) \
         .lte('expiration_date_iso', (datetime.now().date() + timedelta(days=90)).isoformat()) \
         .execute()
        
        total_in_window = eligible_response.count
        
        # Get web-searched companies
        searched_response = supabase.table('codicen_enrichment_attempts').select(
            'license_no'
        ).eq('method', 'web_search').execute()
        
        searched_licenses = {row['license_no'] for row in searched_response.data}
        
        log(f"Total in 90-day window (no domain):  {total_in_window:,}")
        log(f"Already web-searched:                {len(searched_licenses):,}")
        log(f"ELIGIBLE for web search:             {total_in_window - len(searched_licenses):,}")


if __name__ == '__main__':
    main()
