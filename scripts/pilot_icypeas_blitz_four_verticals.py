#!/usr/bin/env python3
"""Pilot / volume runner: Icypeas people.search → Blitz email.find.

Gates:
  --scope-only          free Icypeas TAM counts only
  --pilot               10 ready × 4 verticals (requires --confirm-spend)
  --full N              N ready *per vertical* (requires --confirm-spend)
  --confirm-spend USD   hard spend cap
  --exclude-json PATH   pre-search exclude set {emails,linkedin,domains}

Quality v2 filters (post QA on first 882):
  V1 — industrial equipment repair (not janitorial/landscaping/facilities)
  V2 — commercial P&C + benefits agencies (not InsurTech/SaaS/personal lines)
  V3 — fire / life-safety ITM (not generic safety consulting/software)
  V4 — HVAC/plumbing/home-services operators (not healthcare AI/real estate/SaaS)

Example:
  python scripts/pilot_icypeas_blitz_four_verticals.py --scope-only
  python scripts/pilot_icypeas_blitz_four_verticals.py --pilot --confirm-spend 1.00
  python scripts/pilot_icypeas_blitz_four_verticals.py --full 500 --confirm-spend 6 \\
      --exclude-json /workspace/artifacts/icypeas-blitz-v2/exclude.json
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


def _base_query(**extra) -> dict:
    q = {
        "currentJobTitle": {"include": TITLES},
        "profileLocation": {"include": ["US"]},
        "currentCompany.headcount": {">=": 5, "<=": 100},
    }
    q.update(extra)
    return q


CAMPAIGNS = [
    {
        "id": "V1",
        "name": "Industrial equipment repair",
        "query": _base_query(
            keyword={
                "include": [
                    "machinery repair",
                    "motor repair",
                    "pump repair",
                    "hydraulic repair",
                    "compressor repair",
                    "gearbox repair",
                    "equipment rebuild",
                    "industrial maintenance",
                ],
                "exclude": [
                    "janitorial",
                    "landscaping",
                    "cleaning",
                    "carpet",
                    "restroom",
                    "lawn",
                    "maid",
                ],
            }
        ),
        "accept_re": re.compile(
            r"\b(machinery repair|motor repair|pump repair|hydraulic|compressor repair|gearbox|"
            r"equipment rebuild|industrial (equipment )?repair|machine repair|industrial maintenance|"
            r"rebuild|overhaul)\b",
            re.I,
        ),
        "reject_re": re.compile(
            r"\b(janitor|landscap|lawn|carpet|restroom|toilet|cleaning company|maid|"
            r"facility cleaning|janitorial|softwar|saas|staffing|recruit)\b",
            re.I,
        ),
    },
    {
        "id": "V2",
        "name": "Commercial P&C + benefits agencies",
        "query": _base_query(
            **{"currentCompany.industry": {"include": ["Insurance"]}},
            keyword={
                "include": [
                    "insurance agency",
                    "insurance brokerage",
                    "commercial insurance",
                    "benefits broker",
                    "employee benefits agency",
                    "commercial lines",
                    "independent insurance agency",
                    "P&C agency",
                ],
                "exclude": [
                    "InsurTech",
                    "SaaS",
                    "software",
                    "Medicare",
                    "LTCi",
                    "long-term care",
                    "wealth management",
                    "fintech",
                    "training",
                ],
            },
        ),
        "accept_re": re.compile(
            r"\b(insurance agency|insurance (broker|brokerage)|independent (agent|agency)|"
            r"commercial (insurance|lines)|P\s*&\s*C|property (and )?casualty|"
            r"employee benefits|benefits (broker|agency))\b",
            re.I,
        ),
        "reject_re": re.compile(
            r"\b(insurtech|saas|software|medicare|ltci|long[- ]term care|"
            r"wealth (management|strateg)|fintech|training|staffing|recruit)\b",
            re.I,
        ),
    },
    {
        "id": "V3",
        "name": "Fire / life-safety ITM",
        "query": _base_query(
            keyword={
                "include": [
                    "fire protection",
                    "fire sprinkler",
                    "fire alarm inspection",
                    "sprinkler inspection",
                    "fire suppression",
                    "life safety",
                    "fire extinguisher",
                ],
                "exclude": [
                    "software",
                    "SaaS",
                    "staffing",
                    "recruiting",
                    "safety consulting",
                    "EHS software",
                    "construction management",
                ],
            }
        ),
        "accept_re": re.compile(
            r"\b(fire protection|fire sprinkler|fire alarm|sprinkler (inspection|service)|"
            r"fire suppression|life safety|fire extinguisher|alarm inspection|NFPA)\b",
            re.I,
        ),
        "reject_re": re.compile(
            r"\b(saas|software|staffing|recruit|safety consulting|EHS software|"
            r"general contractor|construction management)\b",
            re.I,
        ),
    },
    {
        "id": "V4",
        "name": "Home-services consolidators / sponsors",
        "query": _base_query(
            keyword={
                "include": [
                    "HVAC company",
                    "plumbing company",
                    "electrical contractor",
                    "home services",
                    "residential HVAC",
                    "multi-location HVAC",
                    "heating and cooling",
                ],
                "exclude": [
                    "SaaS",
                    "software",
                    "real estate",
                    "healthcare",
                    "AI platform",
                    "franchise coach",
                    "exit planning",
                    "PropTech",
                    "coaching",
                ],
            }
        ),
        "accept_re": re.compile(
            r"\b(HVAC|plumbing|electrical contractor|home services|multi-?location|"
            r"roll-?up|consolidat|heating (and )?air|air conditioning|furnace|drain|sewer)\b",
            re.I,
        ),
        "reject_re": re.compile(
            r"\b(saas|software|real estate|realtor|healthcare|biotech|\bAI\b|"
            r"franchise coach|exit (school|planning)|proptech|venture|staffing|recruit)\b",
            re.I,
        ),
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
        hdrs["X-Treg-Route-Exclude"] = "aiark"
    req = urllib.request.Request(
        f"https://treg.to/call/{endpoint}", data=data, method="POST" if body is not None else "GET", headers=hdrs
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
        raw = resp.read()
        return (json.loads(raw.decode()) if raw else {}), cost


def title_ok(title: str) -> bool:
    t = (title or "").lower()
    if "vice president" in t or t.startswith("vp ") or " assistant" in t:
        return False
    return any(x in t for x in ["ceo", "chief executive", "owner", "founder", "president", "managing partner", "principal"])


def emp_ok(n) -> bool:
    try:
        n = int(n)
        return 5 <= n <= 100
    except Exception:
        return False


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


def quality_ok(c: dict, L: dict) -> bool:
    blob = lead_blob(L)
    if c.get("reject_re") and c["reject_re"].search(blob):
        return False
    if not c["accept_re"].search(blob):
        return False
    return True


def scope_only(exclude_path: str | None = None) -> None:
    _, _, domains = load_exclude(exclude_path)
    print("=== FREE TAM (icypeas.people.search.count) ===")
    if domains:
        print(f"  (excluding {len(domains)} known company domains)")
    total = 0
    for c in CAMPAIGNS:
        q = with_domain_exclude(c["query"], domains)
        out, cost = call("icypeas.people.search.count", {"query": q})
        assert cost == 0, cost
        n = out.get("total") or 0
        total += n
        print(f"  {c['id']} {c['name']}: {n:,}")
    print(f"TOTAL: {total:,}")


def run(ready_per: int, hard_cap: float, exclude_path: str | None = None) -> None:
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
        out, cost = call(endpoint, body)
        spend_micro += cost
        if spend_micro / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded (spent ${spend_micro/1e6:.4f})")
        return out

    print(f"Exclude sets: emails={len(excl_emails)} linkedin={len(excl_li)} domains={len(excl_domains)}")
    print("=== FREE TAM ===")
    tam = {}
    for c in CAMPAIGNS:
        q = with_domain_exclude(c["query"], excl_domains)
        out = pay("icypeas.people.search.count", {"query": q})
        tam[c["id"]] = out.get("total") or 0
        print(f"  {c['id']}: {tam[c['id']]:,}")

    for c in CAMPAIGNS:
        print(f"\n--- {c['id']} {c['name']} ---")
        q = with_domain_exclude(c["query"], excl_domains)
        candidates = []
        token = None
        searched = skipped_existing = rejected_quality = 0
        for _ in range(8):
            body = {"query": q, "pagination": {"size": 50}}
            if token:
                body["pagination"]["token"] = token
            out = pay("icypeas.people.search", body)
            leads = out.get("leads") or []
            searched += len(leads)
            for L in leads:
                title = L.get("lastJobTitle") or L.get("headline") or ""
                if not title_ok(title) or not emp_ok(L.get("lastCompanySize")):
                    continue
                if not quality_ok(c, L):
                    rejected_quality += 1
                    continue
                li = norm_li(L.get("profileUrl") or "")
                if not li:
                    continue
                # Exclude existing BEFORE email enrichment
                if li in seen_li:
                    skipped_existing += 1
                    continue
                seen_li.add(li)
                candidates.append(L)
                if len(candidates) >= ready_per * 3:
                    break
            token = (out.get("pagination") or {}).get("token")
            if not token or len(candidates) >= ready_per * 3:
                break
            time.sleep(0.1)

        ready = []
        attempts = hits = 0
        for L in candidates:
            if len(ready) >= ready_per:
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
            if any(el.endswith("@" + d) for d in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]):
                continue
            seen_email.add(el)
            hits += 1
            ready.append(
                {
                    "vertical": c["id"],
                    "vertical_name": c["name"],
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
            print(f"  ✓ {ready[-1]['name']} <{email}>")
            time.sleep(0.08)

        camps.append(
            {
                "id": c["id"],
                "tam": tam[c["id"]],
                "searched": searched,
                "candidates": len(candidates),
                "skipped_existing": skipped_existing,
                "rejected_quality": rejected_quality,
                "email_attempts": attempts,
                "email_hits": hits,
                "ready": len(ready),
            }
        )
        rows.extend(ready)

    ready_n = max(len(rows), 1)
    searched_total = sum(c["searched"] for c in camps)
    attempts_total = sum(c["email_attempts"] for c in camps)
    spend = spend_micro / 1e6
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "hard_cap_usd": hard_cap,
        "spend_usd": round(spend, 6),
        "excluded": {"emails": len(excl_emails), "linkedin": len(excl_li), "domains": len(excl_domains)},
        "tam": tam,
        "tam_total": sum(tam.values()),
        "campaigns": camps,
        "ready_total": len(rows),
        "unit_economics": {
            "cost_per_ready_usd": round(spend / ready_n, 6),
            "cost_per_1k_ready_usd": round(spend / ready_n * 1000, 2),
            "search_rows_per_ready": round(searched_total / ready_n, 2),
            "email_attempts_per_ready": round(attempts_total / ready_n, 2),
        },
        "rows": rows,
    }
    cols = [
        "vertical",
        "vertical_name",
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
    print(json.dumps({k: report[k] for k in ("spend_usd", "ready_total", "tam_total", "unit_economics", "excluded")}, indent=2))


def main() -> None:
    if not TOKEN:
        print("Missing TREG_TOKEN / ~/.treg/config.json", file=sys.stderr)
        sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-only", action="store_true")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--full", type=int, default=0, help="ready per vertical for volume run")
    ap.add_argument("--confirm-spend", type=float, default=None)
    ap.add_argument("--exclude-json", type=str, default=None, help="JSON with emails/linkedin/domains to exclude before email find")
    args = ap.parse_args()
    if args.scope_only:
        scope_only(args.exclude_json)
        return
    if args.pilot or args.full:
        if args.confirm_spend is None:
            print("Paid run requires --confirm-spend USD", file=sys.stderr)
            sys.exit(2)
        ready = 10 if args.pilot else args.full
        run(ready_per=ready, hard_cap=args.confirm_spend, exclude_path=args.exclude_json)
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
