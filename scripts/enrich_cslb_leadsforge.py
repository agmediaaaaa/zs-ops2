#!/usr/bin/env python3
"""Enrich CSLB companies with LeadsForge → Icypeas → Blitz (Jessica's required flow).

Flow (Nov 1, 2026 pipeline architecture):
  1. CSLB company name → Clearbit domain autocomplete (free, primary)
     - Strict matching: scores candidates against cleaned license name
     - Rejects non-US TLDs (.com.au, .co.uk, etc.)
     - Optional Hunter fallback (--with-hunter-fallback)
     - Optional paid Blitz (--with-paid-domain)
  2. LeadsForge people search (batched domains, suppression always-on, no per-company limits)
  3. Icypeas exact-person match (batched ~25 people per query by name+domain)
  4. Supabase ALL-client cache check (email/LinkedIn/name+domain) before paid email find
  5. Blitz email find from LinkedIn URL
  6. MillionVerifier + BounceBan (catch-alls)
  7. Upsert to Lead Database, pipeline_leads (with lead_database_id), create lead_list + members, merge to codicen_campaign_leads

Cost control (mandatory):
  --cap-usd USD                Hard spend cap (required, no default unlimited mode)
  --target-ready N             Stop once N ready leads are reached
  --estimate                   Free Clearbit sample + small LF sizing (<$0.25), extrapolate costs
  --resolve-only               Domain resolution quality check (free, seeded sample)
  --pilot                      Small target + cap for testing (100 ready)
  --window-days N              Window size in days (default: 90)
  --with-hunter-fallback       Enable Hunter as fallback after Clearbit (off by default)
  --with-paid-domain           Enable paid Blitz domain enrich (off by default)
  --allow-empty-suppression    Allow empty suppression sets (not recommended)

Window definition:
  The "Codicen window" = CSLB companies with:
    - primary_status = 'CLEAR'
    - expiration_date_iso BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL 'N days'
  Default: 90 days (actual: 13,321 companies as of Nov 1, 2026)

Examples:
  # Resolve-only mode (check domain resolution quality, free)
  python3 scripts/enrich_cslb_leadsforge.py --resolve-only

  # Estimate on current window (free Clearbit + small LF sample, <$0.25 total)
  python3 scripts/enrich_cslb_leadsforge.py --estimate

  # Pilot run (100 ready leads, $1 cap, 90-day window)
  python3 scripts/enrich_cslb_leadsforge.py --pilot --cap-usd 1.00 --window-days 90

  # Full run with 1000 ready target
  python3 scripts/enrich_cslb_leadsforge.py --target-ready 1000 --cap-usd 50.00

  # With Hunter fallback and paid domain enrichment
  python3 scripts/enrich_cslb_leadsforge.py --target-ready 500 --cap-usd 30.00 --with-hunter-fallback --with-paid-domain
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import urllib.parse
from urllib.parse import urlparse

# Environment
TREG_TOKEN = os.environ.get("TREG_TOKEN") or os.environ.get("treg")
if not TREG_TOKEN:
    try:
        TREG_TOKEN = json.loads(Path.home().joinpath(".treg/config.json").read_text()).get("token")
    except Exception:
        pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
PLUSVIBE_API_KEY = os.environ.get("PLUSVIBE_API_KEY", "")

# Catalog costs (micro USD) - observed rates Nov 1, 2026
COST_HUNTER_DOMAIN = 0  # Free
COST_BLITZ_COMPANY = 495  # $0.000495 per success (assumption)
COST_LEADSFORGE_CALL = 5000  # $0.005 per call (observed after ~117 free calls)
COST_ICYPEAS_SEARCH = 380  # $0.00038 per row (observed)
COST_BLITZ_EMAIL = 500  # ~$0.0005 per hit (observed)
COST_MV = 1780  # $0.00178 per success (catalog)
COST_BB = 5000  # Up to $0.005 (catalog)

# Worker pool sizes
HUNTER_WORKERS = int(os.environ.get("HUNTER_WORKERS", "8"))
LEADSFORGE_WORKERS = int(os.environ.get("LEADSFORGE_WORKERS", "4"))
ICYPEAS_WORKERS = int(os.environ.get("ICYPEAS_WORKERS", "16"))
BLITZ_WORKERS = int(os.environ.get("BLITZ_WORKERS", "32"))
MV_WORKERS = int(os.environ.get("MV_WORKERS", "16"))

# Timeouts
DEFAULT_TIMEOUT = float(os.environ.get("DEFAULT_TIMEOUT", "120.0"))

# Output directory
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/cslb-leadsforge"))

# Decision-maker titles (Owner, CEO, President, Founder + current script titles)
DM_TITLES = [
    "Owner",
    "CEO",
    "Chief Executive Officer",
    "President",
    "Founder",
    "Co-Founder",
    "Principal",
    "Partner",
    "Managing Partner",
    "Managing Member",
    "Officer",
    "Responsible Managing Officer",
    "Responsible Managing Employee",
]

# Freemail domains
FREEMAIL = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "aol.com", "mail.com", "protonmail.com"
}


@dataclass
class CSLBCompany:
    """CSLB company from Supabase."""
    license_no: str
    business_name: str
    full_business_name: str = ""
    city: str = ""
    state: str = ""
    county: str = ""
    business_phone: str = ""
    primary_status: str = ""
    expiration_date: str = ""
    expiration_date_iso: str = ""
    classifications: str = ""
    business_type: str = ""
    primary_principal_name: str = ""
    primary_principal_first: str = ""
    primary_principal_last: str = ""
    company_domain: str = ""
    website: str = ""
    
    def display_name(self) -> str:
        return self.full_business_name or self.business_name or f"License {self.license_no}"


@dataclass
class Person:
    """Person through enrichment pipeline."""
    license_no: str = ""
    company_name: str = ""
    company_domain: str = ""
    
    # From LeadsForge
    lf_id: str = ""
    first_name: str = ""
    last_name: str = ""
    lf_title: str = ""
    lf_company: str = ""
    lf_location: str = ""
    
    # From Icypeas exact match
    linkedin_url: str = ""
    job_title: str = ""
    headline: str = ""
    company_website: str = ""
    company_industry: str = ""
    company_description: str = ""
    company_size: int = None
    location: str = ""
    
    # Email enrichment
    email: str = ""
    email_source: str = ""  # cache, blitz
    
    # Verification
    mv_result: str = ""  # ok, catch_all, invalid, unknown, disposable
    bb_result: str = ""  # deliverable, undeliverable
    
    # Status
    suppressed: bool = False
    cached: bool = False
    ready: bool = False
    
    # Metadata
    batch_id: str = ""
    enriched_at: str = ""


class CostTracker:
    """Thread-safe cost tracking with hard cap enforcement."""
    
    def __init__(self, hard_cap_usd: float):
        self.hard_cap_micro = int(hard_cap_usd * 1e6)
        self.spent_micro = 0
        self.reserved_micro = 0
        self.by_step = Counter()
        self.lock = threading.Lock()
    
    def reserve(self, amount_micro: int, step: str = "") -> None:
        """Reserve cost before calling API. Raises if would exceed cap."""
        with self.lock:
            if self.spent_micro + self.reserved_micro + amount_micro > self.hard_cap_micro:
                raise RuntimeError(
                    f"Cost cap exceeded before {step}: "
                    f"spent ${self.spent_micro/1e6:.4f} "
                    f"+ reserved ${self.reserved_micro/1e6:.4f} "
                    f"+ next ${amount_micro/1e6:.4f} "
                    f"> cap ${self.hard_cap_micro/1e6:.2f}"
                )
            self.reserved_micro += amount_micro
    
    def settle(self, reserved_micro: int, actual_micro: int, step: str) -> None:
        """Settle reserved cost with actual cost."""
        with self.lock:
            self.reserved_micro -= reserved_micro
            self.spent_micro += actual_micro
            self.by_step[step] += actual_micro
    
    def spent_usd(self) -> float:
        """Current spend in USD."""
        with self.lock:
            return self.spent_micro / 1e6
    
    def summary(self) -> dict:
        """Cost summary."""
        with self.lock:
            return {
                "spent_micro": self.spent_micro,
                "spent_usd": round(self.spent_micro / 1e6, 6),
                "cap_usd": round(self.hard_cap_micro / 1e6, 2),
                "by_step_usd": {k: round(v / 1e6, 6) for k, v in self.by_step.items()},
            }


class TregClient:
    """Treg API client with cost tracking."""
    
    def __init__(self, token: str, cost_tracker: CostTracker):
        self.token = token
        self.cost_tracker = cost_tracker
    
    def call(
        self,
        endpoint: str,
        body: dict = None,
        query: dict = None,
        headers: dict = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: bool = True,
    ) -> tuple[dict, int]:
        """Call Treg endpoint. Returns (response, cost_micro)."""
        url = f"https://treg.to/call/{endpoint}"
        if query:
            url += "?" + "&".join(f"{k}={v}" for k, v in query.items())
        
        hdrs = {
            "X-Treg-Token": self.token,
            "Accept": "application/json",
        }
        if body is not None:
            hdrs["Content-Type"] = "application/json"
        if headers:
            hdrs.update(headers)
        
        # Blitz email find route headers
        if "email.find" in endpoint:
            hdrs["X-Treg-Route-Max-Cost"] = "0.01"
            hdrs["X-Treg-Route-Waterfall"] = "0"
            hdrs["X-Treg-Route-Exclude"] = "aiark,icypeas"
        
        data = None if body is None else json.dumps(body).encode()
        attempts = 0
        max_attempts = 6 if retry else 1
        
        while attempts < max_attempts:
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers=hdrs,
                    method="POST" if body is not None else "GET",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
                    raw = resp.read()
                    result = json.loads(raw.decode()) if raw else {}
                    return result, cost
            
            except urllib.error.HTTPError as e:
                cost = int((e.headers or {}).get("X-Treg-Cost-Micro") or 0)
                
                # HTTP 429 rate limit - back off and retry
                if e.code == 429 and retry:
                    attempts += 1
                    if attempts < max_attempts:
                        backoff = min(30, 2 ** attempts) + (time.time() % 1)
                        print(f"[{endpoint}] HTTP 429, backoff {backoff:.1f}s (attempt {attempts}/{max_attempts})")
                        time.sleep(backoff)
                        continue
                
                # HTTP 402 payment required
                if e.code == 402:
                    raise RuntimeError(f"HTTP 402: insufficient balance")
                
                # Other errors
                try:
                    err_body = json.loads(e.read().decode())
                except Exception:
                    err_body = {"error": e.read().decode()[:300]}
                
                raise RuntimeError(f"HTTP {e.code}: {err_body}")
            
            except (urllib.error.URLError, TimeoutError) as e:
                attempts += 1
                if attempts < max_attempts and retry:
                    backoff = 2 ** attempts
                    print(f"[{endpoint}] Network error, retry {attempts}/{max_attempts} after {backoff}s: {e}")
                    time.sleep(backoff)
                    continue
                raise RuntimeError(f"Network error after {attempts} attempts: {e}")
        
        raise RuntimeError(f"Max retries exceeded for {endpoint}")


class SupabaseClient:
    """Supabase client for Lead Database operations."""
    
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key
    
    def _headers(self) -> dict:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    
    def query(self, table: str, select: str = "*", filters: dict = None, limit: int = None) -> list[dict]:
        """Query Supabase table."""
        url = f"{self.url}/rest/v1/{table}?select={select}"
        if filters:
            for k, v in filters.items():
                url += f"&{k}={v}"
        if limit:
            url += f"&limit={limit}"
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        
        # Paginate; PostgREST silently caps responses at 1000 rows
        out, page = [], 1000
        while True:
            req = urllib.request.Request(url + f"&offset={len(out)}&limit={page}", headers=self._headers())
            with urllib.request.urlopen(req, timeout=120) as resp:
                rows = json.loads(resp.read().decode())
            out.extend(rows)
            if len(rows) < page:
                return out
    
    def insert(self, table: str, rows: list[dict]) -> list[dict]:
        """Insert rows into Supabase table."""
        url = f"{self.url}/rest/v1/{table}"
        data = json.dumps(rows).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    
    def upsert(self, table: str, rows: list[dict], on_conflict: str = None) -> list[dict]:
        """Upsert rows into Supabase table."""
        url = f"{self.url}/rest/v1/{table}"
        if on_conflict:
            url += f"?on_conflict={on_conflict}"
        hdrs = self._headers()
        hdrs["Prefer"] = "resolution=merge-duplicates,return=representation"
        data = json.dumps(rows).encode()
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())


def norm_domain(value: str | None) -> str:
    """Normalize domain to bare host."""
    if not value:
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    if "://" not in v:
        v = "https://" + v
    try:
        host = urlparse(v).hostname or ""
    except Exception:
        host = ""
    host = host.lower().removeprefix("www.")
    return host


def norm_li(u: str) -> str:
    """Normalize LinkedIn URL."""
    return (u or "").lower().split("?")[0].rstrip("/")


def load_codicen_window(sb: SupabaseClient, window_days: int = 90) -> list[CSLBCompany]:
    """Load CSLB companies in Codicen window (CLEAR, expiring 0-N days)."""
    today = datetime.now().date().isoformat()
    end_date = (datetime.now().date() + timedelta(days=window_days)).isoformat()
    
    print(f"Loading Codicen window from Supabase (window: {window_days} days)...")
    rows = sb.query(
        "cslb_companies",
        select="license_no,business_name,full_business_name,city,state,county,business_phone,"
               "primary_status,expiration_date,expiration_date_iso,classifications,business_type,"
               "primary_principal_name,primary_principal_first,primary_principal_last,"
               "company_domain,website",
        filters={
            "client": "eq.Codicen",
            "primary_status": "eq.CLEAR",
            "and": f"(expiration_date_iso.gte.{today},expiration_date_iso.lte.{end_date})",
        },
    )
    companies = [CSLBCompany(**{k: v or "" for k, v in r.items()}) for r in rows]
    print(f"  Loaded {len(companies):,} companies in window (CLEAR, exp {today} to {end_date}, {window_days} days)")
    return companies


def load_plusvibe_suppression() -> tuple[set[str], set[str], set[str]]:
    """Load PlusVibe workspace leads and blocklist for Codicen."""
    if not PLUSVIBE_API_KEY:
        print("  PlusVibe: no API key, skipping")
        return set(), set(), set()
    
    print("  Loading PlusVibe workspace suppression...")
    
    linkedin_urls = set()
    emails = set()
    domains = set()
    
    # Get Codicen workspace ID (assumption: first workspace or known ID)
    # TODO: Update with actual Codicen workspace ID when known
    workspace_id = None
    
    try:
        # List workspaces
        req = urllib.request.Request(
            "https://api.plusvibe.com/v1/workspaces",
            headers={"Authorization": f"Bearer {PLUSVIBE_API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            workspaces = json.loads(resp.read().decode())
        
        # Find Codicen workspace
        for ws in workspaces.get("workspaces", []):
            if "codicen" in ws.get("name", "").lower():
                workspace_id = ws.get("id")
                break
        
        if not workspace_id and workspaces.get("workspaces"):
            workspace_id = workspaces["workspaces"][0].get("id")
        
        if not workspace_id:
            print("    No PlusVibe workspace found")
            return set(), set(), set()
        
        print(f"    Workspace ID: {workspace_id}")
        
        # Get all leads from workspace
        req = urllib.request.Request(
            f"https://api.plusvibe.com/v1/workspaces/{workspace_id}/leads",
            headers={"Authorization": f"Bearer {PLUSVIBE_API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            leads_data = json.loads(resp.read().decode())
        
        for lead in leads_data.get("leads", []):
            if lead.get("linkedin_url"):
                linkedin_urls.add(norm_li(lead["linkedin_url"]))
            if lead.get("email"):
                emails.add(lead["email"].lower().strip())
            if lead.get("company_domain"):
                domains.add(norm_domain(lead["company_domain"]))
        
        # Get blocklist
        req = urllib.request.Request(
            f"https://api.plusvibe.com/v1/workspaces/{workspace_id}/blocklist",
            headers={"Authorization": f"Bearer {PLUSVIBE_API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            blocklist_data = json.loads(resp.read().decode())
        
        for item in blocklist_data.get("blocklist", []):
            if item.get("linkedin_url"):
                linkedin_urls.add(norm_li(item["linkedin_url"]))
            if item.get("email"):
                emails.add(item["email"].lower().strip())
            if item.get("domain"):
                domains.add(norm_domain(item["domain"]))
        
        print(f"    PlusVibe: {len(linkedin_urls)} LinkedIn, {len(emails)} emails, {len(domains)} domains")
        
    except Exception as e:
        print(f"    PlusVibe error (non-fatal): {e}")
    
    return linkedin_urls, emails, domains


def load_suppression_sets(sb: SupabaseClient, allow_empty: bool = False) -> tuple[set[str], set[str], set[str]]:
    """Load suppression sets from Supabase + PlusVibe (LinkedIn, emails, domains)."""
    print("Loading suppression sets...")
    
    linkedin_urls = set()
    emails = set()
    domains = set()
    
    # From codicen_campaign_leads
    rows = sb.query("codicen_campaign_leads", select="linkedin,email,company_domain")
    for r in rows:
        if r.get("linkedin"):
            linkedin_urls.add(norm_li(r["linkedin"]))
        if r.get("email"):
            emails.add(r["email"].lower().strip())
        if r.get("company_domain"):
            domains.add(norm_domain(r["company_domain"]))
    
    print(f"  Supabase codicen_campaign_leads: {len(linkedin_urls)} LinkedIn, {len(emails)} emails, {len(domains)} domains")
    
    # From pipeline_leads (Codicen campaign)
    rows = sb.query("pipeline_leads", select="linkedin,email,company_domain", filters={"client": "eq.Codicen"})
    for r in rows:
        if r.get("linkedin"):
            linkedin_urls.add(norm_li(r["linkedin"]))
        if r.get("email"):
            emails.add(r["email"].lower().strip())
        if r.get("company_domain"):
            domains.add(norm_domain(r["company_domain"]))
    
    print(f"  Supabase pipeline_leads (Codicen): +{len(linkedin_urls) - len(set())} LinkedIn, +{len(emails) - len(set())} emails, +{len(domains) - len(set())} domains")
    
    # From PlusVibe
    pv_linkedin, pv_emails, pv_domains = load_plusvibe_suppression()
    linkedin_urls.update(pv_linkedin)
    emails.update(pv_emails)
    domains.update(pv_domains)
    
    print(f"  TOTAL suppression: {len(linkedin_urls):,} LinkedIn, {len(emails):,} emails, {len(domains):,} domains")
    
    if not linkedin_urls and not emails and not allow_empty:
        raise RuntimeError(
            "ABORT: Both LinkedIn and email suppression sets are empty! "
            "This risks duplicates. Pass --allow-empty-suppression to override."
        )
    
    if not linkedin_urls and not emails:
        print("  WARNING: Both LinkedIn and email suppression sets are empty (--allow-empty-suppression passed)")
    
    return linkedin_urls, emails, domains


def load_supabase_cache(sb: SupabaseClient, days: int = 30) -> dict[str, dict]:
    """Load Supabase 30-day email cache keyed by LinkedIn URL, email, and name+domain.
    
    Checks ALL clients' pipeline_leads rows (not just Codicen) to never pay twice for the same person.
    """
    print(f"Loading Supabase {days}-day email cache (all clients)...")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    cache_by_linkedin = {}
    cache_by_email = {}
    cache_by_name_domain = {}
    
    # From pipeline_leads (ALL clients, ~70k recent rows)
    rows = sb.query(
        "pipeline_leads",
        select="linkedin,email,email_source,mv_status,first_name,last_name,company_domain,updated_at",
        filters={
            "email": "not.is.null",
            "updated_at": f"gte.{cutoff}",
        },
    )
    
    for r in rows:
        email = (r.get("email") or "").lower().strip()
        if not email:
            continue
        
        # Cache by LinkedIn URL
        if r.get("linkedin"):
            li_norm = norm_li(r["linkedin"])
            cache_by_linkedin[li_norm] = {
                "email": email,
                "source": r.get("email_source", "unknown"),
                "mv_result": r.get("mv_status"),
                "fresh": True,
            }
        
        # Cache by email
        cache_by_email[email] = {
            "email": email,
            "source": r.get("email_source", "unknown"),
            "mv_result": r.get("mv_status"),
            "fresh": True,
        }
        
        # Cache by name+domain
        first = (r.get("first_name") or "").lower().strip()
        last = (r.get("last_name") or "").lower().strip()
        domain = norm_domain(r.get("company_domain") or "")
        if first and last and domain:
            key = f"{first}|{last}|{domain}"
            cache_by_name_domain[key] = {
                "email": email,
                "source": r.get("email_source", "unknown"),
                "mv_result": r.get("mv_status"),
                "fresh": True,
            }
    
    print(f"  Cache: {len(cache_by_linkedin):,} LinkedIn, {len(cache_by_email):,} emails, {len(cache_by_name_domain):,} name+domain (<{days} days old)")
    
    return {
        "linkedin": cache_by_linkedin,
        "email": cache_by_email,
        "name_domain": cache_by_name_domain,
    }


def resolve_domains_batch(
    companies: list[CSLBCompany],
    treg: TregClient,
    cost_tracker: CostTracker,
    with_hunter_fallback: bool = False,
    with_paid: bool = False,
) -> list[CSLBCompany]:
    """Resolve company domains (Clearbit primary, optional Hunter fallback + paid Blitz)."""
    fallback_str = ""
    if with_hunter_fallback:
        fallback_str = " + Hunter fallback"
    if with_paid:
        fallback_str += " + Blitz paid"
    
    print(f"\n=== Stage 1: Domain Resolution (Clearbit free{fallback_str}) ===")
    
    updated = []
    stats = Counter()
    
    with ThreadPoolExecutor(max_workers=HUNTER_WORKERS, thread_name_prefix="Resolve") as pool:
        futures = {}
        for company in companies:
            if company.company_domain or company.website:
                stats["already_had_domain"] += 1
                updated.append(company)
                continue
            
            if not company.display_name():
                stats["no_name"] += 1
                updated.append(company)
                continue
            
            future = pool.submit(_resolve_one_domain, company, treg, cost_tracker, with_hunter_fallback, with_paid)
            futures[future] = company
        
        for future in as_completed(futures):
            company = futures[future]
            try:
                resolved = future.result()
                updated.append(resolved)
                if resolved.company_domain:
                    stats["hunter_resolved"] += 1
                else:
                    stats["no_domain"] += 1
            except Exception as e:
                print(f"  Error resolving {company.display_name()[:40]}: {e}")
                stats["error"] += 1
                updated.append(company)
    
    print(f"\nDomain resolution: {dict(stats)}")
    print(f"  Total with domain: {sum(1 for c in updated if c.company_domain):,}")
    return updated


def _resolve_one_domain(
    company: CSLBCompany,
    treg: TregClient,
    cost_tracker: CostTracker,
    with_hunter_fallback: bool = False,
    with_paid: bool = False,
) -> CSLBCompany:
    """Resolve one company domain (Clearbit primary, optional Hunter fallback)."""
    name = company.display_name()
    
    # 1. Clearbit autocomplete (free, no key, primary)
    domain = _clearbit_domain_finder(name)
    if domain:
        cost_tracker.incr_counter("clearbit_hit")
        company.company_domain = domain
        company.website = f"https://{domain}"
        return company
    
    cost_tracker.incr_counter("clearbit_miss")
    
    # 2. Hunter fallback (optional, free)
    if with_hunter_fallback:
        domain = _hunter_domain_finder(name, treg, cost_tracker)
        if domain:
            cost_tracker.incr_counter("hunter_hit")
            company.company_domain = domain
            company.website = f"https://{domain}"
            return company
        
        cost_tracker.incr_counter("hunter_miss")
    
    # 3. Optional paid Blitz company enrich
    if with_paid:
        try:
            cost_tracker.reserve(COST_BLITZ_COMPANY, "blitz_company")
            out, cost = treg.call("blitzapi.companies.enrich", {"name": name})
            cost_tracker.settle(COST_BLITZ_COMPANY, cost, "blitz_company")
            
            if isinstance(out, dict):
                website = (
                    out.get("website")
                    or out.get("domain")
                    or (out.get("company") or {}).get("website")
                    or ""
                )
                domain = norm_domain(website)
                
                # Apply same strict check
                if domain and _is_us_domain(domain) and _score_domain_match(domain, name) >= 0.7:
                    company.company_domain = domain
                    company.website = f"https://{domain}"
                    cost_tracker.incr_counter("blitz_hit")
                    return company
        
        except Exception as e:
            cost_tracker.settle(COST_BLITZ_COMPANY, 0, "blitz_company")
    
    return company


def _clean_company_name(name: str) -> str:
    """Clean company name by removing legal suffixes and common noise."""
    if not name:
        return ""
    
    # Remove common legal suffixes (case-insensitive)
    suffixes = [
        r'\bINC\.?$', r'\bLLC\.?$', r'\bCORP\.?$', r'\bLTD\.?$',
        r'\bCONST\.?$', r'\bCONSTRUCTION$', r'\bCONTRACTORS?$',
        r'\bENTERPRISES?$', r'\bCOMPANY$', r'\bCO\.?$',
        r'\bGROUP$', r'\bSERVICES?$', r'\bSOLUTIONS?$',
    ]
    
    cleaned = name.upper()
    for suffix in suffixes:
        cleaned = re.sub(suffix, '', cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()


def _is_us_domain(domain: str) -> bool:
    """Check if domain is US-based (reject .com.au, .co.uk, etc.)."""
    if not domain:
        return False
    
    # Reject non-US country TLDs
    non_us_tlds = [
        '.com.au', '.co.uk', '.com.mx', '.ca', '.com.br',
        '.de', '.fr', '.es', '.it', '.nl', '.jp', '.cn',
        '.in', '.com.sg', '.com.hk', '.co.nz', '.ie',
    ]
    
    domain_lower = domain.lower()
    return not any(domain_lower.endswith(tld) for tld in non_us_tlds)


def _score_domain_match(domain: str, company_name: str, candidate_name: str = "") -> float:
    """Score how well a domain matches a company name (0.0 to 1.0).
    
    Requires strong normalized match between candidate and license name.
    """
    if not domain or not company_name:
        return 0.0
    
    # Clean both names
    cleaned_company = _clean_company_name(company_name)
    cleaned_candidate = _clean_company_name(candidate_name) if candidate_name else ""
    
    # Extract domain base (before first dot)
    domain_base = domain.split(".")[0].lower()
    
    # Normalize: remove spaces, dashes, underscores
    company_norm = re.sub(r'[^\w]', '', cleaned_company).lower()
    candidate_norm = re.sub(r'[^\w]', '', cleaned_candidate).lower() if cleaned_candidate else ""
    domain_norm = re.sub(r'[^\w]', '', domain_base).lower()
    
    # Exact match
    if domain_norm == company_norm or (candidate_norm and domain_norm == candidate_norm):
        return 1.0
    
    # Strong substring match (domain in company or company in domain)
    if len(domain_norm) >= 5:
        if domain_norm in company_norm or company_norm in domain_norm:
            return 0.9
        if candidate_norm and (domain_norm in candidate_norm or candidate_norm in domain_norm):
            return 0.85
    
    # Token overlap (count of matching significant words)
    company_tokens = set(t for t in re.findall(r'\w+', company_norm) if len(t) > 3)
    domain_tokens = set(t for t in re.findall(r'\w+', domain_norm) if len(t) > 3)
    
    if not company_tokens:
        return 0.0
    
    overlap = len(company_tokens & domain_tokens)
    if overlap > 0:
        return min(0.7, 0.4 + (overlap * 0.15))
    
    return 0.0


def _clearbit_domain_finder(company_name: str) -> str | None:
    """Find domain using Clearbit autocomplete (free, no key required).
    
    Returns best matching domain or None if no strong match.
    """
    if not company_name:
        return None
    
    try:
        query = urllib.parse.quote(company_name)
        url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={query}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read().decode())
        
        if not isinstance(results, list) or not results:
            return None
        
        # Score all candidates
        best_domain = None
        best_score = 0.0
        
        for candidate in results[:5]:  # Check top 5
            domain = candidate.get("domain", "")
            name = candidate.get("name", "")
            
            if not domain:
                continue
            
            # Reject non-US domains
            if not _is_us_domain(domain):
                continue
            
            score = _score_domain_match(domain, company_name, name)
            
            if score > best_score:
                best_score = score
                best_domain = domain
        
        # Require strong match (0.7+ score)
        if best_score >= 0.7:
            return best_domain
        
        return None
        
    except Exception as e:
        # Clearbit errors are silent (not critical)
        return None


def _hunter_domain_finder(company_name: str, treg: TregClient, cost_tracker: CostTracker) -> str | None:
    """Find domain using Hunter (free, optional fallback).
    
    Returns best matching domain or None if no strong match.
    """
    if not company_name:
        return None
    
    try:
        out, cost = treg.call("hunter.x.domain-finder", query={"company": urllib.parse.quote(company_name)})
        cost_tracker.settle(0, cost, "hunter_domain")
        
        # Parse candidates
        candidates = []
        if isinstance(out, dict):
            if isinstance(out.get("data"), list):
                candidates = out["data"]
            elif out.get("domain"):
                candidates = [{"domain": out["domain"]}]
            elif out.get("domains"):
                candidates = out["domains"]
        
        if not candidates:
            return None
        
        # Score all candidates
        best_domain = None
        best_score = 0.0
        
        for candidate in candidates:
            domain = candidate.get("domain", "")
            if not domain:
                continue
            
            # Reject non-US domains
            if not _is_us_domain(domain):
                continue
            
            score = _score_domain_match(domain, company_name)
            
            if score > best_score:
                best_score = score
                best_domain = domain
        
        # Require strong match (0.7+ score)
        if best_score >= 0.7:
            return best_domain
        
        return None
        
    except Exception:
        return None


def leadsforge_search(
    companies: list[CSLBCompany],
    treg: TregClient,
    cost_tracker: CostTracker,
    suppress_domains: set[str],
    suppress_emails: set[str],
    suppress_linkedin: set[str],
) -> list[Person]:
    """
    LeadsForge people search with batched domains.
    IMPORTANT: LeadsForge charges $0.005 per call after ~117 free calls, so minimize call count.
    
    Observed: ~117 calls free, then $0.005/call (Nov 1, 2026)
    """
    print(f"\n=== Stage 2: LeadsForge People Search (batched domains) ===")
    
    # Filter to companies with domains and not suppressed
    valid_companies = [
        c for c in companies
        if c.company_domain and norm_domain(c.company_domain) not in suppress_domains
    ]
    
    if not valid_companies:
        print("  No companies with valid domains to search")
        return []
    
    print(f"  {len(valid_companies):,} companies with domains (not suppressed)")
    
    # Batch domains (LeadsForge accepts multiple domains per call)
    batch_size = int(os.environ.get("LF_BATCH_SIZE", "25"))  # Balance: API limits vs call minimization
    company_by_domain = {norm_domain(c.company_domain): c for c in valid_companies}
    domains = list(company_by_domain.keys())
    
    # Never put a domain in both include and exclude (breaks include filter)
    exclude_domains_clean = [d for d in suppress_domains if d not in domains]
    
    domain_batches = [domains[i:i+batch_size] for i in range(0, len(domains), batch_size)]
    
    print(f"  Batched into {len(domain_batches)} LeadsForge calls ({batch_size} domains/call)")
    print(f"  Suppression: {len(exclude_domains_clean)} domains, {len(suppress_emails)} emails, {len(suppress_linkedin)} LinkedIn URLs")
    
    all_people = []
    
    for batch_idx, domain_batch in enumerate(domain_batches):
        try:
            # Reserve cost for this LeadsForge call
            cost_tracker.reserve(COST_LEADSFORGE_CALL, "leadsforge")
            
            # LeadsForge people search query
            query = {
                "companyDomains": {"include": domain_batch},
                "leadJobTitles": {"include": DM_TITLES},
                "leadLocations": {"include": ["United States"]},
                "companyLocations": {"include": ["United States"]},
                "excludeEmails": list(suppress_emails),
                "excludeDomains": exclude_domains_clean,
                "excludeLinkedInURLs": list(suppress_linkedin),
                "limit": 100,
            }
            
            print(f"  LeadsForge call {batch_idx+1}/{len(domain_batches)} ({len(domain_batch)} domains)...")
            
            # Call LeadsForge
            out, cost = treg.call("leadsforge.people.search", body=query, timeout=120.0)
            cost_tracker.settle(COST_LEADSFORGE_CALL, cost, "leadsforge")
            
            # Parse response
            people = _parse_leadsforge_response(out, company_by_domain)
            all_people.extend(people)
            
            print(f"    Found {len(people)} people (cost: ${cost/1e6:.6f})")
            time.sleep(0.5)  # Rate limit
        
        except Exception as e:
            cost_tracker.settle(COST_LEADSFORGE_CALL, 0, "leadsforge")
            print(f"  LeadsForge error batch {batch_idx+1}: {e}")
            continue
    
    print(f"\nLeadsForge: {len(all_people):,} people found across {len(valid_companies):,} companies")
    return all_people


def _parse_leadsforge_response(response: dict, company_by_domain: dict[str, CSLBCompany]) -> list[Person]:
    """Parse LeadsForge API response into Person objects.
    
    Response structure (observed Nov 1, 2026):
    {
        "leads": [
            {
                "id": "...",
                "firstName": "...", "lastName": "...", "jobTitle": "...",
                "location": {"city": "...", "state": "...", "country": "..."},
                "company": {
                    "id": "...", "domain": "...", "website": "...",
                    "employeeCount": N, "industry": "...", "keywords": [...],
                    "location": {...}, "revenueRange": {...}, "yearsInBusiness": N
                }
            }
        ],
        ... paging/meta ...
    }
    
    NOTE: NO LinkedIn URL, NO email in response (that's why Icypeas exact-person comes next).
    """
    people = []
    
    if not isinstance(response, dict):
        return people
    
    leads = response.get("leads", [])
    
    for item in leads:
        if not isinstance(item, dict):
            continue
        
        # Extract company domain
        company_info = item.get("company", {})
        if not isinstance(company_info, dict):
            continue
        
        domain = norm_domain(company_info.get("domain", ""))
        if not domain:
            # Try website as fallback
            domain = norm_domain(company_info.get("website", ""))
        
        if not domain:
            continue
        
        company = company_by_domain.get(domain)
        if not company:
            continue
        
        # Extract location
        loc_info = item.get("location", {})
        if isinstance(loc_info, dict):
            location = ", ".join(filter(None, [
                loc_info.get("city", ""),
                loc_info.get("state", ""),
                loc_info.get("country", "")
            ]))
        else:
            location = ""
        
        # Extract company size
        company_size = company_info.get("employeeCount")
        
        person = Person(
            license_no=company.license_no,
            company_name=company.display_name(),
            company_domain=company.company_domain,
            lf_id=item.get("id", ""),
            first_name=item.get("firstName", ""),
            last_name=item.get("lastName", ""),
            lf_title=item.get("jobTitle", ""),
            lf_company=company_info.get("domain", ""),
            lf_location=location,
            company_size=company_size,
            company_industry=company_info.get("industry", ""),
        )
        people.append(person)
    
    return people


def icypeas_exact_match(
    people: list[Person],
    treg: TregClient,
    cost_tracker: CostTracker,
) -> list[Person]:
    """
    Icypeas exact-person search: batched by first name, last name, currentCompanyWebsite.
    ~25 people per query at $0.00038 per row returned.
    """
    print(f"\n=== Stage 3: Icypeas Exact-Person Match (batched ~25/query) ===")
    
    if not people:
        return []
    
    # Batch people by ~25 per query
    batch_size = 25
    batches = [people[i:i+batch_size] for i in range(0, len(people), batch_size)]
    
    print(f"  {len(people):,} people → {len(batches)} Icypeas queries")
    
    matched = []
    
    with ThreadPoolExecutor(max_workers=ICYPEAS_WORKERS, thread_name_prefix="Icypeas") as pool:
        futures = {}
        for batch in batches:
            future = pool.submit(_icypeas_batch, batch, treg, cost_tracker)
            futures[future] = batch
        
        for future in as_completed(futures):
            batch = futures[future]
            try:
                batch_matched = future.result()
                matched.extend(batch_matched)
            except Exception as e:
                print(f"  Icypeas batch error: {e}")
    
    print(f"\nIcypeas matched: {len(matched):,} / {len(people):,} people")
    return matched


def _icypeas_batch(
    batch: list[Person],
    treg: TregClient,
    cost_tracker: CostTracker,
) -> list[Person]:
    """Process one Icypeas batch (first names, last names, domains as arrays)."""
    if not batch:
        return []
    
    # Build query with include arrays
    first_names = list({p.first_name for p in batch if p.first_name})
    last_names = list({p.last_name for p in batch if p.last_name})
    domains = list({p.company_domain for p in batch if p.company_domain})
    
    query = {
        "firstname": {"include": first_names},
        "lastname": {"include": last_names},
        "currentCompanyWebsite": {"include": domains},
        "profileLocation": {"include": ["US", "California, US", "CA, US"]},
    }
    
    # Reserve estimated cost (batch_size * cost per row)
    estimated_cost = len(batch) * COST_ICYPEAS_SEARCH
    cost_tracker.reserve(estimated_cost, "icypeas")
    
    try:
        out, cost = treg.call(
            "icypeas.people.search",
            body={"query": query, "pagination": {"size": min(200, len(batch) * 3)}},
        )
        cost_tracker.settle(estimated_cost, cost, "icypeas")
        
        # Match Icypeas results back to batch by name+domain
        leads = out.get("leads") or []
        matched = _match_icypeas_to_batch(leads, batch)
        
        return matched
    
    except Exception as e:
        cost_tracker.settle(estimated_cost, 0, "icypeas")
        raise


def _match_icypeas_to_batch(leads: list[dict], batch: list[Person]) -> list[Person]:
    """Match Icypeas leads back to batch people by name+domain, drop cross-combinations."""
    matched = []
    
    # Build lookup: (first, last, domain) -> Person
    lookup = {}
    for p in batch:
        key = (p.first_name.lower(), p.last_name.lower(), norm_domain(p.company_domain))
        lookup[key] = p
    
    for lead in leads:
        first = (lead.get("firstname") or "").lower()
        last = (lead.get("lastname") or "").lower()
        domain = norm_domain(lead.get("lastCompanyWebsite") or "")
        
        key = (first, last, domain)
        person = lookup.get(key)
        if not person:
            continue  # Cross-combination, drop
        
        # Enrich person with Icypeas data
        person.linkedin_url = lead.get("profileUrl", "")
        person.job_title = lead.get("lastJobTitle") or lead.get("headline") or ""
        person.headline = lead.get("headline", "")
        person.company_website = lead.get("lastCompanyWebsite", "")
        person.company_industry = lead.get("lastCompanyIndustry", "")
        person.company_description = (lead.get("lastCompanyDescription") or "")[:500]
        person.company_size = lead.get("lastCompanySize")
        person.location = lead.get("address") or lead.get("lastCompanyAddress") or ""
        
        matched.append(person)
    
    return matched


def check_cache_and_enrich(
    people: list[Person],
    cache: dict[str, dict],
    treg: TregClient,
    cost_tracker: CostTracker,
    suppress_emails: set[str],
    suppress_linkedin: set[str],
) -> list[Person]:
    """
    Stage 4-5: Supabase cache check, then Blitz email find.
    """
    print(f"\n=== Stage 4-5: Cache Check + Blitz Email Find ===")
    
    if not people:
        return []
    
    stats = Counter()
    
    # Check cache first (LinkedIn, email, name+domain)
    for person in people:
        li_norm = norm_li(person.linkedin_url)
        
        # Check LinkedIn suppression
        if li_norm in suppress_linkedin:
            person.suppressed = True
            stats["linkedin_suppressed"] += 1
            continue
        
        # Check cache by LinkedIn
        if li_norm and li_norm in cache.get("linkedin", {}):
            cached = cache["linkedin"][li_norm]
            person.email = cached["email"]
            person.email_source = f"cache:{cached['source']}"
            person.mv_result = cached.get("mv_result", "")
            person.cached = True
            stats["cache_hit_linkedin"] += 1
            continue
        
        # Check cache by email (if person already has email somehow)
        if person.email:
            email_lower = person.email.lower().strip()
            if email_lower in cache.get("email", {}):
                cached = cache["email"][email_lower]
                person.mv_result = cached.get("mv_result", "")
                person.cached = True
                stats["cache_hit_email"] += 1
                continue
        
        # Check cache by name+domain
        first = person.first_name.lower().strip()
        last = person.last_name.lower().strip()
        domain = norm_domain(person.company_domain)
        if first and last and domain:
            key = f"{first}|{last}|{domain}"
            if key in cache.get("name_domain", {}):
                cached = cache["name_domain"][key]
                person.email = cached["email"]
                person.email_source = f"cache:{cached['source']}"
                person.mv_result = cached.get("mv_result", "")
                person.cached = True
                stats["cache_hit_name_domain"] += 1
                continue
    
    # Find people needing email enrichment
    need_email = [p for p in people if not p.email and not p.suppressed and p.linkedin_url]
    
    total_cache_hits = stats.get("cache_hit_linkedin", 0) + stats.get("cache_hit_email", 0) + stats.get("cache_hit_name_domain", 0)
    print(f"  Cache hits: {total_cache_hits} / {len(people)} (LinkedIn: {stats.get('cache_hit_linkedin', 0)}, email: {stats.get('cache_hit_email', 0)}, name+domain: {stats.get('cache_hit_name_domain', 0)})")
    print(f"  Need Blitz: {len(need_email)}")
    
    if not need_email:
        return people
    
    # Blitz email find (concurrent)
    with ThreadPoolExecutor(max_workers=BLITZ_WORKERS, thread_name_prefix="Blitz") as pool:
        futures = {}
        for person in need_email:
            future = pool.submit(_blitz_email_find, person, treg, cost_tracker)
            futures[future] = person
        
        for future in as_completed(futures):
            person = futures[future]
            try:
                email = future.result()
                if email:
                    person.email = email
                    person.email_source = "blitz"
                    stats["blitz_hit"] += 1
                else:
                    stats["blitz_miss"] += 1
            except Exception as e:
                print(f"  Blitz error for {person.first_name} {person.last_name}: {e}")
                stats["blitz_error"] += 1
    
    # Check email suppression and freemail
    for person in people:
        if not person.email:
            continue
        
        email_lower = person.email.lower().strip()
        domain = email_lower.split("@")[-1]
        
        # Freemail check
        if domain in FREEMAIL:
            person.email = ""
            person.email_source = ""
            stats["freemail_drop"] += 1
            continue
        
        # Email suppression
        if email_lower in suppress_emails:
            person.suppressed = True
            person.email = ""
            person.email_source = ""
            stats["email_suppressed"] += 1
    
    print(f"\nEmail enrichment: {dict(stats)}")
    return people


def _blitz_email_find(person: Person, treg: TregClient, cost_tracker: CostTracker) -> str | None:
    """Find email for one person via Blitz."""
    if not person.linkedin_url:
        return None
    
    cost_tracker.reserve(COST_BLITZ_EMAIL, "blitz_email")
    
    try:
        out, cost = treg.call(
            "blitzapi.people.email.find",
            body={"person_linkedin_url": person.linkedin_url},
        )
        cost_tracker.settle(COST_BLITZ_EMAIL, cost, "blitz_email")
        
        email = None
        if isinstance(out, dict):
            email = out.get("email")
            if not email:
                for item in out.get("all_emails") or []:
                    if isinstance(item, dict) and item.get("email"):
                        email = item["email"]
                        break
        
        return (email or "").lower().strip() or None
    
    except Exception as e:
        cost_tracker.settle(COST_BLITZ_EMAIL, 0, "blitz_email")
        raise


def verify_emails(
    people: list[Person],
    treg: TregClient,
    cost_tracker: CostTracker,
) -> list[Person]:
    """
    Stage 6: MillionVerifier + BounceBan (catch-alls).
    """
    print(f"\n=== Stage 6: Email Verification (MV + BounceBan) ===")
    
    to_verify = [p for p in people if p.email and not p.mv_result and not p.cached]
    
    if not to_verify:
        print("  No emails to verify")
        return people
    
    print(f"  Verifying {len(to_verify)} emails...")
    
    # MillionVerifier
    with ThreadPoolExecutor(max_workers=MV_WORKERS, thread_name_prefix="MV") as pool:
        futures = {}
        for person in to_verify:
            future = pool.submit(_mv_one, person.email, treg, cost_tracker)
            futures[future] = person
        
        for future in as_completed(futures):
            person = futures[future]
            try:
                result = future.result()
                person.mv_result = result
            except Exception as e:
                print(f"  MV error for {person.email}: {e}")
                person.mv_result = "error"
    
    # BounceBan for catch-alls (async, non-blocking for now)
    catch_alls = [p for p in to_verify if p.mv_result == "catch_all"]
    if catch_alls:
        print(f"  {len(catch_alls)} catch-alls → BounceBan (async, results may be pending)")
        # TODO: Implement BounceBan async polling
    
    # Mark ready
    for person in people:
        if person.email and person.mv_result in ("ok", "catch_all"):
            person.ready = True
    
    ready_count = sum(1 for p in people if p.ready)
    print(f"  Ready: {ready_count} / {len(people)}")
    
    return people


def _mv_one(email: str, treg: TregClient, cost_tracker: CostTracker) -> str:
    """Verify one email with MillionVerifier."""
    cost_tracker.reserve(COST_MV, "mv")
    
    try:
        out, cost = treg.call(
            "millionverifier.people.email.verify",
            query={"email": email},
        )
        cost_tracker.settle(COST_MV, cost, "mv")
        
        result = out.get("result") if isinstance(out, dict) else "error"
        return result
    
    except Exception as e:
        cost_tracker.settle(COST_MV, 0, "mv")
        return "error"


def upsert_to_supabase(
    people: list[Person],
    sb: SupabaseClient,
    batch_id: str,
) -> dict:
    """
    Stage 7: Upsert to Lead Database, pipeline_leads, create lead_list + members, merge to codicen_campaign_leads.
    """
    print(f"\n=== Stage 7: Supabase Upload ===")
    
    ready = [p for p in people if p.ready]
    
    if not ready:
        print("  No ready leads to upload")
        return {"ready": 0, "list_id": None}
    
    print(f"  Uploading {len(ready)} ready leads...")
    
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # Step 1: Insert/update Lead Database rows (core lead identity table)
    print("  Creating Lead Database entries...")
    lead_db_rows = []
    email_to_person = {}
    
    for p in ready:
        lead_db_rows.append({
            "email": p.email,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "linkedin_url": p.linkedin_url,
            "company_domain": p.company_domain,
            "created_at": now_iso,
            "updated_at": now_iso,
        })
        email_to_person[p.email] = p
    
    # Upsert to Lead Database (on conflict: email)
    lead_db_result = sb.upsert("Lead Database", lead_db_rows, on_conflict="email")
    
    # Build email -> lead_database_id mapping
    email_to_lead_id = {}
    if lead_db_result:
        for row in lead_db_result:
            email_to_lead_id[row["email"]] = row["id"]
    
    # Step 2: Upsert to pipeline_leads with lead_database_id
    print("  Upserting to pipeline_leads...")
    pipeline_rows = []
    
    for p in ready:
        lead_db_id = email_to_lead_id.get(p.email)
        row = {
            "client": "Codicen",
            "campaign_id": "cslb_leadsforge",
            "batch_id": batch_id,
            "lead_database_id": lead_db_id,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "email": p.email,
            "title": p.job_title or p.lf_title,
            "linkedin": p.linkedin_url,
            "company_name": p.company_name,
            "company_domain": p.company_domain,
            "company_website": p.company_website,
            "company_description": p.company_description,
            "company_size": p.company_size,
            "location": p.location or p.lf_location,
            "email_source": p.email_source,
            "mv_status": p.mv_result,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        pipeline_rows.append(row)
    
    # Upsert to pipeline_leads (on conflict: email)
    sb.upsert("pipeline_leads", pipeline_rows, on_conflict="email")
    
    # Step 3: Create lead_list entry
    print("  Creating lead list...")
    list_row = {
        "client": "Codicen",
        "campaign_id": "cslb_leadsforge",
        "batch_id": batch_id,
        "name": f"CSLB LeadsForge {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "source": "leadsforge_icypeas_blitz",
        "total_leads": len(ready),
        "ready_leads": len(ready),
        "created_at": now_iso,
    }
    list_result = sb.insert("lead_lists", [list_row])
    list_id = list_result[0]["id"] if list_result else None
    
    # Step 4: Create lead_list_members (many-to-many join with Lead Database)
    if list_id and email_to_lead_id:
        print("  Creating lead list members...")
        member_rows = []
        
        for p in ready:
            lead_db_id = email_to_lead_id.get(p.email)
            if not lead_db_id:
                continue
            
            # enrichment_status: pending, in_progress, enriched, failed, skipped
            # Use "enriched" for ready leads, "failed" for non-ready
            status = "enriched" if p.ready else "failed"
            
            member_rows.append({
                "list_id": list_id,
                "lead_id": lead_db_id,
                "enrichment_status": status,
                "created_at": now_iso,
                "updated_at": now_iso,
            })
        
        if member_rows:
            try:
                sb.insert("lead_list_members", member_rows)
                print(f"    Created {len(member_rows)} lead list members")
            except Exception as e:
                print(f"    Warning: lead_list_members insert failed: {e}")
    
    # Step 5: Merge to codicen_campaign_leads
    print("  Merging to codicen_campaign_leads...")
    campaign_rows = []
    
    for p in ready:
        row = {
            "license_no": p.license_no,
            "client": "Codicen",
            "campaign_id": "cslb_leadsforge",
            "batch_id": batch_id,
            "company_name": p.company_name,
            "company_domain": p.company_domain,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "title": p.job_title or p.lf_title,
            "email": p.email,
            "linkedin": p.linkedin_url,
            "company_description": p.company_description,
            "location": p.location or p.lf_location,
            "company_size": str(p.company_size) if p.company_size else "",
            "email_source": p.email_source,
            "email_status": "ready",
            "plusvibe_ready": True,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        campaign_rows.append(row)
    
    sb.upsert("codicen_campaign_leads", campaign_rows, on_conflict="license_no,email")
    
    print(f"  ✓ Uploaded {len(ready)} ready leads (list_id={list_id})")
    
    return {"ready": len(ready), "list_id": list_id}


def write_report(
    out_dir: Path,
    companies: list[CSLBCompany],
    people: list[Person],
    cost_tracker: CostTracker,
    mode: str,
) -> None:
    """Write enrichment report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    
    ready = [p for p in people if p.ready]
    
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "window_companies": len(companies),
        "companies_with_domain": sum(1 for c in companies if c.company_domain),
        "people_found": len(people),
        "ready_leads": len(ready),
        "coverage": round(len(ready) / max(len(people), 1), 3),
        "cost": cost_tracker.summary(),
        "cost_per_ready": round(cost_tracker.spent_usd() / max(len(ready), 1), 6) if ready else None,
        "cost_per_1k_ready": round(cost_tracker.spent_usd() / max(len(ready), 1) * 1000, 2) if ready else None,
    }
    
    stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    
    (out_dir / f"report_{stamp}.json").write_text(json.dumps(report, indent=2))
    (out_dir / "report_latest.json").write_text(json.dumps(report, indent=2))
    
    # Write ready leads CSV
    if ready:
        import csv
        csv_path = out_dir / f"ready_{stamp}.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "license_no", "company_name", "company_domain",
                "first_name", "last_name", "title", "email", "linkedin",
                "company_description", "location", "email_source", "mv_result",
            ])
            writer.writeheader()
            for p in ready:
                writer.writerow({
                    "license_no": p.license_no,
                    "company_name": p.company_name,
                    "company_domain": p.company_domain,
                    "first_name": p.first_name,
                    "last_name": p.last_name,
                    "title": p.job_title or p.lf_title,
                    "email": p.email,
                    "linkedin": p.linkedin_url,
                    "company_description": p.company_description[:200],
                    "location": p.location or p.lf_location,
                    "email_source": p.email_source,
                    "mv_result": p.mv_result,
                })
    
    print(f"\n{'='*80}")
    print(f"Report written: {out_dir / f'report_{stamp}.json'}")
    print(json.dumps(report, indent=2))


def estimate_mode(sb: SupabaseClient, window_days: int = 90, allow_empty_suppression: bool = False) -> None:
    """
    Estimate mode: Free Hunter on sampled companies, small LeadsForge sample (<$0.25).
    Extrapolate costs and print recommended caps.
    """
    print("="*80)
    print("ESTIMATE MODE")
    print("="*80)
    
    # Load full window
    companies = load_codicen_window(sb, window_days)
    total_companies = len(companies)
    
    if not companies:
        print("ERROR: No companies in window")
        return
    
    print(f"\nWindow: {total_companies:,} companies (CLEAR, exp 0-{window_days} days)")
    
    # Stage 1: Hunter domain resolution on sampled companies (free)
    print("\n--- Hunter Domain Resolution (free, sampled companies) ---")
    
    # Use a seeded random sample for speed
    import random
    sample_size = min(int(os.environ.get("ESTIMATE_SAMPLE", "500")), total_companies)
    sample = random.Random(42).sample(companies, sample_size)
    
    print(f"Resolving domains for {len(sample):,} sample companies...")
    
    dummy_cost_tracker = CostTracker(999999.0)
    dummy_treg = TregClient(TREG_TOKEN, dummy_cost_tracker)
    
    resolved = resolve_domains_batch(sample, dummy_treg, dummy_cost_tracker, with_hunter_fallback=False, with_paid=False)
    
    sample_with_domain = sum(1 for c in resolved if c.company_domain)
    domain_rate = sample_with_domain / max(len(sample), 1)
    
    extrapolated_domains = int(total_companies * domain_rate)
    
    print(f"\nSample: {sample_with_domain}/{len(sample)} = {domain_rate:.1%} with domain")
    print(f"Extrapolated: ~{extrapolated_domains:,} / {total_companies:,} companies with domains")
    
    # Stage 2: Small LeadsForge sizing (<$0.25 spend)
    print("\n--- LeadsForge Sizing (small sample, <$0.25 spend) ---")
    
    max_lf_spend = 0.25  # USD
    max_lf_calls = int(max_lf_spend / (COST_LEADSFORGE_CALL / 1e6))
    
    # Each call can handle ~100 domains
    domains_per_call = 100
    sample_domains = min(max_lf_calls * domains_per_call, extrapolated_domains)
    
    print(f"LeadsForge budget: ${max_lf_spend} = {max_lf_calls} calls × {domains_per_call} domains/call")
    print(f"Sampling {sample_domains} domains (out of {extrapolated_domains:,} estimated)")
    
    # Use resolved sample companies with domains
    lf_sample = [c for c in resolved if c.company_domain][:min(sample_domains, len(resolved))]
    
    if not lf_sample:
        print("ERROR: No domains to sample for LeadsForge")
        return
    
    lf_cost_tracker = CostTracker(max_lf_spend)
    lf_treg = TregClient(TREG_TOKEN, lf_cost_tracker)
    
    # Load minimal suppression (just to avoid errors)
    suppress_linkedin, suppress_emails, suppress_domains = load_suppression_sets(sb, allow_empty=allow_empty_suppression)
    
    try:
        lf_people = leadsforge_search(lf_sample, lf_treg, lf_cost_tracker, suppress_domains, suppress_emails, suppress_linkedin)
        lf_spent = lf_cost_tracker.spent_usd()
        
        people_per_company = len(lf_people) / max(len(lf_sample), 1)
        
        print(f"\nLeadsForge sample: {len(lf_people)} people from {len(lf_sample)} companies (sampled)")
        print(f"  = {people_per_company:.2f} people/company (sampled)")
        print(f"  Spent: ${lf_spent:.4f}")
        
    except Exception as e:
        print(f"LeadsForge sampling failed: {e}")
        lf_spent = 0
        people_per_company = 2.5  # Fallback assumption if sampling fails
    
    # Extrapolate full costs (based on observed rates Nov 1, 2026)
    print("\n" + "="*80)
    print("COST EXTRAPOLATION (Observed Rates)")
    print("="*80)
    
    expected_people = int(extrapolated_domains * people_per_company)
    
    # Icypeas: ~25 people per query, $0.00038/row, ~67% exact-person match (observed)
    icypeas_match_rate = 0.67  # Observed
    icypeas_matches = int(expected_people * icypeas_match_rate)
    icypeas_queries = (expected_people // 25) + 1
    icypeas_cost = expected_people * (COST_ICYPEAS_SEARCH / 1e6)
    
    # Blitz: ~$0.0005/hit (observed), assume 50% hit rate
    blitz_attempts = icypeas_matches
    blitz_hit_rate = 0.50  # Assumption
    blitz_hits = int(blitz_attempts * blitz_hit_rate)
    blitz_cost = blitz_hits * (COST_BLITZ_EMAIL / 1e6)
    
    # MV: all blitz hits (catalog rate)
    mv_cost = blitz_hits * (COST_MV / 1e6)
    
    # BounceBan: assume 10% catch-alls (catalog rate)
    bb_count = int(blitz_hits * 0.1)
    bb_cost = bb_count * (COST_BB / 1e6)
    
    # Ready leads = MV valid + BB deliverable
    # Assume 85% MV valid, 90% BB deliverable (on catch-alls only)
    mv_valid_rate = 0.85
    bb_deliverable_rate = 0.90
    ready_count = int(blitz_hits * mv_valid_rate * (1 - 0.1 + 0.1 * bb_deliverable_rate))  # Most pass MV, some need BB
    
    # LeadsForge: full run (~117 calls free, then $0.005/call observed)
    lf_batch_size = int(os.environ.get("LF_BATCH_SIZE", "25"))
    lf_calls_full = (extrapolated_domains // lf_batch_size) + (1 if extrapolated_domains % lf_batch_size else 0)
    lf_free_calls = 117  # Observed
    lf_paid_calls = max(0, lf_calls_full - lf_free_calls)
    lf_cost_full = lf_paid_calls * (COST_LEADSFORGE_CALL / 1e6)
    
    total_cost = lf_cost_full + icypeas_cost + blitz_cost + mv_cost + bb_cost
    
    pilot_ready = 100
    pilot_cost = (pilot_ready / max(ready_count, 1)) * total_cost if ready_count > 0 else 1.0
    
    print(f"\nWindow companies: {total_companies:,}")
    print(f"Expected domains: ~{extrapolated_domains:,} ({domain_rate:.1%})")
    print(f"Expected people (LeadsForge): ~{expected_people:,} ({'sampled' if lf_spent > 0 else 'assumed'})")
    print(f"Icypeas exact matches (~67%): ~{icypeas_matches:,}")
    print(f"Blitz hits (~50%): ~{blitz_hits:,}")
    print(f"Expected ready leads (MV+BB): ~{ready_count:,}")
    print()
    print(f"Cost breakdown (observed rates + catalog):")
    print(f"  Hunter domain (free):              $0.00")
    print(f"  LeadsForge ({lf_calls_full} calls, batch={lf_batch_size}): ${lf_cost_full:.2f}")
    print(f"    ({lf_free_calls} free + {lf_paid_calls} paid @ $0.005/call)")
    print(f"  Icypeas ({icypeas_queries} queries):              ${icypeas_cost:.2f}")
    print(f"    (~{expected_people:,} rows @ $0.00038/row, ~67% match)")
    print(f"  Blitz email ({blitz_hits} hits):           ${blitz_cost:.2f}")
    print(f"    (~50% hit rate @ ~$0.0005/hit)")
    print(f"  MillionVerifier (catalog):         ${mv_cost:.2f}")
    print(f"  BounceBan (10% catch-alls):        ${bb_cost:.2f}")
    print(f"  ----------------------------------------")
    print(f"  TOTAL (full window):               ${total_cost:.2f}")
    print()
    print(f"Cost per 1k ready: ${(total_cost / max(ready_count, 1) * 1000):.2f}")
    print()
    print(f"PILOT BREAKDOWN (100 ready leads):")
    print(f"  LeadsForge:        ${(pilot_ready / max(ready_count, 1)) * lf_cost_full:.2f}")
    print(f"  Icypeas:           ${(pilot_ready / max(ready_count, 1)) * icypeas_cost:.2f}")
    print(f"  Blitz:             ${(pilot_ready / max(ready_count, 1)) * blitz_cost:.2f}")
    print(f"  MV + BB:           ${(pilot_ready / max(ready_count, 1)) * (mv_cost + bb_cost):.2f}")
    print(f"  ----------------------------------------")
    print(f"  TOTAL:             ${pilot_cost:.2f}")
    print()
    print(f"ASSUMPTIONS:")
    print(f"  - Domain resolution rate: {domain_rate:.1%} (sampled)")
    print(f"  - LeadsForge people/company: {people_per_company:.2f} ({'sampled' if lf_spent > 0 else 'assumed'})")
    print(f"  - Icypeas exact-person match: 67% (observed)")
    print(f"  - Blitz email hit rate: 50% (assumption)")
    print(f"  - MV valid rate: 85%, BB deliverable: 90% (assumptions)")
    print(f"  - LeadsForge batch size: {lf_batch_size} domains/call")
    print(f"  - LeadsForge free calls: ~{lf_free_calls} (observed Nov 1, 2026)")
    print()
    print(f"Recommended caps (with 40% safety buffer):")
    buffer = 1.4
    print(f"  --pilot (100 ready):               ${pilot_cost * buffer:.2f}")
    print(f"  --target-ready 500:                ${(500 / max(ready_count, 1)) * total_cost * buffer:.2f}")
    print(f"  --target-ready 2000:               ${(2000 / max(ready_count, 1)) * total_cost * buffer:.2f}")
    print(f"  Full window run (~{ready_count:,}):     ${total_cost * buffer:.2f}")
    print()
    
    # Check Treg balance
    try:
        dummy_treg = TregClient(TREG_TOKEN, CostTracker(999999.0))
        balance_resp = dummy_treg._call("treg", "balance", {}, timeout=10.0)
        balance_usd = balance_resp.get("balance_usd", 0.0) if isinstance(balance_resp, dict) else 0.0
        print(f"Treg balance: ${balance_usd:.2f}")
        
        if pilot_cost * buffer > balance_usd:
            print(f"  ⚠️  WARNING: Pilot cap (${pilot_cost * buffer:.2f}) exceeds balance!")
        if total_cost * buffer > balance_usd:
            print(f"  ⚠️  WARNING: Full window cap (${total_cost * buffer:.2f}) exceeds balance!")
    except Exception:
        pass
    
    print()
    print(f"LeadsForge sample spent: ${lf_spent:.4f} / ${max_lf_spend:.2f} limit")
    print()
    print("Next: python3 scripts/enrich_cslb_leadsforge.py --pilot --cap-usd 1.00 --window-days 90")


def resolve_only_mode(sb: SupabaseClient, window_days: int = 90, with_hunter_fallback: bool = False) -> None:
    """
    Resolve-only mode: Test domain resolution quality on a seeded sample (free).
    Prints resolve rate and sample name-to-domain pairs for quality checking.
    """
    print("="*80)
    print("RESOLVE-ONLY MODE (Domain Resolution Quality Check)")
    print("="*80)
    
    # Load full window
    companies = load_codicen_window(sb, window_days)
    total_companies = len(companies)
    
    if not companies:
        print("ERROR: No companies in window")
        return
    
    print(f"\nWindow: {total_companies:,} companies (CLEAR, exp 0-{window_days} days)")
    
    # Use a seeded random sample
    import random
    sample_size = min(int(os.environ.get("ESTIMATE_SAMPLE", "500")), total_companies)
    sample = random.Random(42).sample(companies, sample_size)
    
    print(f"Resolving domains for {len(sample):,} sample companies...")
    print()
    
    dummy_cost_tracker = CostTracker(0.0)  # No spend cap needed
    dummy_treg = TregClient(TREG_TOKEN, dummy_cost_tracker)
    
    resolved = resolve_domains_batch(sample, dummy_treg, dummy_cost_tracker, with_hunter_fallback=with_hunter_fallback, with_paid=False)
    
    sample_with_domain = sum(1 for c in resolved if c.company_domain)
    domain_rate = sample_with_domain / max(len(sample), 1)
    
    print(f"\n{'='*80}")
    print("RESULTS")
    print("="*80)
    print(f"\nSample: {sample_with_domain}/{len(sample)} = {domain_rate:.1%} with domain")
    print(f"Extrapolated: ~{int(total_companies * domain_rate):,} / {total_companies:,} companies with domains")
    print()
    
    # Print sample mappings for quality check
    print("Sample name-to-domain mappings (first 30):")
    print("-" * 80)
    
    resolved_with_domain = [c for c in resolved if c.company_domain][:30]
    for company in resolved_with_domain:
        print(f"  {company.business_name[:50]:50} → {company.company_domain}")
    
    if not resolved_with_domain:
        print("  (No domains resolved in sample)")
    
    print()
    print(f"Cost tracker summary: {dummy_cost_tracker.summary()}")
    print()
    print("Next: Review sample mappings for quality, then run --estimate or --pilot")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="CSLB LeadsForge → Icypeas → Blitz enrichment with strict cost control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--estimate", action="store_true", help="Estimate costs only (free Clearbit sample + small LF sizing <$0.25)")
    ap.add_argument("--resolve-only", action="store_true", help="Domain resolution quality check (free, seeded sample)")
    ap.add_argument("--pilot", action="store_true", help="Pilot run (~100 ready leads)")
    ap.add_argument("--target-ready", type=int, help="Stop once N ready leads are reached")
    ap.add_argument("--cap-usd", type=float, help="Hard spend cap in USD (REQUIRED for paid runs)")
    ap.add_argument("--with-hunter-fallback", action="store_true", help="Enable Hunter as fallback after Clearbit (off by default)")
    ap.add_argument("--with-paid-domain", action="store_true", help="Allow paid Blitz company enrich if all free options miss (off by default)")
    ap.add_argument("--window-days", type=int, default=90, help="Window size in days (default: 90)")
    ap.add_argument("--allow-empty-suppression", action="store_true", help="Allow empty suppression sets (not recommended)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="Output directory")
    
    args = ap.parse_args(argv)
    
    # Validation
    if not TREG_TOKEN:
        print("ERROR: Missing TREG_TOKEN", file=sys.stderr)
        return 1
    
    if not SUPABASE_KEY:
        print("ERROR: Missing SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1
    
    if args.estimate:
        # Estimate mode - no cap required
        sb = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)
        estimate_mode(sb, window_days=args.window_days, allow_empty_suppression=args.allow_empty_suppression)
        return 0
    
    if args.resolve_only:
        # Resolve-only mode - domain resolution quality check (free)
        sb = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)
        resolve_only_mode(sb, window_days=args.window_days, with_hunter_fallback=args.with_hunter_fallback)
        return 0
    
    # Paid runs require cap
    if not args.cap_usd:
        print("ERROR: Paid runs require --cap-usd USD (no default unlimited mode)", file=sys.stderr)
        print("Run --estimate first to get recommended cap", file=sys.stderr)
        return 1
    
    # Set target
    if args.pilot:
        target_ready = 100
    elif args.target_ready:
        target_ready = args.target_ready
    else:
        print("ERROR: Specify --pilot or --target-ready N", file=sys.stderr)
        return 1
    
    mode = "pilot" if args.pilot else f"target_{target_ready}"
    batch_id = f"cslb_lf_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print("="*80)
    print("CSLB LeadsForge → Icypeas → Blitz Enrichment")
    print("="*80)
    print(f"Mode: {mode}")
    print(f"Target ready: {target_ready}")
    print(f"Cap: ${args.cap_usd:.2f}")
    print(f"Window days: {args.window_days}")
    print(f"Paid domain enrich: {args.with_paid_domain}")
    print(f"Allow empty suppression: {args.allow_empty_suppression}")
    print(f"Batch ID: {batch_id}")
    print()
    
    # Initialize clients
    sb = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)
    cost_tracker = CostTracker(args.cap_usd)
    treg = TregClient(TREG_TOKEN, cost_tracker)
    
    # Load data
    companies = load_codicen_window(sb, window_days=args.window_days)
    suppress_linkedin, suppress_emails, suppress_domains = load_suppression_sets(sb, allow_empty=args.allow_empty_suppression)
    cache = load_supabase_cache(sb, days=30)
    
    if not companies:
        print("ERROR: No companies in window")
        return 2
    
    # Pipeline
    try:
        # Stage 1: Domain resolution
        companies = resolve_domains_batch(companies, treg, cost_tracker, with_hunter_fallback=args.with_hunter_fallback, with_paid=args.with_paid_domain)
        
        # Stage 2: LeadsForge people search
        people = leadsforge_search(companies, treg, cost_tracker, suppress_domains, suppress_emails, suppress_linkedin)
        
        if not people:
            print("\nNo people found from LeadsForge")
            write_report(args.out_dir, companies, [], cost_tracker, mode)
            return 0
        
        # Stage 3: Icypeas exact match
        people = icypeas_exact_match(people, treg, cost_tracker)
        
        # Stage 4-5: Cache check + Blitz email find
        people = check_cache_and_enrich(people, cache, treg, cost_tracker, suppress_emails, suppress_linkedin)
        
        # Check if we've hit target
        ready_count = sum(1 for p in people if p.ready)
        if ready_count >= target_ready:
            print(f"\n✓ Target reached: {ready_count} >= {target_ready} ready leads")
            people = [p for p in people if p.ready][:target_ready]
        
        # Stage 6: Email verification
        people = verify_emails(people, treg, cost_tracker)
        
        # Write report BEFORE DB operations (so crash doesn't lose it)
        write_report(args.out_dir, companies, people, cost_tracker, mode)
        
        # Stage 7: Upload to Supabase
        result = upsert_to_supabase(people, sb, batch_id)
        
        print(f"\n{'='*80}")
        print("✓ DONE")
        print(f"  Ready leads: {result['ready']}")
        print(f"  List ID: {result['list_id']}")
        print(f"  Spent: ${cost_tracker.spent_usd():.4f} / ${args.cap_usd:.2f}")
        
        return 0
    
    except RuntimeError as e:
        print(f"\n{'='*80}")
        print(f"STOPPED: {e}")
        write_report(args.out_dir, companies, [], cost_tracker, mode)
        return 3
    
    except KeyboardInterrupt:
        print(f"\n{'='*80}")
        print("Interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
