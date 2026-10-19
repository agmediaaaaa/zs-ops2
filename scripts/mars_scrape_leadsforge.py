#!/usr/bin/env python3
"""MARS volume: free Leadsforge people.search → Trykitt/treg email.find.

Matches user seniority filters natively (founder/owner/c_suite/partner/director/head/manager).
Search is free; email ~$0.005/hit via trykitt.

  python scripts/mars_scrape_leadsforge.py --scope-only
  python scripts/mars_scrape_leadsforge.py --full 1800 --confirm-spend 12 --upload-plusvibe
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

TOKEN = (
    json.loads(Path.home().joinpath(".treg/config.json").read_text()).get("token")
    if Path.home().joinpath(".treg/config.json").exists()
    else None
) or os.environ.get("TREG_TOKEN") or os.environ.get("treg")

OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/mars-scrape/volume-lf"))
EXCLUDE_PATH = Path(
    os.environ.get("MARS_EXCLUDE_JSON", "/workspace/artifacts/mars-scrape/plusvibe_exclude.json")
)
PLUSVIBE_API_KEY = os.environ.get("PLUSVIBE_API_KEY", "")
PLUSVIBE_WORKSPACE_ID = os.environ.get("PLUSVIBE_WORKSPACE_ID", "6a8d53c5977bb5537e41fcf2")
PLUSVIBE_CAMPAIGN_ID = os.environ.get("PLUSVIBE_CAMPAIGN_ID", "6ac63d95542d3f7788938ecc")

SENIORITY_CS = ["founder", "owner", "c_suite", "partner"]
SENIORITY_OPS = ["director", "head", "manager"]  # vp excluded via title reject
# user asked manager stay in for Plant Manager / GM

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

TITLE_REJECT_RE = re.compile(
    r"("
    r"\bvp\b|vice[\s-]?president|assistant|sales|marketing|\bhr\b|"
    r"engineer|engineering|quality|purchasing|supply[\s-]?chain|"
    r"machinist|welder|operator|technician|accounting|admin|"
    r"project manager|product manager|\bcfo\b|\bcto\b|\bcmo\b|\bcio\b|"
    r"board|advisor|consultant|retired|former|intern|student"
    r")",
    re.I,
)
CSUITE_KEEP_RE = re.compile(
    r"\b(ceo|chief executive|owner|co-?owner|founder|co-?founder|president)\b", re.I
)
OPS_KEEP_RE = re.compile(
    r"(plant manager|director of operations|general manager|\bgm\b|"
    r"operations manager|operations director|head of operations|"
    r"director of manufacturing|production manager|manufacturing manager)",
    re.I,
)
GLOBAL_REJECT_RE = re.compile(
    r"("
    r"casting (director|partner|agency)|talent|software|saas|staffing|recruit|"
    r"apparel|digital foundry|healthcare foundry|protein foundry|sales agency|"
    r"machine(?:ry)? sales|equipment (dealer|broker)|distributor|wholesale|"
    r"board chair|airline spares|tax professional|capital partner|private equity|"
    r"foundry commercial"
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
KW_EXCLUDE = [
    "staffing",
    "recruiting",
    "recruitment",
    "software",
    "SaaS",
    "consulting",
    "IT services",
    "wholesale",
    "banking",
    "financial services",
    "manufacturers rep",
    "sales agency",
]

SEGMENTS = [
    {
        "seg": "S1",
        "name": "Precision CNC / machine shops",
        "keywords": [
            "CNC machining",
            "precision machining",
            "machine shop",
            "job shop",
            "contract machining",
            "Swiss turning",
            "wire EDM",
            "5-axis",
        ],
        "emp_cs": (10, 199),
        "emp_ops": (200, 500),
        "accept_re": re.compile(
            r"cnc|precision machin|machine shop|job shop|contract machin|swiss|edm|machining",
            re.I,
        ),
        "reject_re": re.compile(r"staffing|recruit|software|saas|sales agency", re.I),
    },
    {
        "seg": "S2",
        "name": "Foundries / metal casting",
        "keywords": [
            "foundry",
            "metal casting",
            "investment casting",
            "sand casting",
            "die casting",
            "aluminum casting",
            "iron casting",
            "steel casting",
        ],
        "emp_cs": (10, 199),
        "emp_ops": (200, 500),
        "accept_re": re.compile(
            r"\bfoundry\b|metal casting|investment casting|sand casting|die casting|"
            r"iron casting|steel casting|aluminum casting|castings",
            re.I,
        ),
        "reject_re": re.compile(
            r"scrap|recycl|foundry supply|digital foundry|healthcare foundry|"
            r"protein|talent|software|saas|staffing|foundry commercial",
            re.I,
        ),
    },
    {
        "seg": "S3",
        "name": "AS9100 aerospace / turbine",
        "keywords": [
            "AS9100",
            "aerospace machining",
            "aircraft parts",
            "NADCAP",
            "turbine components",
            "jet engine components",
        ],
        "emp_cs": (10, 199),
        "emp_ops": (200, 500),
        "accept_re": re.compile(
            r"as.?9100|nadcap|aerospace machin|aircraft parts|turbine|"
            r"(aerospace|aircraft).{0,80}(machin|cnc)|"
            r"(machin|cnc).{0,80}(aerospace|aircraft|as.?9100|nadcap)",
            re.I,
        ),
        "reject_re": re.compile(r"staffing|software|saas|airline spares|airport", re.I),
    },
    {
        "seg": "S4",
        "name": "Sheet metal / fabrication",
        "keywords": [
            "sheet metal fabrication",
            "precision sheet metal",
            "metal fabrication",
            "press brake",
            "laser cutting",
            "CNC punching",
        ],
        "emp_cs": (10, 199),
        "emp_ops": (200, 999),
        "accept_re": re.compile(
            r"sheet[\s-]?metal|metal fabricat|press brake|laser cut|cnc punch|fabricat",
            re.I,
        ),
        "reject_re": re.compile(
            r"\bhvac\b|roofing|ductwork|steel service|construction|mining|staffing|software|saas",
            re.I,
        ),
    },
]


def call(endpoint, body=None, method=None, extra_headers=None):
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"X-Treg-Token": TOKEN, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if extra_headers:
        hdrs.update(extra_headers)
    verb = method or ("POST" if body is not None else "GET")
    req = urllib.request.Request(
        f"https://treg.to/call/{endpoint}", data=data, method=verb, headers=hdrs
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
        served = resp.headers.get("X-Treg-Served-By")
        raw = resp.read()
        out = json.loads(raw.decode()) if raw else {}
        if served:
            out["_served_by"] = served
        return out, cost


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


def load_excludes():
    emails, domains = set(), set()
    linkedins = set()
    if EXCLUDE_PATH.exists():
        data = json.loads(EXCLUDE_PATH.read_text())
        emails = {e.strip().lower() for e in data.get("emails") or [] if e}
        linkedins = {x.strip().lower().rstrip("/") for x in data.get("linkedins") or [] if x}
        domains = {norm_domain(x) for x in data.get("domains") or [] if x} - FREEMAIL
    return {"emails": emails, "domains": domains, "linkedins": linkedins}


def seed_seen(seen_email, seen_domain, seen_key):
    for d in Path("/workspace/artifacts/mars-scrape").rglob("*ready.csv"):
        try:
            with open(d, newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("email"):
                        seen_email.add(r["email"].strip().lower())
                    dom = norm_domain(r.get("company_website") or "")
                    if not dom and r.get("email") and "@" in r["email"]:
                        dom = r["email"].split("@", 1)[1].lower()
                    if dom and dom not in FREEMAIL:
                        seen_domain.add(dom)
                    key = f"{(r.get('name') or '').lower()}|{dom}"
                    seen_key.add(key)
        except Exception:
            pass


def title_ok(title: str, band: str) -> bool:
    if not title or TITLE_REJECT_RE.search(title):
        return False
    return bool((CSUITE_KEEP_RE if band == "CS" else OPS_KEEP_RE).search(title))


def extract_email(eout: dict) -> str | None:
    if not isinstance(eout, dict):
        return None
    if eout.get("email"):
        return str(eout["email"]).strip().lower()
    out = eout.get("output")
    if isinstance(out, dict) and out.get("email"):
        return str(out["email"]).strip().lower()
    for item in eout.get("all_emails") or []:
        if isinstance(item, dict) and item.get("email"):
            return str(item["email"]).strip().lower()
    return None


def plusvibe_upload(rows):
    added = skipped = errors = 0
    details = []
    for i in range(0, len(rows), 50):
        batch = rows[i : i + 50]
        leads = []
        for r in batch:
            name = (r.get("name") or "").strip()
            parts = name.split(" ", 1)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""
            leads.append(
                {
                    "email": r["email"],
                    "first_name": first,
                    "last_name": last,
                    "company_name": r.get("company_name") or "",
                    "company_website": r.get("company_website") or "",
                    "job_title": r.get("job_title") or "",
                    "custom_variables": {
                        "employee_count": str(r.get("employee_count") or ""),
                        "mars_seg": r.get("seg") or "",
                        "mars_band": r.get("band") or "",
                        "location": r.get("location") or "",
                        "industry": r.get("company_industry") or "",
                        "company_keywords": r.get("company_keywords") or "",
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
        req = urllib.request.Request(
            "https://api.plusvibe.ai/api/v1/lead/add",
            data=json.dumps(payload).encode(),
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
            added += int(body.get("leads_uploaded") or len(batch))
            skipped += int(body.get("skipped") or body.get("already_in_campaign") or 0)
            details.append({"batch": i // 50, "response": body})
            print(f"  uploaded batch {i // 50}: +{len(batch)}")
        except urllib.error.HTTPError as e:
            errors += len(batch)
            details.append({"batch": i // 50, "error": e.read().decode()[:400]})
        time.sleep(0.25)
    return {"added": added, "skipped": skipped, "errors": errors, "details": details}


def lf_query(seg, band, titles, lo, hi, exclude_domains=None):
    seniority = SENIORITY_CS if band == "CS" else SENIORITY_OPS
    q = {
        "leadJobTitles": {"include": titles},
        "leadSeniorities": {"include": seniority},
        "leadLocations": {"include": ["United States"]},
        "companyLocations": {"include": ["United States"]},
        "companyEmployeeNumberRange": {"min": lo, "max": hi},
        "companyTypes": {
            "include": ["PRIVATELY_HELD", "PARTNERSHIP", "SELF_OWNED"],
            "exclude": ["PUBLIC_COMPANY", "NON_PROFIT", "EDUCATIONAL", "GOVERNMENT_AGENCY"],
        },
        "companyKeywords": {
            "include": seg["keywords"],
            "exclude": KW_EXCLUDE
            + (["scrap metal", "recycling", "foundry supply"] if seg["seg"] == "S2" else [])
            + (["HVAC", "roofing", "ductwork"] if seg["seg"] == "S4" else []),
        },
        "companyRequired": True,
        "maxContactsPerCompany": 1,
        "limit": 25,
    }
    if exclude_domains:
        q["excludeDomains"] = list(exclude_domains)[:500]
    return q


def scope_only():
    print("=== FREE TAM (leadsforge.people.search.count) — MARS ===")
    total = 0
    for seg in SEGMENTS:
        for band, titles, (lo, hi) in (
            ("CS", CSUITE_TITLES, seg["emp_cs"]),
            ("OPS", OPS_TITLES, seg["emp_ops"]),
        ):
            q = lf_query(seg, band, titles, lo, hi)
            q.pop("limit", None)
            out, cost = call("leadsforge.people.search.count", q)
            assert cost == 0
            n = out.get("totalCount") or out.get("total") or 0
            total += n
            print(f"  {seg['seg']}_{band}: {n:,}  {seg['name']}")
    print(f"TOTAL: {total:,}")


def run(ready_target: int, hard_cap: float, upload: bool):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excl = load_excludes()
    seen_email = set(excl["emails"])
    seen_domain = set(excl["domains"])
    seen_key = set()
    seed_seen(seen_email, seen_domain, seen_key)
    print(f"Excludes+seed emails={len(seen_email)} domains={len(seen_domain)}")

    spend_micro = 0
    rows = []
    stats = []
    progress_path = OUT_DIR / "progress.json"

    def pay_email(name: str, domain: str):
        nonlocal spend_micro
        if spend_micro / 1e6 >= hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap}")
        out, cost = call(
            "treg.people.email.find",
            {"full_name": name, "domain": domain},
            extra_headers={
                "X-Treg-Route-Max-Cost": "0.006",
                "X-Treg-Route-Waterfall": "0",
                "X-Treg-Route-Exclude": "aiark",
                "X-Treg-Route-Prefer": "trykitt,quickenrich,tomba",
            },
        )
        email = None
        if isinstance(out, dict):
            email = out.get("email") or (out.get("output") or {}).get("email")
        # Only apply trykitt fallback cost on a successful hit when header cost is missing
        if cost <= 0 and email and str(email).lower() not in ("", "n/a", "null", "none"):
            cost = 5000
        spend_micro += max(cost, 0)
        if spend_micro / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap exceeded ${spend_micro/1e6:.4f}")
        return out

    def save():
        progress_path.write_text(
            json.dumps(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "ready": len(rows),
                    "spend_usd": round(spend_micro / 1e6, 6),
                    "target": ready_target,
                    "hard_cap_usd": hard_cap,
                },
                indent=2,
            )
        )

    for seg in SEGMENTS:
        for band, titles, (lo, hi) in (
            ("CS", CSUITE_TITLES, seg["emp_cs"]),
            ("OPS", OPS_TITLES, seg["emp_ops"]),
        ):
            if len(rows) >= ready_target:
                break
            want = max(200, min(500, ready_target - len(rows)))
            print(f"\n--- {seg['seg']}_{band} {seg['name']} want={want} ---")
            cursor = None
            searched = 0
            candidates = []
            pages = 0
            while pages < 80 and len(candidates) < want * 3:
                # Keep excludeDomains small — large lists make Leadsforge hang/timeout.
                q = lf_query(
                    seg,
                    band,
                    titles,
                    lo,
                    hi,
                    exclude_domains=list(seen_domain)[:80],
                )
                body = dict(q)
                if cursor:
                    # cursor is query param per catalog
                    pass
                try:
                    if cursor:
                        # POST with cursor as query string
                        from urllib.parse import urlencode

                        url = f"https://treg.to/call/leadsforge.people.search?{urlencode({'cursor': cursor})}"
                        req = urllib.request.Request(
                            url,
                            data=json.dumps(body).encode(),
                            method="POST",
                            headers={
                                "X-Treg-Token": TOKEN,
                                "Content-Type": "application/json",
                                "Accept": "application/json",
                            },
                        )
                        with urllib.request.urlopen(req, timeout=120) as resp:
                            out = json.loads(resp.read().decode())
                    else:
                        out, _ = call("leadsforge.people.search", body)
                except urllib.error.HTTPError as e:
                    print(f"  search http {e.code}: {e.read().decode()[:200]}")
                    break
                leads = out.get("leads") or []
                pages += 1
                searched += len(leads)
                if not leads:
                    break
                for L in leads:
                    title = L.get("jobTitle") or ""
                    if not title_ok(title, band):
                        continue
                    co = L.get("company") or {}
                    domain = norm_domain(co.get("domain") or co.get("website") or "")
                    if not domain or domain in seen_domain or domain in FREEMAIL:
                        continue
                    name = f"{L.get('firstName') or ''} {L.get('lastName') or ''}".strip()
                    if not name:
                        continue
                    key = f"{name.lower()}|{domain}"
                    if key in seen_key:
                        continue
                    emp = co.get("employeeCount")
                    try:
                        emp_n = int(emp) if emp is not None else None
                    except Exception:
                        emp_n = None
                    if emp_n is not None and not (lo <= emp_n <= hi):
                        continue
                    kws = co.get("keywords") or []
                    if isinstance(kws, list):
                        kw_s = " ".join(kws)
                    else:
                        kw_s = str(kws)
                    blob = " ".join(
                        [
                            title,
                            name,
                            str(co.get("industry") or ""),
                            domain,
                            kw_s,
                        ]
                    )
                    if GLOBAL_REJECT_RE.search(blob) or seg["reject_re"].search(blob):
                        continue
                    if not seg["accept_re"].search(blob):
                        continue
                    loc = L.get("location") or {}
                    candidates.append(
                        {
                            "name": name,
                            "title": title,
                            "domain": domain,
                            "emp": emp_n,
                            "industry": co.get("industry"),
                            "keywords": kw_s[:300],
                            "website": co.get("website") or domain,
                            "location": ", ".join(
                                str(loc.get(k) or "")
                                for k in ("city", "state", "country")
                                if loc.get(k)
                            ),
                            "key": key,
                        }
                    )
                    if len(candidates) >= want * 3:
                        break
                cursor = out.get("cursor")
                if not cursor:
                    break
                time.sleep(0.05)

            ready_here = attempts = hits = skips = 0
            for c in candidates:
                if ready_here >= want or len(rows) >= ready_target:
                    break
                if c["domain"] in seen_domain or c["key"] in seen_key:
                    continue
                attempts += 1
                try:
                    eout = pay_email(c["name"], c["domain"])
                except RuntimeError as e:
                    print(f"  cap: {e}")
                    break
                except urllib.error.HTTPError as e:
                    print(f"  email http {e.code} skip")
                    continue
                email = extract_email(eout)
                if not email or "@" not in email:
                    continue
                hits += 1
                edom = email.split("@", 1)[1]
                if edom in FREEMAIL:
                    continue
                if email in seen_email or edom in seen_domain:
                    skips += 1
                    continue
                row = {
                    "seg": seg["seg"],
                    "band": band,
                    "stream_id": f"{seg['seg']}_{band}",
                    "stream_name": seg["name"],
                    "name": c["name"],
                    "job_title": c["title"],
                    "employee_count": c["emp"],
                    "company_desc": "",
                    "email": email,
                    "email_status": "unverified",
                    "location": c["location"],
                    "company_name": "",
                    "company_website": c["website"],
                    "company_industry": c["industry"],
                    "company_keywords": c["keywords"],
                    "person_linkedin": "",
                    "company_linkedin": "",
                }
                # company name often missing in LF — use domain stem
                row["company_name"] = (c["domain"].split(".")[0] or "").replace("-", " ").title()
                rows.append(row)
                ready_here += 1
                seen_email.add(email)
                seen_domain.add(edom)
                seen_domain.add(c["domain"])
                seen_key.add(c["key"])
                print(
                    f"  ✓ [{len(rows)}/{ready_target}] {c['name']} <{email}> | {c['title']} @ {c['domain']}"
                )
                save()
                time.sleep(0.08)

            stats.append(
                {
                    "id": f"{seg['seg']}_{band}",
                    "searched": searched,
                    "candidates": len(candidates),
                    "email_attempts": attempts,
                    "email_hits": hits,
                    "skipped": skips,
                    "ready": ready_here,
                }
            )
            print(
                f"  done ready={ready_here} searched={searched} cand={len(candidates)} "
                f"email={hits}/{attempts}"
            )

    spend = spend_micro / 1e6
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
        "company_keywords",
        "person_linkedin",
        "company_linkedin",
    ]
    csv_path = OUT_DIR / "volume-ready.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "provider": "leadsforge+trykitt",
        "campaign_id": PLUSVIBE_CAMPAIGN_ID,
        "spend_usd": round(spend, 6),
        "ready_total": len(rows),
        "target": ready_target,
        "streams": stats,
        "unit_economics": {
            "cost_per_ready_usd": round(spend / max(len(rows), 1), 6),
            "cost_per_1k_ready_usd": round(spend / max(len(rows), 1) * 1000, 2),
        },
    }
    if upload and rows:
        print("\n=== PlusVibe upload ===")
        up = plusvibe_upload(rows)
        report["plusvibe_upload"] = {k: up[k] for k in ("added", "skipped", "errors")}
        (OUT_DIR / "plusvibe-upload.json").write_text(json.dumps(up, indent=2, default=str))
    (OUT_DIR / "volume-report.json").write_text(json.dumps(report, indent=2))
    save()
    print(json.dumps({k: report[k] for k in ("spend_usd", "ready_total", "unit_economics")}, indent=2))
    print(f"CSV: {csv_path}")


def main():
    if not TOKEN:
        print("Missing TOKEN", file=sys.stderr)
        sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-only", action="store_true")
    ap.add_argument("--full", type=int, default=0)
    ap.add_argument("--confirm-spend", type=float, default=None)
    ap.add_argument("--upload-plusvibe", action="store_true")
    args = ap.parse_args()
    if args.scope_only:
        scope_only()
        return
    if args.full:
        if args.confirm_spend is None:
            sys.exit("need --confirm-spend")
        run(args.full, args.confirm_spend, args.upload_plusvibe)
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
