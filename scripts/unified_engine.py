#!/usr/bin/env python3
"""
Unified Lead Pipeline Engine: LeadsForge → Icypeas → Blitz (ONLY supported path)

This engine enforces the Oct 30, 2026 pipeline architecture:
  1. LeadsForge people search (free count + paginated search)
  2. Icypeas exact-person match (batched by name+domain)
  3. Always-on suppression (LinkedIn + email, cannot be disabled)
  4. Supabase 30-day cache check
  5. Pattern email + ContactOut verify (best effort, short timeout)
  6. Blitz email find (primary enrichment)
  7. Optional QuickEnrich/TryKitt fallback (config-gated, per-run cap)
  8. MillionVerifier + BounceBan
  9. Bulk Supabase upload

Key features:
  - Concurrent worker pools per provider (configurable limits)
  - Per-person enrichment pipeline (not sequential batches)
  - Always-on suppression (separate SUPPRESS flag, never disabled by NOFILTER)
  - 30-day cache reuse before any paid step
  - Never pay twice (dedupe + cache)
  - Economic gates (early-stop if cost/ready explodes)
  - Target: ~70-75 ready leads/min

Usage:
  python scripts/unified_engine.py --client ZS --scope-only --exclude-json suppress.json
  python scripts/unified_engine.py --client ZS --pilot --confirm-spend 2.50 --exclude-json suppress.json
  python scripts/unified_engine.py --client ZS --full 1000 --confirm-spend 45.00 --exclude-json suppress.json
"""

from __future__ import annotations

import argparse
import csv
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
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Config from environment
TREG_TOKEN = os.environ.get("TREG_TOKEN") or os.environ.get("treg")
if not TREG_TOKEN:
    try:
        TREG_TOKEN = json.loads(Path.home().joinpath(".treg/config.json").read_text()).get("token")
    except Exception:
        pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
PLUSVIBE_API_KEY = os.environ.get("PLUSVIBE_API_KEY", "")

# Concurrency settings
NWORK = int(os.environ.get("NWORK", "64"))  # Main worker pool
CO_WORKERS = int(os.environ.get("CO_WORKERS", "8"))  # ContactOut best-effort pool
BLITZ_WORKERS = int(os.environ.get("BLITZ_WORKERS", "32"))  # Blitz pool
FALLBACK_WORKERS = int(os.environ.get("FALLBACK_WORKERS", "4"))  # QuickEnrich/TryKitt pool
MV_WORKERS = int(os.environ.get("MV_WORKERS", "16"))  # MillionVerifier pool

# Fallback enrichment settings
ENABLE_FALLBACK_ENRICH = os.environ.get("ENABLE_FALLBACK_ENRICH", "false").lower() in ("true", "1", "yes")
MAX_FALLBACK_ENRICH_COUNT = int(os.environ.get("MAX_FALLBACK_ENRICH_COUNT", "100"))

# Timeouts
CO_TIMEOUT = float(os.environ.get("CO_TIMEOUT", "3.0"))  # ContactOut short timeout (best effort)
BLITZ_TIMEOUT = float(os.environ.get("BLITZ_TIMEOUT", "60.0"))
FALLBACK_TIMEOUT = float(os.environ.get("FALLBACK_TIMEOUT", "45.0"))

# Output directory
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/unified-pipeline"))

# Catalog costs (micro USD)
COST_LEADSFORGE_SEARCH = 0  # Free count, variable search cost
COST_ICYPEAS_SEARCH = 380  # $0.00038 per row
COST_CONTACTOUT = 0  # Free tier
COST_BLITZ = 495  # $0.000495 per success
COST_QUICKENRICH = 5000  # $0.005 per hit
COST_TRYKITT = 5000  # $0.005 per hit
COST_MV = 1780  # $0.00178 per success
COST_BB = 5000  # Up to $0.005

# Freemail domains
FREEMAIL = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", 
    "icloud.com", "aol.com", "mail.com", "protonmail.com"
}

# Economic gates
MAX_SEARCH_ROWS_PER_READY = 12
MAX_EMAIL_ATTEMPTS_PER_READY = 4
MAX_COST_PER_1K_READY = 10.0  # USD


@dataclass
class Person:
    """Person record through enrichment pipeline."""
    # Identity
    lf_id: str = None  # LeadsForge ID
    first_name: str = None
    last_name: str = None
    company_domain: str = None
    
    # From Icypeas match
    linkedin_url: str = None
    job_title: str = None
    headline: str = None
    company_name: str = None
    company_website: str = None
    company_industry: str = None
    company_description: str = None
    company_size: int = None
    location: str = None
    
    # Email enrichment
    email: str = None
    email_source: str = None  # contactout, blitz, quickenrich, trykitt, cache
    
    # Verification
    mv_result: str = None  # ok, catch_all, invalid, unknown, disposable
    bb_result: str = None  # deliverable, undeliverable
    
    # Status flags
    suppressed: bool = False
    cached: bool = False
    
    # Metadata
    segment: str = None
    page: int = None


class SuppressChecker:
    """Always-on suppression checker (cannot be disabled by NOFILTER or any other flag)."""
    
    def __init__(self, linkedin_urls: set[str], emails: set[str], domains: set[str]):
        self.linkedin_urls = {self._norm_li(u) for u in linkedin_urls}
        self.emails = {e.lower().strip() for e in emails}
        self.domains = {d.lower().strip() for d in domains}
        self.lock = threading.Lock()
        
        # Fail loudly if suppression sets are empty
        if not self.linkedin_urls and not self.emails:
            raise ValueError("SUPPRESS FAILURE: both LinkedIn and email suppression sets are empty!")
        
        print(f"[SUPPRESS] Initialized: {len(self.linkedin_urls)} LinkedIn, {len(self.emails)} emails, {len(self.domains)} domains")
    
    @staticmethod
    def _norm_li(url: str) -> str:
        """Normalize LinkedIn URL."""
        u = (url or "").lower().split("?")[0].rstrip("/")
        return u.replace("https://www.linkedin.com/in/", "").replace("http://www.linkedin.com/in/", "").replace("linkedin.com/in/", "")
    
    @staticmethod
    def _bare_domain(url: str) -> str:
        """Extract bare domain from URL."""
        if not url:
            return ""
        u = url.lower().strip()
        u = re.sub(r"^https?://", "", u)
        u = re.sub(r"^www\.", "", u)
        u = u.split("/")[0]
        return u
    
    def check_linkedin(self, url: str) -> bool:
        """Check if LinkedIn URL is suppressed. Thread-safe."""
        if not url:
            return False
        norm = self._norm_li(url)
        with self.lock:
            is_suppressed = norm in self.linkedin_urls
            if not is_suppressed:
                self.linkedin_urls.add(norm)  # Add to seen set
            return is_suppressed
    
    def check_email(self, email: str) -> bool:
        """Check if email is suppressed. Thread-safe."""
        if not email:
            return False
        e = email.lower().strip()
        with self.lock:
            is_suppressed = e in self.emails
            if not is_suppressed:
                self.emails.add(e)  # Add to seen set
            return is_suppressed
    
    def check_domain(self, domain: str) -> bool:
        """Check if domain is suppressed."""
        if not domain:
            return False
        d = self._bare_domain(domain)
        return d in self.domains


class CostTracker:
    """Thread-safe cost tracking with hard cap enforcement."""
    
    def __init__(self, hard_cap_usd: float):
        self.hard_cap_micro = int(hard_cap_usd * 1e6)
        self.spent_micro = 0
        self.reserved_micro = 0
        self.by_step = Counter()
        self.lock = threading.Lock()
    
    def reserve(self, amount_micro: int) -> None:
        """Reserve cost before calling API. Raises if would exceed cap."""
        with self.lock:
            if self.spent_micro + self.reserved_micro + amount_micro > self.hard_cap_micro:
                raise RuntimeError(
                    f"Cost cap exceeded: spent ${self.spent_micro/1e6:.4f} "
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
                "by_step_micro": dict(self.by_step),
                "by_step_usd": {k: round(v / 1e6, 6) for k, v in self.by_step.items()},
            }


class TregClient:
    """Treg API client with rate limiting and retries."""
    
    def __init__(self, token: str, cost_tracker: CostTracker):
        self.token = token
        self.cost_tracker = cost_tracker
    
    def call(
        self,
        endpoint: str,
        body: dict = None,
        query: dict = None,
        headers: dict = None,
        timeout: float = 120.0,
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
        max_attempts = 8 if retry else 1
        
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
                
                # HTTP 402 payment required - wait for top-up (not implemented here)
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


class EnrichmentPipeline:
    """Concurrent enrichment pipeline with per-provider worker pools."""
    
    def __init__(
        self,
        treg: TregClient,
        cost_tracker: CostTracker,
        suppress: SuppressChecker,
        cache: dict,
    ):
        self.treg = treg
        self.cost_tracker = cost_tracker
        self.suppress = suppress
        self.cache = cache  # Supabase 30-day cache
        
        # Worker pools
        self.co_pool = ThreadPoolExecutor(max_workers=CO_WORKERS, thread_name_prefix="CO")
        self.blitz_pool = ThreadPoolExecutor(max_workers=BLITZ_WORKERS, thread_name_prefix="Blitz")
        self.fallback_pool = ThreadPoolExecutor(max_workers=FALLBACK_WORKERS, thread_name_prefix="Fallback")
        self.mv_pool = ThreadPoolExecutor(max_workers=MV_WORKERS, thread_name_prefix="MV")
        
        # Results caches (never pay twice)
        self.co_cache = {}
        self.blitz_cache = {}
        self.fallback_cache = {}
        self.mv_cache = {}
        self.bb_cache = {}
        
        # Counters
        self.counters = Counter()
        self.lock = threading.Lock()
        
        # Fallback enrichment counter
        self.fallback_count = 0
    
    def enrich_person(self, person: Person) -> Person:
        """
        Enrich one person through the pipeline.
        Returns updated Person object.
        """
        # Check cache first (30-day window)
        if person.linkedin_url in self.cache:
            cached = self.cache[person.linkedin_url]
            if cached.get("fresh") and cached.get("email"):
                person.email = cached["email"]
                person.email_source = f"cache:{cached.get('src', 'unknown')}"
                person.cached = True
                person.mv_result = cached.get("mv_result")
                person.bb_result = cached.get("bb_result")
                with self.lock:
                    self.counters["cache_hit"] += 1
                return person
        
        # Pattern email + ContactOut verify (best effort, short timeout)
        if not person.email:
            email = self._try_contactout(person)
            if email:
                person.email = email
                person.email_source = "pattern+contactout"
        
        # Blitz email find (primary enrichment)
        if not person.email:
            email = self._try_blitz(person)
            if email:
                person.email = email
                person.email_source = "blitz"
        
        # Optional fallback (QuickEnrich/TryKitt)
        if not person.email and ENABLE_FALLBACK_ENRICH:
            if self.fallback_count < MAX_FALLBACK_ENRICH_COUNT:
                email = self._try_fallback(person)
                if email:
                    person.email = email
                    person.email_source = "fallback"
                    with self.lock:
                        self.fallback_count += 1
        
        # Check suppression on found email
        if person.email:
            # Freemail check
            domain = person.email.split("@")[-1].lower()
            if domain in FREEMAIL:
                with self.lock:
                    self.counters["freemail_drop"] += 1
                person.email = None
                return person
            
            # Email suppression check (always-on)
            if self.suppress.check_email(person.email):
                person.suppressed = True
                with self.lock:
                    self.counters["email_suppressed"] += 1
                person.email = None
                return person
        
        return person
    
    def verify_emails(self, people: list[Person]) -> list[Person]:
        """
        Verify emails with MillionVerifier + BounceBan (async, non-blocking).
        Returns updated people.
        """
        to_verify = [p for p in people if p.email and not p.mv_result]
        
        if not to_verify:
            return people
        
        # MillionVerifier
        futures = {}
        for p in to_verify:
            if p.email not in self.mv_cache:
                future = self.mv_pool.submit(self._mv_one, p.email)
                futures[future] = p
        
        for future in as_completed(futures):
            p = futures[future]
            try:
                result = future.result()
                p.mv_result = result
            except Exception as e:
                print(f"[MV] Error for {p.email}: {e}")
                p.mv_result = "error"
        
        # BounceBan for catch-alls (async polling, non-blocking)
        catch_alls = [p for p in to_verify if p.mv_result == "catch_all"]
        if catch_alls:
            for p in catch_alls:
                if p.email not in self.bb_cache:
                    # Submit BB job (non-blocking)
                    self.mv_pool.submit(self._bb_one, p.email)
                else:
                    p.bb_result = self.bb_cache[p.email]
        
        return people
    
    def _generate_patterns(self, first: str, last: str, domain: str) -> list[str]:
        """Generate pattern emails: f.l@domain, f@domain."""
        if not first or not last or not domain:
            return []
        f = re.sub(r"[^a-z]", "", first.lower())
        l = re.sub(r"[^a-z]", "", last.lower())
        if not f or not l:
            return []
        return [f"{f}.{l}@{domain}", f"{f}@{domain}"]
    
    def _try_contactout(self, person: Person) -> str | None:
        """Try ContactOut verify on pattern emails (best effort, short timeout)."""
        patterns = self._generate_patterns(
            person.first_name,
            person.last_name,
            person.company_domain,
        )
        
        for email in patterns:
            if email in self.co_cache:
                result = self.co_cache[email]
                if result in ("valid", "ok", "deliverable", "smtp_valid", "good"):
                    with self.lock:
                        self.counters["contactout_hit"] += 1
                    return email
                elif result in ("invalid", "undeliverable", "not_found", "bad", "rejected"):
                    continue  # Try next pattern
                else:
                    # Unknown/catch-all - stop guessing
                    return None
            
            # Call ContactOut (best effort, short timeout)
            try:
                out, cost = self.treg.call(
                    "contactout.people.email.verify",
                    query={"email": email},
                    timeout=CO_TIMEOUT,
                    retry=False,  # Don't retry on timeout
                )
                
                if cost:
                    self.cost_tracker.settle(0, cost, "contactout")
                
                inner = out.get("data") if isinstance(out.get("data"), dict) else out
                result = str(inner.get("status") or inner.get("result") or "").lower()
                
                self.co_cache[email] = result
                
                if result in ("valid", "ok", "deliverable", "smtp_valid", "good"):
                    with self.lock:
                        self.counters["contactout_hit"] += 1
                    return email
                elif result in ("invalid", "undeliverable", "not_found", "bad", "rejected"):
                    continue
                else:
                    # Unknown/catch-all - stop guessing
                    return None
            
            except (RuntimeError, TimeoutError) as e:
                # Timeout or rate limit - skip ContactOut, don't block
                with self.lock:
                    self.counters["contactout_skip"] += 1
                return None
        
        return None
    
    def _try_blitz(self, person: Person) -> str | None:
        """Try Blitz email find."""
        if not person.linkedin_url:
            return None
        
        slug = person.linkedin_url
        if slug in self.blitz_cache:
            with self.lock:
                self.counters["blitz_cached"] += 1
            return self.blitz_cache[slug]
        
        # Reserve cost
        self.cost_tracker.reserve(COST_BLITZ)
        
        try:
            out, cost = self.treg.call(
                "blitzapi.people.email.find",
                body={"person_linkedin_url": person.linkedin_url},
                timeout=BLITZ_TIMEOUT,
            )
            self.cost_tracker.settle(COST_BLITZ, cost, "blitz")
            
            email = None
            if isinstance(out, dict):
                email = out.get("email")
                if not email:
                    for item in out.get("all_emails") or []:
                        if isinstance(item, dict) and item.get("email"):
                            email = item["email"]
                            break
            
            email = (email or "").lower().strip() or None
            self.blitz_cache[slug] = email
            
            if email:
                with self.lock:
                    self.counters["blitz_hit"] += 1
            else:
                with self.lock:
                    self.counters["blitz_miss"] += 1
            
            return email
        
        except Exception as e:
            self.cost_tracker.settle(COST_BLITZ, 0, "blitz")
            with self.lock:
                self.counters["blitz_error"] += 1
            raise
    
    def _try_fallback(self, person: Person) -> str | None:
        """Try QuickEnrich or TryKitt as fallback (config-gated, per-run cap)."""
        # Not implemented yet - placeholder
        # Would call quickenrich or trykitt endpoints here
        return None
    
    def _mv_one(self, email: str) -> str:
        """Verify one email with MillionVerifier."""
        if email in self.mv_cache:
            return self.mv_cache[email]
        
        self.cost_tracker.reserve(COST_MV)
        
        try:
            out, cost = self.treg.call(
                "millionverifier.people.email.verify",
                query={"email": email},
            )
            self.cost_tracker.settle(COST_MV, cost, "mv")
            
            result = out.get("result") if isinstance(out, dict) else "error"
            self.mv_cache[email] = result
            return result
        
        except Exception as e:
            self.cost_tracker.settle(COST_MV, 0, "mv")
            self.mv_cache[email] = "error"
            return "error"
    
    def _bb_one(self, email: str) -> str:
        """Verify catch-all email with BounceBan (async polling)."""
        if email in self.bb_cache:
            return self.bb_cache[email]
        
        self.cost_tracker.reserve(COST_BB)
        
        try:
            hdrs = {
                "X-Treg-Route-Waterfall": "0",
                "X-Treg-Route-Max-Cost": "0.005",
            }
            out, cost = self.treg.call(
                "bounceban.people.email.verify",
                query={"email": email},
                headers=hdrs,
            )
            
            # Poll for result (up to 10 attempts, 20s between)
            rid = out.get("id") if isinstance(out, dict) else None
            attempts = 0
            while isinstance(out, dict) and str(out.get("status", "")).lower() in ("pending", "verifying", "processing") and rid and attempts < 10:
                time.sleep(20)
                attempts += 1
                out2, cost2 = self.treg.call(
                    "bounceban.people.email.verify.status",
                    query={"id": rid},
                    headers=hdrs,
                )
                cost += cost2
                if isinstance(out2, dict):
                    out = out2
            
            self.cost_tracker.settle(COST_BB, cost, "bb")
            
            result = out.get("result") if isinstance(out, dict) else None
            self.bb_cache[email] = result
            return result
        
        except Exception as e:
            self.cost_tracker.settle(COST_BB, 0, "bb")
            self.bb_cache[email] = None
            return None
    
    def shutdown(self):
        """Shutdown worker pools."""
        self.co_pool.shutdown(wait=True)
        self.blitz_pool.shutdown(wait=True)
        self.fallback_pool.shutdown(wait=True)
        self.mv_pool.shutdown(wait=True)


def load_suppress_sets(exclude_json: str | None) -> tuple[set, set, set]:
    """Load LinkedIn URLs, emails, and domains from exclude JSON + Supabase + PlusVibe."""
    linkedin_urls = set()
    emails = set()
    domains = set()
    
    # From JSON file
    if exclude_json and Path(exclude_json).exists():
        data = json.loads(Path(exclude_json).read_text())
        linkedin_urls.update(data.get("linkedin") or [])
        emails.update(data.get("emails") or [])
        domains.update(data.get("domains") or [])
    
    # From Supabase (placeholder - would query pipeline_leads, lead_lists)
    # TODO: Implement Supabase query
    
    # From PlusVibe workspace (placeholder - would query workspace leads)
    # TODO: Implement PlusVibe query
    
    return linkedin_urls, emails, domains


def load_supabase_cache() -> dict:
    """Load Supabase pipeline_leads cache (30-day window)."""
    # Placeholder - would query Supabase for recent emails
    # TODO: Implement Supabase query
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Unified Lead Pipeline: LeadsForge → Icypeas → Blitz (ONLY supported path)"
    )
    parser.add_argument("--client", required=True, help="Client code (e.g. ZS, MARS, ATC)")
    parser.add_argument("--scope-only", action="store_true", help="Free TAM count only")
    parser.add_argument("--pilot", action="store_true", help="Pilot run (10-25 ready per segment)")
    parser.add_argument("--full", type=int, help="Full run (N ready total)")
    parser.add_argument("--confirm-spend", type=float, help="Hard spend cap (USD)")
    parser.add_argument("--exclude-json", help="Path to suppress.json with LinkedIn/emails/domains")
    parser.add_argument("--dry-run", action="store_true", help="Test mode (mock paid calls)")
    
    args = parser.parse_args()
    
    if not TREG_TOKEN:
        print("ERROR: Missing TREG_TOKEN environment variable or ~/.treg/config.json", file=sys.stderr)
        sys.exit(1)
    
    if (args.pilot or args.full) and not args.confirm_spend:
        print("ERROR: Paid runs require --confirm-spend USD", file=sys.stderr)
        sys.exit(2)
    
    # Ensure output directory exists
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("Unified Lead Pipeline: LeadsForge → Icypeas → Blitz")
    print("=" * 80)
    print(f"Client: {args.client}")
    print(f"Mode: {'scope-only' if args.scope_only else 'pilot' if args.pilot else f'full ({args.full} ready)'}")
    if args.confirm_spend:
        print(f"Spend cap: ${args.confirm_spend:.2f}")
    print(f"Dry run: {args.dry_run}")
    print()
    
    # Load suppression sets
    print("Loading suppression sets...")
    linkedin_urls, emails, domains = load_suppress_sets(args.exclude_json)
    print(f"  LinkedIn URLs: {len(linkedin_urls)}")
    print(f"  Emails: {len(emails)}")
    print(f"  Domains: {len(domains)}")
    print()
    
    if args.scope_only:
        print("Scope-only mode: Free TAM count")
        print("TODO: Implement LeadsForge free count")
        # TODO: Implement
        return
    
    # Initialize components
    cost_tracker = CostTracker(args.confirm_spend)
    treg = TregClient(TREG_TOKEN, cost_tracker)
    suppress = SuppressChecker(linkedin_urls, emails, domains)
    cache = load_supabase_cache()
    pipeline = EnrichmentPipeline(treg, cost_tracker, suppress, cache)
    
    try:
        print("TODO: Implement full pipeline")
        # TODO: Implement LeadsForge → Icypeas → enrichment → verify → upload
        
    finally:
        pipeline.shutdown()
        print()
        print("Cost summary:")
        print(json.dumps(cost_tracker.summary(), indent=2))


if __name__ == "__main__":
    main()
