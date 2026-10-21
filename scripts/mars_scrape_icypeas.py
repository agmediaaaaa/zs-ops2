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
    "Manufacturing",
]

INDUSTRY_EXCLUDE = [
    "Staffing and Recruiting",
    "Business Consulting and Services",
    "Non-profit Organizations",
    "Wholesale",
    "Retail",
    "Software Development",
    "IT Services and IT Consulting",
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
    ap.add_argument("--pull", type=int, default=0)
    ap.add_argument("--confirm-spend", type=float, default=0.0)
    ap.add_argument("--exclude-json", default="")
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

    if args.pull > 0:
        if args.confirm_spend <= 0:
            print("Refusing paid run without --confirm-spend <USD>", file=sys.stderr)
            sys.exit(2)
        print("Paid pull not implemented in this turn — use after confirm.", file=sys.stderr)
        print("Got --pull", args.pull, "--confirm-spend", args.confirm_spend)
        sys.exit(3)

    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
