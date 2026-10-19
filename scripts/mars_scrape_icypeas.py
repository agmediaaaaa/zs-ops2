#!/usr/bin/env python3
"""MARS scrape: Icypeas people.search → Blitz email.find → Million Verifier.

Mirrors the Cheap Scrape (icypeas→blitz) path with MARS ICP filters across
4 segments and a <200 vs 200+ title split.

Gates:
  --scope-only          free Icypeas TAM counts only
  --pilot               ~10 ready × 4 segments (requires --confirm-spend)
  --full N              N ready total across streams (requires --confirm-spend)
  --confirm-spend USD   hard spend cap
  --upload-plusvibe     push ready CSV to PlusVibe campaign after scrape
  --skip-verify         skip Million Verifier (email_status=unverified)

Example:
  python scripts/mars_scrape_icypeas.py --scope-only
  python scripts/mars_scrape_icypeas.py --pilot --confirm-spend 1.00
  python scripts/mars_scrape_icypeas.py --full 2000 --confirm-spend 3.50 --upload-plusvibe
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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Absolute max Treg spend for any paid MARS run unless user explicitly overrides
# with a LOWER --confirm-spend. Never allow confirm-spend above this without
# changing HARD_SPEND_CAP_USD after user approval.
HARD_SPEND_CAP_USD = 2.00  # user-authorized hard cap for this run

# Abort a stream / run early when unit economics go bad (avoid tail spend for tiny yield).
MAX_SEARCH_ROWS_PER_READY = 12   # Cheap Scrape ~3–5; stop paging well before 12
MAX_EMAIL_ATTEMPTS_PER_READY = 4  # Cheap Scrape ~1.5–2; stop emailing past 4
MIN_CAND_YIELD = 0.04             # candidates / searched rows; below this after 2 pages → stop
RESERVE_USD = 0.05                # leave buffer; do not start new work under this remaining


TOKEN = (
    json.loads(Path.home().joinpath(".treg/config.json").read_text()).get("token")
    if Path.home().joinpath(".treg/config.json").exists()
    else None
) or os.environ.get("TREG_TOKEN") or os.environ.get("treg")

OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/mars-scrape"))
EXCLUDE_PATH = Path(
    os.environ.get("MARS_EXCLUDE_JSON", "/workspace/artifacts/mars-scrape/plusvibe_exclude.json")
)

PLUSVIBE_API_KEY = os.environ.get("PLUSVIBE_API_KEY", "")
PLUSVIBE_WORKSPACE_ID = os.environ.get("PLUSVIBE_WORKSPACE_ID", "6a8d53c5977bb5537e41fcf2")
# v3 Generic - all
PLUSVIBE_CAMPAIGN_ID = os.environ.get("PLUSVIBE_CAMPAIGN_ID", "6ac63d95542d3f7788938ecc")

CSUITE_TITLES = [
    "President",
    "Owner",
    "Co-Owner",
    "CEO",
    "Chief Executive Officer",
    "Founder",
    "Co-Founder",
]
OPS_TITLES = [
    "Plant Manager",
    "Director of Operations",
    "General Manager",
    "GM",
    "Operations Manager",
    "Operations Director",
    "Head of Operations",
    "Director of Manufacturing",
    "Production Manager",
    "Manufacturing Manager",
]

SHARED_KEYWORD_EXCLUDE = [
    "staffing",
    "recruiting",
    "recruitment",
    "staffing agency",
    "manufacturers rep",
    "manufacturer's rep",
    "sales agency",
    "consulting firm",
    "IT services",
    "software",
    "SaaS",
    "wholesale distributor",
    "bank",
    "financial services",
    "nonprofit",
    "university",
    "government",
]

# Pushed into Icypeas currentJobTitle.exclude BEFORE search (billed per row).
# Post-search TITLE_REJECT_RE stays as a free safety net for fuzzy matches.
TITLE_EXCLUDE = [
    "VP",
    "Vice President",
    "Assistant",
    "Sales",
    "Marketing",
    "Human Resources",
    "HR",
    "Engineer",
    "Engineering",
    "Quality",
    "Purchasing",
    "Supply Chain",
    "Machinist",
    "Welder",
    "Operator",
    "Technician",
    "Shop Floor",
    "Accounting",
    "Accountant",
    "Administrative",
    "Administrator",
    "Project Manager",
    "Product Manager",
    "CFO",
    "CTO",
    "CMO",
    "CIO",
    "Board Member",
    "Advisor",
    "Consultant",
    "Retired",
    "Former",
    "Intern",
    "Student",
]

TITLE_REJECT_RE = re.compile(
    r"("
    r"\bvp\b|vice[\s-]?president|assistant|"
    r"sales|marketing|human resources|\bhr\b|"
    r"engineer(?!ing manager)|engineering|"
    r"quality|purchasing|supply[\s-]?chain|"
    r"machinist|welder|operator|technician|shop[\s-]?floor|"
    r"accounting|accountant|admin(?:istrative|istrator)?|"
    r"project manager|product manager|"
    r"\bcfo\b|\bcto\b|\bcmo\b|\bcio\b|"
    r"board member|advisor|consultant|retired|former|"
    r"intern|student"
    r")",
    re.I,
)

# Hard junk that keyword search still returns (talent casting, apparel, SaaS, etc.)
GLOBAL_REJECT_RE = re.compile(
    r"("
    r"casting (director|partner|agency|call|couch)|talent casting|voice[\s-]?over|"
    r"actor|actress|film|tv production|entertainment|"
    r"software|saas|digital agency|marketing agency|staffing|recruit|"
    r"apparel|clothing|fashion|lingerie|honeylove|"
    r"wifi|hotel|coffee|sign(s)? & graphics|fleet supply|"
    r"crypto|bitcoin|foundry digital|web3|"
    r"consulting firm|it services|managed (it|services)|"
    r"sales agency|component sales|machine(?:ry)? sales|equipment (dealer|broker|sales)|"
    r"used (machinery|equipment)|machinery auction|"
    r"distributor(?!.*machin)|wholesale(?!.*machin)|"
    r"board chair|board member|advisory"
    r")",
    re.I,
)

INDUSTRIAL_HINT_RE = re.compile(
    r"("
    r"machin|cnc|mill|lathe|turn(?:ing)?|grind|edm|"
    r"foundry|casting|castings|forge|"
    r"sheet[\s-]?metal|fabricat|press brake|laser cut|"
    r"as.?9100|nadcap|aerospace|aircraft|turbine|"
    r"metal|steel|aluminum|iron|bronze|alloy|"
    r"manufactur|machine shop|job shop|tool(?:ing)?|die|"
    r"precision|component|parts"
    r")",
    re.I,
)

MFG_INDUSTRIES = [
    "Manufacturing",
    "Industrial Machinery Manufacturing",
    "Machinery Manufacturing",
    "Aviation and Aerospace Component Manufacturing",
    "Defense and Space Manufacturing",
    "Fabricated Metal Products",
    "Primary Metal Manufacturing",
    "Metalworking Machinery Manufacturing",
    "Shipbuilding",
]

CSUITE_KEEP_RE = re.compile(
    r"\b(ceo|chief executive|owner|co-?owner|founder|co-?founder|president)\b",
    re.I,
)
OPS_KEEP_RE = re.compile(
    r"("
    r"plant manager|director of operations|general manager|\bgm\b|"
    r"operations manager|operations director|dir(?:ector)?\.?\s+of\s+ops|"
    r"head of operations|director of manufacturing|production manager|"
    r"manufacturing manager"
    r")",
    re.I,
)

FREEMAIL = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "mail.com",
    "protonmail.com",
    "live.com",
    "msn.com",
    "me.com",
    "ymail.com",
}

MV_VALID = {"ok", "catch_all", "valid", "smtp_valid", "catch_all_valid", "good"}


def _streams(broad: bool = False) -> list[dict]:
    """Four MARS segments × csuite(<200) / ops(200+)."""
    specs = [
        {
            "seg": "S1",
            "name": "Precision CNC / machine shops",
            "emp_cs": (10, 199),
            "emp_ops": (200, 500),
            "keywords": (
                [
                    "CNC",
                    "CNC machining",
                    "precision machining",
                    "Swiss turning",
                    "5-axis",
                    "machine shop",
                    "job shop",
                    "contract machining",
                    "machining",
                    "screw machine",
                    "wire EDM",
                    "EDM",
                    "CNC mill",
                    "CNC turning",
                ]
                if broad
                else [
                    "CNC machining",
                    "precision machining",
                    "Swiss turning",
                    "5-axis machining",
                    "machine shop",
                    "job shop",
                    "contract machining",
                    "screw machine products",
                    "wire EDM",
                ]
            ),
            "exclude_extra": [],
            "accept_re": re.compile(
                r"cnc|precision machin|swiss turn|5[\s-]?axis|grind|"
                r"machine shop|job shop|contract machin|screw machine|wire edm|\bedm\b|machining",
                re.I,
            ),
            "reject_re": re.compile(
                r"staffing|recruit|sales agency|software|saas|consulting only",
                re.I,
            ),
        },
        {
            "seg": "S2",
            "name": "Foundries / metal casting",
            "emp_cs": (10, 199),
            "emp_ops": (200, 500),
            "keywords": (
                [
                    "foundry",
                    "metal casting",
                    "investment casting",
                    "sand casting",
                    "die casting",
                    "permanent mold",
                    "lost wax",
                    "aluminum casting",
                    "iron casting",
                    "steel casting",
                    "bronze casting",
                    "castings",
                ]
                if broad
                else [
                    "foundry",
                    "metal casting",
                    "investment casting",
                    "sand casting",
                    "die casting",
                    "permanent mold casting",
                    "lost wax casting",
                    "aluminum casting",
                    "iron casting",
                    "steel casting",
                    "bronze casting",
                ]
            ),
            "exclude_extra": ["scrap metal", "recycling", "foundry supply"],
            # Require metal/manufacturing casting context (blocks talent/"digital foundry")
            "accept_re": re.compile(
                r"("
                r"metal casting|iron casting|steel casting|aluminum casting|bronze casting|"
                r"investment casting|sand casting|die casting|permanent mold|lost wax|"
                r"gray iron|ductile iron|"
                r"(foundry).{0,60}(metal|iron|steel|aluminum|cast|pour|melt|mold|alloy|manufactur)|"
                r"(cast(?:ing|ings)?).{0,60}(foundry|metal|iron|steel|aluminum|manufactur|plant)"
                r")",
                re.I,
            ),
            "reject_re": re.compile(
                r"scrap metal|recycl|foundry supply|staffing|recruit|software|saas|"
                r"digital foundry|healthcare foundry|protein foundry|fierce foundry|"
                r"foundry\.(la|io)|talent|casting partner|knock\.com",
                re.I,
            ),
        },
        {
            "seg": "S3",
            "name": "AS9100 aerospace / turbine",
            "emp_cs": (10, 199),
            "emp_ops": (200, 500),
            "keywords": (
                [
                    "AS9100",
                    "aerospace machining",
                    "aerospace",
                    "aircraft parts",
                    "aircraft components",
                    "turbine components",
                    "jet engine",
                    "NADCAP",
                    "defense machining",
                ]
                if broad
                else [
                    "AS9100",
                    "aerospace machining",
                    "aircraft parts",
                    "aircraft components",
                    "turbine components",
                    "jet engine components",
                    "NADCAP",
                ]
            ),
            "exclude_extra": [],
            "accept_re": re.compile(
                r"as.?9100|nadcap|"
                r"aerospace machin|aircraft parts|aircraft components|"
                r"turbine components|jet engine components|"
                r"(aerospace|aircraft|turbine|jet engine).{0,160}(machin|cnc|mill|turn)|"
                r"(machin|cnc|mill|turn).{0,160}(aerospace|aircraft|turbine|jet engine|as.?9100|nadcap)",
                re.I,
            ),
            "reject_re": re.compile(
                r"staffing|recruit|software|saas|consulting only|"
                r"airline passenger|airport|airline spares",
                re.I,
            ),
        },
        {
            "seg": "S4",
            "name": "Sheet metal / fabrication",
            "emp_cs": (10, 199),
            "emp_ops": (200, 999),
            "keywords": (
                [
                    "sheet metal",
                    "sheet metal fabrication",
                    "precision sheet metal",
                    "metal fabrication",
                    "fabrication",
                    "press brake",
                    "laser cutting",
                    "CNC punching",
                    "welding fabrication",
                    "plate fabrication",
                ]
                if broad
                else [
                    "sheet metal fabrication",
                    "precision sheet metal",
                    "metal fabrication",
                    "press brake",
                    "laser cutting",
                    "CNC punching",
                    "welding and fabrication",
                ]
            ),
            "exclude_extra": ["HVAC", "roofing", "ductwork", "steel service center"],
            "accept_re": re.compile(
                r"sheet[\s-]?metal|precision sheet|metal fabricat|press brake|"
                r"laser cut|cnc punch|weld.{0,20}fabricat|fabricat",
                re.I,
            ),
            "reject_re": re.compile(
                r"\bhvac\b|roofing|ductwork|steel service|construction company|"
                r"mining|staffing|recruit|software|saas|fence|awning|enameling",
                re.I,
            ),
        },
    ]
    streams: list[dict] = []
    for s in specs:
        excl = SHARED_KEYWORD_EXCLUDE + s["exclude_extra"]
        for band, titles, (lo, hi), keep_re in (
            ("CS", CSUITE_TITLES, s["emp_cs"], CSUITE_KEEP_RE),
            ("OPS", OPS_TITLES, s["emp_ops"], OPS_KEEP_RE),
        ):
            streams.append(
                {
                    "id": f"{s['seg']}_{band}",
                    "seg": s["seg"],
                    "band": band,
                    "name": f"{s['name']} [{band} {lo}-{hi}]",
                    "keep_re": keep_re,
                    "accept_re": s["accept_re"],
                    "reject_re": s["reject_re"],
                    "emp_lo": lo,
                    "emp_hi": hi,
                    "query": {
                        # Include only ICP titles; exclude junk titles in-query so we
                        # do not pay for VP/Sales/HR/etc. rows Icypeas would otherwise return.
                        "currentJobTitle": {
                            "include": titles,
                            "exclude": TITLE_EXCLUDE,
                        },
                        "profileLocation": {"include": ["US"]},
                        "currentCompany.headcount": {">=": lo, "<=": hi},
                        "currentCompany.type": {"include": ["Privately Held", "Partnership"]},
                        # Industry left off the query (too restrictive vs TAM); enforced
                        # via INDUSTRIAL_HINT_RE + accept/reject post-filters instead.
                        "keyword": {"include": s["keywords"], "exclude": excl},
                    },
                }
            )
    return streams


STREAMS = _streams(False)


def website_exclude_list(domains: set[str] | list[str]) -> list[str]:
    """Normalize domains for Icypeas currentCompanyWebsite.exclude (bare host)."""
    out: list[str] = []
    seen: set[str] = set()
    for d in domains:
        host = norm_domain(d)
        if not host or host in FREEMAIL or host in seen:
            continue
        seen.add(host)
        out.append(host)
    return out


def with_website_excludes(query: dict, domains: list[str]) -> dict:
    """Inject company-website excludes into the Icypeas query BEFORE search.

    Icypeas bills per returned row — exclude in-query wherever possible:
      - currentJobTitle.include / .exclude  (set on stream queries)
      - currentCompanyWebsite.exclude       (PlusVibe company domains here)
      - keyword.exclude                     (set on stream queries)
    LinkedIn profileUrl is NOT a valid Icypeas people.search filter; those
    people are skipped post-search / pre-Blitz (free — no email spend).
    """
    q = json.loads(json.dumps(query))  # deep copy
    if domains:
        q["currentCompanyWebsite"] = {"exclude": domains}
    return q


def call(
    endpoint: str,
    body: dict | None = None,
    method: str | None = None,
    query: dict | None = None,
) -> tuple[dict, int]:
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"X-Treg-Token": TOKEN, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if "email.find" in endpoint:
        hdrs["X-Treg-Route-Max-Cost"] = "0.01"
        hdrs["X-Treg-Route-Waterfall"] = "0"
        hdrs["X-Treg-Route-Exclude"] = "aiark"
    verb = method or ("POST" if body is not None else "GET")
    url = f"https://treg.to/call/{endpoint}"
    if query:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(query)}"
        verb = method or "GET"
        data = None
    req = urllib.request.Request(url, data=data, method=verb, headers=hdrs)
    with urllib.request.urlopen(req, timeout=120) as resp:
        cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
        raw = resp.read()
        return (json.loads(raw.decode()) if raw else {}), cost


def norm_linkedin(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    if "?" in u:
        u = u.split("?", 1)[0]
    return u


def norm_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    if not d:
        return ""
    if "://" not in d:
        d = "http://" + d
    try:
        host = urlparse(d).hostname or ""
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def load_excludes() -> dict[str, set[str]]:
    emails: set[str] = set()
    linkedins: set[str] = set()
    domains: set[str] = set()
    if EXCLUDE_PATH.exists():
        data = json.loads(EXCLUDE_PATH.read_text())
        emails = {e.strip().lower() for e in data.get("emails") or [] if e}
        linkedins = {norm_linkedin(x) for x in data.get("linkedins") or [] if x}
        domains = {norm_domain(x) for x in data.get("domains") or [] if x}
        domains -= FREEMAIL
    return {"emails": emails, "linkedins": linkedins, "domains": domains}


def title_ok(title: str, keep_re: re.Pattern) -> bool:
    t = title or ""
    if not t.strip():
        return False
    if TITLE_REJECT_RE.search(t):
        return False
    return bool(keep_re.search(t))


def emp_ok(n, lo: int, hi: int) -> bool:
    try:
        n = int(n)
    except Exception:
        return True  # keep if unknown; band already in query
    return lo <= n <= hi


def lead_blob(L: dict) -> str:
    return " ".join(
        str(x or "")
        for x in [
            L.get("firstname"),
            L.get("lastname"),
            L.get("headline"),
            L.get("lastJobTitle"),
            L.get("lastCompanyName"),
            L.get("lastCompanyWebsite"),
            L.get("lastCompanyDescription"),
            L.get("lastCompanyIndustry"),
        ]
    )


def extract_email(eout: dict) -> str | None:
    if not isinstance(eout, dict):
        return None
    email = eout.get("email")
    if email:
        return str(email).strip().lower()
    for item in eout.get("all_emails") or []:
        if isinstance(item, dict) and item.get("email"):
            return str(item["email"]).strip().lower()
        if isinstance(item, str) and "@" in item:
            return item.strip().lower()
    return None


def scope_only(broad: bool = False) -> None:
    global STREAMS
    STREAMS = _streams(broad=broad)
    excl = load_excludes()
    site_excl = website_exclude_list(excl["domains"])
    print(f"=== FREE TAM (icypeas.people.search.count) — MARS [{'BROAD' if broad else 'precise'}] ===")
    print(f"In-query website excludes: {len(site_excl)} (from PlusVibe domains)")
    print(f"LinkedIn pre-email skips: {len(excl['linkedins'])} (not an Icypeas query field)")
    total = 0
    total_raw = 0
    for s in STREAMS:
        raw, cost = call("icypeas.people.search.count", {"query": s["query"]})
        assert cost == 0, cost
        q = with_website_excludes(s["query"], site_excl)
        out, cost = call("icypeas.people.search.count", {"query": q})
        assert cost == 0, cost
        n_raw = raw.get("total") or 0
        n = out.get("total") or 0
        total_raw += n_raw
        total += n
        print(f"  {s['id']:12} {n:>7,}  (raw {n_raw:,})  {s['name']}")
    print(f"TOTAL with website exclude: {total:,}  (raw {total_raw:,})")
    print()
    est = total * 0.00038 + min(total, 2000) * 0.0015  # search upper + email attempts
    print(f"Rough spend upper-bound if searching full TAM then emailing: ~${est:.2f}")
    print(f"HARD_SPEND_CAP_USD=${HARD_SPEND_CAP_USD:.2f} — confirm before paid run")
    print(f"PlusVibe exclude loaded from: {EXCLUDE_PATH} (exists={EXCLUDE_PATH.exists()})")


def plusvibe_upload(rows: list[dict], batch_size: int = 50) -> dict:
    if not PLUSVIBE_API_KEY:
        raise RuntimeError("PLUSVIBE_API_KEY missing")
    added = skipped = errors = 0
    details = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        leads = []
        for r in batch:
            first, last = "", ""
            name = (r.get("name") or "").strip()
            if " " in name:
                first, last = name.split(" ", 1)
            else:
                first = name
            leads.append(
                {
                    "email": r["email"],
                    "first_name": first,
                    "last_name": last,
                    "company_name": r.get("company_name") or "",
                    "company_website": r.get("company_website") or "",
                    "linkedin_person_url": r.get("person_linkedin") or "",
                    "linkedin_company_url": r.get("company_linkedin") or "",
                    "job_title": r.get("job_title") or "",
                    "custom_variables": {
                        "company_description": (r.get("company_desc") or "")[:1500],
                        "employee_count": str(r.get("employee_count") or ""),
                        "mars_seg": r.get("seg") or "",
                        "mars_band": r.get("band") or "",
                        "location": r.get("location") or "",
                        "industry": r.get("company_industry") or "",
                    },
                }
            )
        payload = {
            "workspace_id": PLUSVIBE_WORKSPACE_ID,
            "campaign_id": PLUSVIBE_CAMPAIGN_ID,
            "skip_if_in_workspace": True,
            "skip_lead_in_active_pause_camp": True,
            "resume_camp_if_completed": True,
            "leads": leads,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://api.plusvibe.ai/api/v1/lead/add",
            data=data,
            method="POST",
            headers={
                "x-api-key": PLUSVIBE_API_KEY,
                "Content-Type": "application/json",
                "User-Agent": "zs-ops-mars-scrape/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:500]
            errors += len(batch)
            details.append({"batch": i // batch_size, "error": err})
            print(f"  upload batch {i // batch_size} HTTP {e.code}: {err}")
            continue
        # response shapes vary; count best-effort
        if isinstance(body, dict):
            added += int(body.get("added") or body.get("success_count") or len(batch))
            skipped += int(body.get("skipped") or body.get("skip_count") or 0)
        else:
            added += len(batch)
        details.append({"batch": i // batch_size, "response": body})
        print(f"  uploaded batch {i // batch_size}: +{len(batch)}")
        time.sleep(0.25)
    return {"added": added, "skipped": skipped, "errors": errors, "details": details}


def run(ready_target: int, hard_cap: float, verify: bool, upload: bool, broad: bool = False) -> None:
    global STREAMS
    STREAMS = _streams(broad=broad)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excl = load_excludes()
    print(f"Mode: {'BROAD' if broad else 'precise'} | streams={len(STREAMS)}")
    print(
        f"Excludes: emails={len(excl['emails'])} linkedin={len(excl['linkedins'])} "
        f"domains={len(excl['domains'])}"
    )
    spend_micro = 0
    rows: list[dict] = []
    # Person-level suppress only (email + LinkedIn). Domains are batch-deduped.
    seen_li: set[str] = set(excl["linkedins"])
    seen_email: set[str] = set(excl["emails"])
    seen_domain: set[str] = set()
    camps: list[dict] = []
    progress_path = OUT_DIR / "progress.json"

    # Seed prior pilot/volume CSVs so we don't re-pay for the same people
    for csv_path in Path("/workspace/artifacts/mars-scrape").rglob("*ready.csv"):
        try:
            with open(csv_path, newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("person_linkedin"):
                        seen_li.add(norm_linkedin(r["person_linkedin"]))
                    if r.get("email"):
                        seen_email.add(r["email"].strip().lower())
        except Exception as e:
            print(f"  seed skip {csv_path}: {e}")
    print(
        f"After seed: seen_li={len(seen_li)} seen_email={len(seen_email)} "
        f"(batch domain dedupe ON)"
    )
    # In-query Icypeas exclude — do not pay search rows for known company websites
    site_excl = website_exclude_list(excl["domains"])
    print(f"Icypeas currentCompanyWebsite.exclude: {len(site_excl)} domains")
    print(f"LinkedIn skip before Blitz (post-search): {len(seen_li)}")

    def pay(endpoint, body=None, query=None, method=None, fallback_cost_micro: int = 0):
        nonlocal spend_micro
        if spend_micro / 1e6 >= hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} reached")
        out, cost = call(endpoint, body=body, query=query, method=method)
        if cost <= 0 and fallback_cost_micro:
            cost = fallback_cost_micro
        spend_micro += cost
        if spend_micro / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded (spent ${spend_micro/1e6:.4f})")
        return out

    def save_progress(extra: dict | None = None):
        payload = {
            "at": datetime.now(timezone.utc).isoformat(),
            "ready": len(rows),
            "spend_usd": round(spend_micro / 1e6, 6),
            "hard_cap_usd": hard_cap,
            "target": ready_target,
            **(extra or {}),
        }
        progress_path.write_text(json.dumps(payload, indent=2))

    print("=== FREE TAM (with website excludes in query) ===")
    tam = {}
    for s in STREAMS:
        q = with_website_excludes(s["query"], site_excl)
        out = pay("icypeas.people.search.count", {"query": q})
        tam[s["id"]] = out.get("total") or 0
        print(f"  {s['id']}: {tam[s['id']]:,}")

    # Round-robin across streams so we don't exhaust one vertical first
    per_stream_target = max(1, ready_target // len(STREAMS))
    remainder = ready_target - per_stream_target * len(STREAMS)

    for idx, s in enumerate(STREAMS):
        if len(rows) >= ready_target:
            break
        want = per_stream_target + (1 if idx < remainder else 0)
        # allow overshoot buffer on later streams if earlier under-delivered
        want = max(want, ready_target - len(rows) - (len(STREAMS) - idx - 1) * max(1, per_stream_target // 2))
        want = min(want, ready_target - len(rows))
        if want <= 0:
            continue

        remaining = hard_cap - spend_micro / 1e6
        if remaining <= RESERVE_USD:
            print(
                f"\nSTOP: remaining ${remaining:.4f} <= reserve ${RESERVE_USD} "
                f"(ready={len(rows)}) — skip further streams"
            )
            break

        print(f"\n--- {s['id']} {s['name']} (want {want}) rem=${remaining:.3f} ---")
        candidates: list[dict] = []
        token = None
        searched = 0
        pages = 0
        stream_start_micro = spend_micro
        abort_reason = ""

        # Keep search spend tight: don't page the entire TAM when want is inflated.
        cand_goal = min(max(want * 2, 20), 80)
        max_pages = 8  # <= 400 search rows / stream
        q = with_website_excludes(s["query"], site_excl)
        while pages < max_pages and len(candidates) < cand_goal:
            if hard_cap - spend_micro / 1e6 <= RESERVE_USD:
                abort_reason = "reserve"
                break
            body: dict = {"query": q, "pagination": {"size": 50}}
            if token:
                body["pagination"]["token"] = token
            try:
                out = pay("icypeas.people.search", body)
            except (RuntimeError, urllib.error.HTTPError) as e:
                print(f"  search stop: {e}")
                abort_reason = "cap/search"
                break
            leads = out.get("leads") or []
            pages += 1
            searched += len(leads)
            if not leads:
                break
            for L in leads:
                title = L.get("lastJobTitle") or L.get("headline") or ""
                if not title_ok(title, s["keep_re"]):
                    continue
                if not emp_ok(L.get("lastCompanySize"), s["emp_lo"], s["emp_hi"]):
                    continue
                blob = lead_blob(L)
                if GLOBAL_REJECT_RE.search(blob) or s["reject_re"].search(blob):
                    continue
                if not s["accept_re"].search(blob):
                    continue
                if not INDUSTRIAL_HINT_RE.search(blob):
                    continue
                li = norm_linkedin(L.get("profileUrl") or "")
                if not li or li in seen_li:
                    continue
                dom = norm_domain(L.get("lastCompanyWebsite") or "")
                if dom and (dom in seen_domain or dom in excl["domains"]):
                    continue
                candidates.append(L)
                if len(candidates) >= cand_goal:
                    break
            # Early abort: bad candidate yield after enough pages — don't keep paying for junk
            if pages >= 2 and searched >= 80:
                yield_rate = len(candidates) / max(searched, 1)
                if yield_rate < MIN_CAND_YIELD:
                    abort_reason = f"low_cand_yield={yield_rate:.3f}"
                    print(
                        f"  search abort: {abort_reason} "
                        f"(cand={len(candidates)} searched={searched})"
                    )
                    break
            token = (out.get("pagination") or {}).get("token")
            if not token or len(candidates) >= cand_goal:
                break
            time.sleep(0.08)

        ready_here: list[dict] = []
        attempts = hits = pv_skip = freemail_skip = mv_fail = 0
        miss_streak = 0
        for L in candidates:
            if len(ready_here) >= want or len(rows) >= ready_target:
                break
            if hard_cap - spend_micro / 1e6 <= RESERVE_USD:
                abort_reason = abort_reason or "reserve"
                break
            # Stop emailing if attempts/ready blows past Cheap Scrape range
            if ready_here and attempts / max(len(ready_here), 1) > MAX_EMAIL_ATTEMPTS_PER_READY:
                abort_reason = f"email_attempts_per_ready={attempts/len(ready_here):.1f}"
                print(f"  email abort: {abort_reason}")
                break
            if not ready_here and attempts >= 12:
                abort_reason = "no_email_hits_after_12"
                print(f"  email abort: {abort_reason}")
                break
            if miss_streak >= 10 and len(ready_here) < 3:
                abort_reason = f"miss_streak={miss_streak}"
                print(f"  email abort: {abort_reason}")
                break
            li = norm_linkedin(L.get("profileUrl") or "")
            if not li or li in seen_li:
                continue
            attempts += 1
            try:
                eout = pay("blitzapi.people.email.find", {"person_linkedin_url": li})
            except (RuntimeError, urllib.error.HTTPError) as e:
                print(f"  email stop: {e}")
                abort_reason = "cap/email"
                break
            email = extract_email(eout)
            if not email or "@" not in email:
                miss_streak += 1
                time.sleep(0.05)
                continue
            hits += 1
            domain = email.split("@", 1)[1]
            if domain in FREEMAIL:
                freemail_skip += 1
                miss_streak += 1
                continue
            if email in seen_email:
                pv_skip += 1
                miss_streak += 1
                continue
            if domain in seen_domain:
                pv_skip += 1
                miss_streak += 1
                continue

            mv_status = "unverified"
            if verify:
                try:
                    mv = pay(
                        "millionverifier.people.email.verify",
                        query={"email": email},
                        method="GET",
                        fallback_cost_micro=1780,
                    )
                    mv_status = str(mv.get("result") or "").lower()
                    if mv_status not in MV_VALID:
                        mv_fail += 1
                        miss_streak += 1
                        time.sleep(0.05)
                        continue
                except RuntimeError as e:
                    print(f"  mv/cap stop: {e}")
                    abort_reason = "cap/mv"
                    break
                except urllib.error.HTTPError as e:
                    print(f"  mv http {e.code}, skipping email")
                    mv_fail += 1
                    miss_streak += 1
                    time.sleep(0.05)
                    continue

            row = {
                "seg": s["seg"],
                "band": s["band"],
                "stream_id": s["id"],
                "stream_name": s["name"],
                "name": f"{L.get('firstname') or ''} {L.get('lastname') or ''}".strip(),
                "job_title": L.get("lastJobTitle") or L.get("headline"),
                "employee_count": L.get("lastCompanySize"),
                "company_desc": (L.get("lastCompanyDescription") or "")[:800],
                "email": email,
                "email_status": mv_status,
                "location": L.get("address") or L.get("lastCompanyAddress"),
                "company_name": L.get("lastCompanyName"),
                "company_website": L.get("lastCompanyWebsite"),
                "company_industry": L.get("lastCompanyIndustry"),
                "person_linkedin": li,
                "company_linkedin": L.get("lastCompanyUrl"),
            }
            ready_here.append(row)
            rows.append(row)
            seen_li.add(li)
            seen_email.add(email)
            if domain:
                seen_domain.add(domain)
            miss_streak = 0
            print(
                f"  ✓ [{len(rows)}/{ready_target}] {row['name']} <{email}> "
                f"| {row['job_title']} @ {row['company_name']}"
            )
            save_progress({"last_stream": s["id"]})
            time.sleep(0.06)

        stream_spend = (spend_micro - stream_start_micro) / 1e6
        # If this stream burned budget for almost nothing, note it (already aborted above)
        if ready_here and searched / max(len(ready_here), 1) > MAX_SEARCH_ROWS_PER_READY:
            print(
                f"  warn: search_rows/ready="
                f"{searched/len(ready_here):.1f} (>{MAX_SEARCH_ROWS_PER_READY})"
            )

        camps.append(
            {
                "id": s["id"],
                "tam": tam[s["id"]],
                "searched": searched,
                "candidates": len(candidates),
                "email_attempts": attempts,
                "email_hits": hits,
                "pv_skipped": pv_skip,
                "freemail_skipped": freemail_skip,
                "mv_fail": mv_fail,
                "ready": len(ready_here),
                "stream_spend_usd": round(stream_spend, 6),
                "abort_reason": abort_reason or None,
            }
        )
        print(
            f"  stream done: ready={len(ready_here)} searched={searched} "
            f"candidates={len(candidates)} email_hit={hits}/{attempts} "
            f"pv_skip={pv_skip} spend=${stream_spend:.4f}"
            + (f" abort={abort_reason}" if abort_reason else "")
        )

    spend = spend_micro / 1e6
    ready_n = max(len(rows), 1)
    searched_total = sum(c["searched"] for c in camps)
    attempts_total = sum(c["email_attempts"] for c in camps)
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "client": "MARS",
        "campaign": "v3 Generic - all",
        "campaign_id": PLUSVIBE_CAMPAIGN_ID,
        "workspace_id": PLUSVIBE_WORKSPACE_ID,
        "hard_cap_usd": hard_cap,
        "spend_usd": round(spend, 6),
        "verify": verify,
        "tam": tam,
        "tam_total": sum(tam.values()),
        "streams": camps,
        "ready_total": len(rows),
        "target": ready_target,
        "excludes": {
            "emails": len(excl["emails"]),
            "linkedins": len(excl["linkedins"]),
            "domains": len(excl["domains"]),
        },
        "unit_economics": {
            "cost_per_ready_usd": round(spend / ready_n, 6),
            "cost_per_1k_ready_usd": round(spend / ready_n * 1000, 2),
            "search_rows_per_ready": round(searched_total / ready_n, 2),
            "email_attempts_per_ready": round(attempts_total / ready_n, 2),
        },
    }

    cols = [
        "seg",
        "band",
        "stream_id",
        "stream_name",
        "name",
        "job_title",
        "employee_count",
        "company_desc",
        "email",
        "email_status",
        "location",
        "company_name",
        "company_website",
        "company_industry",
        "person_linkedin",
        "company_linkedin",
    ]
    csv_path = OUT_DIR / ("pilot-ready.csv" if ready_target <= 50 else "volume-ready.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    if upload and rows:
        print("\n=== PlusVibe upload (v3 Generic - all) ===")
        up = plusvibe_upload(rows)
        report["plusvibe_upload"] = {k: up[k] for k in ("added", "skipped", "errors")}
        (OUT_DIR / "plusvibe-upload.json").write_text(json.dumps(up, indent=2, default=str))

    report_path = OUT_DIR / ("pilot-report.json" if ready_target <= 50 else "volume-report.json")
    # omit full rows from report to keep file smaller; CSV is source of truth
    report_path.write_text(json.dumps(report, indent=2))
    save_progress({"done": True, "csv": str(csv_path)})
    print(json.dumps({k: report[k] for k in ("spend_usd", "ready_total", "tam_total", "unit_economics")}, indent=2))
    print(f"CSV: {csv_path}")
    print(f"Report: {report_path}")


def main() -> None:
    if not TOKEN:
        print("Missing TREG_TOKEN / ~/.treg/config.json", file=sys.stderr)
        sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-only", action="store_true")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--full", type=int, default=0, help="total ready target")
    ap.add_argument("--confirm-spend", type=float, default=None)
    ap.add_argument("--upload-plusvibe", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--broad", action="store_true", help="wider keywords for fill-up volume")
    args = ap.parse_args()
    if args.scope_only:
        scope_only(broad=args.broad)
        return
    if args.pilot or args.full:
        if args.confirm_spend is None:
            print("Paid run requires --confirm-spend USD", file=sys.stderr)
            sys.exit(2)
        if args.confirm_spend > HARD_SPEND_CAP_USD:
            print(
                f"Refusing --confirm-spend ${args.confirm_spend:.2f}: "
                f"HARD_SPEND_CAP_USD=${HARD_SPEND_CAP_USD:.2f}. "
                "Ask the user before raising the cap.",
                file=sys.stderr,
            )
            sys.exit(2)
        ready = 40 if args.pilot else args.full
        run(
            ready_target=ready,
            hard_cap=args.confirm_spend,
            verify=not args.skip_verify,
            upload=args.upload_plusvibe,
            broad=args.broad,
        )
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
