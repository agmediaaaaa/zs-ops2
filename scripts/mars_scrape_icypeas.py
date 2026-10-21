#!/usr/bin/env python3
"""MARS (CL-5) broad manufacturing list: Icypeas → Blitz.

Gates:
  --scope-only          free Icypeas TAM counts only
  --pull N              Pull-N people (requires --confirm-spend)
  --confirm-spend USD   hard spend cap
  --exclude-json PATH   {emails,linkedin,domains} for in-query + pre-Blitz skip

Default pathway: icypeas.people.search → blitzapi.people.email.find
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TOKEN = (
    json.loads(Path.home().joinpath(".treg/config.json").read_text()).get("token")
    if Path.home().joinpath(".treg/config.json").exists()
    else None
) or os.environ.get("TREG_TOKEN") or os.environ.get("treg")

OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/mars-broad-scope"))

# --- ICP (MARS broad) -------------------------------------------------------

TITLES_INCLUDE = [
    "Owner",
    "Co-Owner",
    "Founder",
    "Co-Founder",
    "CEO",
    "President",
    "COO",
    "General Manager",
    "Plant Manager",
    "Operations Manager",
    "Production Manager",
    "Director of Operations",
    "Director of Manufacturing",
    "VP of Operations",
    "VP Manufacturing",
    "Vice President of Operations",
    "Vice President of Manufacturing",
]

TITLE_EXCLUDE = [
    "VP",
    "Vice President",
    "Assistant",
    "Sales",
    "Marketing",
    "HR",
    "Engineer",
    "Intern",
    "Student",
    "Retired",
    "Former",
    "Consultant",
    "Advisor",
    "Board Member",
    "Human",
    "People",
    "Financial",
    "CFO",
    "CTO",
    "Technology",
    "Investor",
    "Project",
    "Quality",
    "Buyer",
    "Purchasing",
    "Supervisor",
    "Technician",
    "Machinist",
    "Operator",
    "Regional",
    "Business Development",
]

# Note: VP of Ops / VP Manufacturing are in include; broad "VP"/"Vice President"
# excludes will also drop them in-query. Keep include list for clarity; safety net
# TITLE_OK_RE allows those two VP variants locally if needed. Prefer tightening
# title exclude to not use bare "VP" if VP Ops/Mfg are required — see query builder.

TITLE_EXCLUDE_KEEP_VP_OPS = [
    "Assistant",
    "Sales",
    "Marketing",
    "HR",
    "Engineer",
    "Intern",
    "Student",
    "Retired",
    "Former",
    "Consultant",
    "Advisor",
    "Board Member",
    "Human",
    "People",
    "Financial",
    "CFO",
    "CTO",
    "Technology",
    "Investor",
    "Project",
    "Quality",
    "Buyer",
    "Purchasing",
    "Supervisor",
    "Technician",
    "Machinist",
    "Operator",
    "Regional",
    "Business Development",
    "VP of Sales",
    "Vice President of Sales",
    "VP Sales",
    "VP Marketing",
    "VP of Marketing",
    "VP of Engineering",
    "Vice President of Engineering",
    # Pilot soft-miss tighten (Cost Accounting Ops Mgr, Auctions SVP, etc.)
    "Accounting",
    "Cost Accounting",
    "Auction",
    "Auctions",
    "Appraisal",
    "Product Development",
    "Supply Chain",
]

INDUSTRIES = [
    "Machinery Manufacturing",
    "Industrial Machinery Manufacturing",
    "Automation Machinery Manufacturing",
    "Fabricated Metal Products",
    "Primary Metal Manufacturing",
    "Aviation and Aerospace Component Manufacturing",
    "Defense and Space Manufacturing",
    "Motor Vehicle Parts Manufacturing",
    "Transportation Equipment Manufacturing",
    "Plastics Manufacturing",
    "Rubber Products Manufacturing",
    "Electrical Equipment Manufacturing",
    "Computers and Electronics Manufacturing",
    "Semiconductor Manufacturing",
    "Medical Equipment Manufacturing",
    # Dropped bare "Manufacturing" — let food/gaming/general mfg bleed through pilot
]

INDUSTRY_EXCLUDE = [
    "Staffing and Recruiting",
    "Business Consulting and Services",
    "Non-profit Organizations",
    "Wholesale",
    "Retail",
    "Software Development",
    "IT Services and IT Consulting",
    "Food and Beverage Manufacturing",
    "Food Production",
    "Food & Beverages",
    "Restaurants",
    "Gambling Facilities and Casinos",
]

KEYWORDS_INCLUDE = [
    "CNC machining",
    "precision machining",
    "machine shop",
    "contract manufacturing",
    "metal fabrication",
    "sheet metal",
    "foundry",
    "metal casting",
    "forging",
    "stamping",
    "injection molding",
    "welding",
    "AS9100",
    "ISO 9001",
    "OEM components",
]

KEYWORDS_EXCLUDE = [
    "staffing",
    "recruiting",
    "consulting",
    "distributor",
    "wholesale",
    "retail",
    "software",
    "SaaS",
    "reseller",
    "dealer",
    "nonprofit",
    "non-profit",
    "3D printing service",
    "marketplace",
    # Pilot soft-miss tighten
    "auction",
    "appraisal",
    "liquidation",
    "asset disposition",
    "capital recovery",
    "food",
    "beverage",
    "nutrition",
    "dessert",
    "restaurant",
    "gaming",
    "bingo",
    "pull tabs",
    "charitable gaming",
    "used equipment",
    "used machinery",
    "used injection",
    "buying and selling",
]


def base_query(**extra) -> dict:
    q: dict = {
        "currentJobTitle": {
            "include": TITLES_INCLUDE,
            "exclude": TITLE_EXCLUDE_KEEP_VP_OPS,
        },
        "profileLocation": {"include": ["US"]},
        "currentCompany.location": {"include": ["US"]},
        "currentCompany.headcount": {">=": 10, "<=": 1000},
    }
    q.update(extra)
    return q


def slices() -> list[dict]:
    """Dual slices for broad TAM (industry OR keyword path). Overlap possible."""
    return [
        {
            "id": "MARS-ind",
            "label": "industry include + kw/industry exclude",
            "query": base_query(
                **{
                    "currentCompany.industry": {
                        "include": INDUSTRIES,
                        "exclude": INDUSTRY_EXCLUDE,
                    },
                    "keyword": {"exclude": KEYWORDS_EXCLUDE},
                }
            ),
        },
        {
            "id": "MARS-kw",
            "label": "keyword include + exclude (no industry gate)",
            "query": base_query(
                keyword={
                    "include": KEYWORDS_INCLUDE,
                    "exclude": KEYWORDS_EXCLUDE,
                },
                **{
                    "currentCompany.industry": {"exclude": INDUSTRY_EXCLUDE},
                },
            ),
        },
        {
            "id": "MARS-and",
            "label": "industry AND keyword (tight)",
            "query": base_query(
                **{
                    "currentCompany.industry": {
                        "include": INDUSTRIES,
                        "exclude": INDUSTRY_EXCLUDE,
                    },
                    "keyword": {
                        "include": KEYWORDS_INCLUDE,
                        "exclude": KEYWORDS_EXCLUDE,
                    },
                }
            ),
        },
    ]


def call(endpoint: str, body: dict | None = None) -> tuple[dict, int]:
    if not TOKEN:
        raise RuntimeError("Missing Treg token (~/.treg/config.json or TREG_TOKEN)")
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"X-Treg-Token": TOKEN, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if "email.find" in endpoint:
        hdrs["X-Treg-Route-Max-Cost"] = "0.01"
        hdrs["X-Treg-Route-Waterfall"] = "0"
        hdrs["X-Treg-Route-Exclude"] = "aiark,icypeas"
    req = urllib.request.Request(
        f"https://treg.to/call/{endpoint}",
        data=data,
        method="POST" if body is not None else "GET",
        headers=hdrs,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
        raw = resp.read()
        return (json.loads(raw.decode()) if raw else {}), cost


def norm_li(u: str) -> str:
    return (u or "").lower().split("?")[0].rstrip("/")


def load_exclude(path: str | None) -> tuple[set[str], set[str], list[str]]:
    if not path:
        return set(), set(), []
    data = json.loads(Path(path).read_text())
    emails = {e.lower().strip() for e in data.get("emails") or [] if e}
    linkedin = {norm_li(u) for u in data.get("linkedin") or [] if u}
    domains = sorted({d.lower().strip() for d in data.get("domains") or [] if d and "." in d})
    return emails, linkedin, domains


def with_domain_exclude(query: dict, domains: list[str], max_domains: int) -> dict:
    q = json.loads(json.dumps(query))
    if domains:
        q["currentCompanyWebsite"] = {"exclude": domains[:max_domains]}
    return q


FREEMAIL = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "protonmail.com", "live.com", "msn.com")


def title_ok(title: str) -> bool:
    """Safety net — ICP titles only; allow VP Ops / VP Manufacturing."""
    t = (title or "").lower()
    hard_reject = (
        "assistant",
        "intern",
        "student",
        "recruit",
        "sales",
        "marketing",
        "machinist",
        "technician",
        "purchasing",
        "buyer",
        "cfo",
        "cto",
        "accounting",
        "auction",
        "appraisal",
        "product development",
        "supply chain",
    )
    if any(x in t for x in hard_reject):
        # still allow pure VP Ops / VP Mfg if somehow combined (rare)
        if not (
            ("vp of operations" in t or "vice president of operations" in t or "vp manufacturing" in t
             or "vice president of manufacturing" in t or "vp of manufacturing" in t)
            and "sales" not in t
            and "accounting" not in t
            and "auction" not in t
            and "supply chain" not in t
            and "product development" not in t
        ):
            return False
    needles = (
        "owner",
        "founder",
        "ceo",
        "president",
        "coo",
        "general manager",
        "plant manager",
        "operations manager",
        "production manager",
        "director of operations",
        "director of manufacturing",
        "vp of operations",
        "vp manufacturing",
        "vice president of operations",
        "vice president of manufacturing",
        "vp operations",
        "vp of manufacturing",
    )
    return any(n in t for n in needles)


def emp_ok(n) -> bool:
    try:
        n = int(n)
        return 10 <= n <= 1000
    except Exception:
        return False


def bare_domain(url: str) -> str:
    u = (url or "").lower().strip()
    u = u.replace("https://", "").replace("http://", "")
    if u.startswith("www."):
        u = u[4:]
    return u.split("/")[0].split("?")[0]


def run_pull(
    pull: int,
    hard_cap: float,
    exclude_path: str | None,
    max_domains: int,
    slice_ids: list[str] | None = None,
) -> dict:
    """Pull-N from Icypeas (MARS-and by default), Blitz email.find, abort at hard_cap."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excl_emails, excl_li, excl_domains = load_exclude(exclude_path)
    seen_li = set(excl_li)
    seen_email = set(excl_emails)
    domain_set = set(excl_domains)
    spend_micro = 0
    search_rows = 0
    email_attempts = 0
    email_hits = 0
    freemail = 0
    skipped_known = 0
    title_emp_fail = 0
    no_desc = 0
    ready: list[dict] = []

    want = set(slice_ids) if slice_ids else {"MARS-and"}
    active = [s for s in slices() if s["id"] in want]
    if not active:
        raise SystemExit(f"No matching slices for {want}")

    def pay(endpoint: str, body: dict) -> dict:
        nonlocal spend_micro
        if spend_micro / 1e6 >= hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} reached")
        if endpoint == "icypeas.people.search":
            size = int(((body or {}).get("pagination") or {}).get("size") or 0)
            projected = spend_micro / 1e6 + size * 0.00038
            if size and projected > hard_cap:
                raise RuntimeError(
                    f"hard cap ${hard_cap} would be exceeded by next page "
                    f"(projected ${projected:.4f} for size={size})"
                )
        out, cost = call(endpoint, body)
        spend_micro += cost
        if spend_micro / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded (spent ${spend_micro/1e6:.4f})")
        return out

    print(f"Exclude: emails={len(excl_emails)} linkedin={len(excl_li)} domains={len(excl_domains)}")
    print(f"Pull-N={pull} hard_cap=${hard_cap} slices={[s['id'] for s in active]}")
    print("=== FREE TAM ===")
    tam: dict[str, int] = {}
    for sl in active:
        q = with_domain_exclude(sl["query"], excl_domains, max_domains)
        out = pay("icypeas.people.search.count", {"query": q})
        tam[sl["id"]] = out.get("total") or 0
        print(f"  {sl['id']}: {tam[sl['id']]:,}")
        time.sleep(0.5)

    # Pull fixed N people (not until N ready). Icypeas pagination.size max 200.
    page_size = min(200, max(pull, 25))
    max_pages = max(30, (pull // 50) + 40)  # enough headroom for known-LI skips
    candidates: list[dict] = []
    for sl in active:
        if len(candidates) >= pull:
            break
        q = with_domain_exclude(sl["query"], excl_domains, max_domains)
        token = None
        pages = 0
        while len(candidates) < pull and pages < max_pages:
            need = pull - len(candidates)
            size = min(page_size, max(need, 25))
            # keep budget for Blitz: leave room for ~need * blitz unit on successes
            spend_now = spend_micro / 1e6
            blitz_reserve = min(need, pull - len(candidates)) * 0.000495
            if spend_now + size * 0.00038 + blitz_reserve > hard_cap:
                # shrink page if possible
                room = hard_cap - spend_now - blitz_reserve
                size = max(0, int(room / 0.00038))
                if size < 1:
                    print(f"  stop/search: reserve for Blitz would exceed cap (spend=${spend_now:.4f})")
                    break
                size = min(size, page_size, need)
            body: dict = {"query": q, "pagination": {"size": size}}
            if token:
                body["pagination"]["token"] = token
            try:
                out = pay("icypeas.people.search", body)
            except RuntimeError as e:
                print(f"  stop/search: {e}")
                break
            leads = out.get("leads") or []
            search_rows += len(leads)
            pages += 1
            for L in leads:
                if len(candidates) >= pull:
                    break
                title = L.get("lastJobTitle") or L.get("headline") or ""
                if not title_ok(title) or not emp_ok(L.get("lastCompanySize")):
                    title_emp_fail += 1
                    continue
                li = norm_li(L.get("profileUrl") or "")
                if not li:
                    continue
                if li in seen_li:
                    skipped_known += 1
                    continue
                website = bare_domain(L.get("lastCompanyWebsite") or "")
                if website and website in domain_set:
                    skipped_known += 1
                    continue
                seen_li.add(li)
                row = dict(L)
                row["_slice"] = sl["id"]
                candidates.append(row)
            token = (out.get("pagination") or {}).get("token")
            if pages % 2 == 0 or len(candidates) >= pull or not token:
                print(
                    f"  {sl['id']} page={pages} searched={search_rows} "
                    f"candidates={len(candidates)} spend=${spend_micro/1e6:.4f}"
                )
            if not token or not leads:
                break
            time.sleep(0.12)

    pulled = len(candidates)
    # Persist candidates so Blitz can resume without re-paying Icypeas search
    cand_path = OUT_DIR / "volume-candidates.json"
    slim = []
    for L in candidates:
        slim.append(
            {
                "profileUrl": L.get("profileUrl"),
                "firstname": L.get("firstname"),
                "lastname": L.get("lastname"),
                "lastJobTitle": L.get("lastJobTitle"),
                "headline": L.get("headline"),
                "lastCompanySize": L.get("lastCompanySize"),
                "lastCompanyDescription": L.get("lastCompanyDescription"),
                "address": L.get("address"),
                "lastCompanyAddress": L.get("lastCompanyAddress"),
                "lastCompanyName": L.get("lastCompanyName"),
                "lastCompanyWebsite": L.get("lastCompanyWebsite"),
                "lastCompanyIndustry": L.get("lastCompanyIndustry"),
                "lastCompanyUrl": L.get("lastCompanyUrl"),
                "_slice": L.get("_slice"),
            }
        )
    cand_path.write_text(
        json.dumps(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "pull_target": pull,
                "search_rows": search_rows,
                "search_spend_usd": round(spend_micro / 1e6, 6),
                "tam": tam,
                "candidates": slim,
            },
            indent=2,
        )
    )
    print(f"Wrote {cand_path} ({len(slim)} candidates)")

    print(f"\n=== Blitz email.find on {pulled} candidates (Pull-N) ===")
    for i, L in enumerate(candidates, 1):
        if spend_micro / 1e6 >= hard_cap:
            print("  stop: hard cap")
            break
        # require company description for ready
        desc = (L.get("lastCompanyDescription") or "").strip()
        if not desc:
            no_desc += 1
            continue
        # Blitz miss is free; only abort if we cannot afford one success
        if spend_micro / 1e6 + 0.000495 > hard_cap:
            print(f"  stop/email: remaining budget below one Blitz success (${spend_micro/1e6:.4f})")
            break
        email_attempts += 1
        li = L["profileUrl"]
        try:
            eout = pay("blitzapi.people.email.find", {"person_linkedin_url": li})
        except (RuntimeError, urllib.error.HTTPError) as e:
            print(f"  stop/email: {e}")
            break
        email = eout.get("email") if isinstance(eout, dict) else None
        if not email and isinstance(eout, dict):
            for item in eout.get("all_emails") or []:
                if isinstance(item, dict) and item.get("email"):
                    email = item["email"]
                    break
        if not email:
            if i % 100 == 0:
                print(f"  … {i}/{pulled} attempts={email_attempts} ready={len(ready)} spend=${spend_micro/1e6:.4f}")
            continue
        el = email.lower().strip()
        if el in seen_email:
            skipped_known += 1
            continue
        if any(el.endswith("@" + d) for d in FREEMAIL):
            freemail += 1
            continue
        seen_email.add(el)
        email_hits += 1
        ready.append(
            {
                "slice": L.get("_slice"),
                "name": f"{L.get('firstname') or ''} {L.get('lastname') or ''}".strip(),
                "job_title": L.get("lastJobTitle") or L.get("headline"),
                "employee_count": L.get("lastCompanySize"),
                "company_desc": desc[:500],
                "email": email,
                "location": L.get("address") or L.get("lastCompanyAddress"),
                "company_name": L.get("lastCompanyName"),
                "company_website": L.get("lastCompanyWebsite"),
                "company_industry": L.get("lastCompanyIndustry"),
                "person_linkedin": norm_li(li),
                "company_linkedin": L.get("lastCompanyUrl"),
            }
        )
        if len(ready) <= 5 or len(ready) % 50 == 0 or i == pulled:
            print(
                f"  ✓ [{len(ready)}] {ready[-1]['name']} <{email}> @ {ready[-1]['company_name']} "
                f"(spend=${spend_micro/1e6:.4f})"
            )
        # Early-stop ONLY on email-phase econ (search is sunk in Pull-N).
        if len(ready) >= 50 and email_attempts >= 100:
            epr = email_attempts / len(ready)
            hit = email_hits / email_attempts
            if epr > 4 or hit < 0.15:
                print(
                    f"  EARLY-STOP bad email econ: email_att/ready={epr:.1f} "
                    f"hit_rate={hit:.3f}"
                )
                break
        time.sleep(0.05)

    spend = spend_micro / 1e6
    ready_n = len(ready)
    coverage = round(ready_n / pulled, 3) if pulled else 0.0
    report = {
        "client": "MARS",
        "path": "icypeas.people.search → blitzapi.people.email.find",
        "at": datetime.now(timezone.utc).isoformat(),
        "hard_cap_usd": hard_cap,
        "spend_usd": round(spend, 6),
        "pull_target": pull,
        "pulled": pulled,
        "search_rows": search_rows,
        "skipped_known": skipped_known,
        "title_emp_fail": title_emp_fail,
        "no_company_desc": no_desc,
        "email_attempts": email_attempts,
        "email_hits": email_hits,
        "freemail_drop": freemail,
        "ready": ready_n,
        "coverage": coverage,
        "tam": tam,
        "excluded": {"emails": len(excl_emails), "linkedin": len(excl_li), "domains": len(excl_domains)},
        "unit_economics": {
            "rows_per_ready": round(search_rows / ready_n, 2) if ready_n else None,
            "email_attempts_per_ready": round(email_attempts / ready_n, 2) if ready_n else None,
            "cost_per_1k_ready_usd": round(spend / ready_n * 1000, 2) if ready_n else None,
            "blitz_hit_rate": round(email_hits / email_attempts, 3) if email_attempts else None,
        },
        "rows": ready,
    }
    cols = [
        "slice",
        "name",
        "job_title",
        "employee_count",
        "company_desc",
        "email",
        "location",
        "company_name",
        "company_website",
        "company_industry",
        "person_linkedin",
        "company_linkedin",
    ]
    tag = "pilot" if pull <= 100 else "volume"
    csv_path = OUT_DIR / f"{tag}-ready.csv"
    report_path = OUT_DIR / f"{tag}-report.json"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(ready)
    (report_path).write_text(json.dumps(report, indent=2))
    print(f"Wrote {csv_path} and {report_path}")
    print(json.dumps({k: report[k] for k in (
        "spend_usd", "pulled", "ready", "coverage", "unit_economics", "tam", "skipped_known", "freemail_drop", "no_company_desc"
    )}, indent=2))
    # End warning: in Pull-N, search_rows/ready can look high if Blitz was truncated.
    # Flag only when email-phase econ is bad OR final $/1k is bad with meaningful ready.
    ue = report["unit_economics"]
    if ready_n and ready_n >= 25 and (
        (ue["email_attempts_per_ready"] or 0) > 4
        or ((ue["cost_per_1k_ready_usd"] or 0) > 10 and (ue["blitz_hit_rate"] or 1) < 0.25)
    ):
        print("⚠ Unit economics outside healthy band — review before more volume.")
    return report


def run_blitz_from_candidates(
    candidates_path: str,
    hard_cap: float,
    exclude_path: str | None,
    seed_ready_paths: list[str] | None = None,
) -> dict:
    """Resume Blitz on a saved candidates JSON without re-paying Icypeas search."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excl_emails, excl_li, _ = load_exclude(exclude_path)
    seen_email = set(excl_emails)
    seen_li = set(excl_li)
    ready: list[dict] = []

    # Seed prior ready rows (wave1 / partial) into output + skip sets
    for sp in seed_ready_paths or []:
        p = Path(sp)
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        rows = data if isinstance(data, list) else (data.get("rows") or [])
        for r in rows:
            if r.get("email"):
                seen_email.add(r["email"].lower())
            if r.get("person_linkedin"):
                seen_li.add(norm_li(r["person_linkedin"]))
            ready.append(r)
        print(f"Seeded {len(rows)} ready from {p}")

    blob = json.loads(Path(candidates_path).read_text())
    candidates = blob.get("candidates") or []
    search_rows = int(blob.get("search_rows") or len(candidates))
    prior_search_spend = float(blob.get("search_spend_usd") or 0.0)
    tam = blob.get("tam") or {}
    spend_micro = 0  # this resume's Blitz-only spend
    email_attempts = email_hits = freemail = skipped_known = no_desc = 0

    def pay(endpoint: str, body: dict) -> dict:
        nonlocal spend_micro
        if spend_micro / 1e6 >= hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} reached")
        if spend_micro / 1e6 + 0.000495 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} would be exceeded by next Blitz success")
        out, cost = call(endpoint, body)
        spend_micro += cost
        if spend_micro / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded (spent ${spend_micro/1e6:.4f})")
        return out

    ready_jsonl = OUT_DIR / "volume-ready.jsonl"
    # rewrite jsonl from seed
    with open(ready_jsonl, "w") as jf:
        for r in ready:
            jf.write(json.dumps(r) + "\n")

    print(
        f"Blitz resume: candidates={len(candidates)} seeded_ready={len(ready)} "
        f"hard_cap=${hard_cap} prior_search_spend=${prior_search_spend:.4f}"
    )
    for i, L in enumerate(candidates, 1):
        li = norm_li(L.get("profileUrl") or "")
        if not li or li in seen_li:
            skipped_known += 1
            continue
        seen_li.add(li)
        desc = (L.get("lastCompanyDescription") or "").strip()
        if not desc:
            no_desc += 1
            continue
        try:
            eout = pay("blitzapi.people.email.find", {"person_linkedin_url": L["profileUrl"]})
        except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"  stop/email: {e}")
            break
        email_attempts += 1
        email = eout.get("email") if isinstance(eout, dict) else None
        if not email and isinstance(eout, dict):
            for item in eout.get("all_emails") or []:
                if isinstance(item, dict) and item.get("email"):
                    email = item["email"]
                    break
        if not email:
            if i % 100 == 0:
                print(
                    f"  … {i}/{len(candidates)} attempts={email_attempts} "
                    f"ready={len(ready)} spend=${spend_micro/1e6:.4f}"
                )
            continue
        el = email.lower().strip()
        if el in seen_email:
            skipped_known += 1
            continue
        if any(el.endswith("@" + d) for d in FREEMAIL):
            freemail += 1
            continue
        seen_email.add(el)
        email_hits += 1
        row = {
            "slice": L.get("_slice"),
            "name": f"{L.get('firstname') or ''} {L.get('lastname') or ''}".strip(),
            "job_title": L.get("lastJobTitle") or L.get("headline"),
            "employee_count": L.get("lastCompanySize"),
            "company_desc": desc[:500],
            "email": email,
            "location": L.get("address") or L.get("lastCompanyAddress"),
            "company_name": L.get("lastCompanyName"),
            "company_website": L.get("lastCompanyWebsite"),
            "company_industry": L.get("lastCompanyIndustry"),
            "person_linkedin": li,
            "company_linkedin": L.get("lastCompanyUrl"),
        }
        ready.append(row)
        with open(ready_jsonl, "a") as jf:
            jf.write(json.dumps(row) + "\n")
        if len(ready) <= 5 or len(ready) % 50 == 0 or i == len(candidates):
            print(
                f"  ✓ [{len(ready)}] {row['name']} <{email}> @ {row['company_name']} "
                f"(blitz_spend=${spend_micro/1e6:.4f})"
            )
        if email_attempts >= 100 and email_hits >= 50:
            epr = email_attempts / max(email_hits, 1)
            hit = email_hits / email_attempts
            if epr > 4 or hit < 0.15:
                print(f"  EARLY-STOP bad email econ: att/hit={epr:.1f} hit_rate={hit:.3f}")
                break
        time.sleep(0.05)

    blitz_spend = spend_micro / 1e6
    total_spend = prior_search_spend + blitz_spend
    # Approximate combined campaign spend (wave1 search+blitz not fully known here)
    ready_n = len(ready)
    pulled = len(candidates)
    report = {
        "client": "MARS",
        "path": "icypeas.people.search → blitzapi.people.email.find",
        "mode": "blitz_from_candidates",
        "at": datetime.now(timezone.utc).isoformat(),
        "hard_cap_usd": hard_cap,
        "blitz_spend_usd": round(blitz_spend, 6),
        "prior_search_spend_usd": prior_search_spend,
        "spend_usd": round(total_spend, 6),
        "pull_target": blob.get("pull_target"),
        "pulled": pulled,
        "search_rows": search_rows,
        "skipped_known": skipped_known,
        "no_company_desc": no_desc,
        "email_attempts": email_attempts,
        "email_hits": email_hits,
        "freemail_drop": freemail,
        "ready": ready_n,
        "coverage": round(ready_n / pulled, 3) if pulled else 0.0,
        "tam": tam,
        "unit_economics": {
            "rows_per_ready": round(search_rows / ready_n, 2) if ready_n else None,
            "email_attempts_per_ready": round(email_attempts / max(email_hits, 1), 2) if email_hits else None,
            "cost_per_1k_ready_usd": round(total_spend / ready_n * 1000, 2) if ready_n else None,
            "blitz_hit_rate": round(email_hits / email_attempts, 3) if email_attempts else None,
        },
        "rows": ready,
    }
    cols = [
        "slice", "name", "job_title", "employee_count", "company_desc", "email", "location",
        "company_name", "company_website", "company_industry", "person_linkedin", "company_linkedin",
    ]
    with open(OUT_DIR / "volume-ready.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(ready)
    (OUT_DIR / "volume-report.json").write_text(json.dumps(report, indent=2))
    print(f"Wrote volume-ready.csv / volume-report.json ready={ready_n} blitz_spend=${blitz_spend:.4f}")
    print(json.dumps({k: report[k] for k in (
        "spend_usd", "blitz_spend_usd", "pulled", "ready", "coverage", "unit_economics"
    )}, indent=2))
    return report


def scope_only(exclude_path: str | None, max_domains: int) -> None:
    _, _, domains = load_exclude(exclude_path)
    print("=== FREE TAM (icypeas.people.search.count) — MARS broad ===")
    print(f"  exclude domains available={len(domains)} using_in_query={min(len(domains), max_domains)}")
    rows = []
    for sl in slices():
        q = with_domain_exclude(sl["query"], domains, max_domains)
        n = 0
        err = None
        for attempt in range(5):
            try:
                out, cost = call("icypeas.people.search.count", {"query": q})
                assert cost == 0, cost
                if out.get("validationErrors"):
                    err = out["validationErrors"]
                    n = 0
                    break
                n = out.get("total") or 0
                err = None
                break
            except Exception as e:
                err = e.read().decode()[:200] if hasattr(e, "read") else str(e)
                time.sleep(2**attempt)
        print(f"  {sl['id']} {sl['label']}: {n:,}" + (f"  ERR={err}" if err else ""))
        rows.append({"id": sl["id"], "label": sl["label"], "tam": n, "error": err})
        time.sleep(0.8)

    # Also: no domain exclude (diagnostic)
    print("\n--- Diagnostic: MARS-and WITHOUT domain exclude ---")
    q = slices()[2]["query"]
    out, cost = call("icypeas.people.search.count", {"query": q})
    assert cost == 0
    print(f"  MARS-and no-domain-excl: {out.get('total') or 0:,}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "client": "MARS",
        "workspace_id": "6a8d53c5977bb5537e41fcf2",
        "max_domains_in_query": max_domains,
        "domains_available": len(domains),
        "slices": rows,
        "mars_and_no_domain_exclude": out.get("total") or 0,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / "tam_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {OUT_DIR / 'tam_report.json'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="MARS Icypeas→Blitz scrape")
    ap.add_argument("--scope-only", action="store_true")
    ap.add_argument("--pull", type=int, default=0, help="Pull-N people from Icypeas (enrich that batch only)")
    ap.add_argument(
        "--blitz-from-candidates",
        default="",
        help="Resume Blitz from saved volume-candidates.json (no Icypeas search)",
    )
    ap.add_argument(
        "--seed-ready",
        action="append",
        default=[],
        help="Prior ready JSON report(s) to merge/skip (e.g. volume-report-wave1.json)",
    )
    ap.add_argument("--confirm-spend", type=float, default=0.0)
    ap.add_argument("--exclude-json", default="")
    ap.add_argument(
        "--slice",
        action="append",
        default=[],
        help="Slice id(s): MARS-and (default), MARS-ind, MARS-kw",
    )
    ap.add_argument(
        "--max-domains",
        type=int,
        default=2000,
        help="Cap domains in currentCompanyWebsite.exclude (Icypeas payload size)",
    )
    args = ap.parse_args()

    if args.scope_only:
        scope_only(args.exclude_json or None, args.max_domains)
        return

    if args.blitz_from_candidates:
        if args.confirm_spend <= 0:
            print("Refusing paid run without --confirm-spend <USD>", file=sys.stderr)
            sys.exit(2)
        run_blitz_from_candidates(
            candidates_path=args.blitz_from_candidates,
            hard_cap=args.confirm_spend,
            exclude_path=args.exclude_json or None,
            seed_ready_paths=args.seed_ready,
        )
        return

    if args.pull > 0:
        if args.confirm_spend <= 0:
            print("Refusing paid run without --confirm-spend <USD>", file=sys.stderr)
            sys.exit(2)
        run_pull(
            pull=args.pull,
            hard_cap=args.confirm_spend,
            exclude_path=args.exclude_json or None,
            max_domains=args.max_domains,
            slice_ids=args.slice or ["MARS-and"],
        )
        return

    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
