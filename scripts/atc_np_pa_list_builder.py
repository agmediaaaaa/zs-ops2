#!/usr/bin/env python3
"""ATC NP/PA clinic-owner list builder — pull-N staged pipeline.

Pull-N (locked): --pull 100 = Icypeas people search of 100, then enrich that
batch only. Ready emails = whatever validates (not a ready-email target).

Stages:
  1) icypeas.people.search → N candidates
  2) Supabase cache on batch
  3) concurrent email find (Blitz/QE/Trykitt via treg; NO Icypeas email)
  4) concurrent MV verify
  5) bulk Supabase upload (desc, loc, …)

Gates (.cursor/skills/lead-scrape-gates/SKILL.md):
  --scope-only          free TAM count only
  --pull N              people to pull (default pilot 100 / full 2000)
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pull_n_pipeline as pull_n

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


def icypeas_people_query() -> dict[str, Any]:
    """Icypeas people search query for ATC NP/PA clinic owners."""
    return {
        "currentJobTitle": {"include": TITLES_INCLUDE},
        "location": {"include": ["United States", "US"]},
        "keyword": {
            "include": KEYWORDS + INCLUDE_INDUSTRIES,
            "exclude": KEYWORD_EXCLUDE + EXCLUDE_INDUSTRIES,
        },
        "currentCompany.headcount": {">=": 2, "<=": 500},
    }


def free_count() -> int:
    data, _ = treg(
        "POST",
        "/call/icypeas.people.search.count",
        {"query": icypeas_people_query()},
    )
    if isinstance(data, dict):
        return int(data.get("total") or data.get("count") or data.get("totalCount") or 0)
    return 0


def search_page(token: str | None = None, size: int = 100) -> tuple[Any, dict]:
    body: dict[str, Any] = {
        "query": icypeas_people_query(),
        "pagination": {"size": size},
    }
    if token:
        body["pagination"]["token"] = token
    return treg("POST", "/call/icypeas.people.search", body)


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
        # Pull-N default: never use Icypeas (or AI Ark) for email find
        "X-Treg-Route-Exclude": pull_n.email_exclude_header(with_icypeas_email=False),
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


def _extract_company_about(payload: Any) -> tuple[str, str, str]:
    """Return (description, company_name, company_linkedin) from enrich payloads."""
    desc = name = li = ""
    if not isinstance(payload, dict):
        return desc, name, li
    company = payload.get("company") if isinstance(payload.get("company"), dict) else None
    out = payload.get("output") if isinstance(payload.get("output"), dict) else None
    result = payload.get("result") if isinstance(payload.get("result"), dict) else None
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else None
    src = company or out or result or payload
    if not isinstance(src, dict):
        return desc, name, li
    desc = (
        src.get("about")
        or src.get("description")
        or src.get("tagline")
        or src.get("company_description")
        or ""
    )
    if isinstance(desc, dict):
        desc = desc.get("text") or desc.get("description") or ""
    # thecompaniesapi nests copy under raw.descriptions
    if not desc and isinstance(raw, dict):
        descriptions = raw.get("descriptions") or {}
        if isinstance(descriptions, dict):
            desc = descriptions.get("website") or descriptions.get("tagline") or ""
        about = raw.get("about") if isinstance(raw.get("about"), dict) else {}
        if not name and about.get("name"):
            name = about["name"]
    name = name or (src.get("name") or src.get("company_name") or "").strip()
    li = (
        src.get("linkedin_url")
        or src.get("company_linkedin_url")
        or src.get("linkedin")
        or ""
    ).strip()
    return str(desc or "").strip(), name, li


def enrich_company_profile(
    domain: str,
    company_linkedin: str = "",
    company_name: str = "",
) -> tuple[dict[str, str], int, str]:
    """Blitz (preferred) then Icypeas for company description. Required for campaign-ready.

    Returns (fields, cost_micro, served_by). fields may include company_description,
    company_name, company_linkedin.
    """
    spent = 0
    fields: dict[str, str] = {}
    li = (company_linkedin or "").strip()
    served = ""

    # 1) Blitz: domain → LinkedIn (if needed)
    if not li and domain:
        data, meta = treg(
            "POST",
            "/call/blitzapi.companies.domain-to-linkedin",
            {"domain": domain},
        )
        spent += int(meta.get("cost_micro") or 0)
        if isinstance(data, dict) and data.get("found"):
            li = (data.get("company_linkedin_url") or "").strip()
            if data.get("company_name") and not company_name:
                fields["company_name"] = data["company_name"]
        served = "blitzapi.companies.domain-to-linkedin"

    # 2) Blitz company enrich (about)
    if li:
        data, meta = treg(
            "POST",
            "/call/blitzapi.companies.enrich",
            {"company_linkedin_url": li},
        )
        spent += int(meta.get("cost_micro") or 0)
        served = "blitzapi.companies.enrich"
        desc, name, li2 = _extract_company_about(data)
        if li2:
            li = li2
        if name:
            fields["company_name"] = name
        if desc:
            fields["company_description"] = desc
            fields["company_linkedin"] = li
            return fields, spent, served

    # 3) thecompaniesapi by domain (often has website blurb when Blitz about is empty)
    if domain:
        data, meta = treg(
            "POST",
            "/call/treg.companies.enrich",
            {k: v for k, v in {"domain": domain, "name": company_name or ""}.items() if v},
            headers={
                "X-Treg-Route-Prefer": "thecompaniesapi,hunter,icypeas",
                "X-Treg-Route-Exclude": "dropleads,blitzapi",
                "X-Treg-Route-Max-Cost": "0.02",
                "X-Treg-Route-Waterfall": "1",
            },
        )
        spent += int(meta.get("cost_micro") or 0)
        served = meta.get("served_by") or "treg.companies.enrich"
        desc, name, li2 = _extract_company_about(data if isinstance(data, dict) else {})
        if li2:
            li = li or li2
        if name:
            fields["company_name"] = name
        if desc:
            fields["company_description"] = desc
            if li:
                fields["company_linkedin"] = li
            return fields, spent, served

    # 4) Icypeas fallback: resolve URL then enrich (returns description)
    lookup = domain or company_name
    if lookup:
        data, meta = treg(
            "POST",
            "/call/icypeas.companies.profile.url",
            {"companyOrDomain": lookup},
        )
        spent += int(meta.get("cost_micro") or 0)
        icy_url = ""
        if isinstance(data, dict):
            icy_url = (data.get("result") or "").strip()
            if data.get("status") == "FOUND" and icy_url:
                li = li or icy_url
        if icy_url:
            data2, meta2 = treg(
                "GET",
                "/call/icypeas.companies.enrich",
                query={"url": icy_url},
            )
            spent += int(meta2.get("cost_micro") or 0)
            served = "icypeas.companies.enrich"
            src = data2
            if isinstance(data2, dict):
                src = data2.get("result") or data2.get("output") or data2
            desc, name, li2 = _extract_company_about(src if isinstance(src, dict) else {})
            if not desc and isinstance(src, dict):
                desc = (
                    src.get("description")
                    or src.get("about")
                    or (src.get("company") or {}).get("description")
                    or ""
                )
                name = name or (src.get("name") or "")
            if name:
                fields["company_name"] = name
            if desc:
                fields["company_description"] = str(desc).strip()
                fields["company_linkedin"] = li or icy_url
                return fields, spent, served

    if li:
        fields["company_linkedin"] = li
    return fields, spent, served or "company_enrich_miss"


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
        "company_description": row.get("company_description"),
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


def _normalize_icypeas_lead(raw: dict) -> dict | None:
    """Map Icypeas people row → common lead shape used by find_email/etc."""
    first = (
        raw.get("firstName")
        or raw.get("firstname")
        or raw.get("first_name")
        or ""
    ).strip()
    last = (
        raw.get("lastName") or raw.get("lastname") or raw.get("last_name") or ""
    ).strip()
    title = (
        raw.get("jobTitle")
        or raw.get("title")
        or raw.get("currentJobTitle")
        or ""
    ).strip()
    if isinstance(title, dict):
        title = (title.get("title") or title.get("name") or "").strip()
    linkedin = (
        raw.get("linkedinUrl")
        or raw.get("linkedin")
        or raw.get("linkedin_url")
        or ""
    ).strip()
    co = raw.get("company") or raw.get("currentCompany") or {}
    if not isinstance(co, dict):
        co = {}
    # Inline company about from Icypeas people payload when present
    desc = (
        raw.get("lastCompanyDescription")
        or co.get("description")
        or co.get("about")
        or ""
    )
    if desc and not co.get("description"):
        co = dict(co)
        co["description"] = desc
    website = co.get("website") or co.get("domain") or ""
    domain = domain_of(co) or domain_of({"website": website})
    pid = str(raw.get("id") or raw.get("_id") or linkedin or f"{first}-{last}-{domain}")
    if not first or not last:
        return None
    return {
        "id": pid,
        "firstName": first,
        "lastName": last,
        "jobTitle": title,
        "linkedinUrl": linkedin,
        "linkedin": linkedin,
        "company": co,
        "location": raw.get("location") or {},
        "_raw": raw,
    }


def collect_candidates(pull: int) -> tuple[list[dict], int]:
    """Stage 1: Icypeas people search until pulled == N (post-filter).

    Returns (candidates, search_cost_micro). No email enrich here.
    """
    token = None
    by_domain: dict[str, list[dict]] = {}
    seen_ids: set[str] = set()
    pages = 0
    search_cost = 0
    max_pages = max(40, (pull // 50) + 10)

    while sum(len(v) for v in by_domain.values()) < pull and pages < max_pages:
        try:
            data, meta = search_page(token, size=100)
        except Exception as e:
            print(f"search_err page={pages}: {e}", flush=True)
            break
        search_cost += int(meta.get("cost_micro") or 0)
        pages += 1
        leads_raw = []
        if isinstance(data, dict):
            for k in ("leads", "results", "people", "data", "items"):
                if isinstance(data.get(k), list):
                    leads_raw = data[k]
                    break
            pag = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
            token = (
                pag.get("token")
                or data.get("token")
                or data.get("nextPageToken")
                or data.get("cursor")
            )
        print(
            f"search_page={pages} got={len(leads_raw)} cost_micro={meta.get('cost_micro')} "
            f"kept={sum(len(v) for v in by_domain.values())}/{pull}",
            flush=True,
        )
        for raw in leads_raw:
            if not isinstance(raw, dict):
                continue
            lead = _normalize_icypeas_lead(raw)
            if not lead:
                continue
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
            cname = (co.get("name") or "").lower()
            if any(x.lower() in cname for x in EXCLUDE_COMPANIES if cname):
                continue
            bucket = by_domain.setdefault(domain, [])
            bucket.append(lead)
            bucket.sort(key=lambda L: title_rank(L.get("jobTitle") or ""))
            del bucket[MAX_PER_COMPANY:]
            if sum(len(v) for v in by_domain.values()) >= pull:
                break
        if not leads_raw or not token:
            break
        time.sleep(0.05)

    flat: list[dict] = []
    for domain, people in by_domain.items():
        for p in people[:MAX_PER_COMPANY]:
            flat.append(p)
    flat.sort(key=lambda L: title_rank(L.get("jobTitle") or ""))
    flat = flat[:pull]
    print(
        f"STAGE1_pulled={len(flat)} domains={len(by_domain)} "
        f"search_cost=${search_cost/1e6:.4f}",
        flush=True,
    )
    return flat, search_cost


def run_build(mode: str, confirm_spend: float, pull: int) -> dict:
    """Pull-N staged build: discover N → cache → find → MV → bulk Supabase."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cap_micro = int(round(confirm_spend * 1_000_000))
    spent_micro = 0
    tam = free_count()
    print(
        f"TAM_people={tam:,} mode={mode} pull={pull} "
        f"(N=Icypeas people, not ready target) cap=${confirm_spend}",
        flush=True,
    )

    pv = load_plusvibe_suppress(PLUSVIBE_WS)

    # --- Stage 1: Icypeas people pull ---
    candidates, search_cost = collect_candidates(pull)
    spent_micro += search_cost
    stats = {
        "pulled": len(candidates),
        "pull_requested": pull,
        "skipped_no_domain": 0,
        "skipped_known_supabase": 0,
        "plusvibe_excluded": 0,
        "find_attempts": 0,
        "find_hits": 0,
        "verify_attempts": 0,
        "ready": 0,
        "failed_find": 0,
        "failed_verify": 0,
        "failed_company_desc": 0,
        "company_enrich_hits": 0,
        "emails_by_source": {},
        "cost_by_provider": {
            "icypeas.people.search": search_cost / 1e6,
        },
    }

    # --- Stage 2: Supabase cache on whole batch ---
    print(f"STAGE2_cache checking {len(candidates)} leads...", flush=True)
    pending: list[dict] = []
    cached_ready: list[dict] = []  # lead + email already known
    for lead in candidates:
        co = lead.get("company") or {}
        domain = domain_of(co)
        first = (lead.get("firstName") or "").strip()
        last = (lead.get("lastName") or "").strip()
        linkedin = lead.get("linkedinUrl") or lead.get("linkedin") or ""
        if not domain or not first or not last:
            stats["skipped_no_domain"] += 1
            continue
        email = ""
        email_source = ""
        cached = sb_lookup_by_domain(domain)
        for row in cached:
            rn = (
                f"{(row.get('First Name') or '').strip()} "
                f"{(row.get('Last Name') or '').strip()}"
            ).lower()
            if rn == f"{first} {last}".lower() and row.get("Email"):
                email = row["Email"].strip().lower()
                email_source = "supabase_cache"
                linkedin = linkedin or row.get("Linkedin") or ""
                stats["skipped_known_supabase"] += 1
                break
        if email and (
            email in pv
            or (linkedin and f"li:{normalize_linkedin(linkedin)}" in pv)
        ):
            stats["plusvibe_excluded"] += 1
            continue
        item = {
            "lead": lead,
            "domain": domain,
            "first": first,
            "last": last,
            "linkedin": linkedin,
            "email": email,
            "email_source": email_source,
            "mv_status": "",
            "co": co,
        }
        if email:
            cached_ready.append(item)
        else:
            pending.append(item)

    print(
        f"STAGE2_done cache_hits={len(cached_ready)} need_find={len(pending)}",
        flush=True,
    )

    # --- Stage 3: concurrent email find (no Icypeas email) ---
    print(f"STAGE3_find concurrent={min(pull_n.FIND_WORKERS, max(len(pending), 1))}...", flush=True)
    found_items: list[dict] = list(cached_ready)

    def _find_one(item: dict) -> tuple[dict, int, str]:
        lead = item["lead"]
        email, meta = find_email(lead)
        cost = int(meta.get("cost_micro") or 0)
        served = meta.get("served_by") or "treg.people.email.find"
        bits = meta.get("enrich_bits") or {}
        if bits.get("linkedin"):
            item["linkedin"] = item["linkedin"] or bits["linkedin"]
        item["email"] = email
        item["email_source"] = served if email else ""
        return item, cost, served

    with ThreadPoolExecutor(max_workers=min(pull_n.FIND_WORKERS, max(len(pending), 1))) as pool:
        futs = {pool.submit(_find_one, it): it for it in pending}
        for fut in as_completed(futs):
            if spent_micro + 6000 > cap_micro:
                print(f"stop_near_cap during find spent=${spent_micro/1e6:.4f}", flush=True)
                break
            stats["find_attempts"] += 1
            try:
                item, cost, served = fut.result()
            except Exception as e:
                print(f"find_err: {e}", flush=True)
                stats["failed_find"] += 1
                continue
            spent_micro += cost
            stats["cost_by_provider"][served] = (
                stats["cost_by_provider"].get(served, 0) + cost / 1e6
            )
            if not item.get("email"):
                stats["failed_find"] += 1
                continue
            stats["find_hits"] += 1
            em = item["email"]
            li = item.get("linkedin") or ""
            if em in pv or (li and f"li:{normalize_linkedin(li)}" in pv):
                stats["plusvibe_excluded"] += 1
                continue
            found_items.append(item)

    print(
        f"STAGE3_done with_email={len(found_items)} spent=${spent_micro/1e6:.4f}",
        flush=True,
    )

    # --- Stage 4: concurrent MV verify ---
    to_verify = [it for it in found_items if it.get("email")]
    print(f"STAGE4_mv verifying {len(to_verify)}...", flush=True)
    verified: list[dict] = []

    def _mv_one(item: dict) -> tuple[dict, int]:
        # Cache hits still get a fresh MV if status empty
        if item.get("email_source") == "supabase_cache" and item.get("mv_status") in VALID_MV:
            return item, 0
        status, cost = verify_mv(item["email"])
        item["mv_status"] = status
        return item, cost

    with ThreadPoolExecutor(max_workers=min(pull_n.MV_WORKERS, max(len(to_verify), 1))) as pool:
        futs = {pool.submit(_mv_one, it): it for it in to_verify}
        for fut in as_completed(futs):
            if spent_micro + 2000 > cap_micro:
                print(f"stop_near_cap during MV spent=${spent_micro/1e6:.4f}", flush=True)
                break
            stats["verify_attempts"] += 1
            try:
                item, vcost = fut.result()
            except Exception as e:
                print(f"verify_err: {e}", flush=True)
                stats["failed_verify"] += 1
                continue
            spent_micro += vcost
            stats["cost_by_provider"]["millionverifier.people.email.verify"] = (
                stats["cost_by_provider"].get(
                    "millionverifier.people.email.verify", 0
                )
                + vcost / 1e6
            )
            if item.get("mv_status") not in VALID_MV:
                stats["failed_verify"] += 1
                continue
            verified.append(item)

    print(
        f"STAGE4_done verified={len(verified)} spent=${spent_micro/1e6:.4f}",
        flush=True,
    )

    # --- Stage 5: company desc + bulk Supabase upload ---
    print(f"STAGE5_upload building {len(verified)} ready rows...", flush=True)
    ready_rows: list[dict] = []
    lead_ids: list[int] = []

    for item in verified:
        if spent_micro + 2000 > cap_micro:
            break
        lead = item["lead"]
        co = item["co"]
        domain = item["domain"]
        # Prefer inline Icypeas company description
        inline_desc = (
            (co.get("description") or co.get("about") or "")
            if isinstance(co, dict)
            else ""
        ).strip()
        cfields: dict[str, str] = {}
        cserved = "icypeas_inline"
        ccost = 0
        if inline_desc:
            cfields = {"company_description": inline_desc, "company_name": co.get("name") or ""}
        else:
            try:
                cfields, ccost, cserved = enrich_company_profile(
                    domain,
                    company_linkedin="",
                    company_name=(co.get("name") or ""),
                )
            except Exception as e:
                print(f"company_enrich_err @{domain}: {e}", flush=True)
                stats["failed_company_desc"] += 1
                continue
            spent_micro += ccost
            stats["cost_by_provider"][cserved] = (
                stats["cost_by_provider"].get(cserved, 0) + ccost / 1e6
            )
        company_description = (cfields.get("company_description") or inline_desc or "").strip()
        if not company_description:
            stats["failed_company_desc"] += 1
            continue
        stats["company_enrich_hits"] += 1

        loc = lead.get("location") or {}
        if not isinstance(loc, dict):
            loc = {}
        location = ", ".join(
            x for x in [loc.get("city"), loc.get("state"), loc.get("country")] if x
        )
        website = co.get("website") or (f"https://{domain}" if domain else "")
        linkedin = item.get("linkedin") or ""
        row = {
            "first_name": item["first"],
            "last_name": item["last"],
            "email": item["email"],
            "linkedin": linkedin
            if str(linkedin).startswith("http")
            else (f"https://{linkedin}" if linkedin else ""),
            "title": lead.get("jobTitle") or "",
            "company_name": cfields.get("company_name") or co.get("name") or domain,
            "website": website,
            "company_size": str(co.get("employeeCount") or co.get("headcount") or ""),
            "company_industry": co.get("industry") or "",
            "company_description": company_description,
            "company_linkedin": cfields.get("company_linkedin") or "",
            "location": location,
            "email_source": item.get("email_source") or "",
            "email_status": item.get("mv_status") or "",
            "domain": domain,
            "person_id": lead.get("id"),
        }
        try:
            lid = upsert_lead(row)
        except Exception as e:
            print(f"sb_upsert_err {row['email']}: {e}", flush=True)
            continue
        lead_ids.append(lid)
        ready_rows.append(row)
        stats["ready"] += 1
        src = row["email_source"] or "unknown"
        stats["emails_by_source"][src] = stats["emails_by_source"].get(src, 0) + 1
        print(
            f"ready={stats['ready']}/{stats['pulled']} pulled "
            f"{row['first_name']} {row['last_name']} <{row['email']}> "
            f"@{domain} mv={row['email_status']} spent=${spent_micro/1e6:.4f}",
            flush=True,
        )

    actual_cost = spent_micro / 1e6
    pull_report = pull_n.report_pull_n(
        pull=pull,
        pulled=stats["pulled"],
        ready=stats["ready"],
        skipped_cache=stats["skipped_known_supabase"],
        plusvibe_excluded=stats["plusvibe_excluded"],
        find_attempts=stats["find_attempts"],
        find_hits=stats["find_hits"],
        spent_usd=actual_cost,
        email_order=[
            "supabase_cache",
            "treg.people.email.find (exclude aiark,icypeas)",
            "millionverifier.people.email.verify",
        ],
    )
    report = {
        "mode": mode,
        "list_name": LIST_NAME,
        "TAM_people": tam,
        "confirm_spend_usd": confirm_spend,
        "actual_cost_usd": round(actual_cost, 6),
        "pull": pull,
        "max_per_company": MAX_PER_COMPANY,
        "plusvibe_workspace_id": PLUSVIBE_WS,
        "plusvibe_suppress_size": len(pv),
        "stats": stats,
        "pull_n": pull_report,
        "tool_order": [
            "icypeas.people.search (Stage 1 pull-N)",
            "supabase cache (Stage 2)",
            "treg.people.email.find exclude aiark,icypeas (Stage 3 concurrent)",
            "millionverifier.people.email.verify (Stage 4 concurrent)",
            "company desc inline/Blitz/Icypeas companies enrich (Stage 5)",
            "supabase Lead Database + lead_lists bulk members",
        ],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }

    list_id = ""
    if lead_ids:
        list_id = create_list_with_members(
            lead_ids, stats["ready"], actual_cost, confirm_spend, report
        )
        report["list_id"] = list_id

    csv_path = OUT_DIR / f"atc-np-pa-{mode}-ready.csv"
    if ready_rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(ready_rows[0].keys()))
            w.writeheader()
            w.writerows(ready_rows)
    report_path = OUT_DIR / f"atc-np-pa-{mode}-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "list_id": list_id,
                "pulled": stats["pulled"],
                "ready": stats["ready"],
                "coverage": pull_report["coverage"],
                "spend": actual_cost,
                "csv": str(csv_path),
                "report": str(report_path),
            },
            indent=2,
        )
    )
    return report


def backfill_company_descriptions(list_id: str, confirm_spend: float) -> dict:
    """Fill company_description (+ name when missing) for an existing list."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cap_micro = int(round(confirm_spend * 1_000_000))
    spent_micro = 0
    members = (
        sb_request(
            "GET",
            "lead_list_members",
            query={
                "list_id": f"eq.{list_id}",
                "select": "lead_id",
                "limit": "500",
            },
        )
        or []
    )
    lead_ids = [int(m["lead_id"]) for m in members]
    print(f"backfill list_id={list_id} members={len(lead_ids)} cap=${confirm_spend}", flush=True)
    updated = 0
    missed = 0
    already = 0
    domain_cache: dict[str, dict[str, str]] = {}

    for lid in lead_ids:
        if spent_micro + 2000 > cap_micro:
            print(f"stop_near_cap spent=${spent_micro/1e6:.4f}", flush=True)
            break
        rows = (
            sb_request(
                "GET",
                "Lead Database",
                query={
                    "id": f"eq.{lid}",
                    "select": 'id,"Company Name","Website",company_description,company_size,location',
                    "limit": "1",
                },
            )
            or []
        )
        if not rows:
            continue
        row = rows[0]
        if (row.get("company_description") or "").strip():
            already += 1
            continue
        website = row.get("Website") or ""
        domain = domain_of({"website": website, "domain": ""})
        if not domain and website:
            domain = domain_of({"domain": website})
        if not domain:
            missed += 1
            print(f"miss_no_domain lead_id={lid}", flush=True)
            continue
        if domain in domain_cache:
            fields = domain_cache[domain]
            ccost = 0
            cserved = "cache"
        else:
            try:
                fields, ccost, cserved = enrich_company_profile(
                    domain,
                    company_name=(row.get("Company Name") or ""),
                )
            except Exception as e:
                print(f"enrich_err lead_id={lid} @{domain}: {e}", flush=True)
                missed += 1
                continue
            spent_micro += ccost
            domain_cache[domain] = fields
        desc = (fields.get("company_description") or "").strip()
        if not desc:
            missed += 1
            print(f"miss_no_desc lead_id={lid} @{domain} via={cserved}", flush=True)
            continue
        patch = {
            "company_description": desc,
            "enrichment_updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if fields.get("company_name"):
            patch["Company Name"] = fields["company_name"]
        sb_request(
            "PATCH",
            "Lead Database",
            patch,
            query={"id": f"eq.{lid}"},
            prefer="return=minimal",
        )
        updated += 1
        print(
            f"updated={updated} lead_id={lid} @{domain} via={cserved} "
            f"spent=${spent_micro/1e6:.4f} desc_len={len(desc)}",
            flush=True,
        )

    report = {
        "mode": "backfill_company_description",
        "list_id": list_id,
        "updated": updated,
        "already_had_desc": already,
        "missed": missed,
        "actual_cost_usd": round(spent_micro / 1e6, 6),
        "confirm_spend_usd": confirm_spend,
    }
    path = OUT_DIR / f"atc-np-pa-backfill-{list_id[:8]}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    # bump list metadata
    try:
        existing = sb_request(
            "GET", "lead_lists", query={"list_id": f"eq.{list_id}", "select": "actual_cost_usd,run_report"}
        ) or []
        if existing:
            prev_cost = float(existing[0].get("actual_cost_usd") or 0)
            prev_report = existing[0].get("run_report") or {}
            if isinstance(prev_report, str):
                prev_report = json.loads(prev_report)
            prev_report["company_desc_backfill"] = report
            sb_request(
                "PATCH",
                "lead_lists",
                {
                    "actual_cost_usd": round(prev_cost + spent_micro / 1e6, 6),
                    "run_report": prev_report,
                },
                query={"list_id": f"eq.{list_id}"},
                prefer="return=minimal",
            )
    except Exception as e:
        print(f"list_meta_update_err: {e}", flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="ATC NP/PA pull-N builder: Icypeas people pull → enrich batch → Supabase"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--scope-only", action="store_true")
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--full", action="store_true")
    g.add_argument("--backfill-list-id", type=str, default=None)
    ap.add_argument("--confirm-spend", type=float, default=None)
    ap.add_argument(
        "--pull",
        type=int,
        default=None,
        help="People to pull from Icypeas (N). Ready emails = subset of N.",
    )
    ap.add_argument(
        "--ready-target",
        type=int,
        default=None,
        help=argparse.SUPPRESS,  # deprecated alias → --pull
    )
    args = ap.parse_args()

    if args.scope_only:
        tam = free_count()
        print(f"TAM_people={tam:,}")
        print("No paid calls. Re-run with --pilot --pull 100 --confirm-spend N")
        return

    if args.backfill_list_id:
        if args.confirm_spend is None:
            raise SystemExit("--confirm-spend USD required for backfill")
        backfill_company_descriptions(args.backfill_list_id, args.confirm_spend)
        return

    if args.confirm_spend is None:
        raise SystemExit("--confirm-spend USD required for pilot/full")
    mode = "pilot" if args.pilot else "full"
    # Pull-N: N = Icypeas people pulled (not ready-email target)
    pull = args.pull or args.ready_target or (100 if args.pilot else 2000)
    if args.ready_target and not args.pull:
        print(
            f"Note: --ready-target is deprecated; treating as --pull {pull} "
            "(people pulled, not ready emails)",
            flush=True,
        )
    run_build(mode, args.confirm_spend, pull)


if __name__ == "__main__":
    main()
