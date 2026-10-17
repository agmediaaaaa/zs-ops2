#!/usr/bin/env python3
"""GWS Icypeas scrape → budget email ladder → Sheet2 CSV, hard spend cap.

Plan: Icypeas (description+headcount) → hygiene → pattern → ContactOut (best-effort)
→ MV → QuickEnrich find → Trykitt (catch-all/QE miss) → MV → artifacts + Sheet2 upload.
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
TOKEN = ""


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
    retries: int = 4,
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
            with urllib.request.urlopen(req, timeout=60) as resp:
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
                wait = min(4 * (2**i), 45)
                if e.code in (418, 429):
                    wait = max(wait, 8 + 5 * i)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {err[:800]}") from e
        except Exception as e:
            last = e
            time.sleep(min(2**i, 6))
    raise RuntimeError(f"treg failed after retries: {last}")


def balance_usd() -> float:
    data, _ = treg("GET", "/orgs/33605/balance")
    return float((data or {}).get("balance_usd") or 0)


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
    # Drop pure deny roles unless also owner/founder/ceo
    if TITLE_DENY_RE.search(t) and not re.search(
        r"\b(owner|founder|ceo|chief\s*executive|managing\s*partner)\b", t, re.I
    ):
        return False
    # Co-op / unclear ownership: bare President only
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


def verify_contactout(email: str) -> tuple[str, int]:
    try:
        data, meta = treg(
            "GET",
            "/call/contactout.people.email.verify",
            query={"email": email},
        )
        status = ""
        if isinstance(data, dict):
            status = (
                data.get("status")
                or data.get("result")
                or data.get("deliverable")
                or ""
            )
            if isinstance(status, bool):
                status = "valid" if status else "invalid"
            status = str(status).lower()
        return status, int(meta.get("cost_micro") or 0)
    except Exception as e:
        print(f"contactout_skip {email}: {e}", flush=True)
        return "error", 0


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


def find_quickenrich(first: str, last: str, domain: str, linkedin: str) -> tuple[str, int]:
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
    email = ""
    if isinstance(data, dict):
        email = data.get("email") or ""
        if not email and isinstance(data.get("data"), dict):
            email = data["data"].get("email") or ""
        if not email and isinstance(data.get("data"), list) and data["data"]:
            email = data["data"][0].get("email") or ""
    if (email or "").lower() in ("", "null", "none", "n/a"):
        email = ""
    return email.strip(), int(meta.get("cost_micro") or 0)


def find_trykitt(first: str, last: str, domain: str) -> tuple[str, int]:
    full = f"{first} {last}".strip()
    data, meta = treg(
        "POST",
        "/call/trykitt.people.email.find",
        {"domain": domain, "fullName": full, "realtime": True},
    )
    email = ""
    if isinstance(data, dict):
        email = data.get("email") or ""
    if (email or "").lower() in ("", "no-results-found", "none", "null"):
        email = ""
    return email.strip(), int(meta.get("cost_micro") or 0)


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
    if not domain and "@" not in company:
        # sometimes website is a LI jobs URL — try nothing
        pass
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


def write_ready_csv(path: Path, rows: list[dict]) -> None:
    cols = [
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
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
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
                    "linkedin_url": r.get("linkedin"),
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


def run(confirm_spend: float) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start_bal = balance_usd()
    effective_cap = min(confirm_spend, start_bal)
    cap_micro = int(effective_cap * 1_000_000)
    spent_micro = 0
    batch_id = (
        f"gws-icypeas-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    print(
        f"start_balance=${start_bal:.4f} confirm=${confirm_spend} "
        f"effective_cap=${effective_cap:.4f} batch={batch_id}",
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
    print(
        f"excludes emails={len(excl_emails)} domains={len(excl_domains)} li={len(excl_li)}",
        flush=True,
    )

    # Free count each campaign/band
    for camp in CAMPAIGNS:
        for band in camp["bands"]:
            try:
                c = free_count(camp, band)
            except Exception as e:
                c = -1
                print(f"count_err {camp['id']} {band}: {e}", flush=True)
            print(f"COUNT {camp['id']} {band[0]}-{band[1]} total={c}", flush=True)
            time.sleep(0.05)

    # Round-robin state
    state: dict[str, Any] = {}
    for camp in CAMPAIGNS:
        state[camp["id"]] = {
            "camp": camp,
            "band_i": 0,
            "token": None,
            "exhausted": False,
            "ready": 0,
            "searched": 0,
            "skipped": 0,
            "spent_usd": 0.0,
            "pages": 0,
        }

    ready_rows: list[dict] = []
    all_found: list[dict] = []
    seen_domains: set[str] = set(excl_domains)
    seen_people: set[str] = set()
    domain_best: dict[str, dict] = {}

    def under_cap(need_micro: int = 0) -> bool:
        return spent_micro + need_micro < cap_micro

    stop = False
    idle_rounds = 0
    while not stop and idle_rounds < 3:
        progress = False
        for camp in CAMPAIGNS:
            st = state[camp["id"]]
            if st["exhausted"] or st["ready"] >= camp["soft_ready"]:
                continue
            if not under_cap(500):  # leave tiny buffer
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
            spent_micro += cost
            st["spent_usd"] += cost / 1_000_000
            leads = (data or {}).get("leads") or []
            st["pages"] += 1
            progress = True
            print(
                f"PAGE {camp['id']} band={band[0]}-{band[1]} n={len(leads)} "
                f"cost_micro={cost} spent=${spent_micro/1e6:.4f}",
                flush=True,
            )
            # collect candidates then email
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
                # description required by plan
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
                # one DM per domain — keep best title
                if d in domain_best:
                    if title_rank(lead["title"]) >= title_rank(
                        domain_best[d]["title"]
                    ):
                        st["skipped"] += 1
                        continue
                domain_best[d] = lead
                candidates.append(lead)

            for lead in candidates:
                if st["ready"] >= camp["soft_ready"] or not under_cap(2000):
                    break
                d = lead["domain"]
                st["searched"] += 1
                email = ""
                email_source = ""
                email_status = ""
                cost_here = 0

                # Fast path: 1 pattern + MV, then paid find. ContactOut skipped (slow/limits).
                for guess in pattern_emails(
                    lead["first_name"], lead["last_name"], d
                )[:1]:
                    if guess.lower() in excl_emails:
                        continue
                    if not under_cap(2000):
                        break
                    mv, mcost = verify_mv(guess)
                    cost_here += mcost
                    spent_micro += mcost
                    if mv in VALID_MV:
                        email, email_source, email_status = guess, "pattern+mv", mv
                        break
                    if mv in CATCH_ALL_MV:
                        email, email_source, email_status = (
                            guess,
                            "pattern+catch_all",
                            mv,
                        )
                        break

                # QuickEnrich on miss / non-ok
                if (not email or email_status not in VALID_MV) and under_cap(6000):
                    try:
                        qe_email, qcost = find_quickenrich(
                            lead["first_name"],
                            lead["last_name"],
                            d,
                            lead["linkedin"],
                        )
                        cost_here += qcost
                        spent_micro += qcost
                        if qe_email and qe_email.lower() not in excl_emails:
                            mv, mcost = verify_mv(qe_email)
                            cost_here += mcost
                            spent_micro += mcost
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

                # Trykitt for catch-all / still missing
                need_tk = (not email) or (email_status in CATCH_ALL_MV)
                if need_tk and under_cap(7000):
                    try:
                        tk_email, tcost = find_trykitt(
                            lead["first_name"], lead["last_name"], d
                        )
                        cost_here += tcost
                        spent_micro += tcost
                        if tk_email and tk_email.lower() not in excl_emails:
                            # Trykitt find is pre-verified; still MV stamp
                            mv, mcost = verify_mv(tk_email)
                            cost_here += mcost
                            spent_micro += mcost
                            if mv in VALID_MV or mv in CATCH_ALL_MV or mv == "":
                                # accept trykitt hit; prefer MV ok
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
                        or email_source.startswith("trykitt")
                    )
                )
                # Prefer only MV ok for "ready" sendable; allow catch_all if trykitt
                if email_status in CATCH_ALL_MV and not email_source.startswith(
                    "trykitt"
                ):
                    ready = False

                row = {
                    **lead,
                    "campaign_id": camp["id"],
                    "offer": camp["offer"],
                    "email": email or None,
                    "email_status": email_status or None,
                    "email_source": email_source or None,
                    "batch_id": batch_id,
                    "plusvibe_ready": ready,
                    "spent_note": f"{cost_here/1e6:.4f}",
                }
                all_found.append(row)
                st["spent_usd"] += cost_here / 1_000_000
                if ready:
                    seen_domains.add(d)
                    excl_emails.add(email.lower())
                    st["ready"] += 1
                    ready_rows.append(row)
                    # incremental flush so kills don't lose progress
                    write_ready_csv(OUT_DIR / f"{batch_id}_ready.csv", ready_rows)
                    print(
                        f"  READY {camp['id']} {st['ready']}/{camp['soft_ready']} "
                        f"{email} {lead['company_name'][:40]} spent=${spent_micro/1e6:.4f}",
                        flush=True,
                    )

            nxt = ((data or {}).get("pagination") or {}).get("token")
            if not leads or not nxt:
                if st["band_i"] + 1 < len(camp["bands"]):
                    st["band_i"] += 1
                    st["token"] = None
                else:
                    st["exhausted"] = True
            else:
                st["token"] = nxt

            if spent_micro >= cap_micro:
                stop = True
                break

        if not progress:
            idle_rounds += 1
        else:
            idle_rounds = 0
        if all(state[c["id"]]["exhausted"] or state[c["id"]]["ready"] >= c["soft_ready"] for c in CAMPAIGNS):
            break

    end_bal = balance_usd()
    stats = {
        "batch_id": batch_id,
        "sheet_id": SHEET_ID,
        "confirm_spend_usd": confirm_spend,
        "effective_cap_usd": effective_cap,
        "start_balance_usd": start_bal,
        "end_balance_usd": end_bal,
        "spent_usd": round(spent_micro / 1_000_000, 6),
        "spent_from_balance_usd": round(start_bal - end_bal, 6),
        "ready_total": len(ready_rows),
        "found_total": len(all_found),
        "campaigns": {
            cid: {
                "ready": state[cid]["ready"],
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
        "email_order": [
            "pattern",
            "contactout.people.email.verify",
            "millionverifier.people.email.verify",
            "quickenrich.people.email.find",
            "trykitt.people.email.find",
        ],
    }
    ready_csv = OUT_DIR / f"{batch_id}_ready.csv"
    all_csv = OUT_DIR / f"{batch_id}_all.csv"
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
    args = p.parse_args()
    TOKEN = load_treg_token()
    run(args.confirm_spend)


if __name__ == "__main__":
    main()
