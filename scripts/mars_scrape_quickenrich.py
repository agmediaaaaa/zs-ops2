#!/usr/bin/env python3
"""MARS volume fill: free Quickenrich people.search → Blitz email.find.

Used after the precise Icypeas pass to reach ~2k net-new leads while keeping
search free. Still excludes PlusVibe workspace leads and applies MARS ICP
post-filters (titles, emp bands, keyword accept/reject).

  python scripts/mars_scrape_quickenrich.py --scope-only
  python scripts/mars_scrape_quickenrich.py --full 1800 --confirm-spend 12 --upload-plusvibe
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

OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/mars-scrape/volume-qe"))
EXCLUDE_PATH = Path(
    os.environ.get("MARS_EXCLUDE_JSON", "/workspace/artifacts/mars-scrape/plusvibe_exclude.json")
)
PLUSVIBE_API_KEY = os.environ.get("PLUSVIBE_API_KEY", "")
PLUSVIBE_WORKSPACE_ID = os.environ.get("PLUSVIBE_WORKSPACE_ID", "6a8d53c5977bb5537e41fcf2")
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

TITLE_REJECT_RE = re.compile(
    r"("
    r"\bvp\b|vice[\s-]?president|assistant|sales|marketing|\bhr\b|human resources|"
    r"engineer|engineering|quality|purchasing|supply[\s-]?chain|"
    r"machinist|welder|operator|technician|accounting|admin|"
    r"project manager|product manager|\bcfo\b|\bcto\b|\bcmo\b|\bcio\b|"
    r"board|advisor|consultant|retired|former|intern|student|"
    r"senior vice|svp"
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
    r"casting (director|partner|agency)|talent casting|software|saas|"
    r"staffing|recruit|apparel|clothing|digital foundry|healthcare foundry|"
    r"protein foundry|sales agency|component sales|machine(?:ry)? sales|"
    r"equipment (dealer|broker)|distributor|wholesale|board chair|"
    r"airline spares|tax professional|capital partner|private equity"
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

SEGMENTS = [
    {
        "seg": "S1",
        "name": "Precision CNC / machine shops",
        "bio": [
            "CNC machining",
            "precision machining",
            "machine shop",
            "job shop",
            "contract machining",
            "Swiss turning",
            "wire EDM",
            "CNC mill",
            "CNC turning",
        ],
        "emp_cs": (10, 199),
        "emp_ops": (200, 500),
        "accept_re": re.compile(
            r"cnc|precision machin|machine shop|job shop|contract machin|"
            r"swiss turn|wire edm|\bedm\b|machining",
            re.I,
        ),
        "reject_re": re.compile(r"staffing|recruit|software|saas|sales agency", re.I),
    },
    {
        "seg": "S2",
        "name": "Foundries / metal casting",
        "bio": [
            "foundry",
            "metal casting",
            "investment casting",
            "sand casting",
            "die casting",
            "iron casting",
            "steel casting",
            "aluminum casting",
        ],
        "emp_cs": (10, 199),
        "emp_ops": (200, 500),
        "accept_re": re.compile(
            r"\bfoundry\b|metal casting|iron casting|steel casting|aluminum casting|"
            r"bronze casting|investment casting|sand casting|die casting|"
            r"permanent mold|lost wax|castings",
            re.I,
        ),
        "reject_re": re.compile(
            r"scrap|recycl|foundry supply|digital foundry|healthcare foundry|"
            r"protein foundry|fierce foundry|talent|software|saas|staffing|"
            r"foundry commercial|commercial real estate",
            re.I,
        ),
    },
    {
        "seg": "S3",
        "name": "AS9100 aerospace / turbine",
        "bio": [
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
            r"as.?9100|nadcap|aerospace machin|aircraft parts|aircraft components|"
            r"turbine components|jet engine|"
            r"(aerospace|aircraft|turbine).{0,120}(machin|cnc|mill|turn)|"
            r"(machin|cnc).{0,120}(aerospace|aircraft|turbine|as.?9100|nadcap)",
            re.I,
        ),
        "reject_re": re.compile(
            r"staffing|software|saas|airline passenger|airline spares|airport|mro(?!.*machin)",
            re.I,
        ),
    },
    {
        "seg": "S4",
        "name": "Sheet metal / fabrication",
        "bio": [
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
            r"sheet[\s-]?metal|precision sheet|metal fabricat|press brake|"
            r"laser cut|cnc punch|fabricat",
            re.I,
        ),
        "reject_re": re.compile(
            r"\bhvac\b|roofing|ductwork|steel service|construction|mining|"
            r"staffing|software|saas|fence|awning",
            re.I,
        ),
    },
]


def call(endpoint: str, body: dict | None = None, query: dict | None = None, method: str | None = None):
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
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.startswith("http://"):
        u = "https://" + u[len("http://") :]
    if u.startswith("linkedin.com/"):
        u = "https://www." + u
    if u.startswith("www.linkedin.com/"):
        u = "https://" + u
    u = u.lower()
    if "?" in u:
        u = u.split("?", 1)[0]
    if "/in/" not in u:
        return ""
    return u.rstrip("/")


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


def parse_emp(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    s = str(raw)
    nums = [int(x) for x in re.findall(r"\d+", s.replace(",", ""))]
    if not nums:
        return None
    if len(nums) >= 2:
        return (nums[0] + nums[1]) // 2
    return nums[0]


def load_excludes():
    emails, linkedins, domains = set(), set(), set()
    if EXCLUDE_PATH.exists():
        data = json.loads(EXCLUDE_PATH.read_text())
        emails = {e.strip().lower() for e in data.get("emails") or [] if e}
        linkedins = {norm_linkedin(x) for x in data.get("linkedins") or [] if x}
        domains = {norm_domain(x) for x in data.get("domains") or [] if x} - FREEMAIL
    return {"emails": emails, "linkedins": linkedins, "domains": domains}


def seed_seen(seen_li, seen_email, seen_domain):
    for d in Path("/workspace/artifacts/mars-scrape").rglob("*ready.csv"):
        try:
            with open(d, newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("person_linkedin"):
                        seen_li.add(norm_linkedin(r["person_linkedin"]))
                    if r.get("email"):
                        seen_email.add(r["email"].strip().lower())
                    dom = norm_domain(r.get("company_website") or "")
                    if not dom and r.get("email") and "@" in r["email"]:
                        dom = r["email"].split("@", 1)[1].lower()
                    if dom and dom not in FREEMAIL:
                        seen_domain.add(dom)
        except Exception:
            pass


def title_ok(title: str, band: str) -> bool:
    if not title or TITLE_REJECT_RE.search(title):
        return False
    keep = CSUITE_KEEP_RE if band == "CS" else OPS_KEEP_RE
    return bool(keep.search(title))


def extract_email(eout: dict) -> str | None:
    if not isinstance(eout, dict):
        return None
    if eout.get("email"):
        return str(eout["email"]).strip().lower()
    for item in eout.get("all_emails") or []:
        if isinstance(item, dict) and item.get("email"):
            return str(item["email"]).strip().lower()
    # treg routed shape
    out = eout.get("output") if isinstance(eout.get("output"), dict) else None
    if out and out.get("email"):
        return str(out["email"]).strip().lower()
    return None


def plusvibe_upload(rows: list[dict], batch_size: int = 50) -> dict:
    added = skipped = errors = 0
    details = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        leads = []
        for r in batch:
            name = (r.get("name") or "").strip()
            first, last = (name.split(" ", 1) + [""])[:2] if name else ("", "")
            leads.append(
                {
                    "email": r["email"],
                    "first_name": first,
                    "last_name": last,
                    "company_name": r.get("company_name") or "",
                    "company_website": r.get("company_website") or "",
                    "linkedin_person_url": r.get("person_linkedin") or "",
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
            added += int(body.get("leads_uploaded") or body.get("added") or len(batch))
            skipped += int(body.get("skipped") or body.get("already_in_campaign") or 0)
            details.append({"batch": i // batch_size, "response": body})
            print(f"  uploaded batch {i // batch_size}: +{len(batch)}")
        except urllib.error.HTTPError as e:
            errors += len(batch)
            details.append({"batch": i // batch_size, "error": e.read().decode()[:400]})
            print(f"  upload fail batch {i // batch_size}: {e}")
        time.sleep(0.25)
    return {"added": added, "skipped": skipped, "errors": errors, "details": details}


def scope_only():
    print("=== FREE TAM (quickenrich.people.search) — MARS ===")
    for seg in SEGMENTS:
        for band, titles in (("CS", CSUITE_TITLES), ("OPS", OPS_TITLES)):
            body = {
                "title": {"include": titles},
                "country_code": {"include": ["US"]},
                "bio_li": {"include": seg["bio"]},
                "per_page": 1,
                "has_email": True,
            }
            out, cost = call("quickenrich.people.search", body)
            assert cost == 0, cost
            total = (out.get("meta") or {}).get("total") or 0
            print(f"  {seg['seg']}_{band}: {total:,}  {seg['name']}")


def run(ready_target: int, hard_cap: float, upload: bool):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    excl = load_excludes()
    seen_li = set(excl["linkedins"])
    seen_email = set(excl["emails"])
    seen_domain = set(excl["domains"])
    seed_seen(seen_li, seen_email, seen_domain)
    print(
        f"Excludes+seed: li={len(seen_li)} email={len(seen_email)} domain={len(seen_domain)}"
    )

    spend_micro = 0
    rows: list[dict] = []
    progress_path = OUT_DIR / "progress.json"
    stream_stats = []

    def pay(endpoint, body):
        nonlocal spend_micro
        if spend_micro / 1e6 >= hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap}")
        out, cost = call(endpoint, body)
        spend_micro += cost
        if spend_micro / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded (${spend_micro/1e6:.4f})")
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

    # Round-robin segments; within each do CS then OPS
    per = max(1, ready_target // (len(SEGMENTS) * 2))
    for seg in SEGMENTS:
        for band, titles, (lo, hi), keep_re in (
            ("CS", CSUITE_TITLES, seg["emp_cs"], CSUITE_KEEP_RE),
            ("OPS", OPS_TITLES, seg["emp_ops"], OPS_KEEP_RE),
        ):
            if len(rows) >= ready_target:
                break
            want = min(per + 50, ready_target - len(rows))
            # allow later streams to catch shortfall
            want = max(want, min(400, ready_target - len(rows)))
            print(f"\n--- {seg['seg']}_{band} {seg['name']} want={want} ---")
            cursor = None
            page = 0
            searched = 0
            candidates = []
            cand_goal = min(want * 3, 900)
            while page < 60 and len(candidates) < cand_goal:
                body = {
                    "title": {"include": titles},
                    "country_code": {"include": ["US"]},
                    "bio_li": {"include": seg["bio"]},
                    "per_page": 50,
                    "has_email": True,
                }
                if cursor:
                    body["cursor"] = cursor
                try:
                    out, cost = call("quickenrich.people.search", body)
                except urllib.error.HTTPError as e:
                    print(f"  search http {e.code}, stop paging")
                    break
                assert cost == 0
                data = out.get("data") or []
                page += 1
                searched += len(data)
                if not data:
                    break
                for d in data:
                    title = d.get("title") or ""
                    if not title_ok(title, band):
                        continue
                    emp = parse_emp(d.get("employee_count"))
                    if emp is not None and not (lo <= emp <= hi):
                        continue
                    blob = " ".join(
                        str(x or "")
                        for x in [
                            title,
                            d.get("company_name"),
                            d.get("industry"),
                            d.get("company_url"),
                            " ".join(d.get("services") or [])
                            if isinstance(d.get("services"), list)
                            else d.get("services"),
                        ]
                    )
                    if GLOBAL_REJECT_RE.search(blob) or seg["reject_re"].search(blob):
                        continue
                    if not seg["accept_re"].search(blob):
                        continue
                    li = norm_linkedin(d.get("employee_linkedin") or "")
                    if not li or li in seen_li:
                        continue
                    dom = norm_domain(d.get("company_url") or d.get("email_domain") or "")
                    if dom and (dom in seen_domain or dom in FREEMAIL):
                        continue
                    candidates.append(d)
                    if len(candidates) >= cand_goal:
                        break
                cursor = (out.get("meta") or {}).get("next_cursor")
                if not cursor or not (out.get("meta") or {}).get("has_more"):
                    break
                time.sleep(0.05)

            ready_here = 0
            attempts = hits = pv = 0
            for d in candidates:
                if ready_here >= want or len(rows) >= ready_target:
                    break
                li = norm_linkedin(d.get("employee_linkedin") or "")
                if not li or li in seen_li:
                    continue
                attempts += 1
                try:
                    eout = pay("blitzapi.people.email.find", {"person_linkedin_url": li})
                except RuntimeError as e:
                    print(f"  cap stop: {e}")
                    break
                except urllib.error.HTTPError as e:
                    err = e.read().decode()[:180] if hasattr(e, "read") else str(e)
                    print(f"  email http {e.code} skip ({li}): {err}")
                    time.sleep(0.1)
                    continue
                email = extract_email(eout)
                if not email or "@" not in email:
                    time.sleep(0.04)
                    continue
                hits += 1
                domain = email.split("@", 1)[1]
                if domain in FREEMAIL:
                    continue
                if email in seen_email or domain in seen_domain:
                    pv += 1
                    continue
                name = f"{d.get('first_name') or ''} {d.get('last_name') or ''}".strip()
                row = {
                    "seg": seg["seg"],
                    "band": band,
                    "stream_id": f"{seg['seg']}_{band}",
                    "stream_name": seg["name"],
                    "name": name,
                    "job_title": d.get("title"),
                    "employee_count": parse_emp(d.get("employee_count")),
                    "company_desc": "",
                    "email": email,
                    "email_status": "unverified",
                    "location": ", ".join(
                        x for x in [d.get("city"), d.get("region_code"), d.get("country_code")] if x
                    ),
                    "company_name": d.get("company_name"),
                    "company_website": d.get("company_url") or d.get("email_domain"),
                    "company_industry": d.get("industry"),
                    "person_linkedin": li,
                    "company_linkedin": d.get("company_linked") or "",
                }
                rows.append(row)
                ready_here += 1
                seen_li.add(li)
                seen_email.add(email)
                seen_domain.add(domain)
                print(
                    f"  ✓ [{len(rows)}/{ready_target}] {name} <{email}> | {row['job_title']} @ {row['company_name']}"
                )
                save()
                time.sleep(0.05)

            stream_stats.append(
                {
                    "id": f"{seg['seg']}_{band}",
                    "searched": searched,
                    "candidates": len(candidates),
                    "email_attempts": attempts,
                    "email_hits": hits,
                    "pv_skipped": pv,
                    "ready": ready_here,
                }
            )
            print(
                f"  done ready={ready_here} searched={searched} cand={len(candidates)} "
                f"email={hits}/{attempts} pv={pv}"
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
        "provider": "quickenrich+blitz",
        "campaign_id": PLUSVIBE_CAMPAIGN_ID,
        "spend_usd": round(spend, 6),
        "hard_cap_usd": hard_cap,
        "ready_total": len(rows),
        "target": ready_target,
        "streams": stream_stats,
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
        print("Missing TREG_TOKEN", file=sys.stderr)
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
            print("Need --confirm-spend", file=sys.stderr)
            sys.exit(2)
        run(args.full, args.confirm_spend, args.upload_plusvibe)
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
