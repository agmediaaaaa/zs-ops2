#!/usr/bin/env python3
"""Pilot / volume runner: Icypeas people.search → Blitz email.find.

Gates:
  --scope-only          free Icypeas TAM counts only
  --pilot               10 ready × 4 verticals (requires --confirm-spend)
  --full N              N ready total across verticals (requires --confirm-spend)
  --confirm-spend USD   hard spend cap

Example:
  python scripts/pilot_icypeas_blitz_four_verticals.py --scope-only
  python scripts/pilot_icypeas_blitz_four_verticals.py --pilot --confirm-spend 1.00
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
]

CAMPAIGNS = [
    {
        "id": "V1",
        "name": "Industrial equipment repair",
        "query": {
            "currentJobTitle": {"include": TITLES},
            "profileLocation": {"include": ["US"]},
            "currentCompany.headcount": {">=": 5, "<=": 100},
            "currentCompany.industry": {"include": ["Facilities Services"]},
            "keyword": {"include": ["repair", "maintenance", "equipment"]},
        },
        "accept_re": re.compile(
            r"repair|maintenance|equipment|elevator|industrial|machinery|motor|pump|hydraulic|facilit|service",
            re.I,
        ),
    },
    {
        "id": "V2",
        "name": "Commercial P&C + benefits agencies",
        "query": {
            "currentJobTitle": {"include": TITLES},
            "profileLocation": {"include": ["US"]},
            "currentCompany.headcount": {">=": 5, "<=": 100},
            "keyword": {"include": ["insurance agency", "insurance brokerage"]},
        },
        "accept_re": re.compile(r"insur|agency|broker|benefit|risk|casualty|commercial", re.I),
    },
    {
        "id": "V3",
        "name": "Fire / life-safety ITM",
        "query": {
            "currentJobTitle": {"include": TITLES},
            "profileLocation": {"include": ["US"]},
            "currentCompany.headcount": {">=": 5, "<=": 100},
            "keyword": {"include": ["fire protection"]},
        },
        "accept_re": re.compile(
            r"fire|sprinkler|alarm|life.?safety|suppression|extinguisher|protection|itm", re.I
        ),
    },
    {
        "id": "V4",
        "name": "Home-services consolidators / sponsors",
        "query": {
            "currentJobTitle": {"include": TITLES},
            "profileLocation": {"include": ["US"]},
            "currentCompany.headcount": {">=": 5, "<=": 100},
            "keyword": {"include": ["home services"]},
        },
        "accept_re": re.compile(
            r"home.?service|hvac|plumb|electric|roof|comfort|heating|air.?cond|multi.?location|platform|holding|group|residential",
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
    return any(x in t for x in ["ceo", "chief executive", "owner", "founder", "president", "managing partner"])


def emp_ok(n) -> bool:
    try:
        n = int(n)
        return 5 <= n <= 100
    except Exception:
        return True


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


def scope_only() -> None:
    print("=== FREE TAM (icypeas.people.search.count) ===")
    total = 0
    for c in CAMPAIGNS:
        out, cost = call("icypeas.people.search.count", {"query": c["query"]})
        assert cost == 0, cost
        n = out.get("total") or 0
        total += n
        print(f"  {c['id']} {c['name']}: {n:,}")
    print(f"TOTAL: {total:,}")


def run(ready_per: int, hard_cap: float) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
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

    print("=== FREE TAM ===")
    tam = {}
    for c in CAMPAIGNS:
        out = pay("icypeas.people.search.count", {"query": c["query"]})
        tam[c["id"]] = out.get("total") or 0
        print(f"  {c['id']}: {tam[c['id']]:,}")

    for c in CAMPAIGNS:
        print(f"\n--- {c['id']} {c['name']} ---")
        candidates = []
        token = None
        searched = 0
        for _ in range(4):
            body = {"query": c["query"], "pagination": {"size": 25}}
            if token:
                body["pagination"]["token"] = token
            out = pay("icypeas.people.search", body)
            leads = out.get("leads") or []
            searched += len(leads)
            for L in leads:
                title = L.get("lastJobTitle") or L.get("headline") or ""
                if not title_ok(title) or not emp_ok(L.get("lastCompanySize")):
                    continue
                if not c["accept_re"].search(lead_blob(L)):
                    continue
                li = L.get("profileUrl") or ""
                if not li:
                    continue
                if any((x.get("profileUrl") or "").lower() == li.lower() for x in candidates):
                    continue
                candidates.append(L)
                if len(candidates) >= ready_per * 2:
                    break
            token = (out.get("pagination") or {}).get("token")
            if not token or len(candidates) >= ready_per * 2:
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
    print(json.dumps({k: report[k] for k in ("spend_usd", "ready_total", "tam_total", "unit_economics")}, indent=2))


def main() -> None:
    if not TOKEN:
        print("Missing TREG_TOKEN / ~/.treg/config.json", file=sys.stderr)
        sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-only", action="store_true")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--full", type=int, default=0, help="ready per vertical for volume run")
    ap.add_argument("--confirm-spend", type=float, default=None)
    args = ap.parse_args()
    if args.scope_only:
        scope_only()
        return
    if args.pilot or args.full:
        if args.confirm_spend is None:
            print("Paid run requires --confirm-spend USD", file=sys.stderr)
            sys.exit(2)
        ready = 10 if args.pilot else args.full
        run(ready_per=ready, hard_cap=args.confirm_spend)
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
