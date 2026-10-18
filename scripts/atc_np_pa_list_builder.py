#!/usr/bin/env python3
"""ATC NP/PA clinic-owner list builder via Treg + PlusVibe suppress + Supabase list_id.

Gates (.cursor/skills/lead-scrape-gates/SKILL.md):
  --scope-only          free TAM count only
  --pilot               target ready leads (default 25); requires --confirm-spend
  --full                volume run; requires --confirm-spend after pilot
  --confirm-spend USD   hard spend cap
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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://treg.to"
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/atc-np-pa-pilot"))
PLUSVIBE_WS = os.environ.get("PLUSVIBE_WORKSPACE_ID", "6a908184e665953cae106e15")
PLUSVIBE_API = "https://api.plusvibe.ai/api/v1"
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CLIENT = "ATC"
LIST_NAME = "ATC NP/PA clinic owners Oct 18"
SOURCE = "treg.to"
MAX_PER_COMPANY = 2
VALID_MV = {"ok", "catch_all", "valid", "smtp_valid", "catch_all_valid"}

INCLUDE_INDUSTRIES = [
    "medical practices",
    "hospitals and health care",
    "mental health care",
]
EXCLUDE_INDUSTRIES = [
    "staffing and recruiting",
    "insurance",
    "pharmaceutical manufacturing",
    "medical equipment manufacturing",
    "biotechnology research",
    "higher education",
    "e-learning providers",
    "government administration",
    "government relations services",
    "software development",
    "it services and it consulting",
    "advertising services",
    "wellness and fitness services",
    "alternative medicine",
    "business consulting and services",
    "retail",
    "non-profit organizations",
    "individual and family services",
    "technology, information and internet",
    "personal care product manufacturing",
]
KEYWORDS = [
    "urgent care",
    "walk-in clinic",
    "primary care",
    "family practice",
    "family medicine",
    "internal medicine",
    "pediatrics",
    "concierge medicine",
    "direct primary care",
    "house calls",
    "home-based primary care",
    "dermatology",
    "med spa",
    "medical weight loss",
    "men's health",
    "hormone replacement",
    "low T",
    "women's health",
    "OB/GYN",
    "pain management",
    "orthopedics",
    "outpatient psychiatry",
    "psychiatric nurse practitioner",
    "ketamine",
    "TMS",
    "Suboxone",
    "medication-assisted treatment",
    "addiction treatment",
    "behavioral health",
    "cardiology",
    "gastroenterology",
    "wound care",
    "occupational medicine",
    "retail clinic",
    "nurse practitioner",
    "physician assistant",
]
KEYWORD_EXCLUDE = ["hospital", "hospitals", "health system"]
EXCLUDE_COMPANIES = [
    "TeamHealth",
    "Envision Healthcare",
    "MinuteClinic",
    "CVS Health",
    "Walgreens",
    "Teladoc",
    "Amwell",
    "Hims",
    "Hers",
    "One Medical",
    "Forward",
    "Carbon Health",
    "Optum",
]
TITLES_INCLUDE = [
    "CEO",
    "Founder",
    "Co-Founder",
    "Owner",
    "Co-Owner",
    "President",
    "COO",
    "Managing Partner",
    "Practice Owner",
    "Clinic Owner",
    "Head of Operations",
    "Practice Administrator",
]
TITLE_EXCLUDE_RE = re.compile(
    r"\b("
    r"VP|V\.P\.|Vice[\s-]?President|Vice\b|"
    r"Coordinator|Assistant|Sales|Marketing|"
    r"Business\s+Development|Advisor|Board|"
    r"CFO|Finance|CTO|Tech(?:nology)?|"
    r"Nursing|Nurse(?!\s+Practitioner)|HR|People\s+Ops|"
    r"Investor|Intern|Student|Retired|Former|Consultant"
    r")\b",
    re.I,
)
TITLE_RANK = [
    (re.compile(r"\b(practice|clinic)\s+owner\b", re.I), 0),
    (re.compile(r"\b(co[-\s]?founder|founder)\b", re.I), 1),
    (re.compile(r"\b(co[-\s]?owner|owner)\b", re.I), 2),
    (re.compile(r"\bCEO\b", re.I), 3),
    (re.compile(r"\bPresident\b", re.I), 4),
    (re.compile(r"\bManaging\s+Partner\b", re.I), 5),
    (re.compile(r"\bCOO\b|\bHead\s+of\s+Operations\b", re.I), 6),
    (re.compile(r"\bPractice\s+Administrator\b", re.I), 7),
]


def treg_token() -> str:
    for name in ("treg", "TREG_TOKEN", "TREG_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    raise SystemExit("Set treg / TREG_TOKEN")


TOKEN = treg_token()


def supabase_key() -> str:
    raw = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
    key = "".join(c for c in raw if 32 <= ord(c) < 127)
    if not key:
        raise SystemExit("Set SUPABASE_SERVICE_ROLE_KEY")
    return key


def plusvibe_key() -> str:
    for name in ("PLUSVIBE_API_KEY", "PLUSVIBE_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    raise SystemExit("Set PLUSVIBE_API_KEY")


def treg(
    method: str,
    path: str,
    body: Any | None = None,
    query: dict | None = None,
    headers: dict | None = None,
    retries: int = 8,
) -> tuple[Any, dict]:
    url = f"{BASE}{path}"
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"X-Treg-Token": TOKEN, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    last: Any = None
    for i in range(retries):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                meta = {
                    "status": resp.status,
                    "call_id": resp.headers.get("X-Treg-Call-Id"),
                    "cost_micro": int(resp.headers.get("X-Treg-Cost-Micro") or 0),
                    "served_by": resp.headers.get("X-Treg-Served-By"),
                }
                if not raw:
                    return None, meta
                return json.loads(raw.decode()), meta
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")
            last = (e.code, err)
            if e.code in (409, 429, 503) or (500 <= e.code < 600):
                wait = min(8 * (2**i), 90)
                if e.code == 429:
                    wait = max(wait, 20 + 10 * i)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {err[:800]}") from e
        except Exception as e:
            last = e
            time.sleep(min(2**i, 8))
    raise RuntimeError(f"treg failed after retries: {last}")


def sb_headers(prefer: str = "return=representation") -> dict[str, str]:
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
    encoded_path = urllib.parse.quote(path.lstrip("/"), safe="/?&=")
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{encoded_path}"
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers=sb_headers(prefer=prefer), method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw.decode()) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"Supabase {method} {path} failed ({e.code}): {err[:500]}")


def normalize_linkedin(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    u = u.split("?")[0]
    return u


def domain_of(co: dict | None) -> str:
    co = co or {}
    d = (co.get("domain") or co.get("website") or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def title_rank(title: str) -> int:
    t = title or ""
    for rx, rank in TITLE_RANK:
        if rx.search(t):
            return rank
    return 50


def title_ok(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if TITLE_EXCLUDE_RE.search(t):
        return False
    # Must look like one of our include intents (loose)
    include_rx = re.compile(
        r"\b(CEO|Founder|Co[-\s]?Founder|Owner|Co[-\s]?Owner|President|COO|"
        r"Managing\s+Partner|Practice\s+Owner|Clinic\s+Owner|"
        r"Head\s+of\s+Operations|Practice\s+Administrator|"
        r"Company\s+Owner|Small\s+Business\s+Owner)\b",
        re.I,
    )
    return bool(include_rx.search(t))


def search_body(limit: int = 50) -> dict[str, Any]:
    return {
        "companyEmployeeNumberRange": {"min": 2, "max": 500},
        "companyLocations": {"include": ["United States"]},
        "leadLocations": {"include": ["United States"]},
        "companyIndustries": {
            "include": INCLUDE_INDUSTRIES,
            "exclude": EXCLUDE_INDUSTRIES,
        },
        "companyKeywords": {
            "include": KEYWORDS,
            "exclude": KEYWORD_EXCLUDE,
        },
        "companyNames": {"exclude": EXCLUDE_COMPANIES},
        "leadJobTitles": {
            "include": TITLES_INCLUDE,
            "exclude": [
                "VP",
                "Vice",
                "Coordinator",
                "Assistant",
                "Sales",
                "Marketing",
                "Business Development",
                "Advisor",
                "Board",
                "CFO",
                "CTO",
                "Nursing",
                "HR",
                "People",
                "Investor",
                "Intern",
                "Student",
                "Retired",
                "Former",
                "Consultant",
            ],
        },
        "companyRequired": True,
        "maxContactsPerCompany": MAX_PER_COMPANY,
        "limit": limit,
    }


def free_count() -> int:
    body = search_body(limit=1)
    body.pop("limit", None)
    data, _ = treg("POST", "/call/leadsforge.people.search.count", body)
    if isinstance(data, dict):
        return int(data.get("totalCount") or 0)
    return 0


def load_plusvibe_suppress(workspace_id: str) -> set[str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = OUT_DIR / f"plusvibe_suppress_{workspace_id}.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 6 * 3600:
        data = json.loads(cache.read_text())
        emails = set(data.get("emails") or [])
        print(f"plusvibe_suppress={len(emails)} (cached)", flush=True)
        return emails
    emails: set[str] = set()
    page = 1
    page_size = 100
    while True:
        path = (
            f"/lead/workspace-leads?workspace_id={workspace_id}"
            f"&limit={page_size}&page={page}"
        )
        url = f"{PLUSVIBE_API}{path}"
        req = urllib.request.Request(
            url,
            headers={
                "x-api-key": plusvibe_key(),
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            batch = json.loads(resp.read().decode() or "[]")
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            em = (row.get("email") or "").strip().lower()
            if em:
                emails.add(em)
            li = normalize_linkedin(row.get("linkedin_person_url") or "")
            if li:
                emails.add(f"li:{li}")
        if len(batch) < page_size:
            break
        page += 1
        if page % 25 == 0:
            print(f"  plusvibe page={page} suppress={len(emails)}", flush=True)
        time.sleep(0.03)
    cache.write_text(
        json.dumps({"emails": sorted(emails), "workspace_id": workspace_id})
    )
    print(f"plusvibe_suppress={len(emails)}", flush=True)
    return emails


def sb_lookup_by_domain(domain: str) -> list[dict]:
    if not domain:
        return []
    # Website ilike %domain%
    return (
        sb_request(
            "GET",
            "Lead Database",
            query={
                "select": 'id,"First Name","Last Name","Email","Linkedin","Company Name","Website",email_status,enrichment_updated_at',
                "Website": f"ilike.*{domain}*",
                "limit": "10",
            },
        )
        or []
    )


def sb_lookup_by_email(email: str) -> dict | None:
    if not email:
        return None
    rows = (
        sb_request(
            "GET",
            "Lead Database",
            query={
                "select": 'id,"Email","Linkedin",email_status,enrichment_updated_at',
                "Email": f"ilike.{email}",
                "limit": "1",
            },
        )
        or []
    )
    return rows[0] if rows else None


def find_email(lead: dict) -> tuple[str, dict]:
    co = lead.get("company") or {}
    domain = domain_of(co)
    first = (lead.get("firstName") or "").strip()
    last = (lead.get("lastName") or "").strip()
    if not domain or not first or not last:
        return "", {"cost_micro": 0, "served_by": ""}
    body = {
        "domain": domain,
        "first_name": first,
        "last_name": last,
        "full_name": f"{first} {last}",
    }
    headers = {
        "X-Treg-Route-Exclude": "aiark",
        "X-Treg-Route-Max-Cost": "0.006",
        "X-Treg-Route-Waterfall": "0",
        "Idempotency-Key": f"atc-np-pa-{lead.get('id')}",
    }
    data, meta = treg(
        "POST", "/call/treg.people.email.find", body, headers=headers
    )
    email = ""
    enrich_bits: dict[str, str] = {}
    if isinstance(data, dict):
        out = data.get("output") or data
        if isinstance(out, dict):
            email = (
                out.get("email")
                or out.get("work_email")
                or out.get("value")
                or ""
            )
            if not email and isinstance(out.get("emails"), list) and out["emails"]:
                e0 = out["emails"][0]
                email = e0 if isinstance(e0, str) else (e0.get("email") or "")
        raw = data.get("raw")
        if isinstance(raw, dict):
            raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            if not email:
                email = raw_data.get("email") or raw_data.get("work_email") or ""
            for src, dst in (
                ("employee_linkedin", "linkedin"),
                ("company_linked", "company_linkedin"),
            ):
                if raw_data.get(src):
                    enrich_bits[dst] = raw_data[src]
    meta = dict(meta or {})
    meta["enrich_bits"] = enrich_bits
    return (email or "").strip().lower(), meta


def verify_mv(email: str) -> tuple[str, int]:
    data, meta = treg(
        "GET",
        "/call/millionverifier.people.email.verify",
        query={"email": email},
    )
    status = ""
    if isinstance(data, dict):
        status = (
            data.get("result")
            or data.get("status")
            or (data.get("output") or {}).get("result")
            or (data.get("output") or {}).get("status")
            or ""
        )
        if isinstance(status, dict):
            status = status.get("result") or status.get("status") or ""
    return str(status).lower().strip(), int(meta.get("cost_micro") or 0)


def upsert_lead(row: dict) -> int:
    email = (row.get("email") or "").strip().lower()
    linkedin = row.get("linkedin") or ""
    existing = None
    if email:
        existing = sb_lookup_by_email(email)
    if not existing and linkedin:
        rows = (
            sb_request(
                "GET",
                "Lead Database",
                query={
                    "select": "id",
                    "Linkedin": f"ilike.*{normalize_linkedin(linkedin).split('/')[-1]}*",
                    "limit": "1",
                },
            )
            or []
        )
        existing = rows[0] if rows else None

    payload = {
        "First Name": row.get("first_name"),
        "Last Name": row.get("last_name"),
        "Email": email or None,
        "Linkedin": linkedin or None,
        "Company Name": row.get("company_name"),
        "Website": row.get("website"),
        "company_size": row.get("company_size"),
        "location": row.get("location"),
        "email_source": row.get("email_source"),
        "email_status": row.get("email_status"),
        "enrichment_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Drop Nones
    payload = {k: v for k, v in payload.items() if v is not None and v != ""}
    if existing:
        lead_id = existing["id"]
        sb_request(
            "PATCH",
            "Lead Database",
            payload,
            query={"id": f"eq.{lead_id}"},
            prefer="return=minimal",
        )
        return int(lead_id)
    created = sb_request("POST", "Lead Database", payload)
    if not created:
        raise RuntimeError("Lead Database insert returned empty")
    return int(created[0]["id"])


def create_list_with_members(
    lead_ids: list[int],
    ready_count: int,
    actual_cost: float,
    cap: float,
    report: dict,
) -> str:
    list_row = sb_request(
        "POST",
        "lead_lists",
        {
            "client": CLIENT,
            "list_name": LIST_NAME,
            "source": SOURCE,
            "status": "enriched" if ready_count else "scraped",
            "total_leads": len(lead_ids),
            "enriched_count": ready_count,
            "ready_count": ready_count,
            "estimated_cost_usd": cap,
            "actual_cost_usd": round(actual_cost, 6),
            "cost_cap_usd": cap,
            "enrichment_completed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "campaign": "ATC NP/PA",
                "max_per_company": MAX_PER_COMPANY,
                "mode": report.get("mode"),
            },
            "run_report": report,
        },
    )
    list_id = list_row[0]["list_id"]
    members = [
        {
            "list_id": list_id,
            "lead_id": lid,
            "enrichment_status": "enriched",
            "enrichment_completed_at": datetime.now(timezone.utc).isoformat(),
        }
        for lid in lead_ids
    ]
    for i in range(0, len(members), 100):
        sb_request("POST", "lead_list_members", members[i : i + 100], prefer="return=minimal")
    return list_id


def collect_candidates(need: int) -> list[dict]:
    """Page search until we have enough post-filtered candidates (overpull)."""
    target = max(need * 4, 80)  # overpull for miss/verify/plusvibe drop
    cursor = None
    by_domain: dict[str, list[dict]] = {}
    seen_ids: set[str] = set()
    pages = 0
    while sum(len(v) for v in by_domain.values()) < target and pages < 40:
        body = search_body(limit=50)
        query = {"cursor": cursor} if cursor else None
        data, meta = treg(
            "POST",
            "/call/leadsforge.people.search",
            body,
            query=query,
        )
        pages += 1
        leads = (data or {}).get("leads") or []
        cursor = (data or {}).get("cursor")
        print(
            f"search_page={pages} got={len(leads)} cost_micro={meta.get('cost_micro')} "
            f"kept={sum(len(v) for v in by_domain.values())}",
            flush=True,
        )
        for lead in leads:
            pid = str(lead.get("id") or "")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            title = lead.get("jobTitle") or ""
            if not title_ok(title):
                continue
            co = lead.get("company") or {}
            domain = domain_of(co)
            if not domain:
                continue
            # company name exclude soft match
            cname = (co.get("name") or "").lower()
            if any(x.lower() in cname for x in EXCLUDE_COMPANIES if cname):
                continue
            bucket = by_domain.setdefault(domain, [])
            if len(bucket) >= MAX_PER_COMPANY:
                # keep higher-rank titles
                bucket.append(lead)
                bucket.sort(key=lambda L: title_rank(L.get("jobTitle") or ""))
                del bucket[MAX_PER_COMPANY:]
            else:
                bucket.append(lead)
                bucket.sort(key=lambda L: title_rank(L.get("jobTitle") or ""))
        if not leads or not cursor:
            break
        time.sleep(0.05)
    flat: list[dict] = []
    for domain, people in by_domain.items():
        for p in people[:MAX_PER_COMPANY]:
            flat.append(p)
    flat.sort(key=lambda L: title_rank(L.get("jobTitle") or ""))
    print(f"candidates={len(flat)} domains={len(by_domain)}", flush=True)
    return flat


def run_build(mode: str, confirm_spend: float, ready_target: int) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cap_micro = int(round(confirm_spend * 1_000_000))
    spent_micro = 0
    tam = free_count()
    print(f"TAM_people={tam:,} mode={mode} ready_target={ready_target} cap=${confirm_spend}", flush=True)

    pv = load_plusvibe_suppress(PLUSVIBE_WS)
    candidates = collect_candidates(ready_target)

    ready_rows: list[dict] = []
    lead_ids: list[int] = []
    stats = {
        "searched": len(candidates),
        "skipped_no_domain": 0,
        "skipped_known_supabase": 0,
        "plusvibe_excluded": 0,
        "find_attempts": 0,
        "find_hits": 0,
        "verify_attempts": 0,
        "ready": 0,
        "failed_find": 0,
        "failed_verify": 0,
        "emails_by_source": {},
        "cost_by_provider": {},
    }

    for lead in candidates:
        if stats["ready"] >= ready_target:
            break
        # leave headroom for one more find+verify (~$0.007)
        if spent_micro + 7000 > cap_micro:
            print(
                f"stop_near_cap spent=${spent_micro/1e6:.4f} ready={stats['ready']}",
                flush=True,
            )
            break

        co = lead.get("company") or {}
        domain = domain_of(co)
        first = (lead.get("firstName") or "").strip()
        last = (lead.get("lastName") or "").strip()
        if not domain or not first or not last:
            stats["skipped_no_domain"] += 1
            continue

        email = ""
        email_source = ""
        linkedin = lead.get("linkedinUrl") or lead.get("linkedin") or ""
        mv_status = ""

        # Supabase cache by domain / name match
        cached = sb_lookup_by_domain(domain)
        for row in cached:
            rn = f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}".lower()
            if rn == f"{first} {last}".lower() and row.get("Email"):
                email = row["Email"].strip().lower()
                email_source = "supabase_cache"
                linkedin = linkedin or row.get("Linkedin") or ""
                stats["skipped_known_supabase"] += 1
                break

        if email and (email in pv or (linkedin and f"li:{normalize_linkedin(linkedin)}" in pv)):
            stats["plusvibe_excluded"] += 1
            continue

        if not email:
            # paid find
            if spent_micro + 6000 > cap_micro:
                break
            stats["find_attempts"] += 1
            try:
                email, meta = find_email(lead)
            except Exception as e:
                print(f"find_err {first} {last} @{domain}: {e}", flush=True)
                stats["failed_find"] += 1
                continue
            cost = int(meta.get("cost_micro") or 0)
            spent_micro += cost
            served = meta.get("served_by") or "treg.people.email.find"
            stats["cost_by_provider"][served] = (
                stats["cost_by_provider"].get(served, 0) + cost / 1e6
            )
            bits = meta.get("enrich_bits") or {}
            if bits.get("linkedin"):
                linkedin = linkedin or bits["linkedin"]
            if email:
                stats["find_hits"] += 1
                email_source = served
            else:
                stats["failed_find"] += 1
                continue

        if email in pv or (linkedin and f"li:{normalize_linkedin(linkedin)}" in pv):
            stats["plusvibe_excluded"] += 1
            continue

        # verify
        if spent_micro + 2000 > cap_micro:
            break
        stats["verify_attempts"] += 1
        try:
            mv_status, vcost = verify_mv(email)
        except Exception as e:
            print(f"verify_err {email}: {e}", flush=True)
            stats["failed_verify"] += 1
            continue
        spent_micro += vcost
        stats["cost_by_provider"]["millionverifier.people.email.verify"] = (
            stats["cost_by_provider"].get("millionverifier.people.email.verify", 0)
            + vcost / 1e6
        )
        if mv_status not in VALID_MV:
            stats["failed_verify"] += 1
            continue

        loc = lead.get("location") or {}
        location = ", ".join(
            x for x in [loc.get("city"), loc.get("state"), loc.get("country")] if x
        )
        website = co.get("website") or (f"https://{domain}" if domain else "")
        row = {
            "first_name": first,
            "last_name": last,
            "email": email,
            "linkedin": linkedin if linkedin.startswith("http") else (f"https://{linkedin}" if linkedin else ""),
            "title": lead.get("jobTitle") or "",
            "company_name": co.get("name") or domain,
            "website": website,
            "company_size": str(co.get("employeeCount") or ""),
            "company_industry": co.get("industry") or "",
            "location": location,
            "email_source": email_source,
            "email_status": mv_status,
            "domain": domain,
            "person_id": lead.get("id"),
        }
        try:
            lid = upsert_lead(row)
        except Exception as e:
            print(f"sb_upsert_err {email}: {e}", flush=True)
            continue
        lead_ids.append(lid)
        ready_rows.append(row)
        stats["ready"] += 1
        stats["emails_by_source"][email_source] = (
            stats["emails_by_source"].get(email_source, 0) + 1
        )
        print(
            f"ready={stats['ready']}/{ready_target} {first} {last} <{email}> "
            f"@{domain} mv={mv_status} spent=${spent_micro/1e6:.4f}",
            flush=True,
        )

    actual_cost = spent_micro / 1e6
    report = {
        "mode": mode,
        "list_name": LIST_NAME,
        "TAM_people": tam,
        "confirm_spend_usd": confirm_spend,
        "actual_cost_usd": round(actual_cost, 6),
        "ready_target": ready_target,
        "max_per_company": MAX_PER_COMPANY,
        "plusvibe_workspace_id": PLUSVIBE_WS,
        "plusvibe_suppress_size": len(pv),
        "stats": stats,
        "tool_order": [
            "leadsforge.people.search",
            "treg.people.email.find (exclude aiark, max $0.006)",
            "millionverifier.people.email.verify",
            "plusvibe workspace suppress",
            "supabase Lead Database + lead_lists",
        ],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }

    list_id = ""
    if lead_ids:
        list_id = create_list_with_members(
            lead_ids, stats["ready"], actual_cost, confirm_spend, report
        )
        report["list_id"] = list_id

    # CSV handoff
    csv_path = OUT_DIR / f"atc-np-pa-{mode}-ready.csv"
    if ready_rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(ready_rows[0].keys()))
            w.writeheader()
            w.writerows(ready_rows)
    report_path = OUT_DIR / f"atc-np-pa-{mode}-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps({"list_id": list_id, "ready": stats["ready"], "spend": actual_cost, "csv": str(csv_path), "report": str(report_path)}, indent=2))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--scope-only", action="store_true")
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--full", action="store_true")
    ap.add_argument("--confirm-spend", type=float, default=None)
    ap.add_argument("--ready-target", type=int, default=None)
    args = ap.parse_args()

    if args.scope_only:
        tam = free_count()
        print(f"TAM_people={tam:,}")
        print("No paid calls. Re-run with --pilot --confirm-spend N")
        return

    if args.confirm_spend is None:
        raise SystemExit("--confirm-spend USD required for pilot/full")
    mode = "pilot" if args.pilot else "full"
    ready = args.ready_target or (25 if args.pilot else 2000)
    run_build(mode, args.confirm_spend, ready)


if __name__ == "__main__":
    main()
