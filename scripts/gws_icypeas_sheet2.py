#!/usr/bin/env python3
"""GWS Icypeas scrape → budget email ladder → Sheet2 CSV, hard spend cap.

Default find-first waterfall (skip pattern+ContactOut):
  Supabase cache → Blitz → QuickEnrich(+MV) → Trykitt(+MV).
Optional --with-pattern-mv for pattern+MV before find.
ContactOut verify is intentionally excluded (free but 429-bound).
No Prospeo; no company enrich stack.
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
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://treg.to"
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/gws-icypeas"))
PLUSVIBE_WS = os.environ.get("PLUSVIBE_WORKSPACE_ID", "6a880928da046f3b189bb4e1")
PLUSVIBE_API = "https://api.plusvibe.ai/api/v1"
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
)
SHEET_ID = os.environ.get(
    "GWS_SHEET_ID", "1tqLmo4vm8CIyQo3x-kJY2hiUvYxTvBbIQhcFPEplH_I"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TREG_TIMEOUT = 25
TREG_RETRIES = 3
DEFAULT_WORKERS = 32

TITLE_INCLUDE = [
    "Owner",
    "Founder",
    "CEO",
    "President",
    "Managing Partner",
    "Founder & CEO",
    "President & CEO",
    "Owner/Operator",
]
TITLE_DENY_RE = re.compile(
    r"\b(vp|vice\s*president|director|manager|coordinator|specialist|"
    r"assistant|intern|student|analyst|engineer|associate)\b",
    re.I,
)
TITLE_ALLOW_RE = re.compile(
    r"\b(owner|founder|ceo|chief\s*executive|president|managing\s*partner|"
    r"co-?founder|owner/?operator)\b",
    re.I,
)
TITLE_PRIORITY = [
    ("owner", 0),
    ("founder", 1),
    ("ceo", 2),
    ("chief executive", 2),
    ("managing partner", 3),
    ("president", 4),
]

# Soft goals ≈ 1.8k proportional of 5k map (fill until spend cap).
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
        "soft_ready": 324,
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
        "soft_ready": 324,
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
        "soft_ready": 216,
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
        "exclude_keywords": ["hospital", "health system"],
        "bands": [(51, 200)],
        "soft_ready": 216,
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
        "soft_ready": 180,
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
        "soft_ready": 180,
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
        "exclude_keywords": ["bank", "credit union"],
        "bands": [(11, 50), (51, 200)],
        "soft_ready": 144,
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
        "soft_ready": 216,
    },
]

VALID_MV = {"ok", "valid", "smtp_valid"}
CATCH_ALL_MV = {"catch_all", "catch_all_valid"}
# ContactOut free verifier statuses
VALID_CO = {"valid", "ok", "deliverable", "smtp_valid", "good"}
CATCH_ALL_CO = {"accept_all", "catch_all", "catchall", "accept-all"}
TOKEN = ""
CHEAP_MODE = False  # deprecated: mapped to find-first (Blitz-only) without ContactOut
WITH_PATTERN_MV = False  # optional cost mode: pattern + MV before find waterfall

# Thread-safe spend accounting
_spend_lock = threading.Lock()
_spent_micro = 0
_cap_micro = 0
_stop_spend = False


def load_treg_token() -> str:
    for name in ("TREG_TOKEN", "treg"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    cfg = Path.home() / ".treg" / "config.json"
    if cfg.exists():
        data = json.loads(cfg.read_text())
        tok = data.get("token") or data.get("TREG_TOKEN") or ""
        if tok:
            return tok
    raise SystemExit("Set TREG_TOKEN")


def treg(
    method: str,
    path: str,
    body: Any | None = None,
    headers: dict | None = None,
    query: dict | None = None,
    retries: int = TREG_RETRIES,
    timeout: float = TREG_TIMEOUT,
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
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            if e.code in (409, 418, 429, 503) or (500 <= e.code < 600):
                wait = min(2 * (2**i), 20)
                if e.code in (418, 429):
                    wait = max(wait, 4 + 3 * i)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {err[:800]}") from e
        except Exception as e:
            last = e
            time.sleep(min(1.5**i, 4))
    raise RuntimeError(f"treg failed after retries: {last}")


def balance_usd() -> float:
    data, _ = treg("GET", "/orgs/33605/balance")
    return float((data or {}).get("balance_usd") or 0)


def spent_usd() -> float:
    with _spend_lock:
        return _spent_micro / 1_000_000


def under_cap(need_micro: int = 0) -> bool:
    global _stop_spend
    with _spend_lock:
        if _stop_spend:
            return False
        ok = _spent_micro + need_micro < _cap_micro
        if not ok:
            _stop_spend = True
        return ok


def charge(cost_micro: int) -> None:
    global _spent_micro, _stop_spend
    if cost_micro <= 0:
        return
    with _spend_lock:
        _spent_micro += cost_micro
        if _spent_micro >= _cap_micro:
            _stop_spend = True


def normalize_linkedin(url: str) -> str:
    u = url.strip().lower().rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    if "/in/" in u:
        return u.split("?")[0]
    return u


def domain_of(website: str) -> str:
    d = (website or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def title_ok(title: str, company_name: str) -> bool:
    t = (title or "").strip()
    if not t or not TITLE_ALLOW_RE.search(t):
        return False
    if TITLE_DENY_RE.search(t) and not re.search(
        r"\b(owner|founder|ceo|chief\s*executive|managing\s*partner)\b", t, re.I
    ):
        return False
    cn = (company_name or "").lower()
    if re.search(r"\bco-?op\b|\bcooperative\b", cn) and re.search(
        r"^\s*president\s*$", t, re.I
    ):
        return False
    if re.fullmatch(r"president", t, re.I) and re.search(
        r"\b(association|chapter|foundation)\b", cn
    ):
        return False
    return True


def title_rank(title: str) -> int:
    t = (title or "").lower()
    best = 99
    for needle, rank in TITLE_PRIORITY:
        if needle in t:
            best = min(best, rank)
    return best


def pattern_emails(first: str, last: str, domain: str) -> list[str]:
    f = re.sub(r"[^a-z]", "", (first or "").lower())
    l = re.sub(r"[^a-z]", "", (last or "").lower())
    if not f or not l or not domain:
        return []
    return [
        f"{f}.{l}@{domain}",
        f"{f}@{domain}",
        f"{f[0]}{l}@{domain}",
        f"{f}{l[0]}@{domain}",
        f"{f}_{l}@{domain}",
    ]


def icypeas_query(camp: dict, band: tuple[int, int]) -> dict:
    q: dict[str, Any] = {
        "currentJobTitle": {"include": TITLE_INCLUDE},
        "location": {"include": ["United States", "US"]},
        "keyword": {"include": camp["keywords"]},
        "currentCompany.headcount": {">=": band[0], "<=": band[1]},
    }
    if camp.get("exclude_keywords"):
        q["keyword"]["exclude"] = camp["exclude_keywords"]
    return q


def free_count(camp: dict, band: tuple[int, int]) -> int:
    data, _ = treg(
        "POST",
        "/call/icypeas.people.search.count",
        {"query": icypeas_query(camp, band)},
    )
    if isinstance(data, dict):
        return int(data.get("total") or data.get("count") or 0)
    return 0


def search_page(camp: dict, band: tuple[int, int], token: str | None, size: int = 100):
    body: dict[str, Any] = {
        "query": icypeas_query(camp, band),
        "pagination": {"size": size},
    }
    if token:
        body["pagination"]["token"] = token
    return treg("POST", "/call/icypeas.people.search", body)


def plusvibe_key() -> str:
    for name in ("PLUSVIBE_API_KEY", "PLUSVIBE_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


def load_plusvibe_suppress(workspace_id: str) -> set[str]:
    key = plusvibe_key()
    if not key:
        print("plusvibe_suppress skipped (no key)", flush=True)
        return set()
    cache = OUT_DIR / f"plusvibe_suppress_{workspace_id}.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 6 * 3600:
        data = json.loads(cache.read_text())
        emails = set(data.get("emails") or [])
        print(f"plusvibe_suppress={len(emails)} (cached)", flush=True)
        return emails
    emails: set[str] = set()
    page = 1
    while True:
        path = (
            f"/lead/workspace-leads?workspace_id={workspace_id}"
            f"&limit=100&page={page}"
        )
        req = urllib.request.Request(
            f"{PLUSVIBE_API}{path}",
            headers={
                "x-api-key": key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            batch = json.loads(resp.read().decode() or "[]")
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            em = (row.get("email") or "").strip().lower()
            if em:
                emails.add(em)
            li = (row.get("linkedin_person_url") or "").strip().lower()
            if li:
                emails.add(f"li:{normalize_linkedin(li)}")
        if len(batch) < 100:
            break
        page += 1
        if page % 25 == 0:
            print(f"  plusvibe loaded={len(emails)} page={page}", flush=True)
        time.sleep(0.03)
    cache.write_text(json.dumps({"emails": sorted(emails)}))
    print(f"plusvibe_suppress={len(emails)}", flush=True)
    return emails


def load_file_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip().lower() for ln in path.read_text().splitlines() if ln.strip()}


def supabase_key() -> str:
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


SB_CACHE_DAYS = 30
_sb_by_li: dict[str, dict] = {}
_sb_by_email: dict[str, dict] = {}
_sb_lock = threading.Lock()


def _sb_headers(prefer: str = "return=representation") -> dict[str, str]:
    key = supabase_key()
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not set")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": prefer,
    }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _sb_index_row(row: dict) -> None:
    li = normalize_linkedin(row.get("linkedin") or "")
    if li:
        _sb_by_li[li] = row
    em = (row.get("email") or "").strip().lower()
    if em and em not in ("n/a", "none", "null", ""):
        prev = _sb_by_email.get(em)
        if not prev:
            _sb_by_email[em] = row
            return
        # keep newest updated_at
        a = _parse_ts(prev.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)
        b = _parse_ts(row.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)
        if b >= a:
            _sb_by_email[em] = row


def load_supabase_lead_index() -> int:
    """Load pipeline_leads into memory for LinkedIn/email reuse checks."""
    global _sb_by_li, _sb_by_email
    _sb_by_li, _sb_by_email = {}, {}
    if not supabase_key():
        print("supabase_index skipped (no key)", flush=True)
        return 0
    base = SUPABASE_URL.rstrip("/") + "/rest/v1/pipeline_leads"
    offset = 0
    page = 1000
    total = 0
    while True:
        url = (
            f"{base}?select=id,email,linkedin,updated_at,created_at,mv_status,"
            f"email_source,company_domain,employees,company_size,company_description,"
            f"location,first_name,last_name"
            f"&order=id.asc&limit={page}&offset={offset}"
        )
        req = urllib.request.Request(url, headers=_sb_headers("count=exact"))
        with urllib.request.urlopen(req, timeout=60) as resp:
            batch = json.loads(resp.read().decode() or "[]")
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            _sb_index_row(row)
            total += 1
        if len(batch) < page:
            break
        offset += page
    print(
        f"supabase_index rows={total} emails={len(_sb_by_email)} li={len(_sb_by_li)}",
        flush=True,
    )
    return total


def lookup_supabase_lead(lead: dict) -> dict | None:
    """Find existing pipeline_leads row by LinkedIn, then by pattern emails."""
    with _sb_lock:
        li = normalize_linkedin(lead.get("linkedin") or "")
        if li and li in _sb_by_li:
            return _sb_by_li[li]
        for guess in pattern_emails(
            lead.get("first_name") or "",
            lead.get("last_name") or "",
            lead.get("domain") or "",
        )[:3]:
            hit = _sb_by_email.get(guess.lower())
            if hit:
                return hit
    return None


def try_supabase_email_reuse(
    lead: dict, excl_emails: set[str]
) -> dict | None:
    """Reuse Supabase email if fresh; if >30d, MV-verify then reuse on ok."""
    existing = lookup_supabase_lead(lead)
    if not existing:
        return None
    email = (existing.get("email") or "").strip()
    if not email or email.lower() in excl_emails or email.lower() in (
        "n/a",
        "none",
        "null",
    ):
        return None
    updated = _parse_ts(existing.get("updated_at")) or _parse_ts(
        existing.get("created_at")
    )
    now = datetime.now(timezone.utc)
    age_days = (
        (now - updated).total_seconds() / 86400.0 if updated else 9999.0
    )
    cost_here = 0

    if age_days <= SB_CACHE_DAYS:
        status = (existing.get("mv_status") or "cached").lower()
        return {
            "email": email,
            "email_status": status or "cached",
            "email_source": "supabase_cache",
            "spent_note": "0",
            "plusvibe_ready": True,
            "stopped": False,
            "supabase_id": existing.get("id"),
            "supabase_age_days": round(age_days, 2),
        }

    # Stale: re-verify with MV before trusting
    if not under_cap(2000):
        return {
            "email": None,
            "email_status": None,
            "email_source": None,
            "spent_note": "0",
            "plusvibe_ready": False,
            "stopped": True,
        }
    try:
        mv, mcost = verify_mv(email)
        cost_here += mcost
    except Exception as e:
        print(f"sb_mv_err {email}: {e}", flush=True)
        return None
    if mv in VALID_MV:
        return {
            "email": email,
            "email_status": mv,
            "email_source": "supabase+mv",
            "spent_note": f"{cost_here/1e6:.4f}",
            "plusvibe_ready": True,
            "stopped": False,
            "supabase_id": existing.get("id"),
            "supabase_age_days": round(age_days, 2),
        }
    return None


def upsert_pipeline_lead(row: dict, source_run: str = "gws_icypeas_sheet2") -> dict | None:
    """Insert or update pipeline_leads for every found email (thread-safe)."""
    if not supabase_key():
        return None
    email = (row.get("email") or "").strip()
    if not email or email.lower() in ("n/a", "none", "null"):
        return None
    li = (row.get("linkedin") or row.get("linkedin_url") or "").strip() or None
    domain = row.get("domain") or domain_of(row.get("website") or "")
    size = row.get("employee_count")
    size_s = "" if size is None else str(size)
    now_iso = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "batch_id": row.get("batch_id") or "unknown",
        "source_run": source_run,
        "client": "GWS",
        "campaign_id": row.get("campaign_id") or "C",
        "offer": row.get("offer"),
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "title": row.get("title"),
        "email": email,
        "linkedin": li,
        "company_name": row.get("company_name"),
        "website": row.get("website") or domain,
        "company_domain": domain or None,
        "employees": size_s or None,
        "company_size": size_s or None,
        "company_description": row.get("company_description") or None,
        "company_industry": row.get("industry") or None,
        "location": row.get("location") or None,
        "company_address": row.get("location") or None,
        "mv_status": row.get("email_status"),
        "email_source": row.get("email_source"),
        "plusvibe_ready": bool(row.get("plusvibe_ready")),
        "handoff_status": "staged",
        "updated_at": now_iso,
        "raw": {
            "spent_note": row.get("spent_note"),
            "company_linkedin": row.get("company_linkedin"),
            "supabase_age_days": row.get("supabase_age_days"),
        },
    }
    # Drop None values except booleans
    body = {k: v for k, v in payload.items() if v is not None or isinstance(v, bool)}

    existing = None
    with _sb_lock:
        existing = _sb_by_email.get(email.lower())
        if not existing and li:
            existing = _sb_by_li.get(normalize_linkedin(li))

    try:
        if existing and existing.get("id"):
            url = (
                SUPABASE_URL.rstrip("/")
                + f"/rest/v1/pipeline_leads?id=eq.{existing['id']}"
            )
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                headers=_sb_headers(),
                method="PATCH",
            )
        else:
            url = SUPABASE_URL.rstrip("/") + "/rest/v1/pipeline_leads"
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                headers=_sb_headers(),
                method="POST",
            )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode() or "[]")
        saved = data[0] if isinstance(data, list) and data else (
            data if isinstance(data, dict) else None
        )
        if saved:
            with _sb_lock:
                _sb_index_row(saved)
        return saved
    except Exception as e:
        print(f"supabase_upsert_err {email}: {e}", flush=True)
        return None


def verify_mv(email: str) -> tuple[str, int]:
    if not under_cap(2000):
        return "stopped", 0
    data, meta = treg(
        "GET",
        "/call/millionverifier.people.email.verify",
        query={"email": email},
    )
    cost = int(meta.get("cost_micro") or 0)
    charge(cost)
    result = ""
    if isinstance(data, dict):
        result = (data.get("result") or data.get("quality") or "").lower()
    return result, cost


def verify_contactout(email: str) -> tuple[str, int]:
    """Free ContactOut verify. Returns normalized status."""
    data, meta = treg(
        "GET",
        "/call/contactout.people.email.verify",
        query={"email": email},
        timeout=20,
        retries=2,
    )
    cost = int(meta.get("cost_micro") or 0)
    charge(cost)
    status = ""
    if isinstance(data, dict):
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        status = str(
            (inner or {}).get("status")
            or (inner or {}).get("result")
            or data.get("status")
            or ""
        ).lower()
    return status, cost


def find_blitz(linkedin: str) -> tuple[str, int]:
    """Cheapest paid find (~$0.0005/hit). Requires LinkedIn URL."""
    if not linkedin or not under_cap(1000):
        return "", 0
    li = linkedin if linkedin.startswith("http") else f"https://{linkedin}"
    data, meta = treg(
        "POST",
        "/call/blitzapi.people.email.find",
        {"person_linkedin_url": li},
        headers={"X-Treg-Route-Exclude": "aiark"},
        timeout=30,
        retries=2,
    )
    cost = int(meta.get("cost_micro") or 0)
    charge(cost)
    email = ""
    if isinstance(data, dict):
        email = data.get("email") or ""
        if not email and isinstance(data.get("all_emails"), list) and data["all_emails"]:
            email = (data["all_emails"][0] or {}).get("email") or ""
    if (email or "").lower() in ("", "null", "none", "n/a"):
        email = ""
    return email.strip(), cost


def find_quickenrich(first: str, last: str, domain: str, linkedin: str) -> tuple[str, int]:
    if not under_cap(6000):
        return "", 0
    query: dict[str, str] = {
        "first_name": first,
        "last_name": last,
        "company_url": domain,
    }
    if linkedin:
        query["linkedin_url"] = (
            linkedin if linkedin.startswith("http") else f"https://{linkedin}"
        )
    data, meta = treg(
        "GET", "/call/quickenrich.people.email.find", query=query
    )
    cost = int(meta.get("cost_micro") or 0)
    charge(cost)
    email = ""
    if isinstance(data, dict):
        email = data.get("email") or ""
        if not email and isinstance(data.get("data"), dict):
            email = data["data"].get("email") or ""
        if not email and isinstance(data.get("data"), list) and data["data"]:
            email = data["data"][0].get("email") or ""
    if (email or "").lower() in ("", "null", "none", "n/a"):
        email = ""
    return email.strip(), cost


def find_trykitt(first: str, last: str, domain: str) -> tuple[str, int]:
    if not under_cap(7000):
        return "", 0
    full = f"{first} {last}".strip()
    data, meta = treg(
        "POST",
        "/call/trykitt.people.email.find",
        {"domain": domain, "fullName": full, "realtime": True},
    )
    cost = int(meta.get("cost_micro") or 0)
    charge(cost)
    email = ""
    if isinstance(data, dict):
        email = data.get("email") or ""
    if (email or "").lower() in ("", "no-results-found", "none", "null"):
        email = ""
    return email.strip(), cost


def parse_lead(raw: dict) -> dict[str, Any]:
    first = (raw.get("firstname") or raw.get("firstName") or "").strip()
    last = (raw.get("lastname") or raw.get("lastName") or "").strip()
    title = (raw.get("lastJobTitle") or raw.get("headline") or "").strip()
    linkedin = (raw.get("profileUrl") or "").strip()
    company = (raw.get("lastCompanyName") or "").strip()
    website = (raw.get("lastCompanyWebsite") or "").strip()
    company_li = (raw.get("lastCompanyUrl") or "").strip()
    location = (raw.get("address") or "").strip()
    emp = raw.get("lastCompanySize")
    desc = (raw.get("lastCompanyDescription") or "").strip()
    industry = (raw.get("lastCompanyIndustry") or "").strip()
    domain = domain_of(website)
    return {
        "first_name": first,
        "last_name": last,
        "title": title,
        "linkedin": linkedin,
        "company_name": company,
        "website": website,
        "company_linkedin": company_li,
        "location": location,
        "employee_count": emp,
        "company_description": desc,
        "industry": industry,
        "domain": domain,
        "person_key": normalize_linkedin(linkedin) or f"{first}|{last}|{domain}",
    }


READY_COLS = [
    "campaign_id",
    "first_name",
    "last_name",
    "title",
    "email",
    "email_status",
    "email_source",
    "linkedin_url",
    "company_name",
    "website",
    "company_linkedin",
    "location",
    "employee_count",
    "company_description",
    "industry",
    "batch_id",
    "spent_note",
]


def write_ready_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=READY_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "campaign_id": r.get("campaign_id"),
                    "first_name": r.get("first_name"),
                    "last_name": r.get("last_name"),
                    "title": r.get("title"),
                    "email": r.get("email"),
                    "email_status": r.get("email_status"),
                    "email_source": r.get("email_source"),
                    "linkedin_url": r.get("linkedin") or r.get("linkedin_url"),
                    "company_name": r.get("company_name"),
                    "website": r.get("website") or r.get("domain"),
                    "company_linkedin": r.get("company_linkedin"),
                    "location": r.get("location"),
                    "employee_count": r.get("employee_count"),
                    "company_description": r.get("company_description"),
                    "industry": r.get("industry"),
                    "batch_id": r.get("batch_id"),
                    "spent_note": r.get("spent_note"),
                }
            )


def load_ready_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            row = dict(r)
            row["linkedin"] = row.get("linkedin_url") or row.get("linkedin") or ""
            row["domain"] = domain_of(row.get("website") or "")
            rows.append(row)
    return rows


def resolve_email_find_first(lead: dict, excl_emails: set[str], *, blitz_only: bool = False) -> dict:
    """Default speed path: cache → Blitz → QE(+MV) → Trykitt(+MV). No ContactOut."""
    reused = try_supabase_email_reuse(lead, excl_emails)
    if reused is not None:
        return reused

    d = lead.get("domain") or ""
    email = ""
    email_source = ""
    email_status = ""
    cost_here = 0

    if not under_cap(1000):
        return {
            "email": None,
            "email_status": None,
            "email_source": None,
            "spent_note": "0",
            "plusvibe_ready": False,
            "stopped": True,
        }

    if WITH_PATTERN_MV and d:
        for guess in pattern_emails(lead["first_name"], lead["last_name"], d)[:1]:
            if guess.lower() in excl_emails:
                continue
            try:
                mv, mcost = verify_mv(guess)
                cost_here += mcost
                if mv == "stopped":
                    break
                if mv in VALID_MV:
                    email, email_source, email_status = guess, "pattern+mv", mv
                    break
                if mv in CATCH_ALL_MV:
                    email_status = mv
            except Exception as e:
                print(f"mv_err {guess}: {e}", flush=True)

    if not email and lead.get("linkedin"):
        try:
            b_email, bcost = find_blitz(lead["linkedin"])
            cost_here += bcost
            if b_email and b_email.lower() not in excl_emails:
                email, email_source, email_status = b_email, "blitz", "blitz"
        except Exception as e:
            print(f"blitz_err {d}: {e}", flush=True)

    if not email and not blitz_only and d and under_cap(6000):
        try:
            qe_email, qcost = find_quickenrich(
                lead["first_name"],
                lead["last_name"],
                d,
                lead.get("linkedin") or "",
            )
            cost_here += qcost
            if qe_email and qe_email.lower() not in excl_emails:
                mv, mcost = verify_mv(qe_email)
                cost_here += mcost
                if mv in VALID_MV or (
                    mv in CATCH_ALL_MV and email_status not in VALID_MV
                ):
                    email, email_source, email_status = (
                        qe_email,
                        "quickenrich+mv",
                        mv,
                    )
        except Exception as e:
            print(f"qe_err {d}: {e}", flush=True)

    if not email and not blitz_only and d and under_cap(7000):
        try:
            tk_email, tcost = find_trykitt(
                lead["first_name"], lead["last_name"], d
            )
            cost_here += tcost
            if tk_email and tk_email.lower() not in excl_emails:
                mv, mcost = verify_mv(tk_email)
                cost_here += mcost
                if mv in VALID_MV or mv in CATCH_ALL_MV or mv == "":
                    email = tk_email
                    email_source = "trykitt+mv"
                    email_status = mv or "trykitt"
        except Exception as e:
            print(f"tk_err {d}: {e}", flush=True)

    ready = bool(
        email
        and email.lower() not in excl_emails
        and (
            email_status in VALID_MV
            or email_status in CATCH_ALL_MV
            or email_source == "blitz"
            or (email_source or "").startswith("trykitt")
        )
    )
    if email_status in CATCH_ALL_MV and not (email_source or "").startswith("trykitt"):
        # Prefer only catch-all if we never escalated past pattern; find-first rarely hits this
        if email_source == "pattern+mv":
            ready = False

    return {
        "email": email or None,
        "email_status": email_status or None,
        "email_source": email_source or None,
        "spent_note": f"{cost_here/1e6:.4f}",
        "plusvibe_ready": ready,
        "stopped": False,
    }


def resolve_email_cheap(lead: dict, excl_emails: set[str]) -> dict:
    """Deprecated alias: Blitz-only find-first (no ContactOut)."""
    return resolve_email_find_first(lead, excl_emails, blitz_only=True)


def resolve_email_fast(lead: dict, excl_emails: set[str]) -> dict:
    """Default find-first waterfall. Optional WITH_PATTERN_MV. No ContactOut."""
    if CHEAP_MODE:
        return resolve_email_cheap(lead, excl_emails)
    return resolve_email_find_first(lead, excl_emails, blitz_only=False)


def process_candidates_parallel(
    candidates: list[dict],
    excl_emails: set[str],
    workers: int,
) -> list[tuple[dict, dict]]:
    """Resolve emails for a page of candidates concurrently."""
    results: list[tuple[dict, dict]] = []
    if not candidates:
        return results
    n = min(workers, max(1, len(candidates)))
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = {
            pool.submit(resolve_email_fast, lead, excl_emails): lead
            for lead in candidates
        }
        for fut in as_completed(futs):
            lead = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                print(f"resolve_err {lead.get('domain')}: {e}", flush=True)
                res = {
                    "email": None,
                    "email_status": None,
                    "email_source": None,
                    "spent_note": "0",
                    "plusvibe_ready": False,
                    "stopped": False,
                }
            results.append((lead, res))
    return results


def scale_soft_goals(target_ready: int) -> None:
    """Scale campaign soft_ready to sum to target_ready (proportional to current)."""
    total = sum(int(c["soft_ready"]) for c in CAMPAIGNS) or 1
    allocated = 0
    for i, camp in enumerate(CAMPAIGNS):
        if i == len(CAMPAIGNS) - 1:
            camp["soft_ready"] = max(1, target_ready - allocated)
        else:
            n = max(1, round(target_ready * int(camp["soft_ready"]) / total))
            camp["soft_ready"] = n
            allocated += n


def run(
    confirm_spend: float,
    resume_csv: str | None = None,
    workers: int = DEFAULT_WORKERS,
    skip_counts: bool = False,
    cheap: bool = False,
    with_pattern_mv: bool = False,
    target_ready: int | None = None,
    exclude_csv: str | None = None,
) -> dict:
    global _spent_micro, _cap_micro, _stop_spend, CHEAP_MODE, WITH_PATTERN_MV
    CHEAP_MODE = cheap
    WITH_PATTERN_MV = with_pattern_mv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start_bal = balance_usd()
    effective_cap = min(confirm_spend, start_bal)
    _cap_micro = int(effective_cap * 1_000_000)
    _spent_micro = 0
    _stop_spend = False
    t0 = time.time()

    if target_ready and target_ready > 0:
        scale_soft_goals(target_ready)

    prior_rows: list[dict] = []
    exclude_only_rows: list[dict] = []
    batch_id = ""
    if resume_csv:
        prior_path = Path(resume_csv)
        prior_rows = load_ready_csv(prior_path)
        # Keep batch id from prior file name when possible
        m = re.search(r"(gws-icypeas-[^/_]+)_ready", prior_path.name)
        batch_id = m.group(1) if m else (
            prior_rows[0].get("batch_id") if prior_rows else ""
        )
        if not batch_id:
            batch_id = (
                f"gws-icypeas-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-"
                f"{uuid.uuid4().hex[:8]}"
            )
        print(
            f"RESUME from {prior_path} prior_ready={len(prior_rows)} batch={batch_id}",
            flush=True,
        )
    else:
        batch_id = (
            f"gws-icypeas-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        if exclude_csv:
            exclude_only_rows = load_ready_csv(Path(exclude_csv))
            print(
                f"EXCLUDE-ONLY from {exclude_csv} n={len(exclude_only_rows)}",
                flush=True,
            )

    print(
        f"start_balance=${start_bal:.4f} confirm=${confirm_spend} "
        f"effective_cap=${effective_cap:.4f} batch={batch_id} workers={workers} "
        f"cheap={cheap} target_ready={target_ready}",
        flush=True,
    )
    print(
        "soft_goals "
        + " ".join(f"{c['id']}={c['soft_ready']}" for c in CAMPAIGNS),
        flush=True,
    )

    excl_emails = load_file_set(OUT_DIR / "exclude_emails.txt")
    excl_domains = load_file_set(OUT_DIR / "exclude_domains.txt")
    excl_li = load_file_set(OUT_DIR / "exclude_linkedin.txt")
    pv = load_plusvibe_suppress(PLUSVIBE_WS)
    for e in pv:
        if e.startswith("li:"):
            excl_li.add(e[3:])
        else:
            excl_emails.add(e)

    # Suppress prior / exclude-csv ready leads (don't re-pay)
    for r in list(prior_rows) + list(exclude_only_rows):
        em = (r.get("email") or "").strip().lower()
        if em:
            excl_emails.add(em)
        d = domain_of(r.get("website") or r.get("domain") or "")
        if d:
            excl_domains.add(d)
        li = normalize_linkedin(r.get("linkedin") or r.get("linkedin_url") or "")
        if li:
            excl_li.add(li)

    print(
        f"excludes emails={len(excl_emails)} domains={len(excl_domains)} li={len(excl_li)}",
        flush=True,
    )
    load_supabase_lead_index()

    if not skip_counts:
        for camp in CAMPAIGNS:
            for band in camp["bands"]:
                try:
                    c = free_count(camp, band)
                except Exception as e:
                    c = -1
                    print(f"count_err {camp['id']} {band}: {e}", flush=True)
                print(f"COUNT {camp['id']} {band[0]}-{band[1]} total={c}", flush=True)
                time.sleep(0.02)

    state: dict[str, Any] = {}
    for camp in CAMPAIGNS:
        prior_ready = sum(1 for r in prior_rows if r.get("campaign_id") == camp["id"])
        state[camp["id"]] = {
            "camp": camp,
            "band_i": 0,
            "token": None,
            "exhausted": False,
            "ready": prior_ready,
            "searched": 0,
            "skipped": 0,
            "spent_usd": 0.0,
            "pages": 0,
            "prior_ready": prior_ready,
        }

    ready_rows: list[dict] = list(prior_rows)
    all_found: list[dict] = []
    seen_domains: set[str] = set(excl_domains)
    seen_people: set[str] = set()
    for r in list(prior_rows) + list(exclude_only_rows):
        li = normalize_linkedin(r.get("linkedin") or r.get("linkedin_url") or "")
        if li:
            seen_people.add(li)
        pk = f"{r.get('first_name')}|{r.get('last_name')}|{domain_of(r.get('website') or '')}"
        seen_people.add(pk)
    domain_best: dict[str, dict] = {}
    csv_lock = threading.Lock()
    ready_csv_path = OUT_DIR / f"{batch_id}_ready.csv"
    new_ready_this_run = 0
    target_new = int(target_ready or 0)

    def flush_ready() -> None:
        with csv_lock:
            write_ready_csv(ready_csv_path, ready_rows)

    flush_ready()

    stop = False
    idle_rounds = 0
    while not stop and idle_rounds < 3 and under_cap(500):
        progress = False
        for camp in CAMPAIGNS:
            st = state[camp["id"]]
            if st["exhausted"] or st["ready"] >= camp["soft_ready"]:
                continue
            if not under_cap(500):
                stop = True
                print("STOP: spend cap", flush=True)
                break
            band = camp["bands"][st["band_i"]]
            try:
                data, meta = search_page(camp, band, st["token"], size=100)
            except Exception as e:
                print(f"search_err {camp['id']} {band}: {e}", flush=True)
                if st["band_i"] + 1 < len(camp["bands"]):
                    st["band_i"] += 1
                    st["token"] = None
                    progress = True
                else:
                    st["exhausted"] = True
                continue
            cost = int(meta.get("cost_micro") or 0)
            charge(cost)
            st["spent_usd"] += cost / 1_000_000
            leads = (data or {}).get("leads") or []
            st["pages"] += 1
            progress = True
            print(
                f"PAGE {camp['id']} band={band[0]}-{band[1]} n={len(leads)} "
                f"cost_micro={cost} spent=${spent_usd():.4f} "
                f"ready_total={len(ready_rows)} t={time.time()-t0:.0f}s",
                flush=True,
            )

            candidates: list[dict] = []
            for raw in leads:
                lead = parse_lead(raw)
                pk = lead["person_key"]
                if not pk or pk in seen_people:
                    st["skipped"] += 1
                    continue
                seen_people.add(pk)
                if not lead["first_name"] or not lead["domain"]:
                    st["skipped"] += 1
                    continue
                if not title_ok(lead["title"], lead["company_name"]):
                    st["skipped"] += 1
                    continue
                if lead["employee_count"] in (None, ""):
                    st["skipped"] += 1
                    continue
                if not lead["company_description"]:
                    st["skipped"] += 1
                    continue
                li_n = normalize_linkedin(lead["linkedin"]) if lead["linkedin"] else ""
                if li_n and li_n in excl_li:
                    st["skipped"] += 1
                    continue
                d = lead["domain"]
                if d in seen_domains and d not in domain_best:
                    st["skipped"] += 1
                    continue
                if d in domain_best:
                    if title_rank(lead["title"]) >= title_rank(domain_best[d]["title"]):
                        st["skipped"] += 1
                        continue
                domain_best[d] = lead
                candidates.append(lead)

            # Cap candidates by remaining soft goal room to avoid overspend
            room = camp["soft_ready"] - st["ready"]
            if room <= 0:
                candidates = []
            # Process all hygiene-passed candidates in parallel (spend gate stops paid calls)
            st["searched"] += len(candidates)
            print(
                f"  EMAIL {camp['id']} candidates={len(candidates)} workers={workers}",
                flush=True,
            )
            resolved = process_candidates_parallel(candidates, excl_emails, workers)

            # Apply results serially for domain/email uniqueness
            page_ready = 0
            sb_upserted = 0
            for lead, res in resolved:
                if res.get("stopped"):
                    stop = True
                row = {
                    **lead,
                    "campaign_id": camp["id"],
                    "offer": camp["offer"],
                    "email": res.get("email"),
                    "email_status": res.get("email_status"),
                    "email_source": res.get("email_source"),
                    "batch_id": batch_id,
                    "plusvibe_ready": res.get("plusvibe_ready"),
                    "spent_note": res.get("spent_note"),
                    "supabase_age_days": res.get("supabase_age_days"),
                }
                all_found.append(row)
                try:
                    st["spent_usd"] += float(res.get("spent_note") or 0)
                except ValueError:
                    pass
                # Every found email → Supabase (with size / description / location)
                if row.get("email"):
                    if upsert_pipeline_lead(row):
                        sb_upserted += 1
                if not res.get("plusvibe_ready"):
                    continue
                d = lead["domain"]
                em = (res.get("email") or "").lower()
                if d in seen_domains or em in excl_emails:
                    continue
                if st["ready"] >= camp["soft_ready"]:
                    continue
                seen_domains.add(d)
                excl_emails.add(em)
                st["ready"] += 1
                page_ready += 1
                new_ready_this_run += 1
                ready_rows.append(row)
                src = res.get("email_source") or ""
                print(
                    f"  READY {camp['id']} {st['ready']}/{camp['soft_ready']} "
                    f"{em} {lead['company_name'][:40]} src={src} "
                    f"spent=${spent_usd():.4f} "
                    f"rate={new_ready_this_run/max(time.time()-t0,1)*60:.1f}/min",
                    flush=True,
                )
            if sb_upserted:
                print(
                    f"  SUPABASE upserted={sb_upserted} page={camp['id']}",
                    flush=True,
                )

            if page_ready:
                flush_ready()

            nxt = ((data or {}).get("pagination") or {}).get("token")
            if not leads or not nxt:
                if st["band_i"] + 1 < len(camp["bands"]):
                    st["band_i"] += 1
                    st["token"] = None
                else:
                    st["exhausted"] = True
            else:
                st["token"] = nxt

            if not under_cap(500):
                stop = True
                print("STOP: spend cap after page", flush=True)
                break
            if target_new and new_ready_this_run >= target_new:
                stop = True
                print(f"STOP: hit target_ready={target_new}", flush=True)
                break

        if not progress:
            idle_rounds += 1
        else:
            idle_rounds = 0
        if target_new and new_ready_this_run >= target_new:
            break
        if all(
            state[c["id"]]["exhausted"] or state[c["id"]]["ready"] >= c["soft_ready"]
            for c in CAMPAIGNS
        ):
            break

    elapsed = time.time() - t0
    end_bal = balance_usd()
    throughput = new_ready_this_run / max(elapsed / 60.0, 0.001)
    stats = {
        "batch_id": batch_id,
        "sheet_id": SHEET_ID,
        "confirm_spend_usd": confirm_spend,
        "effective_cap_usd": effective_cap,
        "start_balance_usd": start_bal,
        "end_balance_usd": end_bal,
        "spent_usd": round(spent_usd(), 6),
        "spent_from_balance_usd": round(start_bal - end_bal, 6),
        "ready_total": len(ready_rows),
        "ready_prior": len(prior_rows),
        "ready_new": new_ready_this_run,
        "found_total": len(all_found),
        "elapsed_sec": round(elapsed, 1),
        "throughput_ready_per_min": round(throughput, 2),
        "workers": workers,
        "campaigns": {
            cid: {
                "ready": state[cid]["ready"],
                "prior_ready": state[cid]["prior_ready"],
                "searched": state[cid]["searched"],
                "skipped": state[cid]["skipped"],
                "spent_usd": round(state[cid]["spent_usd"], 6),
                "soft_ready": state[cid]["camp"]["soft_ready"],
                "pages": state[cid]["pages"],
                "exhausted": state[cid]["exhausted"],
            }
            for cid in state
        },
        "db_order": ["icypeas.people.search"],
        "email_order": (
            [
                "supabase_cache_or_supabase+mv",
                "pattern",
                "contactout.people.email.verify",
                "blitzapi.people.email.find",
            ]
            if cheap
            else [
                "supabase_cache_or_supabase+mv",
                "pattern",
                "millionverifier.people.email.verify",
                "quickenrich.people.email.find",
                "trykitt.people.email.find",
            ]
        ),
        "fast_mode": True,
        "cheap_mode": cheap,
        "target_ready": target_ready,
        "contactout_skipped": not cheap,
        "supabase_reuse_days": SB_CACHE_DAYS,
        "supabase_upsert": True,
    }
    ready_csv = ready_csv_path
    all_csv = OUT_DIR / f"{batch_id}_all_fast.csv"
    write_ready_csv(ready_csv, ready_rows)
    write_ready_csv(all_csv, all_found)
    summary = OUT_DIR / f"{batch_id}_summary.json"
    stats["artifacts"] = {
        "ready_csv": str(ready_csv),
        "all_csv": str(all_csv),
        "summary": str(summary),
    }
    summary.write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2), flush=True)
    return stats


def main() -> None:
    global TOKEN
    p = argparse.ArgumentParser()
    p.add_argument("--confirm-spend", type=float, required=True)
    p.add_argument("--resume-csv", type=str, default="")
    p.add_argument("--exclude-csv", type=str, default="")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--skip-counts", action="store_true")
    p.add_argument(
        "--cheap",
        action="store_true",
        help="Blitz-only find-first (no ContactOut; QE/Trykitt skipped)",
    )
    p.add_argument(
        "--with-pattern-mv",
        action="store_true",
        help="Optional: try pattern+MillionVerifier before find waterfall",
    )
    p.add_argument(
        "--target-ready",
        type=int,
        default=0,
        help="Scale soft goals to this many ready leads",
    )
    args = p.parse_args()
    TOKEN = load_treg_token()
    run(
        args.confirm_spend,
        resume_csv=args.resume_csv or None,
        workers=args.workers,
        skip_counts=args.skip_counts,
        cheap=args.cheap,
        with_pattern_mv=args.with_pattern_mv,
        target_ready=args.target_ready or None,
        exclude_csv=args.exclude_csv or None,
    )


if __name__ == "__main__":
    main()
