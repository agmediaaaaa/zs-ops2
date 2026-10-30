#!/usr/bin/env python3
"""Pilot / volume runner: Icypeas people.search → Blitz email.find.

Gates:
  --scope-only          free Icypeas TAM counts only
  --pilot               10 ready × 4 verticals (requires --confirm-spend)
  --full N              N ready *per vertical* (requires --confirm-spend)
  --confirm-spend USD   hard spend cap
  --exclude-json PATH   pre-search exclude set {emails,linkedin,domains}
  --local-quality       optional post-filter (OFF by default — ICP must be in-query)

v3 (post no-quality pilot):
  Dual slices per vertical = industry.include AND keyword.include/exclude in Icypeas.
  No local accept/reject regex by default — filter junk in the query itself.

Example:
  python scripts/pilot_icypeas_blitz_four_verticals.py --scope-only \\
      --exclude-json artifacts/zs-four-verticals-scope/exclude.json
  python scripts/pilot_icypeas_blitz_four_verticals.py --pilot --confirm-spend 0.25 \\
      --exclude-json artifacts/zs-four-verticals-scope/exclude.json
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

TOKEN = json.loads(Path.home().joinpath(".treg/config.json").read_text()).get("token") or os.environ.get(
    "TREG_TOKEN"
) or os.environ.get("treg")
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/icypeas-blitz-pilot"))

TITLES = [
    "CEO",
    "Chief Executive Officer",
    "Owner",
    "Founder",
    "Co-Founder",
    "President",
    "Founder & CEO",
    "Managing Partner",
    "Principal",
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
    "Director of Sales",
    "Account Executive",
    "Recruiter",
    "Recruiting",
]

# Shared junk learned from no-quality pilot hits (recruiting, SaaS, PE, coaching, ads)
HARD_KW_EXCLUDE = [
    "staffing",
    "recruiting",
    "recruiter",
    "headhunt",
    "job board",
    "talent acquisition",
    "SaaS",
    "software",
    "software development",
    "InsurTech",
    "fintech",
    "PropTech",
    "venture",
    "private equity",
    "venture capital",
    "coaching",
    "coach",
    "leadership coach",
    "Vistage",
    "marketing agency",
    "advertising",
    "digital marketing",
    "AI platform",
    "e-learning",
    "nonprofit",
    "non-profit",
]


def _base_query(**extra) -> dict:
    q = {
        "currentJobTitle": {"include": TITLES, "exclude": TITLE_EXCLUDE},
        "profileLocation": {"include": ["US"]},
        "currentCompany.headcount": {">=": 5, "<=": 100},
    }
    q.update(extra)
    return q


def _kw(include: list[str], extra_exclude: list[str] | None = None) -> dict:
    excl = list(dict.fromkeys(HARD_KW_EXCLUDE + (extra_exclude or [])))
    return {"include": include, "exclude": excl}


# Dual slices: industry AND keywords both required in-query (no local ICP reject by default).
CAMPAIGNS = [
    {
        "id": "V1",
        "name": "Industrial equipment repair",
        "slices": [
            {
                "id": "V1a",
                "label": "machinery mfg + repair kw",
                "query": _base_query(
                    **{
                        "currentCompany.industry": {
                            "include": [
                                "Machinery Manufacturing",
                                "Industrial Machinery Manufacturing",
                            ]
                        }
                    },
                    keyword=_kw(
                        [
                            "machinery repair",
                            "motor repair",
                            "pump repair",
                            "hydraulic repair",
                            "compressor repair",
                            "gearbox repair",
                            "equipment rebuild",
                            "industrial maintenance",
                            "machine repair",
                        ],
                        ["janitorial", "landscaping", "cleaning", "carpet", "restroom", "lawn", "maid", "consulting"],
                    ),
                ),
            },
            {
                "id": "V1b",
                "label": "repair & maintenance + industrial kw",
                "query": _base_query(
                    **{"currentCompany.industry": {"include": ["Repair and Maintenance"]}},
                    keyword=_kw(
                        [
                            "industrial",
                            "machinery",
                            "motor repair",
                            "pump repair",
                            "hydraulic",
                            "compressor",
                            "gearbox",
                            "equipment repair",
                            "equipment rebuild",
                        ],
                        ["janitorial", "landscaping", "cleaning", "auto body", "car wash", "residential"],
                    ),
                ),
            },
        ],
    },
    {
        "id": "V2",
        "name": "Commercial P&C + benefits agencies",
        "slices": [
            {
                "id": "V2a",
                "label": "insurance + agency/broker kw",
                "query": _base_query(
                    **{"currentCompany.industry": {"include": ["Insurance"]}},
                    keyword=_kw(
                        [
                            "insurance agency",
                            "insurance brokerage",
                            "independent insurance agency",
                            "commercial insurance",
                            "benefits broker",
                            "employee benefits agency",
                            "employee benefits",
                            "commercial lines",
                            "P&C agency",
                            "property and casualty",
                        ],
                        [
                            "Medicare",
                            "LTCi",
                            "long-term care",
                            "wealth management",
                            "training",
                            "CSR training",
                            "job board",
                        ],
                    ),
                ),
            },
        ],
    },
    {
        "id": "V3",
        "name": "Fire / life-safety ITM",
        "slices": [
            {
                "id": "V3a",
                "label": "fire protection industry + ITM kw",
                "query": _base_query(
                    **{"currentCompany.industry": {"include": ["Fire Protection"]}},
                    keyword=_kw(
                        [
                            "fire protection",
                            "fire sprinkler",
                            "fire alarm",
                            "fire suppression",
                            "life safety",
                            "sprinkler inspection",
                            "fire extinguisher",
                            "inspection",
                        ],
                        ["safety consulting", "EHS software", "construction management"],
                    ),
                ),
            },
            {
                "id": "V3b",
                "label": "security industry + fire/life-safety kw",
                "query": _base_query(
                    **{"currentCompany.industry": {"include": ["Security and Investigations"]}},
                    keyword=_kw(
                        [
                            "fire protection",
                            "fire sprinkler",
                            "fire alarm",
                            "fire suppression",
                            "life safety",
                            "sprinkler inspection",
                            "alarm inspection",
                        ],
                        ["cyber", "cybersecurity", "safety consulting", "EHS software"],
                    ),
                ),
            },
        ],
    },
    {
        "id": "V4",
        "name": "Home-services consolidators / sponsors",
        "slices": [
            {
                "id": "V4a",
                "label": "consumer services + HVAC/plumbing kw",
                "query": _base_query(
                    **{"currentCompany.industry": {"include": ["Consumer Services"]}},
                    keyword=_kw(
                        [
                            "HVAC",
                            "plumbing",
                            "electrical contractor",
                            "heating and cooling",
                            "home services",
                            "air conditioning",
                            "residential HVAC",
                            "residential plumbing",
                        ],
                        ["real estate", "healthcare", "franchise coach", "exit planning"],
                    ),
                ),
            },
            {
                "id": "V4b",
                "label": "construction + HVAC/plumbing kw",
                "query": _base_query(
                    **{"currentCompany.industry": {"include": ["Construction"]}},
                    keyword=_kw(
                        [
                            "HVAC",
                            "plumbing",
                            "electrical contractor",
                            "heating and air",
                            "home services",
                            "multi-location HVAC",
                        ],
                        [
                            "real estate",
                            "general contractor only",
                            "franchise coach",
                            "exit planning",
                            "headhunt",
                            "construction headhunting",
                        ],
                    ),
                ),
            },
        ],
    },
]


def call(endpoint: str, body: dict | None = None) -> tuple[dict, int]:
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"X-Treg-Token": TOKEN, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if "email.find" in endpoint:
        hdrs["X-Treg-Route-Max-Cost"] = "0.01"
        hdrs["X-Treg-Route-Waterfall"] = "0"
        hdrs["X-Treg-Route-Exclude"] = "aiark,icypeas"
    req = urllib.request.Request(
        f"https://treg.to/call/{endpoint}", data=data, method="POST" if body is not None else "GET", headers=hdrs
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
        raw = resp.read()
        return (json.loads(raw.decode()) if raw else {}), cost


def title_ok(title: str) -> bool:
    """Safety net mirroring in-query title filters (not ICP keyword reject)."""
    t = (title or "").lower()
    if "vice president" in t or t.startswith("vp ") or " assistant" in t or "recruit" in t:
        return False
    return any(
        x in t for x in ["ceo", "chief executive", "owner", "founder", "president", "managing partner", "principal"]
    )


def emp_ok(n) -> bool:
    try:
        n = int(n)
        return 5 <= n <= 100
    except Exception:
        return False


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


def with_domain_exclude(query: dict, domains: list[str]) -> dict:
    q = json.loads(json.dumps(query))
    if domains:
        q["currentCompanyWebsite"] = {"exclude": domains}
    return q


def scope_only(exclude_path: str | None = None) -> None:
    _, _, domains = load_exclude(exclude_path)
    print("=== FREE TAM (icypeas.people.search.count) — dual industry+keyword slices ===")
    if domains:
        print(f"  (excluding {len(domains)} known company domains)")
    total = 0
    for c in CAMPAIGNS:
        v_total = 0
        for sl in c["slices"]:
            q = with_domain_exclude(sl["query"], domains)
            for attempt in range(6):
                try:
                    out, cost = call("icypeas.people.search.count", {"query": q})
                    assert cost == 0, cost
                    n = out.get("total") or 0
                    break
                except Exception as e:
                    err = e.read().decode()[:120] if hasattr(e, "read") else str(e)
                    print(f"  {sl['id']} retry {attempt+1}: {err}")
                    time.sleep(2**attempt)
                    n = 0
            v_total += n
            print(f"  {sl['id']} {sl['label']}: {n:,}")
            time.sleep(1.0)
        total += v_total
        print(f"  → {c['id']} {c['name']} sum(slices)≈{v_total:,} (overlap possible)")
    print(f"TOTAL (sum of slices, may double-count): {total:,}")


def run(
    ready_per: int,
    hard_cap: float,
    exclude_path: str | None = None,
    local_quality: bool = False,
) -> None:
    """Pull-N per vertical across dual slices → Blitz. ICP filtering is in-query."""
    del local_quality  # reserved; local accept/reject removed by design
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excl_emails, excl_li, excl_domains = load_exclude(exclude_path)
    seen_li = set(excl_li)
    seen_email = set(excl_emails)
    spend_micro = 0
    rows: list[dict] = []
    camps = []

    def pay(endpoint, body):
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

    print(f"Exclude sets: emails={len(excl_emails)} linkedin={len(excl_li)} domains={len(excl_domains)}")
    print("Mode: in-query industry+keyword dual slices; NO local quality reject")
    print("=== FREE TAM ===")
    tam: dict[str, int] = {}
    for c in CAMPAIGNS:
        for sl in c["slices"]:
            q = with_domain_exclude(sl["query"], excl_domains)
            out = pay("icypeas.people.search.count", {"query": q})
            tam[sl["id"]] = out.get("total") or 0
            print(f"  {sl['id']}: {tam[sl['id']]:,}")
            time.sleep(0.8)

    page_size = 25 if ready_per <= 15 else 50
    max_pages_per_slice = 3 if ready_per <= 15 else 6
    cand_mult = 2

    for c in CAMPAIGNS:
        print(f"\n--- {c['id']} {c['name']} ---")
        if spend_micro / 1e6 >= hard_cap * 0.95:
            print(f"  skip: near hard cap (${spend_micro/1e6:.4f}/${hard_cap})")
            camps.append({"id": c["id"], "searched": 0, "candidates": 0, "ready": 0, "skipped_reason": "near_hard_cap"})
            continue

        candidates: list[dict] = []
        searched = skipped_existing = title_or_emp_fail = 0
        slice_stats = []

        for sl in c["slices"]:
            if len(candidates) >= ready_per * cand_mult:
                break
            q = with_domain_exclude(sl["query"], excl_domains)
            token = None
            sl_searched = 0
            for _ in range(max_pages_per_slice):
                body = {"query": q, "pagination": {"size": page_size}}
                if token:
                    body["pagination"]["token"] = token
                try:
                    out = pay("icypeas.people.search", body)
                except RuntimeError as e:
                    print(f"  stop/search {sl['id']}: {e}")
                    break
                leads = out.get("leads") or []
                sl_searched += len(leads)
                searched += len(leads)
                for L in leads:
                    title = L.get("lastJobTitle") or L.get("headline") or ""
                    if not title_ok(title) or not emp_ok(L.get("lastCompanySize")):
                        title_or_emp_fail += 1
                        continue
                    li = norm_li(L.get("profileUrl") or "")
                    if not li:
                        continue
                    if li in seen_li:
                        skipped_existing += 1
                        continue
                    seen_li.add(li)
                    L = dict(L)
                    L["_slice"] = sl["id"]
                    candidates.append(L)
                    if len(candidates) >= ready_per * cand_mult:
                        break
                token = (out.get("pagination") or {}).get("token")
                if not token or len(candidates) >= ready_per * cand_mult:
                    break
                time.sleep(0.15)
            slice_stats.append({"id": sl["id"], "searched": sl_searched})
            print(f"  {sl['id']}: searched={sl_searched} candidates_so_far={len(candidates)}")

        ready = []
        attempts = hits = freemail = 0
        for L in candidates:
            if len(ready) >= ready_per:
                break
            if spend_micro / 1e6 >= hard_cap:
                break
            attempts += 1
            li = L["profileUrl"]
            try:
                eout = pay("blitzapi.people.email.find", {"person_linkedin_url": li})
            except (RuntimeError, urllib.error.HTTPError) as e:
                print(f"  stop/email err: {e}")
                break
            email = eout.get("email") if isinstance(eout, dict) else None
            if not email:
                for item in (eout.get("all_emails") or []) if isinstance(eout, dict) else []:
                    if isinstance(item, dict) and item.get("email"):
                        email = item["email"]
                        break
            if not email:
                continue
            el = email.lower().strip()
            if el in seen_email:
                skipped_existing += 1
                continue
            if any(
                el.endswith("@" + d)
                for d in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com"]
            ):
                freemail += 1
                continue
            seen_email.add(el)
            hits += 1
            ready.append(
                {
                    "vertical": c["id"],
                    "vertical_name": c["name"],
                    "slice": L.get("_slice"),
                    "name": f"{L.get('firstname') or ''} {L.get('lastname') or ''}".strip(),
                    "job_title": L.get("lastJobTitle") or L.get("headline"),
                    "employee_count": L.get("lastCompanySize"),
                    "company_desc": (L.get("lastCompanyDescription") or "")[:500],
                    "email": email,
                    "location": L.get("address") or L.get("lastCompanyAddress"),
                    "company_name": L.get("lastCompanyName"),
                    "company_website": L.get("lastCompanyWebsite"),
                    "company_industry": L.get("lastCompanyIndustry"),
                    "person_linkedin": li,
                    "company_linkedin": L.get("lastCompanyUrl"),
                }
            )
            print(f"  ✓ [{L.get('_slice')}] {ready[-1]['name']} <{email}> @ {ready[-1]['company_name']}")
            time.sleep(0.08)

        camps.append(
            {
                "id": c["id"],
                "tam_slices": {s["id"]: tam.get(s["id"]) for s in c["slices"]},
                "slice_stats": slice_stats,
                "searched": searched,
                "candidates": len(candidates),
                "skipped_existing": skipped_existing,
                "title_or_emp_fail": title_or_emp_fail,
                "email_attempts": attempts,
                "email_hits": hits,
                "freemail_drop": freemail,
                "ready": len(ready),
                "blitz_hit_rate": round(hits / attempts, 3) if attempts else None,
            }
        )
        rows.extend(ready)

    ready_n = max(len(rows), 1)
    searched_total = sum(c.get("searched", 0) for c in camps)
    attempts_total = sum(c.get("email_attempts", 0) for c in camps)
    spend = spend_micro / 1e6
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "mode": "dual_industry_keyword_in_query_no_local_quality",
        "hard_cap_usd": hard_cap,
        "spend_usd": round(spend, 6),
        "excluded": {"emails": len(excl_emails), "linkedin": len(excl_li), "domains": len(excl_domains)},
        "tam": tam,
        "tam_total_sum_slices": sum(tam.values()),
        "campaigns": camps,
        "ready_total": len(rows),
        "unit_economics": {
            "cost_per_ready_usd": round(spend / ready_n, 6) if rows else None,
            "cost_per_1k_ready_usd": round(spend / ready_n * 1000, 2) if rows else None,
            "search_rows_per_ready": round(searched_total / ready_n, 2) if rows else None,
            "email_attempts_per_ready": round(attempts_total / ready_n, 2) if rows else None,
            "blitz_hit_rate": round(sum(c.get("email_hits", 0) for c in camps) / max(attempts_total, 1), 3),
        },
        "rows": rows,
    }
    cols = [
        "vertical",
        "vertical_name",
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
    with open(OUT_DIR / "pilot-ready.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (OUT_DIR / "pilot-report.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {k: report[k] for k in ("spend_usd", "ready_total", "tam_total_sum_slices", "unit_economics", "excluded")},
            indent=2,
        )
    )


def main() -> None:
    print("=" * 80)
    print("DEPRECATED: Direct Icypeas → Blitz path is NO LONGER SUPPORTED")
    print("=" * 80)
    print()
    print("As of Oct 30, 2026, the ONLY supported people-sourcing path is:")
    print("  LeadsForge → Icypeas → Blitz")
    print()
    print("This script (pilot_icypeas_blitz_four_verticals.py) bypasses LeadsForge")
    print("and goes directly from Icypeas people.search to email finding.")
    print()
    print("That workflow is now DISABLED.")
    print()
    print("MIGRATION:")
    print("  Use scripts/unified_engine.py instead:")
    print()
    print("  # Free TAM count")
    print("  python scripts/unified_engine.py --client ZS --scope-only --exclude-json suppress.json")
    print()
    print("  # Pilot run")
    print("  python scripts/unified_engine.py --client ZS --pilot --confirm-spend 2.50 --exclude-json suppress.json")
    print()
    print("  # Full run")
    print("  python scripts/unified_engine.py --client ZS --full 1000 --confirm-spend 45.00 --exclude-json suppress.json")
    print()
    print("For help migrating your Icypeas queries to LeadsForge, see:")
    print("  - README.md (Migration Guide)")
    print("  - docs/waterfall-cost-matrix.md")
    print("  - 08-treg-lead-scrape/MASTER-PROMPT.md")
    print()
    sys.exit(1)


if __name__ == "__main__":
    main()
