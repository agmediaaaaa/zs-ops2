#!/usr/bin/env python3
"""GWS list builder: Treg → MV/Trykitt → Plusvibe suppress → Supabase + Sheet.

Gates (see .cursor/skills/lead-scrape-gates/SKILL.md):
  --scope-only          free TAM counts only
  --pilot               pull-N pilot (requires --confirm-spend)
  --full                volume run (requires --confirm-spend; after pilot)
  --confirm-spend USD   hard spend cap; required for paid modes

Pull-N: campaign targets are people pulled, then enrich that batch.
Email find excludes Icypeas (use enrich_list --with-icypeas-email to opt in).
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
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/gws-pilot"))
PLUSVIBE_WS = os.environ.get("PLUSVIBE_WORKSPACE_ID", "6a880928da046f3b189bb4e1")
PLUSVIBE_API = "https://api.plusvibe.ai/api/v1"
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TITLES = [
    "Owner",
    "Founder",
    "CEO",
    "President",
    "Managing Partner",
    "Founder & CEO",
    "President & CEO",
    "Owner/Operator",
]

COMPANY_TYPES = {"include": ["PRIVATELY_HELD", "PARTNERSHIP", "SELF_OWNED"]}
FUNDING_EXCLUDE = {
    "exclude": [
        "PRIVATE_EQUITY",
        "SEED",
        "SERIES_A",
        "SERIES_B",
        "SERIES_C",
        "SERIES_D",
        "SERIES_E",
        "SERIES_F",
        "VENTURE_SERIES_UNKNOWN",
        "ANGEL",
        "PRE_SEED",
    ]
}

# keyword-led ICP slices (GWS canvases). headcount: list of (min, max) bands.
CAMPAIGNS: list[dict[str, Any]] = [
    {
        "id": "A1",
        "name": "Construction / AEC / trades",
        "offer": "Buyer + niche consolidator",
        "keywords": [
            "general contractor",
            "commercial construction",
            "specialty trade contractor",
            "electrical contractor",
            "HVAC",
            "plumbing contractor",
            "roofing contractor",
            "concrete contractor",
            "AEC",
        ],
        "bands": [(51, 200)],
        "pilot_ready": 10,
        "full_ready": 1800,
    },
    {
        "id": "A2",
        "name": "Specialty manufacturing",
        "offer": "Buyer (strategic/PE roll-up)",
        "keywords": [
            "machine shop",
            "CNC",
            "tool and die",
            "metal plating",
            "precision manufacturing",
            "contract manufacturing",
            "fabrication",
            "foundry",
        ],
        "bands": [(51, 200)],
        "pilot_ready": 10,
        "full_ready": 1800,
    },
    {
        "id": "A3",
        "name": "Cyber / MSSP / security svcs",
        "offer": "Valuation + buyer-in-space",
        "keywords": [
            "managed security",
            "MSSP",
            "cybersecurity services",
            "SOC",
            "penetration testing",
            "IT security consulting",
        ],
        "bands": [(51, 200), (11, 50)],
        "pilot_ready": 10,
        "full_ready": 1200,
    },
    {
        "id": "A4",
        "name": "Healthcare services",
        "offer": "Soft valuation / what buyers pay",
        "keywords": [
            "outpatient clinic",
            "specialty practice group",
            "behavioral health",
            "dental group",
            "home health",
            "physical therapy clinic",
            "ambulatory care",
        ],
        "bands": [(51, 200)],
        "exclude_keywords": ["hospital", "health system"],
        "pilot_ready": 10,
        "full_ready": 1200,
    },
    {
        "id": "A5",
        "name": "Commercial landscaping / facilities",
        "offer": "Buyer / what a buyer would pay",
        "keywords": [
            "commercial landscaping",
            "grounds maintenance",
            "irrigation",
            "lawn care commercial",
            "exterior property services",
        ],
        "bands": [(51, 200), (201, 500)],
        "pilot_ready": 10,
        "full_ready": 1000,
    },
    {
        "id": "B1",
        "name": "Agencies / creative / production",
        "offer": "Agency soft buyer",
        "keywords": [
            "advertising agency",
            "digital marketing agency",
            "creative agency",
            "branding agency",
            "production studio",
            "content studio",
        ],
        "bands": [(11, 50), (51, 200)],
        "pilot_ready": 10,
        "full_ready": 1000,
    },
    {
        "id": "B2",
        "name": "Specialty / premium finance",
        "offer": "Soft buyer / valuation",
        "keywords": [
            "premium finance",
            "specialty finance",
            "commercial finance company",
            "equipment finance",
            "insurance premium financing",
        ],
        "bands": [(11, 50), (51, 200)],
        "exclude_keywords": ["bank", "credit union"],
        "pilot_ready": 10,
        "full_ready": 800,
    },
    {
        "id": "C",
        "name": "Broad Sub-ICP (C6-style)",
        "offer": "Generic soft buyer / valuation",
        "keywords": [
            "staffing",
            "logistics",
            "wholesale distribution",
            "business services",
            "facilities services",
        ],
        "bands": [(51, 200)],
        "pilot_ready": 10,
        "full_ready": 1200,
    },
]

VALID_MV = {"ok", "catch_all", "valid", "smtp_valid", "catch_all_valid"}
VALID_TRYKITT = {"valid", "catch_all", "catchall", "catch-all"}


def load_treg_token() -> str:
    env = os.environ.get("TREG_TOKEN", "").strip()
    if env:
        return env
    cfg = Path.home() / ".treg" / "config.json"
    if cfg.exists():
        data = json.loads(cfg.read_text())
        tok = data.get("token") or data.get("TREG_TOKEN") or ""
        if tok:
            return tok
    raise SystemExit("Set TREG_TOKEN or run scripts/setup-treg.sh")


TOKEN = ""


def treg(
    method: str,
    path: str,
    body: Any | None = None,
    headers: dict | None = None,
    query: dict | None = None,
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
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait = float(retry_after) if retry_after and str(retry_after).isdigit() else min(8 * (2**i), 90)
                # share_busy / rate_limited: wait longer
                if e.code == 429:
                    wait = max(wait, 20 + 10 * i)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {err[:800]}") from e
        except Exception as e:
            last = e
            time.sleep(min(2**i, 8))
    raise RuntimeError(f"treg failed after retries: {last}")


def balance_usd() -> float:
    import subprocess

    out = subprocess.check_output(["treg", "balance"], text=True)
    for line in out.splitlines():
        if "Balance" in line and "$" in line:
            amt = line.split("$", 1)[1].split()[0].replace(",", "")
            return float(amt)
    raise RuntimeError(f"could not parse balance:\n{out}")


def search_body(camp: dict, band: tuple[int, int], limit: int = 50) -> dict:
    body: dict[str, Any] = {
        "leadJobTitles": {"include": TITLES},
        "companyLocations": {"include": ["United States"]},
        "leadLocations": {"include": ["United States"]},
        "companyEmployeeNumberRange": {"min": band[0], "max": band[1]},
        "companyTypes": COMPANY_TYPES,
        "companyFundingRounds": FUNDING_EXCLUDE,
        "companyKeywords": {"include": camp["keywords"]},
        "companyRequired": True,
        "maxContactsPerCompany": 1,
        "limit": limit,
    }
    if camp.get("exclude_keywords"):
        body["companyKeywords"]["exclude"] = camp["exclude_keywords"]
    return body


def free_count(camp: dict, band: tuple[int, int]) -> int:
    body = search_body(camp, band, limit=1)
    body.pop("limit", None)
    data, meta = treg("POST", "/call/leadsforge.people.search.count", body)
    # free
    total = 0
    if isinstance(data, dict):
        total = int(data.get("totalCount") or data.get("count") or 0)
    return total


def scope_campaigns() -> list[dict]:
    rows = []
    for camp in CAMPAIGNS:
        band_counts = []
        total = 0
        for band in camp["bands"]:
            try:
                c = free_count(camp, band)
            except Exception as e:
                print(f"count_err {camp['id']} {band}: {e}", flush=True)
                c = -1
            band_counts.append({"band": f"{band[0]}-{band[1]}", "count": c})
            if c > 0:
                total += c
            time.sleep(0.05)
        rows.append(
            {
                "campaign_id": camp["id"],
                "name": camp["name"],
                "bands": band_counts,
                "tam_estimate": total,
                "pilot_ready_target": camp["pilot_ready"],
                "full_ready_target": camp["full_ready"],
            }
        )
        print(
            f"SCOPE {camp['id']} tam≈{total} bands={band_counts}",
            flush=True,
        )
    return rows


def estimate_spend(mode: str, scope_rows: list[dict]) -> dict:
    """Catalog-backed quote for paid find-first email ladder."""
    sys.path.insert(0, str(Path(__file__).parent))
    import treg_pricing

    if mode == "pilot":
        ready_target = sum(c["pilot_ready"] for c in CAMPAIGNS)
    else:
        ready_target = sum(c["full_ready"] for c in CAMPAIGNS)
    # assume ~2.5 people searched / ready → pending enrich volume
    searched = int(ready_target * 2.5)
    quote = treg_pricing.quote_run(
        mode=mode,
        people=searched,
        pending_leads=searched,
        with_pattern_mv=False,
    )
    out = quote.to_dict()
    out.update(
        {
            "ready_target": ready_target,
            "est_searched": searched,
            "est_total_usd": quote.expected_usd,
            "recommended_cap_usd": quote.recommended_cap_usd,
            "tam_by_campaign": scope_rows,
            "waterfall": "find-first (Blitz→QE→Trykitt; ContactOut excluded)",
        }
    )
    return out


def plusvibe_key() -> str:
    for name in ("PLUSVIBE_API_KEY", "PLUSVIBE_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    raise SystemExit("Set PLUSVIBE_API_KEY")


def plusvibe_get(path: str) -> Any:
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
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def load_plusvibe_emails(workspace_id: str) -> set[str]:
    """All emails already in Plusvibe workspace (any status)."""
    cache = OUT_DIR / f"plusvibe_suppress_{workspace_id}.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 6 * 3600:
        data = json.loads(cache.read_text())
        emails = set(data.get("emails") or [])
        print(f"plusvibe_suppress_emails={len(emails)} (cached)", flush=True)
        return emails
    emails: set[str] = set()
    page = 1
    page_size = 100
    while True:
        path = (
            f"/lead/workspace-leads?workspace_id={workspace_id}"
            f"&limit={page_size}&page={page}"
        )
        batch = plusvibe_get(path)
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            em = (row.get("email") or "").strip().lower()
            if em:
                emails.add(em)
            li = (row.get("linkedin_person_url") or "").strip().lower()
            if li:
                emails.add(f"li:{normalize_linkedin(li)}")
        if len(batch) < page_size:
            break
        page += 1
        if page % 20 == 0:
            print(f"  plusvibe suppress loaded={len(emails)} page={page}", flush=True)
        time.sleep(0.05)
    cache.write_text(json.dumps({"emails": sorted(emails), "workspace_id": workspace_id}))
    print(f"plusvibe_suppress_emails={len(emails)}", flush=True)
    return emails


def normalize_linkedin(url: str) -> str:
    u = url.strip().lower().rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    if "/in/" in u:
        return u.split("?")[0]
    return u


def domain_of(website: str, company: dict | None = None) -> str:
    co = company or {}
    d = (co.get("domain") or website or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def supabase_key() -> str:
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    raise SystemExit("Set SUPABASE_SERVICE_ROLE_KEY")


def sb_request(method: str, path: str, body: Any | None = None, params: dict | None = None) -> Any:
    url = f"{SUPABASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "apikey": supabase_key(),
            "Authorization": f"Bearer {supabase_key()}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"Supabase {method} {path} -> {e.code}: {err[:500]}") from e


def lookup_known(domain: str, linkedin: str, email: str) -> bool:
    """True if identity already in Lead Database / email_cache / pipeline_leads."""
    clauses = []
    if email:
        q = urllib.parse.quote(f"email.eq.{email}")
        # PostgREST or filters
    # Use rpc-less or filters via REST
    filters = []
    if email:
        try:
            rows = sb_request(
                "GET",
                "/rest/v1/Lead%20Database",
                params={"Email": f"eq.{email}", "select": "id", "limit": "1"},
            )
            if rows:
                return True
        except Exception:
            pass
        try:
            rows = sb_request(
                "GET",
                "/rest/v1/email_cache",
                params={"email": f"eq.{email}", "select": "id", "limit": "1"},
            )
            if rows:
                return True
        except Exception:
            pass
    if linkedin:
        li = linkedin if linkedin.startswith("http") else f"https://{linkedin}"
        try:
            rows = sb_request(
                "GET",
                "/rest/v1/Lead%20Database",
                params={"Linkedin": f"ilike.*{normalize_linkedin(linkedin).split('/')[-1]}*", "select": "id", "limit": "1"},
            )
            if rows:
                return True
        except Exception:
            pass
    # Domain-only match is too broad for ready-list building; skip paid enrich
    # only when we already have this person (email/linkedin), not whole company.
    return False


def verify_mv(email: str) -> tuple[str, int]:
    data, meta = treg(
        "GET",
        "/call/millionverifier.people.email.verify",
        query={"email": email},
    )
    result = ""
    if isinstance(data, dict):
        result = (data.get("result") or data.get("quality") or "").lower()
    return result, int(meta.get("cost_micro") or 0)


def find_email_trykitt(first: str, last: str, domain: str, person_id: str) -> tuple[str, int, str]:
    full = f"{first} {last}".strip()
    headers = {
        "X-Treg-Route-Exclude": "aiark,icypeas",
        "X-Treg-Route-Max-Cost": "0.006",
        "X-Treg-Route-Waterfall": "0",
        "Idempotency-Key": f"gws-email-{person_id}-{domain}",
    }
    # Routed cheap find (quickenrich → trykitt …); exclude aiark
    data, meta = treg(
        "POST",
        "/call/treg.people.email.find",
        {
            "domain": domain,
            "first_name": first,
            "last_name": last,
            "full_name": full,
        },
        headers=headers,
    )
    email = ""
    served = (meta or {}).get("served_by") or ""
    if isinstance(data, dict):
        served = served or ((data.get("_treg") or {}).get("served_by") or "")
        out = data.get("output") or data
        if isinstance(out, dict):
            email = out.get("email") or out.get("work_email") or ""
            if not email and isinstance(out.get("emails"), list) and out["emails"]:
                e0 = out["emails"][0]
                email = e0 if isinstance(e0, str) else (e0.get("email") or "")
        if not email:
            raw = data.get("raw")
            if isinstance(raw, dict):
                rd = raw.get("data") if isinstance(raw.get("data"), dict) else raw
                email = (rd or {}).get("email") or ""
        # Direct trykitt-shaped miss
        if (email or "").lower() in ("", "no-results-found", "none", "null"):
            email = ""
    # Fallback: trykitt direct with required camelCase fields
    if not email:
        data2, meta2 = treg(
            "POST",
            "/call/trykitt.people.email.find",
            {"domain": domain, "fullName": full, "realtime": True},
            headers={"Idempotency-Key": f"gws-trykitt-{person_id}-{domain}"},
        )
        meta["cost_micro"] = int(meta.get("cost_micro") or 0) + int(meta2.get("cost_micro") or 0)
        served = meta2.get("served_by") or served or "trykitt.people.email.find"
        if isinstance(data2, dict):
            email = data2.get("email") or ""
            if (email or "").lower() in ("", "no-results-found", "none", "null"):
                email = ""
    return (email or "").strip(), int(meta.get("cost_micro") or 0), served or "treg.people.email.find"


def search_page(camp: dict, band: tuple[int, int], cursor: str | None, limit: int = 50):
    body = search_body(camp, band, limit=limit)
    path = "/call/leadsforge.people.search"
    if cursor:
        path += f"?cursor={urllib.parse.quote(cursor)}"
    return treg("POST", path, body)


def upsert_pipeline(rows: list[dict]) -> None:
    if not rows:
        return
    # chunk inserts (bulk — not 1 call/lead)
    for i in range(0, len(rows), 100):
        chunk = rows[i : i + 100]
        sb_request("POST", "/rest/v1/pipeline_leads", chunk)


def _batch_lookup_emails_lead_db(emails: list[str]) -> set[str]:
    """Return set of emails already in Lead Database."""
    have: set[str] = set()
    if not emails:
        return have
    for i in range(0, len(emails), 80):
        batch = emails[i : i + 80]
        try:
            rows = sb_request(
                "GET",
                "/rest/v1/Lead%20Database",
                params={
                    "select": "Email",
                    "or": f'({",".join(f"Email.eq.{em}" for em in batch)})',
                    "limit": str(len(batch) * 2),
                },
            )
            for r in rows or []:
                em = (r.get("Email") or "").strip().lower()
                if em:
                    have.add(em)
        except Exception as e:
            print(f"lead_db_batch_lookup_err: {e}", flush=True)
    return have


def upsert_lead_db_batch(rows: list[dict]) -> None:
    """Bulk insert new Lead Database rows (skip emails already present)."""
    payloads = []
    emails = []
    for row in rows:
        email = (row.get("email") or "").strip()
        if not email:
            continue
        emails.append(email.lower())
        payloads.append(
            {
                "First Name": row.get("first_name"),
                "Last Name": row.get("last_name"),
                "Email": email,
                "Linkedin": row.get("linkedin"),
                "Company Name": row.get("company_name"),
                "Website": row.get("website") or row.get("company_domain"),
            }
        )
    if not payloads:
        return
    existing = _batch_lookup_emails_lead_db(emails)
    to_insert = [
        p
        for p in payloads
        if (p.get("Email") or "").strip().lower() not in existing
    ]
    for i in range(0, len(to_insert), 100):
        chunk = to_insert[i : i + 100]
        try:
            sb_request("POST", "/rest/v1/Lead%20Database", chunk)
        except Exception as e:
            print(f"lead_db_batch_insert_err: {e}", flush=True)
    print(
        f"  Lead Database bulk: {len(to_insert)} inserted, "
        f"{len(payloads) - len(to_insert)} already present",
        flush=True,
    )


def upsert_lead_db(row: dict) -> None:
    """Legacy single-row helper; prefer upsert_lead_db_batch."""
    upsert_lead_db_batch([row])


def upsert_email_cache_batch(rows: list[dict]) -> None:
    """Bulk POST email_cache; conflicts ignored via merge-duplicates when available."""
    now = datetime.now(timezone.utc).isoformat()
    payloads = []
    seen: set[str] = set()
    for row in rows:
        email = (row.get("email") or "").strip()
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        payloads.append(
            {
                "email": email,
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "linkedin": row.get("linkedin"),
                "company_name": row.get("company_name"),
                "company_domain": row.get("company_domain"),
                "source": row.get("email_source") or "gws_list_builder",
                "mv_status": row.get("mv_status"),
                "verified_at": now,
            }
        )
    for i in range(0, len(payloads), 100):
        chunk = payloads[i : i + 100]
        try:
            # Prefer upsert semantics if unique(email) exists
            url = f"{SUPABASE_URL}/rest/v1/email_cache"
            data = json.dumps(chunk).encode()
            req = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={
                    "apikey": supabase_key(),
                    "Authorization": f"Bearer {supabase_key()}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp.read()
        except Exception as e:
            # Fall back to plain insert (skip dupes individually is fine for cache)
            print(f"email_cache_batch_err: {e}", flush=True)
            for payload in chunk:
                try:
                    sb_request("POST", "/rest/v1/email_cache", payload)
                except Exception:
                    pass


def upsert_email_cache(row: dict) -> None:
    """Legacy single-row helper; prefer upsert_email_cache_batch."""
    upsert_email_cache_batch([row])


def write_sheet_csv(path: Path, rows: list[dict]) -> None:
    cols = [
        "Campaign",
        "Offer",
        "First Name",
        "Last Name",
        "Title",
        "Email",
        "Person Linkedin Url",
        "Company Name",
        "Website",
        "Employees",
        "MV Status",
        "Plusvibe Ready",
        "Already In Lead DB",
        "Plusvibe Excluded",
        "Batch ID",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "Campaign": r.get("campaign_id"),
                    "Offer": r.get("offer"),
                    "First Name": r.get("first_name"),
                    "Last Name": r.get("last_name"),
                    "Title": r.get("title"),
                    "Email": r.get("email"),
                    "Person Linkedin Url": r.get("linkedin"),
                    "Company Name": r.get("company_name"),
                    "Website": r.get("website") or r.get("company_domain"),
                    "Employees": r.get("employees"),
                    "MV Status": r.get("mv_status"),
                    "Plusvibe Ready": r.get("plusvibe_ready"),
                    "Already In Lead DB": r.get("already_in_lead_db"),
                    "Plusvibe Excluded": r.get("plusvibe_excluded"),
                    "Batch ID": r.get("batch_id"),
                }
            )


def run_build(mode: str, confirm_spend: float, campaign_filter: list[str] | None) -> dict:
    batch_id = f"gws-{mode}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start_bal = balance_usd()
    spent_micro = 0
    cap_micro = int(confirm_spend * 1_000_000)

    print("Loading Plusvibe GWS suppress set...", flush=True)
    pv_emails = load_plusvibe_emails(PLUSVIBE_WS)

    camps = [c for c in CAMPAIGNS if not campaign_filter or c["id"] in campaign_filter]
    all_rows: list[dict] = []
    stats: dict[str, Any] = {
        "batch_id": batch_id,
        "mode": mode,
        "confirm_spend_usd": confirm_spend,
        "start_balance_usd": start_bal,
        "campaigns": {},
        "db_order": ["leadsforge.people.search"],
        "email_order": [
            "extract_or_trykitt.people.email.find",
            "millionverifier.people.email.verify",
        ],
    }

    seen_domains_global: set[str] = set()
    seen_people: set[str] = set()

    for camp in camps:
        target = camp["pilot_ready"] if mode == "pilot" else camp["full_ready"]
        cstat = {
            "searched": 0,
            "skipped_known": 0,
            "plusvibe_excluded": 0,
            "ready": 0,
            "found_total": 0,
            "spent_usd": 0.0,
        }
        print(f"\n=== {camp['id']} {camp['name']} target_ready={target} ===", flush=True)
        for band in camp["bands"]:
            if cstat["ready"] >= target:
                break
            cursor = None
            pages = 0
            while cstat["ready"] >= 0 and cstat["ready"] < target and pages < 40:
                if spent_micro >= cap_micro:
                    print("STOP: spend cap reached", flush=True)
                    break
                try:
                    data, meta = search_page(camp, band, cursor, limit=50)
                except Exception as e:
                    print(f"search_err {camp['id']} {band}: {e}", flush=True)
                    break
                spent_micro += int(meta.get("cost_micro") or 0)
                leads = (data or {}).get("leads") or []
                if not leads:
                    break
                pages += 1
                for lead in leads:
                    if cstat["ready"] >= target:
                        break
                    if spent_micro >= cap_micro:
                        break
                    pid = lead.get("id") or ""
                    if not pid or pid in seen_people:
                        continue
                    seen_people.add(pid)
                    co = lead.get("company") or {}
                    domain = domain_of(co.get("website") or "", co)
                    if domain and domain in seen_domains_global:
                        continue
                    if domain:
                        seen_domains_global.add(domain)

                    first = (lead.get("firstName") or "").strip()
                    last = (lead.get("lastName") or "").strip()
                    title = lead.get("jobTitle") or ""
                    linkedin = (
                        lead.get("linkedinUrl")
                        or lead.get("linkedin")
                        or ""
                    ).strip()
                    company_name = (co.get("name") or domain or "").strip()
                    website = (co.get("website") or domain or "").strip()
                    emp = co.get("employeeCount")
                    cstat["searched"] += 1

                    already = lookup_known(domain, linkedin, "")
                    email = ""
                    email_source = ""
                    mv_status = ""
                    cost_here = 0

                    if already:
                        cstat["skipped_known"] += 1
                        # Still record; skip paid enrich
                    else:
                        # Email ladder: find then MV verify
                        if first and last and domain:
                            try:
                                email, cost, served = find_email_trykitt(
                                    first, last, domain, pid
                                )
                                cost_here += cost
                                spent_micro += cost
                                email_source = served or "trykitt.people.email.find"
                            except Exception as e:
                                print(f"find_err {pid}: {e}", flush=True)
                        if email and spent_micro < cap_micro:
                            try:
                                mv_status, vcost = verify_mv(email)
                                cost_here += vcost
                                spent_micro += vcost
                            except Exception as e:
                                print(f"mv_err {email}: {e}", flush=True)
                                mv_status = "error"

                    pv_ex = False
                    pv_reason = ""
                    if email and email.lower() in pv_emails:
                        pv_ex = True
                        pv_reason = "in_plusvibe_workspace"
                        cstat["plusvibe_excluded"] += 1
                    if linkedin and f"li:{normalize_linkedin(linkedin)}" in pv_emails:
                        pv_ex = True
                        pv_reason = pv_reason or "linkedin_in_plusvibe"
                        cstat["plusvibe_excluded"] += 1

                    ready = bool(
                        email
                        and mv_status in VALID_MV
                        and not pv_ex
                    )
                    if ready:
                        cstat["ready"] += 1

                    row = {
                        "batch_id": batch_id,
                        "source_run": f"gws_list_builder:{mode}",
                        "client": "GWS",
                        "campaign_id": camp["id"],
                        "offer": camp["offer"],
                        "first_name": first,
                        "last_name": last,
                        "title": title,
                        "email": email or None,
                        "linkedin": linkedin or None,
                        "company_name": company_name,
                        "website": website or None,
                        "company_domain": domain or None,
                        "employees": str(emp) if emp is not None else None,
                        "country": "United States",
                        "mv_status": mv_status or None,
                        "email_source": email_source or None,
                        "already_in_lead_db": already,
                        "plusvibe_excluded": pv_ex,
                        "plusvibe_exclude_reason": pv_reason or None,
                        "plusvibe_ready": ready,
                        "handoff_status": "staged",
                        "raw": {
                            "person_id": pid,
                            "band": f"{band[0]}-{band[1]}",
                            "cost_micro": cost_here,
                        },
                    }
                    all_rows.append(row)
                    cstat["found_total"] += 1
                    cstat["spent_usd"] = round(
                        cstat["spent_usd"] + cost_here / 1_000_000, 6
                    )

                    if cstat["found_total"] % 10 == 0:
                        print(
                            f"  {camp['id']} searched={cstat['searched']} ready={cstat['ready']} "
                            f"known={cstat['skipped_known']} pv_ex={cstat['plusvibe_excluded']} "
                            f"spent=${spent_micro/1_000_000:.4f}",
                            flush=True,
                        )

                cursor = (data or {}).get("cursor")
                if not cursor:
                    break
                time.sleep(0.05)

            if spent_micro >= cap_micro:
                break

        # Bulk write campaign chunk (Lead DB + email_cache + pipeline) — not 4–5 calls/lead
        camp_rows = [r for r in all_rows if r["campaign_id"] == camp["id"]]
        email_rows = [r for r in camp_rows if r.get("email")]
        if email_rows:
            upsert_lead_db_batch(email_rows)
            upsert_email_cache_batch(email_rows)
        upsert_pipeline(
            [
                {k: v for k, v in r.items() if k != "raw"}
                | {"raw": r.get("raw")}
                for r in camp_rows
            ]
        )
        cov = (
            round(cstat["ready"] / cstat["searched"], 4) if cstat["searched"] else 0
        )
        cstat["coverage"] = cov
        stats["campaigns"][camp["id"]] = cstat
        print(
            f"DONE {camp['id']} ready={cstat['ready']}/{target} coverage={cov}",
            flush=True,
        )

    end_bal = balance_usd()
    stats["end_balance_usd"] = end_bal
    stats["spent_usd"] = round(spent_micro / 1_000_000, 6)
    stats["spent_from_balance_usd"] = round(start_bal - end_bal, 6)
    stats["ready_total"] = sum(c["ready"] for c in stats["campaigns"].values())
    stats["searched_total"] = sum(c["searched"] for c in stats["campaigns"].values())
    stats["coverage_overall"] = (
        round(stats["ready_total"] / stats["searched_total"], 4)
        if stats["searched_total"]
        else 0
    )

    # artifacts
    jsonl = OUT_DIR / f"{batch_id}.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, default=str) + "\n")
    csv_path = OUT_DIR / f"{batch_id}_apollo.csv"
    write_sheet_csv(csv_path, all_rows)
    ready_csv = OUT_DIR / f"{batch_id}_ready.csv"
    write_sheet_csv(ready_csv, [r for r in all_rows if r.get("plusvibe_ready")])
    summary_path = OUT_DIR / f"{batch_id}_summary.json"
    stats["artifacts"] = {
        "jsonl": str(jsonl),
        "all_csv": str(csv_path),
        "ready_csv": str(ready_csv),
    }
    summary_path.write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2), flush=True)
    return stats


def main() -> None:
    global TOKEN
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scope-only", action="store_true")
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--full", action="store_true")
    p.add_argument(
        "--confirm-spend",
        type=float,
        default=None,
        help="Hard USD spend cap; required for --pilot/--full",
    )
    p.add_argument(
        "--campaigns",
        default="",
        help="Comma-separated campaign ids (default all)",
    )
    p.add_argument(
        "--skip-scope",
        action="store_true",
        help="Reuse artifacts/gws-pilot/scope_latest.json (avoid rate limits)",
    )
    args = p.parse_args()
    TOKEN = load_treg_token()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"treg_balance=${balance_usd():.4f}", flush=True)
    scope_path = OUT_DIR / "scope_latest.json"
    if args.skip_scope and scope_path.exists() and not args.scope_only:
        scope_rows = json.loads(scope_path.read_text())
        print(f"reusing scope from {scope_path}", flush=True)
    else:
        scope_rows = scope_campaigns()
        scope_path.write_text(json.dumps(scope_rows, indent=2))

    if args.scope_only:
        est = estimate_spend("pilot", scope_rows)
        est_full = estimate_spend("full", scope_rows)
        report = {
            "scope": scope_rows,
            "pilot_spend_estimate": est,
            "full_spend_estimate": est_full,
            "note": "Confirm a numeric --confirm-spend before --pilot or --full",
        }
        (OUT_DIR / "scope_report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        print(
            "\nNEXT: approve spend then run:\n"
            f"  python scripts/gws_list_builder.py --pilot --confirm-spend {est['recommended_cap_usd']}"
        )
        return

    mode = "pilot" if args.pilot else "full"
    if args.confirm_spend is None:
        est = estimate_spend(mode, scope_rows)
        print(json.dumps({"error": "confirm_spend_required", "estimate": est}, indent=2))
        raise SystemExit(
            f"Refusing paid run without --confirm-spend. Recommended cap: ${est['recommended_cap_usd']}"
        )

    camp_filter = [x.strip() for x in args.campaigns.split(",") if x.strip()] or None
    run_build(mode, args.confirm_spend, camp_filter)


if __name__ == "__main__":
    main()
