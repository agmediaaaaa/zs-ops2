#!/usr/bin/env python3
"""List-based enrichment runner using bulk/batch operations.

Jessica's requirements:
- Use bulk/batch endpoints where available
- Concurrent requests with rate-limit backoff
- Detailed run report per list (searches, sources, costs per provider)
- Fall back to per-lead only where no bulk exists
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

# Import enrichment logic from gws_icypeas_sheet2
sys.path.insert(0, str(Path(__file__).parent))
import gws_icypeas_sheet2 as enricher

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


class RunReport:
    """Track detailed enrichment metrics per run."""
    
    def __init__(self, list_id: str, list_name: str):
        self.list_id = list_id
        self.list_name = list_name
        self.start_time = time.time()
        
        # Core metrics
        self.searches_run = 0
        self.leads_found = 0
        
        # Emails by source
        self.emails_by_source = defaultdict(int)
        
        # Cost by provider (in USD)
        self.cost_by_provider = defaultdict(float)
        
        # Batch stats
        self.bulk_verify_calls = 0
        self.concurrent_finds = 0
        self.rate_limit_hits = 0
        self.batch_sizes = []
        
        # Thread-safe access
        self._lock = threading.Lock()
    
    def add_email(self, source: str, cost_micro: int = 0, provider: str | None = None) -> None:
        """Record a found email."""
        with self._lock:
            self.emails_by_source[source] += 1
            if cost_micro > 0 and provider:
                self.cost_by_provider[provider] += cost_micro / 1_000_000
    
    def add_search(self, cost_micro: int = 0, provider: str = "icypeas") -> None:
        """Record a search operation."""
        with self._lock:
            self.searches_run += 1
            if cost_micro > 0:
                self.cost_by_provider[provider] += cost_micro / 1_000_000
    
    def add_bulk_verify(self, batch_size: int, cost_micro: int, provider: str) -> None:
        """Record a bulk verification call."""
        with self._lock:
            self.bulk_verify_calls += 1
            self.batch_sizes.append(batch_size)
            if cost_micro > 0:
                self.cost_by_provider[provider] += cost_micro / 1_000_000
    
    def add_concurrent_find(self) -> None:
        """Record a concurrent find operation."""
        with self._lock:
            self.concurrent_finds += 1
    
    def add_rate_limit_hit(self) -> None:
        """Record a rate limit encounter."""
        with self._lock:
            self.rate_limit_hits += 1
    
    def to_dict(self) -> dict:
        """Generate final report."""
        duration = time.time() - self.start_time
        throughput = (self.leads_found / (duration / 60)) if duration > 0 else 0
        
        return {
            "list_id": self.list_id,
            "list_name": self.list_name,
            "searches_run": self.searches_run,
            "leads_found": self.leads_found,
            "emails_by_source": dict(self.emails_by_source),
            "cost_by_provider": {
                k: round(v, 6) for k, v in self.cost_by_provider.items()
            },
            "batch_stats": {
                "bulk_verify_calls": self.bulk_verify_calls,
                "concurrent_finds": self.concurrent_finds,
                "rate_limit_hits": self.rate_limit_hits,
                "avg_batch_size": (
                    round(sum(self.batch_sizes) / len(self.batch_sizes), 1)
                    if self.batch_sizes else 0
                ),
            },
            "duration_sec": round(duration, 1),
            "throughput_per_min": round(throughput, 2),
            "total_cost_usd": round(sum(self.cost_by_provider.values()), 6),
        }


def normalize_linkedin(url: str) -> str:
    """Normalize LinkedIn URL for deduplication."""
    u = url.strip().lower().rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    if "/in/" in u:
        return u.split("?")[0]
    return u


def fetch_list_pending_leads(list_id: str) -> tuple[dict, list[dict]]:
    """Fetch list metadata and all pending leads from Lead Database."""
    # Fetch the list
    lists = sb_request("GET", "lead_lists", query={"list_id": f"eq.{list_id}"})
    if not lists or len(lists) == 0:
        raise SystemExit(f"Error: List not found: {list_id}")
    
    lst = lists[0]
    
    # Fetch pending leads from Lead Database (page if >1000)
    members = []
    offset = 0
    page_size = 1000
    
    while True:
        batch = sb_request(
            "GET",
            "lead_list_members",
            query={
                "list_id": f"eq.{list_id}",
                "enrichment_status": "eq.pending",
                "select": 'lead_id,"Lead Database"(id,"Linkedin","Email","First Name","Last Name","Company Name","Website",location,company_description,company_size)',
                "limit": str(page_size),
                "offset": str(offset),
            }
        )
        
        if not batch or len(batch) == 0:
            break
        
        members.extend(batch)
        
        if len(batch) < page_size:
            break
        
        offset += page_size

    if not members:
        return lst, []

    leads = []
    for m in members:
        lead_data = m.get("Lead Database")
        if not lead_data:
            continue

        website = lead_data.get("Website") or ""
        lead = {
            "id": lead_data["id"],
            "lead_id": m["lead_id"],
            "linkedin": lead_data.get("Linkedin") or "",
            "email": lead_data.get("Email"),
            "first_name": lead_data.get("First Name") or "",
            "last_name": lead_data.get("Last Name") or "",
            "company_name": lead_data.get("Company Name") or "",
            "website": website,
            "location": lead_data.get("location") or "",
            "company_description": lead_data.get("company_description") or "",
            "company_size": lead_data.get("company_size") or "",
            "domain": enricher.domain_of(website),
        }
        leads.append(lead)

    return lst, leads


def upsert_lead_database(lead: dict, email: str, email_source: str, email_status: str) -> None:
    """Upsert enriched lead to Lead Database."""
    try:
        # Update by lead_id
        sb_request(
            "PATCH",
            f"Lead Database?id=eq.{lead['id']}",
            {
                "Email": email,
                "email_source": email_source,
                "email_status": email_status,
                "company_size": lead.get("company_size") or None,
                "company_description": lead.get("company_description") or None,
                "location": lead.get("location") or None,
                "enrichment_updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        print(f"  ⚠ Failed to update Lead Database: {e}", flush=True)


def update_member_status(
    list_id: str,
    lead_id: int,
    status: str,
    cost_micro: int = 0,
) -> None:
    """Update enrichment status for a lead in a list."""
    now_iso = datetime.now(timezone.utc).isoformat()
    update_data: dict[str, Any] = {
        "enrichment_status": status,
    }

    if status == "in_progress":
        update_data["enrichment_attempted_at"] = now_iso
    elif status in ("enriched", "failed", "skipped"):
        update_data["enrichment_completed_at"] = now_iso

    if cost_micro > 0:
        update_data["cost_micro"] = cost_micro

    try:
        sb_request(
            "PATCH",
            f"lead_list_members?list_id=eq.{list_id}&lead_id=eq.{lead_id}",
            update_data
        )
    except Exception as e:
        print(f"  ⚠ Failed to update member status: {e}", flush=True)


def update_list_counts(list_id: str) -> None:
    """Recalculate and update list counts (called after batch processing)."""
    try:
        # Count by status - page through if >1000 rows
        members = []
        offset = 0
        page_size = 1000
        
        while True:
            batch = sb_request(
                "GET",
                "lead_list_members",
                query={
                    "list_id": f"eq.{list_id}",
                    "select": 'enrichment_status,cost_micro,lead_id,"Lead Database"("Email")',
                    "limit": str(page_size),
                    "offset": str(offset),
                }
            )
            
            if not batch or len(batch) == 0:
                break
            
            members.extend(batch)
            
            if len(batch) < page_size:
                break
            
            offset += page_size
        
        if not members:
            return
        
        enriched_count = sum(1 for m in members if m["enrichment_status"] == "enriched")
        failed_count = sum(1 for m in members if m["enrichment_status"] == "failed")
        skipped_count = sum(1 for m in members if m["enrichment_status"] == "skipped")
        
        # Count ready (enriched with valid email)
        ready_count = sum(
            1 for m in members 
            if m["enrichment_status"] == "enriched"
            and m.get("Lead Database")
            and m["Lead Database"].get("Email")
            and m["Lead Database"]["Email"] not in ("", "n/a", "none", "null")
        )
        
        # Sum cost
        actual_cost_usd = sum(
            (m.get("cost_micro") or 0) / 1_000_000 
            for m in members
        )
        
        # Update list
        sb_request(
            "PATCH",
            f"lead_lists?list_id=eq.{list_id}",
            {
                "enriched_count": enriched_count,
                "ready_count": ready_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
                "actual_cost_usd": round(actual_cost_usd, 6),
            }
        )
    except Exception as e:
        print(f"  ⚠ Failed to update list counts: {e}", flush=True)


def bulk_verify_mv(emails: list[str], report: RunReport) -> dict[str, str]:
    """Bulk verify emails with MillionVerifier (if available, else batch concurrent)."""
    # MillionVerifier doesn't have a bulk API via treg.to, so we do concurrent
    results = {}
    
    if not emails:
        return results
    
    batch_size = min(len(emails), 50)  # Concurrent batch
    
    def verify_one(email: str) -> tuple[str, str, int]:
        try:
            if not enricher.under_cap(2000):
                return email, "stopped", 0
            data, meta = enricher.treg(
                "GET",
                "/call/millionverifier.people.email.verify",
                query={"email": email},
            )
            cost = int(meta.get("cost_micro") or 0)
            enricher.charge(cost)
            result = ""
            if isinstance(data, dict):
                result = (data.get("result") or data.get("quality") or "").lower()
            return email, result, cost
        except urllib.error.HTTPError as e:
            if e.code == 429:
                report.add_rate_limit_hit()
                time.sleep(2)
                return verify_one(email)  # Retry
            return email, "error", 0
        except Exception:
            return email, "error", 0
    
    # Concurrent batch
    with ThreadPoolExecutor(max_workers=batch_size) as pool:
        futures = [pool.submit(verify_one, em) for em in emails]
        for fut in as_completed(futures):
            email, status, cost = fut.result()
            results[email] = status
            if cost > 0:
                report.cost_by_provider["millionverifier"] += cost / 1_000_000
    
    report.add_bulk_verify(len(emails), 0, "millionverifier")
    return results


def bulk_verify_contactout(emails: list[str], report: RunReport) -> dict[str, str]:
    """Bulk verify with ContactOut (free, concurrent batch)."""
    results = {}
    
    if not emails:
        return results
    
    batch_size = min(len(emails), 30)  # Smaller batch for free tier
    
    def verify_one(email: str) -> tuple[str, str]:
        try:
            data, meta = enricher.treg(
                "GET",
                "/call/contactout.people.email.verify",
                query={"email": email},
                timeout=20,
                retries=2,
            )
            cost = int(meta.get("cost_micro") or 0)
            enricher.charge(cost)
            status = ""
            if isinstance(data, dict):
                inner = data.get("data") if isinstance(data.get("data"), dict) else data
                status = str(
                    (inner or {}).get("status")
                    or (inner or {}).get("result")
                    or data.get("status")
                    or ""
                ).lower()
            return email, status
        except urllib.error.HTTPError as e:
            if e.code == 429:
                report.add_rate_limit_hit()
                time.sleep(1.5)
                return verify_one(email)  # Retry
            return email, "error"
        except Exception:
            return email, "error"
    
    with ThreadPoolExecutor(max_workers=batch_size) as pool:
        futures = [pool.submit(verify_one, em) for em in emails]
        for fut in as_completed(futures):
            email, status = fut.result()
            results[email] = status
    
    report.add_bulk_verify(len(emails), 0, "contactout")
    return results


def enrich_lead_batch(
    leads: list[dict],
    excl_emails: set[str],
    list_id: str,
    report: RunReport,
    cheap: bool,
) -> list[tuple[dict, dict]]:
    """Enrich a batch of leads using bulk/concurrent operations."""
    results: list[tuple[dict, dict]] = []
    
    # Step 1: Check Supabase cache for all leads
    cache_hits = []
    cache_misses = []
    
    for lead in leads:
        cached = enricher.try_supabase_email_reuse(lead, excl_emails)
        if cached is not None and not cached.get("stopped"):
            email = cached.get("email")
            if email:
                source = cached.get("email_source", "supabase_cache")
                if "mv" in source.lower():
                    report.add_email("supabase_mv_reverify", 2000, "millionverifier")
                else:
                    report.add_email("supabase_cache", 0, None)
                cache_hits.append((lead, cached))
            else:
                cache_misses.append(lead)
        else:
            cache_misses.append(lead)
    
    print(f"  Cache: {len(cache_hits)} hits, {len(cache_misses)} misses", flush=True)
    results.extend(cache_hits)
    
    if not cache_misses:
        return results
    
    # Step 2: Generate pattern emails for all misses
    pattern_candidates: dict[str, tuple[dict, str]] = {}  # email -> (lead, pattern)
    
    for lead in cache_misses:
        patterns = enricher.pattern_emails(
            lead["first_name"],
            lead["last_name"],
            lead["domain"]
        )
        if patterns:
            guess = patterns[0]
            if guess.lower() not in excl_emails:
                pattern_candidates[guess.lower()] = (lead, guess)
    
    if not pattern_candidates:
        # No pattern candidates, go straight to find
        return results + enrich_with_find(cache_misses, excl_emails, list_id, report, cheap)
    
    print(f"  Pattern candidates: {len(pattern_candidates)}", flush=True)
    
    # Step 3: Bulk verify pattern emails
    if cheap:
        # ContactOut (free)
        verify_results = bulk_verify_contactout(list(pattern_candidates.keys()), report)
        valid_statuses = enricher.VALID_CO
        catch_all_statuses = enricher.CATCH_ALL_CO
    else:
        # MillionVerifier
        verify_results = bulk_verify_mv(list(pattern_candidates.keys()), report)
        valid_statuses = enricher.VALID_MV
        catch_all_statuses = enricher.CATCH_ALL_MV
    
    # Step 4: Process verification results
    pattern_hits = []
    pattern_misses = []
    
    for email_lower, status in verify_results.items():
        lead, original_email = pattern_candidates[email_lower]
        
        if status in valid_statuses:
            provider = "contactout" if cheap else "millionverifier"
            source = f"pattern_{provider}"
            report.add_email(source, 0, None)  # Cost already tracked in bulk_verify
            pattern_hits.append((
                lead,
                {
                    "email": original_email,
                    "email_status": status,
                    "email_source": source,
                    "spent_note": "0",
                    "plusvibe_ready": True,
                    "stopped": False,
                }
            ))
        elif status in catch_all_statuses:
            # Catch-all needs escalation
            pattern_misses.append(lead)
        else:
            pattern_misses.append(lead)
    
    print(f"  Pattern hits: {len(pattern_hits)}, misses: {len(pattern_misses)}", flush=True)
    results.extend(pattern_hits)
    
    # Step 5: Escalate misses to find services
    if pattern_misses:
        results.extend(enrich_with_find(pattern_misses, excl_emails, list_id, report, cheap))
    
    return results


def enrich_with_find(
    leads: list[dict],
    excl_emails: set[str],
    list_id: str,
    report: RunReport,
    cheap: bool,
) -> list[tuple[dict, dict]]:
    """Enrich leads using find services (Blitz, QuickEnrich, Trykitt)."""
    results: list[tuple[dict, dict]] = []
    
    if not leads:
        return results
    
    # Concurrent finds with rate-limit backoff
    max_workers = min(32, len(leads))
    
    def find_one(lead: dict) -> tuple[dict, dict]:
        """Find email for one lead."""
        report.add_concurrent_find()
        
        email = ""
        email_source = ""
        email_status = ""
        cost_here = 0
        
        # Try Blitz first (cheapest, requires LinkedIn)
        if lead.get("linkedin") and not cheap:
            try:
                if enricher.under_cap(1000):
                    b_email, bcost = enricher.find_blitz(lead["linkedin"])
                    cost_here += bcost
                    if bcost > 0:
                        report.cost_by_provider["blitz"] += bcost / 1_000_000
                    if b_email and b_email.lower() not in excl_emails:
                        email, email_source, email_status = b_email, "blitz", "blitz"
                        report.add_email("blitz", bcost, "blitz")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    report.add_rate_limit_hit()
                    time.sleep(1)
            except Exception:
                pass
        
        # Try QuickEnrich if no email yet
        if not email and not cheap and enricher.under_cap(6000):
            try:
                qe_email, qcost = enricher.find_quickenrich(
                    lead["first_name"],
                    lead["last_name"],
                    lead["domain"],
                    lead["linkedin"],
                )
                cost_here += qcost
                if qcost > 0:
                    report.cost_by_provider["quickenrich"] += qcost / 1_000_000
                if qe_email and qe_email.lower() not in excl_emails:
                    # Verify with MV
                    mv, mcost = enricher.verify_mv(qe_email)
                    cost_here += mcost
                    if mcost > 0:
                        report.cost_by_provider["millionverifier"] += mcost / 1_000_000
                    if mv in enricher.VALID_MV or mv in enricher.CATCH_ALL_MV:
                        email = qe_email
                        email_source = "quickenrich_mv"
                        email_status = mv
                        report.add_email("quickenrich", qcost, "quickenrich")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    report.add_rate_limit_hit()
                    time.sleep(1.5)
            except Exception:
                pass
        
        # Try Trykitt as last resort
        if not email and enricher.under_cap(7000):
            try:
                tk_email, tcost = enricher.find_trykitt(
                    lead["first_name"],
                    lead["last_name"],
                    lead["domain"],
                )
                cost_here += tcost
                if tcost > 0:
                    report.cost_by_provider["trykitt"] += tcost / 1_000_000
                if tk_email and tk_email.lower() not in excl_emails:
                    if not cheap:
                        mv, mcost = enricher.verify_mv(tk_email)
                        cost_here += mcost
                        if mcost > 0:
                            report.cost_by_provider["millionverifier"] += mcost / 1_000_000
                        email_status = mv or "trykitt"
                    else:
                        email_status = "trykitt"
                    email = tk_email
                    email_source = "trykitt_mv" if not cheap else "trykitt"
                    report.add_email("trykitt", tcost, "trykitt")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    report.add_rate_limit_hit()
                    time.sleep(2)
            except Exception:
                pass
        
        ready = bool(
            email
            and email.lower() not in excl_emails
            and (
                email_status in enricher.VALID_MV
                or email_status in enricher.CATCH_ALL_MV
                or email_source in ("blitz", "trykitt")
            )
        )
        
        return lead, {
            "email": email or None,
            "email_status": email_status or None,
            "email_source": email_source or None,
            "spent_note": f"{cost_here/1e6:.4f}",
            "plusvibe_ready": ready,
            "stopped": False,
        }
    
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(find_one, lead): lead for lead in leads}
        for fut in as_completed(futures):
            lead = futures[fut]
            try:
                result = fut.result()
                results.append(result)
            except Exception as e:
                print(f"  ✗ Error finding for {lead.get('domain')}: {e}", flush=True)
                results.append((lead, {
                    "email": None,
                    "email_status": None,
                    "email_source": None,
                    "spent_note": "0",
                    "plusvibe_ready": False,
                    "stopped": False,
                }))
            
            if not enricher.under_cap(500):
                break
    
    return results


def enrich_list(
    list_id: str,
    confirm_spend: float,
    workers: int = 32,
    cheap: bool = False,
) -> dict:
    """Enrich all pending leads in a list using bulk operations."""
    # Fetch list and pending leads
    print("Fetching list and pending leads...")
    lst, leads = fetch_list_pending_leads(list_id)
    
    print(f"Enriching list: {lst['list_name']} ({lst['client']})")
    print(f"Status: {lst['status']}")
    print(f"Pending leads: {len(leads)}\n")
    
    # Initialize report
    report = RunReport(list_id, lst['list_name'])
    
    if not leads:
        print("✓ No pending leads to enrich")
        sb_request(
            "PATCH",
            f"lead_lists?list_id=eq.{list_id}",
            {
                "status": "enriched",
                "enrichment_completed_at": datetime.now(timezone.utc).isoformat(),
                "run_report": report.to_dict(),
            }
        )
        return {"leads_enriched": 0, "cost_usd": 0}
    
    # Mark list as enriching
    sb_request(
        "PATCH",
        f"lead_lists?list_id=eq.{list_id}",
        {
            "status": "enriching",
            "enrichment_started_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    
    # Filter valid leads
    valid_leads = []
    for lead in leads:
        if not lead["first_name"] or not lead["last_name"]:
            update_member_status(list_id, lead["lead_id"], "skipped")
            continue
        if not lead["domain"] and not lead["linkedin"]:
            update_member_status(list_id, lead["lead_id"], "skipped")
            continue
        valid_leads.append(lead)
    
    print(f"Valid leads for enrichment: {len(valid_leads)}\n")
    
    if not valid_leads:
        print("✓ No valid leads to enrich (all skipped)")
        sb_request(
            "PATCH",
            f"lead_lists?list_id=eq.{list_id}",
            {
                "status": "enriched",
                "enrichment_completed_at": datetime.now(timezone.utc).isoformat(),
                "run_report": report.to_dict(),
            }
        )
        return {"leads_enriched": 0, "leads_skipped": len(leads), "cost_usd": 0}
    
    # Initialize enrichment globals
    enricher.TOKEN = enricher.load_treg_token()
    enricher.CHEAP_MODE = cheap
    enricher._spent_micro = 0
    enricher._cap_micro = int(confirm_spend * 1_000_000)
    enricher._stop_spend = False
    
    # Load Supabase cache
    print("Loading Supabase lead cache...")
    enricher.load_supabase_lead_index()
    
    # Build exclusion set
    print("Building exclusion set...")
    excl_emails = set()
    
    # Process in batches
    print(f"\nStarting enrichment with ${confirm_spend:.2f} cap...")
    print(f"Mode: {'cheap' if cheap else 'standard'}\n")
    
    batch_size = 100
    enriched = 0
    failed = 0
    
    for i in range(0, len(valid_leads), batch_size):
        batch = valid_leads[i:i + batch_size]
        print(f"Batch {i//batch_size + 1}/{(len(valid_leads) + batch_size - 1)//batch_size} ({len(batch)} leads)")
        
        # Enrich batch
        batch_results = enrich_lead_batch(batch, excl_emails, list_id, report, cheap)
        
        # Update leads
        for lead, result in batch_results:
            email = result.get("email")
            cost_note = result.get("spent_note") or "0"
            try:
                cost_usd = float(cost_note)
                cost_micro = int(cost_usd * 1_000_000)
            except (ValueError, TypeError):
                cost_micro = 0
            
            # Update lead in Lead Database
            if email:
                upsert_lead_database(
                    lead,
                    email,
                    result.get("email_source") or "",
                    result.get("email_status") or "",
                )
            
            # Update member status
            if result.get("stopped"):
                update_member_status(list_id, lead["lead_id"], "failed", cost_micro)
                failed += 1
                print(f"  ✗ Stopped (cap reached)", flush=True)
                break
            elif result.get("plusvibe_ready"):
                update_member_status(list_id, lead["lead_id"], "enriched", cost_micro)
                enriched += 1
                report.leads_found += 1
                src = result.get("email_source") or ""
                print(f"  ✓ {lead['first_name']} {lead['last_name']} | {email} | {src}", flush=True)
            else:
                update_member_status(list_id, lead["lead_id"], "failed", cost_micro)
                failed += 1
        
        if not enricher.under_cap(500):
            print("\n⚠ Cost cap reached, stopping enrichment")
            break
        
        # Update counts after each batch
        update_list_counts(list_id)
        print()
    
    # Final count update
    update_list_counts(list_id)
    
    # Generate final report
    final_report = report.to_dict()
    
    # Mark list as enriched and save report
    sb_request(
        "PATCH",
        f"lead_lists?list_id=eq.{list_id}",
        {
            "status": "enriched",
            "enrichment_completed_at": datetime.now(timezone.utc).isoformat(),
            "run_report": final_report,
        }
    )
    
    print(f"\n{'='*60}")
    print(f"Enrichment complete!")
    print(f"{'='*60}")
    print(f"\nResults:")
    print(f"  Enriched: {enriched}")
    print(f"  Failed: {failed}")
    print(f"\nEmails by source:")
    for source, count in sorted(final_report["emails_by_source"].items()):
        print(f"  {source:<25} {count}")
    print(f"\nCost by provider:")
    for provider, cost in sorted(final_report["cost_by_provider"].items()):
        print(f"  {provider:<25} ${cost:.4f}")
    print(f"\nTotal cost: ${final_report['total_cost_usd']:.4f}")
    print(f"Duration: {final_report['duration_sec']:.1f}s")
    print(f"Throughput: {final_report['throughput_per_min']:.1f} leads/min")
    print(f"{'='*60}\n")
    
    return {
        "leads_enriched": enriched,
        "leads_failed": failed,
        "cost_usd": final_report['total_cost_usd'],
        "report": final_report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich a lead list using bulk/batch operations"
    )
    parser.add_argument("list_id", help="List ID (UUID)")
    parser.add_argument(
        "--confirm-spend",
        type=float,
        required=True,
        help="Confirmed spend cap in USD"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=32,
        help="Number of parallel workers"
    )
    parser.add_argument(
        "--cheap",
        action="store_true",
        help="Use cheap mode (pattern → ContactOut → Blitz, no MV/QE/Trykitt)"
    )

    args = parser.parse_args()

    try:
        results = enrich_list(
            args.list_id,
            args.confirm_spend,
            workers=args.workers,
            cheap=args.cheap,
        )
        print("\nFinal results:")
        print(json.dumps(results, indent=2))
    except KeyboardInterrupt:
        print("\n\nEnrichment interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
