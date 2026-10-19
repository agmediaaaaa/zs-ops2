#!/usr/bin/env python3
"""ATC NP/PA v3 generic — cheap path (Icypeas people.search → Blitz email.find).

Size split (Oct 16 ICP):
  - 2–199 employees: C-suite / founders
  - 200–500 employees: ops leaders

No per-company cap. Uploads all ready leads to Supabase with list_id.
Campaign metadata: v3 generic.

Gates:
  --scope-only          free Icypeas TAM counts
  --pilot               small ready target (default 40)
  --full                ready target (default 2000)
  --confirm-spend USD   hard spend cap (required for pilot/full)
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

BASE = "https://treg.to"
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/atc-np-pa-v3"))
PLUSVIBE_WS = os.environ.get("PLUSVIBE_WORKSPACE_ID", "6a908184e665953cae106e15")
PLUSVIBE_API = "https://api.plusvibe.ai/api/v1"
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
)
CLIENT = "ATC"
SOURCE = "treg.to / icypeas→blitz"
CAMPAIGN = "v3 generic"
LIST_NAME_BASE = "ATC NP/PA v3 generic Oct 19"
# No 2-per-company exclusion for this run
MAX_PER_COMPANY = 9999
PAGE_SIZE = 50
FREEMAIL = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "me.com",
    "msn.com",
    "live.com",
    "protonmail.com",
    "mail.com",
}

ICY_INDUSTRIES = [
    "Medical Practices",
    "Hospitals and Health Care",
    "Mental Health Care",
    "Outpatient Care Centers",
    "Physicians",
]

KEYWORDS = [
    "urgent care",
    "walk-in clinic",
    "primary care practice",
    "family practice",
    "family medicine",
    "internal medicine",
    "pediatric practice",
    "concierge medicine",
    "direct primary care",
    "house calls",
    "home-based primary care",
    "retail clinic",
    "occupational medicine",
    "dermatology",
    "med spa",
    "medical spa",
    "medical weight loss",
    "weight loss clinic",
    "men's health",
    "low T",
    "hormone replacement",
    "women's health",
    "OB/GYN",
    "pain management",
    "interventional pain",
    "orthopedic",
    "cardiology",
    "GI practice",
    "gastroenterology",
    "wound care",
    "outpatient psychiatry",
    "psychiatric practice",
    "psychiatric nurse practitioner",
    "ketamine clinic",
    "TMS therapy",
    "Suboxone",
    "medication-assisted treatment",
    "addiction treatment",
    "behavioral health",
    "nurse practitioner",
    "physician assistant",
]
KEYWORD_EXCLUDE = [
    "hospital",
    "hospitals",
    "health system",
    "staffing",
    "insurance",
    "pharma",
    "biotech",
    "medical device",
    "laboratory",
    "nursing home",
    "nonprofit",
    "software",
    "SaaS",
    "wellness",
    "fitness",
    "alternative medicine",
]
EXCLUDE_COMPANIES = [
    "TeamHealth",
    "Envision",
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

CSUITE_TITLES = [
    "CEO",
    "Founder",
    "Co-Founder",
    "Owner",
    "Co-Owner",
    "President",
    "Managing Partner",
    "Practice Owner",
    "Clinic Owner",
]
OPS_TITLES = [
    "COO",
    "Head of Operations",
    "Practice Administrator",
    "Director of Operations",
    "Operations Manager",
    "VP of Operations",
]
# VP of Operations is ops intent; still reject generic VP via title_ok

TITLE_EXCLUDE_RE = re.compile(
    r"\b("
    r"SVP|EVP|"
    r"Coordinator|Assistant|Sales|Marketing|"
    r"Business\s+Development|\bBD\b|Advisor|Board|"
    r"CFO|Financial|Finance|Revenue|"
    r"CTO|Technology|Information|"
    r"Nursing|Nurse(?!\s+Practitioner)|Human\s+Resources|\bHR\b|People|"
    r"Investor|Product\s+Owner|Process\s+Owner|"
    r"Intern|Student|Retired|Former|Consultant"
    r")\b",
    re.I,
)
GENERIC_VP_RE = re.compile(
    r"\b(VP|V\.P\.|Vice[\s-]?President)\b",
    re.I,
)
OPS_VP_OK_RE = re.compile(
    r"\b(VP|V\.P\.|Vice[\s-]?President)\s+of\s+Operations\b",
    re.I,
)
CSUITE_OK = re.compile(
    r"\b(CEO|Founder|Co[-\s]?Founder|Owner|Co[-\s]?Owner|President|"
    r"Managing\s+Partner|Practice\s+Owner|Clinic\s+Owner)\b",
    re.I,
)
OPS_OK = re.compile(
    r"\b(COO|Chief\s+Operating\s+Officer|Head\s+of\s+Operations|"
    r"Practice\s+Administrator|Director\s+of\s+Operations|"
    r"Operations\s+Manager|VP\s+of\s+Operations|"
    r"Vice\s+President\s+of\s+Operations)\b",
    re.I,
)

BANDS = [
    {
        "id": "csuite_lt200",
        "name": "C-suite / founders (2–199)",
        "titles": CSUITE_TITLES,
        "lo": 2,
        "hi": 199,
        "title_kind": "csuite",
        "ready_share": 0.92,
    },
    {
        "id": "ops_200_500",
        "name": "Ops leaders (200–500)",
        "titles": OPS_TITLES,
        "lo": 200,
        "hi": 500,
        "title_kind": "ops",
        "ready_share": 0.08,
    },
]


def treg_token() -> str:
    for name in ("treg", "TREG_TOKEN", "TREG_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    cfg = Path.home() / ".treg" / "config.json"
    if cfg.exists():
        try:
            v = (json.loads(cfg.read_text()).get("token") or "").strip()
            if v:
                return v
        except Exception:
            pass
    raise SystemExit("Set treg / TREG_TOKEN")


TOKEN = treg_token()


def supabase_key() -> str:
    raw = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
    key = "".join(c for c in raw if 32 <= ord(c) < 127)
    if not key:
        raise SystemExit("Set SUPABASE_SERVICE_ROLE_KEY")
    return key


def plusvibe_key() -> str | None:
    for name in ("PLUSVIBE_API_KEY", "PLUSVIBE_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return None


def call(endpoint: str, body: dict | None = None, extra_headers: dict | None = None) -> tuple[Any, int]:
    data = None if body is None else json.dumps(body).encode()
    hdrs = {
        "X-Treg-Token": TOKEN,
        "Accept": "application/json",
        "User-Agent": "zs-ops2-atc-v3/1.0",
    }
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if "email.find" in endpoint:
        hdrs["X-Treg-Route-Max-Cost"] = "0.01"
        hdrs["X-Treg-Route-Waterfall"] = "0"
        hdrs["X-Treg-Route-Exclude"] = "aiark,icypeas"
    if extra_headers:
        hdrs.update(extra_headers)
    req = urllib.request.Request(
        f"{BASE}/call/{endpoint}",
        data=data,
        method="POST" if body is not None else "GET",
        headers=hdrs,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
            raw = resp.read()
            return (json.loads(raw.decode()) if raw else {}), cost
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"{endpoint} HTTP {e.code}: {err}") from e


def sb_request(
    method: str,
    table: str,
    payload: Any | None = None,
    query: dict | None = None,
    prefer: str = "return=representation",
) -> Any:
    path = urllib.parse.quote(table, safe="")
    qs = f"?{urllib.parse.urlencode(query)}" if query else ""
    url = f"{SUPABASE_URL}/rest/v1/{path}{qs}"
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "apikey": supabase_key(),
            "Authorization": f"Bearer {supabase_key()}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else None


def normalize_linkedin(url: str) -> str:
    u = (url or "").strip().split("?")[0].rstrip("/")
    if u.startswith("http://"):
        u = "https://" + u[len("http://") :]
    return u.lower()


def domain_of(website: str) -> str:
    w = (website or "").strip().lower()
    if not w:
        return ""
    w = re.sub(r"^https?://", "", w)
    w = w.split("/")[0]
    w = w[4:] if w.startswith("www.") else w
    return w


def title_ok(title: str, kind: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if TITLE_EXCLUDE_RE.search(t):
        return False
    if GENERIC_VP_RE.search(t) and not OPS_VP_OK_RE.search(t):
        return False
    if kind == "csuite":
        return bool(CSUITE_OK.search(t))
    return bool(OPS_OK.search(t))


def emp_ok(n: Any, lo: int, hi: int) -> bool:
    try:
        v = int(n)
    except Exception:
        return False
    return lo <= v <= hi


def company_excluded(name: str) -> bool:
    n = (name or "").lower()
    return any(x.lower() in n for x in EXCLUDE_COMPANIES)


def band_query(band: dict) -> dict[str, Any]:
    excludes = [
        "Intern",
        "Student",
        "Consultant",
        "Coordinator",
        "Assistant",
        "Sales",
        "Marketing",
        "SVP",
        "EVP",
    ]
    # Keep VP available for ops band (VP of Operations); drop for csuite
    if band["title_kind"] == "csuite":
        excludes.extend(["VP", "Vice President"])
    return {
        "currentJobTitle": {
            "include": band["titles"],
            "exclude": excludes,
        },
        "profileLocation": {"include": ["US"]},
        "keyword": {"include": KEYWORDS, "exclude": KEYWORD_EXCLUDE},
        "currentCompany.headcount": {">=": band["lo"], "<=": band["hi"]},
        "currentCompany.industry": {"include": ICY_INDUSTRIES},
    }


def scope_only() -> None:
    print("=== FREE TAM (icypeas.people.search.count) ===")
    total = 0
    for b in BANDS:
        out, cost = call("icypeas.people.search.count", {"query": band_query(b)})
        assert cost == 0, cost
        n = int(out.get("total") or 0)
        total += n
        print(f"  {b['id']} {b['name']}: {n:,}")
    print(f"TOTAL: {total:,}")
    print("\n=== CATALOG QUOTE (cheap path, target 2000 ready) ===")
    # Cheap scrape observed ~4.3 search rows / ready, ~1.5 email attempts / ready, ~67% hit
    search_rows = 2000 * 4.3
    email_hits = 2000 * 1.0  # billable successes ≈ ready (misses free)
    email_attempts = 2000 * 1.5
    search_usd = search_rows * 0.00038
    email_usd = email_hits * 0.000495
    print(f"  icypeas.people.search     ~{search_rows:.0f} rows × $0.00038 = ${search_usd:.2f}")
    print(f"  blitzapi.people.email.find ~{email_attempts:.0f} attempts / ~{email_hits:.0f} hits × $0.000495 = ${email_usd:.2f}")
    print(f"  expected_usd ≈ ${search_usd + email_usd:.2f}")
    print(f"  recommended_cap_usd ≈ ${(search_usd + email_usd) * 1.4:.2f}  (×1.4)")
    print("  (MV verify skipped — cheap-scrape path; emails marked unverified)")


def load_plusvibe_suppress(ws: str) -> set[str]:
    key = plusvibe_key()
    out: set[str] = set()
    if not key:
        print("plusvibe_skip: no API key", flush=True)
        return out
    # Best-effort; ignore failures
    try:
        url = f"{PLUSVIBE_API}/leads/export?workspace_id={ws}&limit=50000"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
        rows = data if isinstance(data, list) else (data.get("data") or data.get("leads") or [])
        for r in rows:
            em = (r.get("email") or "").strip().lower()
            if em:
                out.add(em)
            li = normalize_linkedin(r.get("linkedin") or r.get("linkedin_url") or "")
            if li:
                out.add(f"li:{li}")
        print(f"plusvibe_suppress={len(out)}", flush=True)
    except Exception as e:
        print(f"plusvibe_warn: {e}", flush=True)
    return out


def sb_known_emails_linkedin() -> tuple[set[str], set[str]]:
    """Cost-skip: known emails + linkedin slugs already in Lead Database (sample via recent ATC lists)."""
    emails: set[str] = set()
    lis: set[str] = set()
    try:
        # Pull prior ATC list members' emails via a broad email select is expensive;
        # instead load emails that match healthcare domains from a limited window is hard.
        # Use lead_lists metadata for ATC and member join is not available via simple REST.
        # Fallback: empty — Blitz is cheap; PlusVibe handles send suppress.
        lists = (
            sb_request(
                "GET",
                "lead_lists",
                query={"client": "eq.ATC", "select": "list_id,list_name", "limit": "20"},
            )
            or []
        )
        print(f"prior_atc_lists={len(lists)}", flush=True)
    except Exception as e:
        print(f"sb_known_warn: {e}", flush=True)
    return emails, lis


def parse_lead(raw: dict, band: dict) -> dict | None:
    first = (raw.get("firstname") or raw.get("firstName") or "").strip()
    last = (raw.get("lastname") or raw.get("lastName") or "").strip()
    title = (raw.get("lastJobTitle") or raw.get("headline") or "").strip()
    linkedin = normalize_linkedin(raw.get("profileUrl") or "")
    company = (raw.get("lastCompanyName") or "").strip()
    website = (raw.get("lastCompanyWebsite") or "").strip()
    location = (raw.get("address") or "").strip()
    emp = raw.get("lastCompanySize")
    desc = (raw.get("lastCompanyDescription") or "").strip()
    industry = (raw.get("lastCompanyIndustry") or "").strip()
    if not first or not last or not linkedin:
        return None
    if not title_ok(title, band["title_kind"]):
        return None
    if not emp_ok(emp, band["lo"], band["hi"]):
        return None
    if company_excluded(company):
        return None
    if not desc:
        return None
    domain = domain_of(website)
    if not domain or domain in FREEMAIL:
        return None
    return {
        "first_name": first,
        "last_name": last,
        "title": title,
        "linkedin": linkedin,
        "company_name": company,
        "website": website if website.startswith("http") else (f"https://{website}" if website else ""),
        "domain": domain,
        "location": location,
        "company_size": int(emp),
        "company_description": desc,
        "company_industry": industry,
        "band": band["id"],
    }


def find_email(linkedin: str) -> tuple[str | None, int, str]:
    out, cost = call(
        "blitzapi.people.email.find",
        {"person_linkedin_url": linkedin},
    )
    email = None
    if isinstance(out, dict):
        email = (
            out.get("email")
            or out.get("work_email")
            or (out.get("data") or {}).get("email")
            or (out.get("result") or {}).get("email")
        )
        if isinstance(email, list):
            email = email[0] if email else None
    if email:
        email = str(email).strip().lower()
        dom = email.split("@")[-1] if "@" in email else ""
        if dom in FREEMAIL:
            email = None
    return email, cost, "blitzapi.people.email.find"


def upsert_lead(row: dict) -> int:
    email = (row.get("email") or "").strip().lower()
    linkedin = row.get("linkedin") or ""
    existing = None
    if email:
        rows = (
            sb_request(
                "GET",
                "Lead Database",
                query={"select": "id", "Email": f"eq.{email}", "limit": "1"},
            )
            or []
        )
        existing = rows[0] if rows else None
    if not existing and linkedin:
        slug = linkedin.rstrip("/").split("/")[-1]
        rows = (
            sb_request(
                "GET",
                "Lead Database",
                query={
                    "select": "id",
                    "Linkedin": f"ilike.*{slug}*",
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
        "title": row.get("title"),
        "email_source": row.get("email_source"),
        "email_status": row.get("email_status"),
        "enrichment_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload = {k: v for k, v in payload.items() if v is not None and v != ""}
    if existing:
        lead_id = int(existing["id"])
        sb_request(
            "PATCH",
            "Lead Database",
            payload,
            query={"id": f"eq.{lead_id}"},
            prefer="return=minimal",
        )
        return lead_id
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
    list_name: str,
) -> str:
    list_row = sb_request(
        "POST",
        "lead_lists",
        {
            "client": CLIENT,
            "list_name": list_name,
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
                "campaign": CAMPAIGN,
                "max_per_company": None,
                "size_split": "csuite_<200 / ops_200_500",
                "mode": report.get("mode"),
                "path": "icypeas.people.search → blitzapi.people.email.find",
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
        sb_request(
            "POST",
            "lead_list_members",
            members[i : i + 100],
            prefer="return=minimal,resolution=merge-duplicates",
        )
    return list_id


def run(mode: str, confirm_spend: float, ready_target: int) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    list_name = (
        f"{LIST_NAME_BASE} pilot"
        if mode == "pilot"
        else f"{LIST_NAME_BASE} ${confirm_spend:g} 2k"
    )
    spend_micro = 0
    ready_rows: list[dict] = []
    seen_li: set[str] = set()
    seen_email: set[str] = set()
    band_stats: dict[str, dict] = {}
    searched = 0
    email_attempts = 0
    email_hits = 0
    skipped_pv = 0
    skipped_dup = 0

    def pay(endpoint: str, body: dict) -> Any:
        nonlocal spend_micro
        if spend_micro / 1e6 >= confirm_spend:
            raise RuntimeError(f"hard cap ${confirm_spend} reached")
        out, cost = call(endpoint, body)
        spend_micro += cost
        if spend_micro / 1e6 > confirm_spend:
            raise RuntimeError(
                f"hard cap ${confirm_spend} exceeded (spent ${spend_micro/1e6:.4f})"
            )
        return out

    print(
        f"mode={mode} ready_target={ready_target} cap=${confirm_spend} campaign={CAMPAIGN}",
        flush=True,
    )
    print("=== FREE TAM ===", flush=True)
    tam: dict[str, int] = {}
    for b in BANDS:
        out = pay("icypeas.people.search.count", {"query": band_query(b)})
        tam[b["id"]] = int(out.get("total") or 0)
        print(f"  {b['id']}: {tam[b['id']]:,}", flush=True)

    pv = load_plusvibe_suppress(PLUSVIBE_WS)
    sb_known_emails_linkedin()

    # Allocate ready targets per band; ops band is thin so take all available share
    remaining = ready_target
    targets: dict[str, int] = {}
    for b in BANDS:
        share = int(round(ready_target * b["ready_share"]))
        targets[b["id"]] = share
    # Fix rounding
    targets[BANDS[0]["id"]] += ready_target - sum(targets.values())

    for b in BANDS:
        need = targets[b["id"]]
        got = 0
        token = None
        pages = 0
        company_counts: dict[str, int] = {}
        band_stats[b["id"]] = {"ready": 0, "searched": 0, "pages": 0, "tam": tam[b["id"]]}
        print(f"\n--- {b['id']} need={need} ---", flush=True)
        while got < need and pages < 120:
            if spend_micro / 1e6 >= confirm_spend * 0.98:
                print("near_cap_stop", flush=True)
                break
            body: dict[str, Any] = {
                "query": band_query(b),
                "pagination": {"size": PAGE_SIZE},
            }
            if token:
                body["pagination"]["token"] = token
            try:
                out = pay("icypeas.people.search", body)
            except RuntimeError as e:
                print(f"search_stop: {e}", flush=True)
                break
            leads = out.get("leads") or []
            token = ((out.get("pagination") or {}).get("token"))
            pages += 1
            band_stats[b["id"]]["pages"] = pages
            searched += len(leads)
            band_stats[b["id"]]["searched"] += len(leads)
            print(
                f"  page={pages} got={len(leads)} spend=${spend_micro/1e6:.4f} ready_band={got}/{need}",
                flush=True,
            )
            for raw in leads:
                if got >= need:
                    break
                lead = parse_lead(raw, b)
                if not lead:
                    continue
                li = lead["linkedin"]
                if li in seen_li:
                    skipped_dup += 1
                    continue
                # No 2-per-company cap — still track counts for reporting
                dom = lead["domain"]
                company_counts[dom] = company_counts.get(dom, 0) + 1

                if f"li:{li}" in pv:
                    skipped_pv += 1
                    seen_li.add(li)
                    continue

                email_attempts += 1
                try:
                    email, cost, src = find_email(li)
                    spend_micro += cost
                except Exception as e:
                    print(f"  email_err: {e}", flush=True)
                    continue
                if spend_micro / 1e6 > confirm_spend:
                    print("cap_after_email", flush=True)
                    break
                seen_li.add(li)
                if not email:
                    continue
                if email in seen_email or email in pv:
                    skipped_pv += 1 if email in pv else skipped_dup
                    continue
                email_hits += 1
                seen_email.add(email)
                row = {
                    **lead,
                    "email": email,
                    "email_source": "blitz",
                    "email_status": "unverified",
                }
                ready_rows.append(row)
                got += 1
                band_stats[b["id"]]["ready"] = got
                if got % 25 == 0 or got == need:
                    print(
                        f"  ready={got}/{need} total_ready={len(ready_rows)} "
                        f"spend=${spend_micro/1e6:.4f}",
                        flush=True,
                    )
                time.sleep(0.04)
            if not leads or not token:
                break
            time.sleep(0.05)
        remaining = ready_target - len(ready_rows)
        # Roll leftover need into next band naturally via remaining target math
        print(
            f"band_done {b['id']} ready={got} spend=${spend_micro/1e6:.4f}",
            flush=True,
        )

    # If under target and budget left, keep paging csuite band
    if len(ready_rows) < ready_target and spend_micro / 1e6 < confirm_spend * 0.95:
        b = BANDS[0]
        print(f"\n--- topup {b['id']} to {ready_target} ---", flush=True)
        token = None
        pages = 0
        while len(ready_rows) < ready_target and pages < 80:
            if spend_micro / 1e6 >= confirm_spend * 0.98:
                break
            body = {"query": band_query(b), "pagination": {"size": PAGE_SIZE}}
            if token:
                body["pagination"]["token"] = token
            try:
                out = pay("icypeas.people.search", body)
            except RuntimeError:
                break
            leads = out.get("leads") or []
            token = ((out.get("pagination") or {}).get("token"))
            pages += 1
            searched += len(leads)
            for raw in leads:
                if len(ready_rows) >= ready_target:
                    break
                lead = parse_lead(raw, b)
                if not lead:
                    continue
                li = lead["linkedin"]
                if li in seen_li or f"li:{li}" in pv:
                    continue
                email_attempts += 1
                try:
                    email, cost, _ = find_email(li)
                    spend_micro += cost
                except Exception:
                    continue
                seen_li.add(li)
                if not email or email in seen_email or email in pv:
                    continue
                email_hits += 1
                seen_email.add(email)
                ready_rows.append(
                    {
                        **lead,
                        "email": email,
                        "email_source": "blitz",
                        "email_status": "unverified",
                    }
                )
                if len(ready_rows) % 25 == 0:
                    print(
                        f"  topup ready={len(ready_rows)} spend=${spend_micro/1e6:.4f}",
                        flush=True,
                    )
                time.sleep(0.04)
            if not leads or not token:
                break
            time.sleep(0.05)

    actual = spend_micro / 1e6
    # Export CSV
    csv_path = OUT_DIR / f"{mode}-ready.csv"
    fields = [
        "first_name",
        "last_name",
        "email",
        "title",
        "linkedin",
        "company_name",
        "website",
        "domain",
        "company_size",
        "company_description",
        "company_industry",
        "location",
        "band",
        "email_source",
        "email_status",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in ready_rows:
            w.writerow(r)

    # Upload
    lead_ids: list[int] = []
    print(f"\n=== UPLOAD {len(ready_rows)} leads ===", flush=True)
    for i, row in enumerate(ready_rows, 1):
        try:
            lid = upsert_lead(row)
            lead_ids.append(lid)
        except Exception as e:
            print(f"upsert_err[{i}]: {e}", flush=True)
        if i % 50 == 0:
            print(f"  upserted {i}/{len(ready_rows)}", flush=True)

    report = {
        "mode": mode,
        "campaign": CAMPAIGN,
        "ready_target": ready_target,
        "ready": len(ready_rows),
        "searched": searched,
        "email_attempts": email_attempts,
        "email_hits": email_hits,
        "email_hit_rate": round(email_hits / email_attempts, 4) if email_attempts else 0,
        "skipped_plusvibe": skipped_pv,
        "skipped_dup": skipped_dup,
        "spend_usd": round(actual, 6),
        "cap_usd": confirm_spend,
        "cost_per_ready": round(actual / len(ready_rows), 6) if ready_rows else None,
        "cost_per_1k_ready": round(actual / len(ready_rows) * 1000, 2) if ready_rows else None,
        "bands": band_stats,
        "tam": tam,
        "path": "icypeas.people.search → blitzapi.people.email.find",
        "max_per_company": None,
        "csv": str(csv_path),
    }
    list_id = ""
    if lead_ids:
        list_id = create_list_with_members(
            lead_ids, len(ready_rows), actual, confirm_spend, report, list_name
        )
        report["list_id"] = list_id
        report["list_name"] = list_name

    report_path = OUT_DIR / f"{mode}-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print("\n=== REPORT ===")
    print(json.dumps(report, indent=2))
    print(f"\nlist_id={list_id}")
    print(f"list_name={list_name}")
    print(f"cost_usd=${actual:.4f}")
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scope-only", action="store_true")
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--full", action="store_true")
    p.add_argument("--confirm-spend", type=float, default=None)
    p.add_argument("--ready-target", type=int, default=None)
    args = p.parse_args()
    if args.scope_only:
        scope_only()
        return
    if args.confirm_spend is None:
        raise SystemExit("--confirm-spend USD required for pilot/full")
    if args.pilot:
        target = args.ready_target or 40
        run("pilot", args.confirm_spend, target)
    else:
        target = args.ready_target or 2000
        run("full", args.confirm_spend, target)


if __name__ == "__main__":
    main()
