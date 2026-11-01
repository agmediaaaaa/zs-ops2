#!/usr/bin/env python3
"""Enrich CSLB companies with LeadsForge → Icypeas → Blitz (Jessica's required flow).

Flow (Oct 30, 2026 pipeline architecture):
  1. CSLB company name → Hunter domain-finder (free) + optional paid Blitz company enrich
  2. LeadsForge people search (batched domains, suppression always-on)
  3. Icypeas exact-person match (batched ~25 people per query by name+domain)
  4. Supabase 30-day cache check before paid email find
  5. Blitz email find from LinkedIn URL
  6. MillionVerifier + BounceBan (catch-alls)
  7. Upsert to pipeline_leads, create lead_list, merge to codicen_campaign_leads

Cost control (mandatory):
  --cap-usd USD         Hard spend cap (required, no default unlimited mode)
  --target-ready N      Stop once N ready leads are reached
  --estimate            Free Hunter sample + small LF sizing (<$0.25), extrapolate costs
  --pilot               Small target + cap for testing

Window definition:
  The "Codicen window" = CSLB companies with:
    - primary_status = 'CLEAR'
    - expiration_date_iso BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '120 days'
  Currently ~23.9k companies (12.2k Sole Owner, 10.4k Corp, 1.3k LLC)

Examples:
  # Estimate on current window (free Hunter + small LF sample, <$0.25 total)
  python3 scripts/enrich_cslb_leadsforge.py --estimate

  # Pilot run (~100 ready leads)
  python3 scripts/enrich_cslb_leadsforge.py --pilot --cap-usd 5.00

  # Full run with 1000 ready target
  python3 scripts/enrich_cslb_leadsforge.py --target-ready 1000 --cap-usd 50.00

  # With optional paid domain enrichment (off by default)
  python3 scripts/enrich_cslb_leadsforge.py --target-ready 500 --cap-usd 30.00 --with-paid-domain
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

# Catalog costs (micro USD) - verify with `treg catalog get` before large runs
COST_HUNTER_DOMAIN = 0  # Free
COST_BLITZ_COMPANY = 495  # $0.000495 per success
COST_LEADSFORGE_CALL = 5000  # $0.005 per call (charged after free allowance)
COST_ICYPEAS_SEARCH = 380  # $0.00038 per row
COST_BLITZ_EMAIL = 495  # $0.000495 per success
COST_MV = 1780  # $0.00178 per success
COST_BB = 5000  # Up to $0.005

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


def load_codicen_window(sb: SupabaseClient) -> list[CSLBCompany]:
    """Load CSLB companies in Codicen window (CLEAR, expiring 0-120 days)."""
    print("Loading Codicen window from Supabase...")
    rows = sb.query(
        "cslb_companies",
        select="license_no,business_name,full_business_name,city,state,county,business_phone,"
               "primary_status,expiration_date,expiration_date_iso,classifications,business_type,"
               "primary_principal_name,primary_principal_first,primary_principal_last,"
               "company_domain,website",
        filters={
            "client": "eq.Codicen",
            "primary_status": "eq.CLEAR",
            "expiration_date_iso": f"gte.{datetime.now().date().isoformat()}",
            "expiration_date_iso": f"lte.{(datetime.now().date() + timedelta(days=120)).isoformat()}",
        },
    )
    companies = [CSLBCompany(**{k: v or "" for k, v in r.items()}) for r in rows]
    print(f"  Loaded {len(companies):,} companies in window (CLEAR, exp 0-120 days)")
    return companies


def load_suppression_sets(sb: SupabaseClient) -> tuple[set[str], set[str], set[str]]:
    """Load suppression sets from Supabase (LinkedIn, emails, domains)."""
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
    
    # From pipeline_leads (Codicen campaign)
    rows = sb.query("pipeline_leads", select="linkedin,email,company_domain", filters={"client": "eq.Codicen"})
    for r in rows:
        if r.get("linkedin"):
            linkedin_urls.add(norm_li(r["linkedin"]))
        if r.get("email"):
            emails.add(r["email"].lower().strip())
        if r.get("company_domain"):
            domains.add(norm_domain(r["company_domain"]))
    
    # TODO: Add PlusVibe workspace suppression (requires PlusVibe API)
    
    print(f"  Suppression: {len(linkedin_urls):,} LinkedIn, {len(emails):,} emails, {len(domains):,} domains")
    
    if not linkedin_urls and not emails:
        print("  WARNING: Both LinkedIn and email suppression sets are empty!")
    
    return linkedin_urls, emails, domains


def load_supabase_cache(sb: SupabaseClient, days: int = 30) -> dict[str, dict]:
    """Load Supabase 30-day email cache keyed by LinkedIn URL."""
    print(f"Loading Supabase {days}-day email cache...")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    cache = {}
    
    # From pipeline_leads
    rows = sb.query(
        "pipeline_leads",
        select="linkedin,email,email_source,mv_result,updated_at",
        filters={
            "client": "eq.Codicen",
            "email": "not.is.null",
            "updated_at": f"gte.{cutoff}",
        },
    )
    for r in rows:
        if r.get("linkedin") and r.get("email"):
            cache[norm_li(r["linkedin"])] = {
                "email": r["email"],
                "source": r.get("email_source", "unknown"),
                "mv_result": r.get("mv_result"),
                "fresh": True,
            }
    
    print(f"  Cache: {len(cache):,} fresh emails (<{days} days old)")
    return cache


def resolve_domains_batch(
    companies: list[CSLBCompany],
    treg: TregClient,
    cost_tracker: CostTracker,
    with_paid: bool = False,
) -> list[CSLBCompany]:
    """Resolve company domains with Hunter (free) + optional paid Blitz."""
    print(f"\n=== Stage 1: Domain Resolution (Hunter free{' + Blitz paid' if with_paid else ''}) ===")
    
    updated = []
    stats = Counter()
    
    with ThreadPoolExecutor(max_workers=HUNTER_WORKERS, thread_name_prefix="Hunter") as pool:
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
            
            future = pool.submit(_resolve_one_domain, company, treg, cost_tracker, with_paid)
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
    with_paid: bool,
) -> CSLBCompany:
    """Resolve one company domain (Hunter free, then optional Blitz paid)."""
    name = company.display_name()
    
    # Hunter domain-finder (free)
    try:
        out, cost = treg.call("hunter.x.domain-finder", {"company": name})
        cost_tracker.settle(0, cost, "hunter_domain")
        
        domain = ""
        if isinstance(out, dict):
            domain = (
                out.get("domain")
                or (out.get("data") or {}).get("domain")
                or (out.get("output") or {}).get("domain")
                or ""
            )
            if not domain and isinstance(out.get("domains"), list) and out["domains"]:
                d0 = out["domains"][0]
                domain = d0 if isinstance(d0, str) else (d0.get("domain") or "")
        
        domain = norm_domain(domain)
        if domain and _domain_plausible(domain, name):
            company.company_domain = domain
            company.website = f"https://{domain}"
            return company
    
    except Exception as e:
        print(f"  Hunter error for {name[:40]}: {e}")
    
    # Optional paid Blitz company enrich
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
                if domain and _domain_plausible(domain, name):
                    company.company_domain = domain
                    company.website = f"https://{domain}"
        
        except Exception as e:
            cost_tracker.settle(COST_BLITZ_COMPANY, 0, "blitz_company")
            # Not an error - just skip paid enrichment
    
    return company


def _domain_plausible(domain: str, company_name: str) -> bool:
    """Check if domain is plausible for company name."""
    if not domain or not company_name:
        return False
    
    # Remove common TLDs and check if domain relates to name
    domain_base = domain.split(".")[0]
    name_tokens = set(re.findall(r"\w+", company_name.lower()))
    
    # Domain should share at least one token with company name
    return any(token in domain_base for token in name_tokens if len(token) > 3)


def leadsforge_search(
    companies: list[CSLBCompany],
    treg: TregClient,
    cost_tracker: CostTracker,
    suppress_domains: set[str],
) -> list[Person]:
    """
    LeadsForge people search with batched domains.
    IMPORTANT: LeadsForge charges $0.005 per call, so minimize call count by batching many domains.
    
    NOTE: LeadsForge endpoint structure TBD - using placeholder "leadsforge.people.search".
    Update with actual Treg endpoint name and request/response structure when available.
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
    batch_size = 100  # Adjust based on LeadsForge API limits
    domain_batches = []
    company_by_domain = {norm_domain(c.company_domain): c for c in valid_companies}
    domains = list(company_by_domain.keys())
    
    for i in range(0, len(domains), batch_size):
        domain_batches.append(domains[i:i+batch_size])
    
    print(f"  Batched into {len(domain_batches)} LeadsForge calls ({batch_size} domains/call)")
    
    all_people = []
    
    for batch_idx, domain_batch in enumerate(domain_batches):
        try:
            # Reserve cost for this LeadsForge call
            cost_tracker.reserve(COST_LEADSFORGE_CALL, "leadsforge")
            
            # LeadsForge people search query
            # TODO: Replace with actual LeadsForge API structure when available
            query = {
                "companyDomains": {"include": domain_batch},
                "title": DM_TITLES,
                "location": {"countries": ["US"]},
                "maxContactsPerCompany": 3,  # Limit contacts per company
                # TODO: Add excludeEmails, excludeLinkedInURLs, excludeDomains from suppression
            }
            
            print(f"  LeadsForge call {batch_idx+1}/{len(domain_batches)} ({len(domain_batch)} domains)...")
            
            # Call LeadsForge (endpoint TBD - using placeholder)
            out, cost = treg.call("leadsforge.people.search", body=query)
            cost_tracker.settle(COST_LEADSFORGE_CALL, cost, "leadsforge")
            
            # Parse LeadsForge response
            people = _parse_leadsforge_response(out, company_by_domain)
            all_people.extend(people)
            
            print(f"    Found {len(people)} people")
            time.sleep(0.5)  # Rate limit
        
        except Exception as e:
            cost_tracker.settle(COST_LEADSFORGE_CALL, 0, "leadsforge")
            print(f"  LeadsForge error batch {batch_idx+1}: {e}")
            continue
    
    print(f"\nLeadsForge: {len(all_people):,} people found across {len(valid_companies):,} companies")
    return all_people


def _parse_leadsforge_response(response: dict, company_by_domain: dict[str, CSLBCompany]) -> list[Person]:
    """Parse LeadsForge API response into Person objects."""
    people = []
    
    # TODO: Update with actual LeadsForge response structure
    results = response.get("contacts") or response.get("people") or []
    
    for item in results:
        domain = norm_domain(item.get("companyDomain") or item.get("company_website") or "")
        company = company_by_domain.get(domain)
        if not company:
            continue
        
        person = Person(
            license_no=company.license_no,
            company_name=company.display_name(),
            company_domain=company.company_domain,
            lf_id=item.get("id", ""),
            first_name=item.get("firstName", ""),
            last_name=item.get("lastName", ""),
            lf_title=item.get("title", ""),
            lf_company=item.get("company", ""),
            lf_location=item.get("location", ""),
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
    
    # Check cache first
    for person in people:
        li_norm = norm_li(person.linkedin_url)
        
        # Check LinkedIn suppression
        if li_norm in suppress_linkedin:
            person.suppressed = True
            stats["linkedin_suppressed"] += 1
            continue
        
        # Check cache
        if li_norm in cache:
            cached = cache[li_norm]
            person.email = cached["email"]
            person.email_source = f"cache:{cached['source']}"
            person.mv_result = cached.get("mv_result", "")
            person.cached = True
            stats["cache_hit"] += 1
            continue
    
    # Find people needing email enrichment
    need_email = [p for p in people if not p.email and not p.suppressed and p.linkedin_url]
    
    print(f"  Cache hits: {stats['cache_hit']} / {len(people)}")
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
    Stage 7: Upsert to pipeline_leads, create lead_list, merge to codicen_campaign_leads.
    """
    print(f"\n=== Stage 7: Supabase Upload ===")
    
    ready = [p for p in people if p.ready]
    
    if not ready:
        print("  No ready leads to upload")
        return {"ready": 0, "list_id": None}
    
    print(f"  Uploading {len(ready)} ready leads...")
    
    # Prepare pipeline_leads rows
    now_iso = datetime.now(timezone.utc).isoformat()
    pipeline_rows = []
    
    for p in ready:
        row = {
            "client": "Codicen",
            "campaign_id": "cslb_leadsforge",
            "batch_id": batch_id,
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
            "mv_result": p.mv_result,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        pipeline_rows.append(row)
    
    # Upsert to pipeline_leads (on conflict: email)
    print("  Upserting to pipeline_leads...")
    sb.upsert("pipeline_leads", pipeline_rows, on_conflict="email")
    
    # Create lead_list entry
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
    
    # Create lead_list_members (many-to-many join)
    if list_id:
        # TODO: Link pipeline_leads.id to lead_list_members
        pass
    
    # Merge to codicen_campaign_leads
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


def estimate_mode(sb: SupabaseClient) -> None:
    """
    Estimate mode: Free Hunter on ALL window companies, small LeadsForge sample (<$0.25).
    Extrapolate costs and print recommended caps.
    """
    print("="*80)
    print("ESTIMATE MODE")
    print("="*80)
    
    # Load full window
    companies = load_codicen_window(sb)
    total_companies = len(companies)
    
    if not companies:
        print("ERROR: No companies in window")
        return
    
    print(f"\nWindow: {total_companies:,} companies (CLEAR, exp 0-120 days)")
    
    # Stage 1: Hunter domain resolution on ALL companies (free)
    print("\n--- Hunter Domain Resolution (free, all companies) ---")
    
    # Use a sample for speed (or all if fast enough)
    sample_size = min(500, total_companies)
    sample = companies[:sample_size]
    
    print(f"Resolving domains for {len(sample):,} sample companies...")
    
    dummy_cost_tracker = CostTracker(999999.0)
    dummy_treg = TregClient(TREG_TOKEN, dummy_cost_tracker)
    
    resolved = resolve_domains_batch(sample, dummy_treg, dummy_cost_tracker, with_paid=False)
    
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
    suppress_linkedin, suppress_emails, suppress_domains = load_suppression_sets(sb)
    
    try:
        lf_people = leadsforge_search(lf_sample, lf_treg, lf_cost_tracker, suppress_domains)
        lf_spent = lf_cost_tracker.spent_usd()
        
        people_per_company = len(lf_people) / max(len(lf_sample), 1)
        
        print(f"\nLeadsForge sample: {len(lf_people)} people from {len(lf_sample)} companies")
        print(f"  = {people_per_company:.2f} people/company")
        print(f"  Spent: ${lf_spent:.4f}")
        
    except Exception as e:
        print(f"LeadsForge sampling failed: {e}")
        lf_spent = 0
        people_per_company = 0
    
    # Extrapolate full costs
    print("\n" + "="*80)
    print("COST EXTRAPOLATION")
    print("="*80)
    
    expected_people = int(extrapolated_domains * people_per_company)
    
    # Icypeas: ~25 people per query, $0.00038/row
    icypeas_queries = (expected_people // 25) + 1
    icypeas_cost = expected_people * (COST_ICYPEAS_SEARCH / 1e6)
    
    # Blitz: assume 50% hit rate
    blitz_attempts = expected_people
    blitz_hits = int(blitz_attempts * 0.5)
    blitz_cost = blitz_hits * (COST_BLITZ_EMAIL / 1e6)
    
    # MV: all blitz hits
    mv_cost = blitz_hits * (COST_MV / 1e6)
    
    # BounceBan: assume 10% catch-alls
    bb_count = int(blitz_hits * 0.1)
    bb_cost = bb_count * (COST_BB / 1e6)
    
    # LeadsForge: full run
    lf_calls_full = (extrapolated_domains // domains_per_call) + 1
    lf_cost_full = lf_calls_full * (COST_LEADSFORGE_CALL / 1e6)
    
    total_cost = lf_cost_full + icypeas_cost + blitz_cost + mv_cost + bb_cost
    
    pilot_ready = 100
    pilot_cost = (pilot_ready / max(blitz_hits, 1)) * total_cost
    
    print(f"\nWindow companies: {total_companies:,}")
    print(f"Expected domains: ~{extrapolated_domains:,} ({domain_rate:.1%})")
    print(f"Expected people (LeadsForge): ~{expected_people:,}")
    print(f"Expected ready leads (50% Blitz hit): ~{blitz_hits:,}")
    print()
    print(f"Cost breakdown:")
    print(f"  Hunter domain (free):     $0.00")
    print(f"  LeadsForge ({lf_calls_full} calls):    ${lf_cost_full:.2f}")
    print(f"  Icypeas ({icypeas_queries} queries):     ${icypeas_cost:.2f}")
    print(f"  Blitz email ({blitz_hits} hits):    ${blitz_cost:.2f}")
    print(f"  MillionVerifier:          ${mv_cost:.2f}")
    print(f"  BounceBan (catch-alls):   ${bb_cost:.2f}")
    print(f"  ----------------------------------")
    print(f"  TOTAL (full window):      ${total_cost:.2f}")
    print()
    print(f"Cost per 1k ready: ${(total_cost / max(blitz_hits, 1) * 1000):.2f}")
    print()
    print(f"Recommended caps:")
    print(f"  --pilot (100 ready):      ${max(5.0, pilot_cost * 1.5):.2f}")
    print(f"  --target-ready 500:       ${max(25.0, (500 / max(blitz_hits, 1)) * total_cost * 1.4):.2f}")
    print(f"  Full window run:          ${total_cost * 1.4:.2f}")
    print()
    print(f"LeadsForge sample spent: ${lf_spent:.4f} (under ${max_lf_spend} limit)")
    print()
    print("Next: Re-run with --pilot --cap-usd <amount> or --target-ready N --cap-usd <amount>")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="CSLB LeadsForge → Icypeas → Blitz enrichment with strict cost control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--estimate", action="store_true", help="Estimate costs only (free Hunter + small LF sample <$0.25)")
    ap.add_argument("--pilot", action="store_true", help="Pilot run (~100 ready leads)")
    ap.add_argument("--target-ready", type=int, help="Stop once N ready leads are reached")
    ap.add_argument("--cap-usd", type=float, help="Hard spend cap in USD (REQUIRED for paid runs)")
    ap.add_argument("--with-paid-domain", action="store_true", help="Allow paid Blitz company enrich if Hunter misses (off by default)")
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
        estimate_mode(sb)
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
    print(f"Paid domain enrich: {args.with_paid_domain}")
    print(f"Batch ID: {batch_id}")
    print()
    
    # Initialize clients
    sb = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)
    cost_tracker = CostTracker(args.cap_usd)
    treg = TregClient(TREG_TOKEN, cost_tracker)
    
    # Load data
    companies = load_codicen_window(sb)
    suppress_linkedin, suppress_emails, suppress_domains = load_suppression_sets(sb)
    cache = load_supabase_cache(sb, days=30)
    
    if not companies:
        print("ERROR: No companies in window")
        return 2
    
    # Pipeline
    try:
        # Stage 1: Domain resolution
        companies = resolve_domains_batch(companies, treg, cost_tracker, args.with_paid_domain)
        
        # Stage 2: LeadsForge people search
        people = leadsforge_search(companies, treg, cost_tracker, suppress_domains)
        
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
        
        # Stage 7: Upload to Supabase
        result = upsert_to_supabase(people, sb, batch_id)
        
        # Write report
        write_report(args.out_dir, companies, people, cost_tracker, mode)
        
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
