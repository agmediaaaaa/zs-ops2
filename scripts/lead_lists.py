#!/usr/bin/env python3
"""Lead list management CLI for zs-ops2 enrichment pipeline.

Commands:
  create      Create a new lead list from scraped/imported data
  list        List all lead lists with status
  show        Show details for a specific list
  enrich      Enrich a specific list (with cost estimate and confirmation)
  export      Export a list to CSV or Google Sheets
  stats       Show enrichment statistics

Examples:
  # Create a list from Icypeas scrape
  ./lead_lists.py create --client "MARS" --name "Midwest CNC Oct 18" \\
      --source icypeas --linkedin-urls urls.txt

  # Show estimated cost for enrichment
  ./lead_lists.py enrich <list_id> --estimate

  # Enrich with cost cap and confirmation
  ./lead_lists.py enrich <list_id> --confirm --cap 50.00

  # Export to CSV
  ./lead_lists.py export <list_id> --format csv --output leads.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

BASE = "https://treg.to"
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
)


def supabase_key() -> str:
    """Get Supabase service role key from environment."""
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    raise SystemExit("Error: SUPABASE_SERVICE_ROLE_KEY not set")


def sb_headers(prefer: str = "return=representation") -> dict[str, str]:
    """Build Supabase API headers."""
    key = supabase_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": prefer,
    }


def sb_request(
    method: str, 
    path: str, 
    body: Any | None = None,
    query: dict | None = None,
    prefer: str = "return=representation",
) -> Any:
    """Make a Supabase REST API request."""
    # URL-encode table name (e.g., "Lead Database" -> "Lead%20Database")
    encoded_path = urllib.parse.quote(path.lstrip('/'), safe='/?&=')
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{encoded_path}"
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url, 
        data=data, 
        headers=sb_headers(prefer=prefer), 
        method=method
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"Supabase {method} {path} failed ({e.code}): {err[:500]}")


def normalize_linkedin(url: str) -> str:
    """Normalize LinkedIn URL for deduplication."""
    u = url.strip().lower().rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    if "/in/" in u:
        return u.split("?")[0]
    return u


def domain_of(website: str) -> str:
    """Extract domain from website URL."""
    d = (website or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


# ============================================================================
# CREATE COMMAND
# ============================================================================

def cmd_create(args: argparse.Namespace) -> None:
    """Create a new lead list from scraped/imported data."""
    # Create the list record
    list_data = {
        "client": args.client,
        "list_name": args.name,
        "source": args.source,
        "status": "scraped",
        "estimated_cost_usd": args.estimated_cost if args.estimated_cost else None,
        "cost_cap_usd": args.cost_cap if args.cost_cap else None,
        "metadata": json.loads(args.metadata) if args.metadata else {},
    }
    
    result = sb_request("POST", "lead_lists", list_data)
    if not result or not isinstance(result, list) or not result:
        raise RuntimeError("Failed to create lead list")
    
    list_record = result[0]
    list_id = list_record["list_id"]
    print(f"✓ Created list: {list_id}")
    print(f"  Client: {args.client}")
    print(f"  Name: {args.name}")
    print(f"  Source: {args.source}")
    
    # Load leads from input
    leads_to_add: list[dict] = []
    
    if args.linkedin_urls:
        # Read LinkedIn URLs from file
        urls_path = Path(args.linkedin_urls)
        if not urls_path.exists():
            raise SystemExit(f"Error: LinkedIn URLs file not found: {urls_path}")
        
        urls = [line.strip() for line in urls_path.read_text().splitlines() if line.strip()]
        print(f"  Loading {len(urls)} LinkedIn URLs...")
        
        # Find or create leads for each LinkedIn URL
        for i, url in enumerate(urls):
            normalized = normalize_linkedin(url)
            if not normalized:
                continue
            
            # Try to find existing lead in Lead Database (normalized LinkedIn match)
            # Use exact match on lower(trim("Linkedin")) for efficiency
            existing = sb_request(
                "GET",
                "Lead Database",
                query={
                    "Linkedin": f"ilike.{normalized}",  # Exact match, not wildcard
                    "limit": "1",
                    "select": 'id,"Linkedin","Email","First Name","Last Name"',
                }
            )
            
            if existing and len(existing) > 0:
                leads_to_add.append({"lead_id": existing[0]["id"], "source": "existing"})
            else:
                # Create placeholder lead (to be enriched later)
                new_lead = sb_request(
                    "POST",
                    "Lead Database",
                    {
                        "Linkedin": url if url.startswith("http") else f"https://{url}",
                    }
                )
                if new_lead and len(new_lead) > 0:
                    leads_to_add.append({"lead_id": new_lead[0]["id"], "source": "created"})
            
            if (i + 1) % 100 == 0:
                print(f"    Processed {i + 1}/{len(urls)}...")
    
    elif args.csv:
        # Import from CSV
        csv_path = Path(args.csv)
        if not csv_path.exists():
            raise SystemExit(f"Error: CSV file not found: {csv_path}")
        
        print(f"  Importing from CSV: {csv_path}")
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        print(f"    Found {len(rows)} rows...")
        
        # Collect normalized LinkedIn URLs and emails for batch lookup
        linkedin_map = {}  # normalized_url -> row_index
        email_map = {}  # lowercase_email -> row_index
        
        for i, row in enumerate(rows):
            linkedin = row.get("linkedin") or row.get("linkedin_url") or ""
            email = (row.get("email") or "").strip().lower()
            
            if linkedin:
                normalized = normalize_linkedin(linkedin)
                if normalized:
                    linkedin_map[normalized] = i
            
            if email and email not in ("", "n/a", "none", "null"):
                email_map[email] = i
        
        # Batch lookup by LinkedIn (use lower(trim("Linkedin")) for index)
        lead_id_map = {}  # row_index -> lead_id
        
        if linkedin_map:
            # Split into batches of 100 for in.(...) queries
            li_list = list(linkedin_map.keys())
            for batch_start in range(0, len(li_list), 100):
                batch = li_list[batch_start:batch_start + 100]
                # PostgREST in filter syntax
                in_clause = ",".join(f'"{li}"' for li in batch)
                
                existing = sb_request(
                    "GET",
                    "Lead Database",
                    query={
                        "select": 'id,"Linkedin"',
                        "or": f'({",".join(f"Linkedin.ilike.{li}" for li in batch)})',
                        "limit": str(len(batch)),
                    }
                )
                
                if existing:
                    for lead in existing:
                        normalized = normalize_linkedin(lead.get("Linkedin") or "")
                        if normalized in linkedin_map:
                            lead_id_map[linkedin_map[normalized]] = lead["id"]
        
        # Batch lookup by email (use lower(btrim("Email")) for index)
        if email_map:
            em_list = list(email_map.keys())
            for batch_start in range(0, len(em_list), 100):
                batch = em_list[batch_start:batch_start + 100]
                
                existing = sb_request(
                    "GET",
                    "Lead Database",
                    query={
                        "select": 'id,"Email"',
                        "or": f'({",".join(f"Email.ilike.{em}" for em in batch)})',
                        "limit": str(len(batch)),
                    }
                )
                
                if existing:
                    for lead in existing:
                        email = (lead.get("Email") or "").strip().lower()
                        if email in email_map and email_map[email] not in lead_id_map:
                            lead_id_map[email_map[email]] = lead["id"]
        
        # Create missing leads and collect all lead_ids
        for i, row in enumerate(rows):
            lead_id = lead_id_map.get(i)
            
            # Create if not found
            if not lead_id:
                linkedin = row.get("linkedin") or row.get("linkedin_url") or ""
                email = (row.get("email") or "").strip().lower()
                
                new_lead = sb_request(
                    "POST",
                    "Lead Database",
                    {
                        "Linkedin": linkedin if linkedin.startswith("http") else (f"https://{linkedin}" if linkedin else None),
                        "Email": email if email and email not in ("", "n/a", "none", "null") else None,
                        "First Name": row.get("first_name") or row.get("First Name"),
                        "Last Name": row.get("last_name") or row.get("Last Name"),
                        "Company Name": row.get("company_name") or row.get("Company Name"),
                        "Website": row.get("website") or row.get("Website"),
                        "title": row.get("title") or row.get("Title") or row.get("job_title") or row.get("jobTitle"),
                    }
                )
                if new_lead and len(new_lead) > 0:
                    lead_id = new_lead[0]["id"]
            
            if lead_id:
                leads_to_add.append({"lead_id": lead_id, "source": "csv"})
            
            if (i + 1) % 100 == 0:
                print(f"    Processed {i + 1}/{len(rows)}...")
    
    # Add leads to the list via lead_list_members
    if leads_to_add:
        print(f"  Adding {len(leads_to_add)} leads to list...")
        
        # Batch insert into lead_list_members
        members = [
            {
                "list_id": list_id,
                "lead_id": lead["lead_id"],
                "enrichment_status": "pending",
            }
            for lead in leads_to_add
        ]
        
        # Insert in batches of 500 to avoid request size limits
        batch_size = 500
        for i in range(0, len(members), batch_size):
            batch = members[i:i + batch_size]
            sb_request("POST", "lead_list_members", batch)
            print(f"    Added batch {i + batch_size}/{len(members)}...")
        
        # Update total_leads count
        sb_request(
            "PATCH",
            f"lead_lists?list_id=eq.{list_id}",
            {"total_leads": len(leads_to_add)}
        )
        
        print(f"✓ Added {len(leads_to_add)} leads to list {list_id}")
    else:
        print("⚠ No leads added")
    
    print(f"\nNext: enrich this list with:")
    print(f"  ./lead_lists.py enrich {list_id} --estimate")


# ============================================================================
# LIST COMMAND
# ============================================================================

def cmd_list(args: argparse.Namespace) -> None:
    """List all lead lists with status."""
    query: dict[str, str] = {
        "select": "list_id,client,list_name,source,status,total_leads,ready_count,actual_cost_usd,created_at",
        "order": "created_at.desc",
    }
    
    if args.client:
        query["client"] = f"eq.{args.client}"
    
    if args.status:
        query["status"] = f"eq.{args.status}"
    
    if args.limit:
        query["limit"] = str(args.limit)
    
    lists = sb_request("GET", "lead_lists", query=query)
    
    if not lists or len(lists) == 0:
        print("No lists found")
        return
    
    print(f"Found {len(lists)} list(s):\n")
    
    for lst in lists:
        list_id = lst["list_id"][:8]
        status_icon = {
            "scraped": "○",
            "enriching": "◐",
            "enriched": "●",
            "exported": "✓",
            "failed": "✗",
        }.get(lst["status"], "?")
        
        print(f"{status_icon} {list_id} | {lst['client']:<10} | {lst['list_name']:<40}")
        print(f"  Status: {lst['status']:<12} | Source: {lst['source']:<15} | Leads: {lst['total_leads']}")
        print(f"  Ready: {lst['ready_count']:<5} | Cost: ${lst['actual_cost_usd'] or 0:.2f}")
        print(f"  Created: {lst['created_at'][:10]}")
        print()


# ============================================================================
# SHOW COMMAND
# ============================================================================

def cmd_show(args: argparse.Namespace) -> None:
    """Show detailed information for a specific list."""
    list_id = args.list_id
    
    # Fetch the list
    lists = sb_request("GET", "lead_lists", query={"list_id": f"eq.{list_id}"})
    if not lists or len(lists) == 0:
        raise SystemExit(f"Error: List not found: {list_id}")
    
    lst = lists[0]
    
    # Print details
    print(f"List ID: {lst['list_id']}")
    print(f"Client: {lst['client']}")
    print(f"Name: {lst['list_name']}")
    print(f"Source: {lst['source']}")
    print(f"Status: {lst['status']}")
    print(f"\nCounts:")
    print(f"  Total leads: {lst['total_leads']}")
    print(f"  Enriched: {lst['enriched_count']}")
    print(f"  Ready (with email): {lst['ready_count']}")
    print(f"  Failed: {lst['failed_count']}")
    print(f"  Skipped: {lst['skipped_count']}")
    print(f"\nCost:")
    print(f"  Estimated: ${lst['estimated_cost_usd'] or 0:.2f}")
    print(f"  Actual: ${lst['actual_cost_usd'] or 0:.2f}")
    print(f"  Cap: ${lst['cost_cap_usd'] or 0:.2f}" if lst['cost_cap_usd'] else "  Cap: (none)")
    print(f"\nTimestamps:")
    print(f"  Created: {lst['created_at']}")
    print(f"  Updated: {lst['updated_at']}")
    if lst['enrichment_started_at']:
        print(f"  Enrichment started: {lst['enrichment_started_at']}")
    if lst['enrichment_completed_at']:
        print(f"  Enrichment completed: {lst['enrichment_completed_at']}")
    if lst['exported_at']:
        print(f"  Exported: {lst['exported_at']}")
    
    # Show run report if available
    if lst.get('run_report'):
        report = lst['run_report']
        print(f"\nRun Report:")
        print(f"  Searches run: {report.get('searches_run', 0)}")
        print(f"  Leads found: {report.get('leads_found', 0)}")
        print(f"  Duration: {report.get('duration_sec', 0):.1f}s")
        print(f"  Throughput: {report.get('throughput_per_min', 0):.1f} leads/min")
        
        if report.get('emails_by_source'):
            print(f"\n  Emails by source:")
            for source, count in sorted(report['emails_by_source'].items()):
                print(f"    {source:<25} {count}")
        
        if report.get('cost_by_provider'):
            print(f"\n  Cost by provider:")
            for provider, cost in sorted(report['cost_by_provider'].items()):
                print(f"    {provider:<25} ${cost:.4f}")
            print(f"    {'Total':<25} ${report.get('total_cost_usd', 0):.4f}")
        
        if report.get('batch_stats'):
            stats = report['batch_stats']
            print(f"\n  Batch stats:")
            print(f"    Bulk verify calls: {stats.get('bulk_verify_calls', 0)}")
            print(f"    Concurrent finds: {stats.get('concurrent_finds', 0)}")
            print(f"    Rate limit hits: {stats.get('rate_limit_hits', 0)}")
            if stats.get('avg_batch_size'):
                print(f"    Avg batch size: {stats['avg_batch_size']:.1f}")
    
    # Show sample leads if requested
    if args.sample:
        print(f"\nSample leads (first {args.sample}):")
        members = sb_request(
            "GET",
            "lead_list_members",
            query={
                "list_id": f"eq.{list_id}",
                "select": 'lead_id,enrichment_status,cost_micro,"Lead Database"("First Name","Last Name","Email","Company Name")',
                "limit": str(args.sample),
            }
        )
        for m in members or []:
            lead = m.get("Lead Database") or {}
            status = m["enrichment_status"]
            cost = m["cost_micro"] / 1_000_000 if m["cost_micro"] else 0
            print(f"  [{status:<12}] {lead.get('First Name')} {lead.get('Last Name')} | {lead.get('Email') or '(no email)'} | ${cost:.4f}")


# ============================================================================
# ENRICH COMMAND
# ============================================================================

def cmd_enrich(args: argparse.Namespace) -> None:
    """Enrich a specific list with cost estimation and confirmation."""
    list_id = args.list_id
    
    # Fetch the list
    lists = sb_request("GET", "lead_lists", query={"list_id": f"eq.{list_id}"})
    if not lists or len(lists) == 0:
        raise SystemExit(f"Error: List not found: {list_id}")
    
    lst = lists[0]
    
    # Fetch pending leads
    members = sb_request(
        "GET",
        "lead_list_members",
        query={
            "list_id": f"eq.{list_id}",
            "enrichment_status": "eq.pending",
            "select": 'lead_id,"Lead Database"(id,"Linkedin","Email","First Name","Last Name","Company Name")',
        }
    )
    
    pending_count = len(members or [])
    
    if pending_count == 0:
        print(f"✓ List {list_id[:8]} is fully enriched (no pending leads)")
        return
    
    # Cost estimation (rough)
    # Assume average of $0.003 per lead for icypeas search + pattern + verify
    avg_cost_per_lead = 0.003
    estimated_cost = pending_count * avg_cost_per_lead
    
    print(f"List: {lst['list_name']} ({lst['client']})")
    print(f"Status: {lst['status']}")
    print(f"Pending leads: {pending_count}")
    print(f"\nCost estimate:")
    print(f"  Avg per lead: ${avg_cost_per_lead:.4f}")
    print(f"  Total estimate: ${estimated_cost:.2f}")
    
    if lst['cost_cap_usd']:
        remaining = lst['cost_cap_usd'] - (lst['actual_cost_usd'] or 0)
        print(f"  Cost cap: ${lst['cost_cap_usd']:.2f}")
        print(f"  Already spent: ${lst['actual_cost_usd'] or 0:.2f}")
        print(f"  Remaining: ${remaining:.2f}")
        
        if estimated_cost > remaining:
            print(f"  ⚠ Warning: Estimated cost exceeds remaining budget!")
    
    if args.estimate:
        print("\nThis was an estimate. To enrich, run with --confirm")
        return
    
    if not args.confirm:
        print("\nError: Must specify --confirm to proceed with enrichment")
        print("Run with --estimate first to see cost estimate")
        return
    
    # Actual enrichment
    print(f"\n{'='*60}")
    print("Starting enrichment...")
    print(f"{'='*60}\n")
    
    # Mark list as enriching
    sb_request(
        "PATCH",
        f"lead_lists?list_id=eq.{list_id}",
        {"status": "enriching", "enrichment_started_at": datetime.now(timezone.utc).isoformat()}
    )
    
    # Use the enrichment runner instead of this command
    print("Use enrich_list.py for actual enrichment:")
    print(f"  ./scripts/enrich_list.py {list_id} --confirm-spend {confirm_spend}")
    print("\nThis will:")
    print("  1. Process each pending lead through the email ladder")
    print("  2. Update lead_list_members.enrichment_status as we go")
    print("  3. Track cost_micro per lead")
    print("  4. Stop if we hit cost cap")
    print("  5. Update Lead Database with found emails")
    print("  6. Generate detailed run report")
    
    # Mark as enriched (placeholder)
    # sb_request(
    #     "PATCH",
    #     f"lead_lists?list_id=eq.{list_id}",
    #     {"status": "enriched", "enrichment_completed_at": datetime.now(timezone.utc).isoformat()}
    # )


# ============================================================================
# EXPORT COMMAND
# ============================================================================

def cmd_export(args: argparse.Namespace) -> None:
    """Export a list to CSV or Google Sheets."""
    list_id = args.list_id
    
    # Fetch the list
    lists = sb_request("GET", "lead_lists", query={"list_id": f"eq.{list_id}"})
    if not lists or len(lists) == 0:
        raise SystemExit(f"Error: List not found: {list_id}")
    
    lst = lists[0]
    
    # Fetch ready leads (enriched with email)
    members = sb_request(
        "GET",
        "lead_list_members",
        query={
            "list_id": f"eq.{list_id}",
            "enrichment_status": "eq.enriched",
            "select": 'lead_id,cost_micro,"Lead Database"(*)',
        }
    )
    
    if not members or len(members) == 0:
        print(f"No enriched leads to export for list {list_id[:8]}")
        return
    
    # Filter to only leads with email
    ready_leads = [
        m for m in members 
        if m.get("Lead Database") 
        and m["Lead Database"].get("Email")
        and m["Lead Database"]["Email"] not in ("", "n/a", "none", "null")
    ]
    
    if not ready_leads:
        print(f"No leads with valid emails to export for list {list_id[:8]}")
        return
    
    print(f"Exporting {len(ready_leads)} ready leads...")
    
    # Export to CSV
    if args.format == "csv":
        output_path = Path(args.output) if args.output else Path(f"export_{list_id[:8]}.csv")
        
        with output_path.open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "first_name", "last_name", "title", "email", "linkedin",
                "company_name", "website", "location", "company_size",
                "company_description", "email_status", "email_source"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            
            for m in ready_leads:
                lead = m["Lead Database"]
                writer.writerow({
                    "first_name": lead.get("First Name"),
                    "last_name": lead.get("Last Name"),
                    "title": lead.get("title") or "",
                    "email": lead.get("Email"),
                    "linkedin": lead.get("Linkedin"),
                    "company_name": lead.get("Company Name"),
                    "website": lead.get("Website"),
                    "location": lead.get("location"),
                    "company_size": lead.get("company_size"),
                    "company_description": lead.get("company_description"),
                    "email_status": lead.get("email_status"),
                    "email_source": lead.get("email_source"),
                })
        
        print(f"✓ Exported to {output_path}")
        
        # Mark list as exported
        sb_request(
            "PATCH",
            f"lead_lists?list_id=eq.{list_id}",
            {"status": "exported", "exported_at": datetime.now(timezone.utc).isoformat()}
        )
    
    else:
        print(f"Error: Export format '{args.format}' not yet implemented")
        print("Supported formats: csv")


# ============================================================================
# STATS COMMAND
# ============================================================================

def cmd_stats(args: argparse.Namespace) -> None:
    """Show enrichment statistics across all lists."""
    # Get aggregate stats
    lists = sb_request(
        "GET", 
        "lead_lists",
        query={"select": "client,status,total_leads,ready_count,actual_cost_usd"}
    )
    
    if not lists or len(lists) == 0:
        print("No lists found")
        return
    
    # Aggregate by client
    by_client: dict[str, dict] = {}
    for lst in lists:
        client = lst["client"]
        if client not in by_client:
            by_client[client] = {
                "lists": 0,
                "total_leads": 0,
                "ready_count": 0,
                "cost_usd": 0.0,
            }
        by_client[client]["lists"] += 1
        by_client[client]["total_leads"] += lst["total_leads"] or 0
        by_client[client]["ready_count"] += lst["ready_count"] or 0
        by_client[client]["cost_usd"] += lst["actual_cost_usd"] or 0
    
    # Aggregate by status
    by_status: dict[str, int] = {}
    for lst in lists:
        status = lst["status"]
        by_status[status] = by_status.get(status, 0) + 1
    
    print("Pipeline statistics:\n")
    print("By client:")
    for client, stats in sorted(by_client.items()):
        print(f"  {client:<12} | {stats['lists']} lists | {stats['total_leads']} leads | {stats['ready_count']} ready | ${stats['cost_usd']:.2f}")
    
    print("\nBy status:")
    for status, count in sorted(by_status.items()):
        print(f"  {status:<12} | {count} lists")
    
    print(f"\nTotal:")
    print(f"  Lists: {len(lists)}")
    print(f"  Leads: {sum(by_client.values(), {'total_leads': 0})}")
    print(f"  Ready: {sum(lst['ready_count'] or 0 for lst in lists)}")
    print(f"  Total cost: ${sum(lst['actual_cost_usd'] or 0 for lst in lists):.2f}")


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lead list management for zs-ops2 enrichment pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # CREATE
    create_parser = subparsers.add_parser("create", help="Create a new lead list")
    create_parser.add_argument("--client", required=True, help="Client name (e.g. MARS, GWS)")
    create_parser.add_argument("--name", required=True, help="List name (e.g. 'Midwest CNC Oct 18')")
    create_parser.add_argument("--source", required=True, help="Source (icypeas, treg.to, AI Ark, manual)")
    create_parser.add_argument("--linkedin-urls", help="File with LinkedIn URLs (one per line)")
    create_parser.add_argument("--csv", help="CSV file with leads")
    create_parser.add_argument("--estimated-cost", type=float, help="Estimated enrichment cost")
    create_parser.add_argument("--cost-cap", type=float, help="Hard cost cap for enrichment")
    create_parser.add_argument("--metadata", help="JSON metadata")
    
    # LIST
    list_parser = subparsers.add_parser("list", help="List all lead lists")
    list_parser.add_argument("--client", help="Filter by client")
    list_parser.add_argument("--status", help="Filter by status")
    list_parser.add_argument("--limit", type=int, help="Limit results")
    
    # SHOW
    show_parser = subparsers.add_parser("show", help="Show details for a specific list")
    show_parser.add_argument("list_id", help="List ID (UUID)")
    show_parser.add_argument("--sample", type=int, default=0, help="Show sample leads")
    
    # ENRICH
    enrich_parser = subparsers.add_parser("enrich", help="Enrich a specific list")
    enrich_parser.add_argument("list_id", help="List ID (UUID)")
    enrich_parser.add_argument("--estimate", action="store_true", help="Show cost estimate only")
    enrich_parser.add_argument("--confirm", action="store_true", help="Confirm and start enrichment")
    enrich_parser.add_argument("--cap", type=float, help="Override cost cap for this run")
    
    # EXPORT
    export_parser = subparsers.add_parser("export", help="Export a list")
    export_parser.add_argument("list_id", help="List ID (UUID)")
    export_parser.add_argument("--format", default="csv", help="Export format (csv, gsheet)")
    export_parser.add_argument("--output", help="Output file path")
    
    # STATS
    stats_parser = subparsers.add_parser("stats", help="Show enrichment statistics")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Dispatch to command handler
    {
        "create": cmd_create,
        "list": cmd_list,
        "show": cmd_show,
        "enrich": cmd_enrich,
        "export": cmd_export,
        "stats": cmd_stats,
    }[args.command](args)


if __name__ == "__main__":
    main()
