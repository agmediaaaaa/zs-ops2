#!/usr/bin/env python3
"""ATC NP-PA Facilities Broad — Pull-N Icypeas → Blitz (cheap scrape).

Gates:
  --scope-only          free Icypeas TAM only
  --pull N              Pull-N people (enrich that batch only)
  --confirm-spend USD   hard spend cap (required for paid)
  --exclude-json PATH   emails / linkedin / domains
  --upload-supabase     bulk upsert Lead Database + lead_lists

Example:
  python scripts/atc_np_pa_facilities_broad_oct21.py --scope-only \\
      --exclude-json artifacts/atc-np-pa-broad-oct21/exclude.json
  python scripts/atc_np_pa_facilities_broad_oct21.py --pull 100 --confirm-spend 0.12 \\
      --exclude-json artifacts/atc-np-pa-broad-oct21/exclude.json --upload-supabase
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

OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/atc-np-pa-broad-oct21"))
LIST_NAME = os.environ.get("ATC_LIST_NAME") or "ATC NP-PA Facilities Broad Oct 21"
CLIENT = "ATC"
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://npkdhahdvilcctjwzdlf.supabase.co").strip()
SUPABASE_KEY = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip().strip('"').strip("'")

TITLE_INCLUDE = [
    "CEO",
    "Founder",
    "Co-Founder",
    "Owner",
    "Co-Owner",
    "President",
    "COO",
    "Managing Partner",
    "Managing Member",
    "Partner",
    "Principal",
    "Practice Owner",
    "Clinic Owner",
    "Head of Operations",
    "Executive Director",
    "Administrator",
    "Practice Administrator",
    "Practice Manager",
    "Medical Director",
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
    "Associate Medical",
    "Assistant Medical",
    "Regional",
    "Product Owner",
    "Process Owner",
]

INDUSTRY_INCLUDE = [
    "Medical Practices",
    "Outpatient Care Centers",
    "Mental Health Care",
    "Physicians",
    "Hospitals and Health Care",
    "Home Health Care Services",
    "Physical, Occupational and Speech Therapists",
]

INDUSTRY_EXCLUDE = [
    "Staffing and Recruiting",
    "Insurance",
    "Pharmaceutical Manufacturing",
    "Biotechnology Research",
    "Medical Equipment Manufacturing",
    "Medical Device",
    "Higher Education",
    "E-Learning Providers",
    "Non-profit Organizations",
    "Government Administration",
    "Software Development",
    "IT Services and IT Consulting",
    "Technology, Information and Internet",
    "Advertising Services",
    "Marketing Services",
    "Wellness and Fitness Services",
    "Personal Care Product Manufacturing",
    "Retail Health and Personal Care Products",
    "Business Consulting and Services",
]

KW_INCLUDE = [
    "urgent care",
    "walk-in clinic",
    "primary care",
    "family practice",
    "family medicine",
    "internal medicine",
    "pediatrics",
    "concierge medicine",
    "direct primary care",
    "house calls",
    "home-based primary care",
    "mobile medical",
    "retail clinic",
    "occupational medicine",
    "employer clinic",
    "onsite clinic",
    "dermatology",
    "med spa",
    "medical spa",
    "medical aesthetics",
    "medical weight loss",
    "men's health",
    "hormone replacement",
    "women's health",
    "OB/GYN",
    "fertility clinic",
    "pain management",
    "orthopedic",
    "sports medicine",
    "cardiology",
    "gastroenterology",
    "urology",
    "endocrinology",
    "pulmonology",
    "neurology",
    "oncology practice",
    "wound care",
    "podiatry",
    "sleep medicine",
    "outpatient psychiatry",
    "psychiatric nurse practitioner",
    "PMHNP",
    "ketamine clinic",
    "TMS therapy",
    "Suboxone",
    "medication-assisted treatment",
    "opioid treatment",
    "addiction treatment",
    "behavioral health",
    "community health center",
    "FQHC",
    "rural health clinic",
    "telehealth practice",
    "geriatric medicine",
    "senior primary care",
    "palliative care",
    "hospice",
    "post-acute care",
    "skilled nursing",
    "nurse practitioner",
    "physician assistant",
    "APRN",
    "NP-led",
    "PA-C",
]

KW_EXCLUDE = [
    "staffing",
    "recruiting",
    "locum tenens",
    "travel nursing",
    "healthcare staffing",
    "medical billing",
    "revenue cycle",
    "EHR",
    "EMR",
    "healthcare software",
    "health tech",
    "SaaS",
    "healthcare consulting",
    "marketing agency",
    "medical device",
    "pharmaceutical",
    "biotech",
    "laboratory",
    "diagnostics",
    "medical supplies",
    "durable medical equipment",
    "insurance",
    "health plan",
    "university",
    "nursing school",
    "education",
    "CME",
    "nonprofit",
    "foundation",
    "association",
    "government",
    "veterinary",
    "dental",
    "chiropractic",
    "massage",
    "yoga",
    "fitness",
    "gym",
    "salon",
    "spa resort",
    "supplements",
    "nutrition coaching",
    "life coaching",
    "wellness retreat",
    "recruiter",
    "headhunt",
    "job board",
    "talent acquisition",
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
    "advertising",
    "digital marketing",
    "AI platform",
    "e-learning",
    "non-profit",
    "hospital system",
    "acute care hospital",
    # Pilot junk (Oct 21)
    "locum",
    "locums",
    "linen",
    "laundry",
    "medical equipment",
    "genomics",
    "marketing",
    "advertising agency",
    "trade association",
    "membership association",
    "health tech platform",
    "digital health platform",
]

COMPANY_NAME_EXCLUDE = [
    "TeamHealth",
    "Envision",
    "MinuteClinic",
    "CVS",
    "Walgreens",
    "Teladoc",
    "Amwell",
    "Hims & Hers",
    "Hims",
    "One Medical",
    "Forward",
    "Carbon Health",
    "Optum",
    # Pilot junk company names
    "Censible Marketing",
    "EcoBrite Linen",
    "Medical Equipment Dynamics",
    "UrologyLocums",
    "Nurture Genomics",
    "HealthEx",
    "PeelAways",
    "Reading2Connect",
]

HARD_DOMAINS = [
    "teamhealth.com",
    "envisionhealth.com",
    "envisionhealthcare.com",
    "minuteclinic.com",
    "cvs.com",
    "walgreens.com",
    "teladoc.com",
    "amwell.com",
    "hims.com",
    "forhers.com",
    "onemedical.com",
    "goforward.com",
    "carbonhealth.com",
    "optum.com",
    "himsandhers.com",
]

FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "me.com", "live.com"}

TITLE_REJECT_RE = re.compile(
    r"(?i)\b(vice\s+president|\bvp\b|assistant|sales|marketing|\bhr\b|engineer|"
    r"intern|student|retired|former|consultant|advisor|board\s+member|"
    r"recruiter|recruiting|associate\s+medical|assistant\s+medical|"
    r"\bregional\b|product\s+owner|process\s+owner)\b"
)

TITLE_ACCEPT_RE = re.compile(
    r"(?i)\b(ceo|chief\s+executive|founder|co-?founder|owner|co-?owner|president|"
    r"coo|chief\s+operating|managing\s+partner|managing\s+member|\bpartner\b|"
    r"principal|practice\s+owner|clinic\s+owner|head\s+of\s+operations|"
    r"executive\s+director|administrator|practice\s+administrator|"
    r"practice\s+manager|medical\s+director)\b"
)


def build_query(domain_exclude: list[str] | None = None) -> dict:
    domains = list(dict.fromkeys(HARD_DOMAINS + (domain_exclude or [])))[:2000]
    return {
        "currentJobTitle": {"include": TITLE_INCLUDE, "exclude": TITLE_EXCLUDE},
        "profileLocation": {"include": ["US"]},
        "location": {"include": ["US"]},
        "currentCompany.headcount": {">=": 2, "<=": 500},
        "currentCompany.industry": {"include": INDUSTRY_INCLUDE, "exclude": INDUSTRY_EXCLUDE},
        "keyword": {"include": KW_INCLUDE, "exclude": KW_EXCLUDE},
        "currentCompanyName": {"exclude": COMPANY_NAME_EXCLUDE},
        "currentCompanyWebsite": {"exclude": domains},
    }


def call(endpoint: str, body: dict | None = None, retries: int = 5) -> tuple[dict, int]:
    import socket

    data = None if body is None else json.dumps(body).encode()
    hdrs = {"X-Treg-Token": TOKEN, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if "email.find" in endpoint:
        hdrs["X-Treg-Route-Max-Cost"] = "0.01"
        hdrs["X-Treg-Route-Waterfall"] = "0"
        hdrs["X-Treg-Route-Exclude"] = "aiark,icypeas"
    last_err: Exception | None = None
    # Avoid indefinite DNS hangs that bypass urllib's timeout on some resolvers.
    socket.setdefaulttimeout(60)
    for attempt in range(retries):
        req = urllib.request.Request(
            f"https://treg.to/call/{endpoint}",
            data=data,
            method="POST" if body is not None else "GET",
            headers=hdrs,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
                raw = resp.read()
                out = json.loads(raw.decode()) if raw else {}
                # Floor costs when header under-reports (observed mid-run undercount vs ledger).
                if endpoint == "icypeas.people.search":
                    n = len(out.get("leads") or [])
                    cost = max(cost, int(round(n * 380)))
                if endpoint == "blitzapi.people.email.find":
                    email = None
                    if isinstance(out, dict):
                        email = out.get("email")
                        if not email:
                            for item in out.get("all_emails") or []:
                                if isinstance(item, dict) and item.get("email"):
                                    email = item["email"]
                                    break
                    if email:
                        cost = max(cost, 495)
                return out, cost
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(min(2**attempt, 20))
    assert last_err is not None
    raise last_err


def norm_li(u: str) -> str:
    u = (u or "").lower().split("?")[0].rstrip("/")
    u = u.replace("http://", "https://")
    u = u.replace("https://linkedin.com", "https://www.linkedin.com")
    return u


def bare_host(v: str) -> str:
    v = (v or "").strip().lower()
    if not v:
        return ""
    if "@" in v and "://" not in v and "/" not in v:
        return v.split("@", 1)[-1]
    if "://" not in v:
        v = "http://" + v
    try:
        host = urlparse(v).hostname or ""
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def load_exclude(path: str | None) -> tuple[set[str], set[str], list[str]]:
    if not path:
        return set(), set(), []
    data = json.loads(Path(path).read_text())
    emails = {e.lower().strip() for e in data.get("emails") or [] if e}
    linkedin = {norm_li(u) for u in data.get("linkedin") or [] if u}
    domains = sorted({d.lower().strip() for d in data.get("domains") or [] if d and "." in d})
    return emails, linkedin, domains


def title_ok(title: str) -> bool:
    t = title or ""
    if TITLE_REJECT_RE.search(t):
        return False
    return bool(TITLE_ACCEPT_RE.search(t))


def emp_ok(n) -> bool:
    try:
        n = int(n)
        return 2 <= n <= 500
    except Exception:
        return False


def scope_only(exclude_path: str | None) -> None:
    _, _, domains = load_exclude(exclude_path)
    q = build_query(domains)
    out, cost = call("icypeas.people.search.count", {"query": q})
    assert cost == 0, cost
    print(json.dumps({"tam": out.get("total"), "domain_exclude_in_query": min(2000, len(HARD_DOMAINS) + len(domains))}, indent=2))


def extract_email(eout: dict) -> str | None:
    email = eout.get("email") if isinstance(eout, dict) else None
    if email:
        return str(email).strip()
    for item in (eout.get("all_emails") or []) if isinstance(eout, dict) else []:
        if isinstance(item, dict) and item.get("email"):
            return str(item["email"]).strip()
        if isinstance(item, str) and "@" in item:
            return item.strip()
    return None


def supabase_headers() -> dict:
    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY missing")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def sb_request(method: str, path: str, body: list | dict | None = None, extra_headers: dict | None = None) -> list | dict:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{path}"
    hdrs = supabase_headers()
    if extra_headers:
        hdrs.update(extra_headers)
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else []


def upload_supabase(rows: list[dict], report: dict) -> dict:
    """Bulk insert/patch Lead Database + create list + members. No per-lead loops for API spam — batched."""
    if not rows:
        return {"inserted": 0, "existing": 0, "members": 0, "list_id": None}

    emails = [r["email"].lower().strip() for r in rows]
    # Fetch existing by email in one IN filter (chunked)
    existing: dict[str, int] = {}
    chunk = 80
    for i in range(0, len(emails), chunk):
        part = emails[i : i + chunk]
        # PostgREST: Email=in.(a,b)
        quoted = ",".join('"' + e.replace('"', "") + '"' for e in part)
        path = f'Lead%20Database?select=id,Email&Email=in.({quoted})'
        got = sb_request("GET", path)
        for g in got if isinstance(got, list) else []:
            existing[(g.get("Email") or "").lower().strip()] = int(g["id"])

    to_insert = []
    to_patch = []
    email_to_id: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        el = r["email"].lower().strip()
        first, _, last = (r.get("name") or "").partition(" ")
        payload = {
            "First Name": first.strip() or None,
            "Last Name": last.strip() or None,
            "Email": r["email"],
            "Linkedin": r.get("person_linkedin"),
            "Company Name": r.get("company_name"),
            "Website": r.get("company_website"),
            "company_size": str(r.get("employee_count") or ""),
            "company_description": r.get("company_desc") or "",
            "location": r.get("location"),
            "title": r.get("job_title"),
            "company_industry": r.get("company_industry"),
            "email_source": "blitzapi.people.email.find",
            "email_status": "found",
            "enrichment_updated_at": now,
        }
        if el in existing:
            payload["id"] = existing[el]
            to_patch.append(payload)
            email_to_id[el] = existing[el]
        else:
            to_insert.append(payload)

    inserted_ids: list[int] = []
    if to_insert:
        for i in range(0, len(to_insert), 100):
            batch = to_insert[i : i + 100]
            got = sb_request("POST", "Lead%20Database", batch, {"Prefer": "return=representation"})
            for g in got if isinstance(got, list) else []:
                eid = (g.get("Email") or "").lower().strip()
                email_to_id[eid] = int(g["id"])
                inserted_ids.append(int(g["id"]))

    patched = 0
    for p in to_patch:
        lid = p.pop("id")
        sb_request("PATCH", f"Lead%20Database?id=eq.{lid}", p, {"Prefer": "return=minimal"})
        patched += 1

    list_row = {
        "client": CLIENT,
        "list_name": LIST_NAME,
        "source": "treg.to / icypeas→blitz",
        "status": "enriched",
        "total_leads": len(rows),
        "enriched_count": len(rows),
        "ready_count": len(rows),
        "failed_count": 0,
        "skipped_count": report.get("skipped_known", 0),
        "estimated_cost_usd": report.get("quote_expected_usd"),
        "actual_cost_usd": report.get("spend_usd"),
        "cost_cap_usd": report.get("hard_cap_usd"),
        "enrichment_started_at": report.get("started_at"),
        "enrichment_completed_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "path": "icypeas.people.search → blitzapi.people.email.find",
            "pull": report.get("pulled"),
            "coverage": report.get("coverage"),
            "plusvibe_upload": False,
            "run": "atc-np-pa-facilities-broad-oct21-pilot",
        },
        "run_report": {k: report[k] for k in report if k != "rows"},
    }
    created = sb_request("POST", "lead_lists", list_row, {"Prefer": "return=representation"})
    list_id = (created[0] if isinstance(created, list) else created)["list_id"]

    members = []
    for r in rows:
        el = r["email"].lower().strip()
        lid = email_to_id.get(el)
        if not lid:
            continue
        members.append(
            {
                "list_id": list_id,
                "lead_id": lid,
                "enrichment_status": "enriched",
                "enrichment_completed_at": now,
                "cost_micro": None,
            }
        )
    for i in range(0, len(members), 200):
        sb_request("POST", "lead_list_members", members[i : i + 200], {"Prefer": "return=minimal"})

    return {
        "list_id": list_id,
        "list_name": LIST_NAME,
        "inserted": len(inserted_ids),
        "patched": patched,
        "members": len(members),
        "existing": len(existing),
    }


def run_pull(
    pull: int,
    hard_cap: float,
    exclude_path: str | None,
    do_upload: bool,
    resume_pulled: str | None = None,
    spend_already: float = 0.0,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    excl_emails, excl_li, excl_domains = load_exclude(exclude_path)
    seen_li = set(excl_li)
    seen_email = set(excl_emails)
    spend_micro = int(round(max(spend_already, 0.0) * 1e6))
    query = build_query(excl_domains)
    if spend_micro:
        print(f"Resuming with spend_already=${spend_already:.4f} (micro={spend_micro})")

    def pay(endpoint: str, body: dict | None = None) -> dict:
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
        if endpoint == "blitzapi.people.email.find":
            # Blitz bills on success only; reserve worst-case success unit so we never overshoot cap.
            projected = spend_micro / 1e6 + 0.000495
            if projected > hard_cap:
                raise RuntimeError(
                    f"hard cap ${hard_cap} would be exceeded by next email.find "
                    f"(projected ${projected:.4f})"
                )
        out, cost = call(endpoint, body)
        spend_micro += cost
        if spend_micro / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded (spent ${spend_micro/1e6:.4f})")
        return out

    print(f"Exclude: emails={len(excl_emails)} linkedin={len(excl_li)} domains={len(excl_domains)}")
    pulled_rows: list[dict] = []
    searched = 0
    skipped_known = 0
    title_emp_fail = 0
    no_li = 0
    tam = None

    if resume_pulled:
        pulled_rows = json.loads(Path(resume_pulled).read_text())
        print(f"=== RESUME from {resume_pulled} n={len(pulled_rows)} (skip Icypeas search) ===")
        # Load any prior ready checkpoint emails so we don't re-upload duplicates.
        ck_ready = OUT_DIR / "checkpoint-ready.json"
        if ck_ready.exists():
            prior = json.loads(ck_ready.read_text())
            for r in prior:
                el = (r.get("email") or "").lower().strip()
                if el:
                    seen_email.add(el)
            print(f"  prior ready emails in seen_email: {len(prior)}")
        salvaged = OUT_DIR / "salvaged-ready.json"
        if salvaged.exists():
            for r in json.loads(salvaged.read_text()):
                el = (r.get("email") or "").lower().strip()
                if el:
                    seen_email.add(el)
    else:
        print("=== FREE TAM ===")
        tam = pay("icypeas.people.search.count", {"query": query}).get("total") or 0
        print(f"  TAM={tam:,}")

        # Pull-N: fetch exactly `pull` people (after safety-net title/emp + LI skip), then enrich that batch only.
        token = None
        page_size = min(100, max(25, min(pull, 100)))
        # High skip rates (known LI/domain) need many more search pages than pull/page_size.
        max_pages = max(50, (pull * 4) // page_size + 20)

        print(f"=== PULL-N search pull={pull} page_size={page_size} max_pages={max_pages} ===")
        for _ in range(max_pages):
            if len(pulled_rows) >= pull:
                break
            need = pull - len(pulled_rows)
            size = min(page_size, max(need * 2, need))  # slight overfetch for skips
            body: dict = {"query": query, "pagination": {"size": size}}
            if token:
                body["pagination"]["token"] = token
            try:
                out = pay("icypeas.people.search", body)
            except RuntimeError as e:
                print(f"  stop/search: {e}")
                break
            leads = out.get("leads") or []
            searched += len(leads)
            if not leads:
                break
            for L in leads:
                if len(pulled_rows) >= pull:
                    break
                title = L.get("lastJobTitle") or L.get("headline") or ""
                if not title_ok(title) or not emp_ok(L.get("lastCompanySize")):
                    title_emp_fail += 1
                    continue
                li = norm_li(L.get("profileUrl") or "")
                if not li:
                    no_li += 1
                    continue
                if li in seen_li:
                    skipped_known += 1
                    continue
                # domain skip (safety beyond in-query)
                host = bare_host(L.get("lastCompanyWebsite") or "")
                if host and host in set(excl_domains):
                    skipped_known += 1
                    continue
                seen_li.add(li)
                pulled_rows.append(L)
            token = (out.get("pagination") or {}).get("token")
            print(
                f"  page searched+= {len(leads)} pulled={len(pulled_rows)}/{pull} "
                f"skipped_known={skipped_known} spend=${spend_micro/1e6:.4f}"
            )
            if not token:
                break
            time.sleep(0.15)

        # Checkpoint pulled batch so a mid-Blitz crash can resume without re-search.
        (OUT_DIR / "checkpoint-pulled.json").write_text(json.dumps(pulled_rows))
        print(f"  checkpoint-pulled.json n={len(pulled_rows)}")

    print(f"=== BLITZ email.find on pulled={len(pulled_rows)} (not until-N-ready) ===")
    ready: list[dict] = []
    attempts = hits = freemail = no_desc = 0
    cols_ckpt = [
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

    def flush_ready_ckpt() -> None:
        with open(OUT_DIR / "checkpoint-ready.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols_ckpt, extrasaction="ignore")
            w.writeheader()
            w.writerows(ready)
        (OUT_DIR / "checkpoint-ready.json").write_text(json.dumps(ready))
        (OUT_DIR / "checkpoint-meta.json").write_text(
            json.dumps(
                {
                    "spend_usd": round(spend_micro / 1e6, 6),
                    "ready": len(ready),
                    "attempts": attempts,
                    "hits": hits,
                    "pulled": len(pulled_rows),
                    "searched": searched,
                },
                indent=2,
            )
        )

    for L in pulled_rows:
        if spend_micro / 1e6 >= hard_cap:
            print("  stop: hard cap")
            break
        li = norm_li(L.get("profileUrl") or "")
        attempts += 1
        try:
            eout = pay("blitzapi.people.email.find", {"person_linkedin_url": L.get("profileUrl")})
        except RuntimeError as e:
            print(f"  stop/email: {e}")
            break
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"  stop/email transport: {e}")
            flush_ready_ckpt()
            break
        email = extract_email(eout if isinstance(eout, dict) else {})
        if not email:
            continue
        el = email.lower().strip()
        if el in seen_email:
            skipped_known += 1
            continue
        domain = el.rsplit("@", 1)[-1]
        if domain in FREEMAIL:
            freemail += 1
            continue
        desc = (L.get("lastCompanyDescription") or "").strip()
        if not desc:
            no_desc += 1
            continue
        seen_email.add(el)
        hits += 1
        row = {
            "name": f"{L.get('firstname') or ''} {L.get('lastname') or ''}".strip(),
            "job_title": L.get("lastJobTitle") or L.get("headline"),
            "employee_count": L.get("lastCompanySize"),
            "company_desc": desc[:800],
            "email": email,
            "location": L.get("address") or L.get("lastCompanyAddress"),
            "company_name": L.get("lastCompanyName"),
            "company_website": L.get("lastCompanyWebsite"),
            "company_industry": L.get("lastCompanyIndustry"),
            "person_linkedin": li,
            "company_linkedin": L.get("lastCompanyUrl"),
        }
        ready.append(row)
        print(f"  ✓ {row['name']} <{email}> @ {row['company_name']}  [${spend_micro/1e6:.4f}]")
        if len(ready) % 5 == 0:
            flush_ready_ckpt()
            print(f"  checkpoint-ready n={len(ready)} spend=${spend_micro/1e6:.4f}")
        time.sleep(0.08)
        if attempts % 50 == 0:
            flush_ready_ckpt()
            print(
                f"  progress attempts={attempts} ready={len(ready)} "
                f"hits={hits} freemail={freemail} no_desc={no_desc} spend=${spend_micro/1e6:.4f}"
            )
    flush_ready_ckpt()

    spend = spend_micro / 1e6
    pulled_n = len(pulled_rows)
    ready_n = len(ready)
    pull_for_quote = pull or pulled_n
    expected = pull_for_quote * 0.00038 + pull_for_quote * 0.45 * 0.000495
    max_usd = pull_for_quote * 0.00038 + pull_for_quote * 0.000495
    report = {
        "started_at": started,
        "at": datetime.now(timezone.utc).isoformat(),
        "client": CLIENT,
        "list_name": LIST_NAME,
        "path": "icypeas.people.search → blitzapi.people.email.find",
        "model": "pull_n",
        "hard_cap_usd": hard_cap,
        "quote_expected_usd": round(expected, 6),
        "quote_max_usd": round(max_usd, 6),
        "spend_usd": round(spend, 6),
        "variance_usd": round(spend - expected, 6),
        "tam": tam,
        "pulled": pulled_n,
        "resumed_from": resume_pulled,
        "spend_already_usd": spend_already,
        "searched_rows": searched,
        "skipped_known": skipped_known,
        "title_emp_fail": title_emp_fail,
        "no_linkedin": no_li,
        "email_attempts": attempts,
        "email_hits": hits,
        "freemail_drop": freemail,
        "no_company_desc": no_desc,
        "ready": ready_n,
        "coverage": round(ready_n / pulled_n, 4) if pulled_n else None,
        "unit_economics": {
            "search_rows_per_ready": round(searched / ready_n, 2) if ready_n else None,
            "email_attempts_per_ready": round(attempts / ready_n, 2) if ready_n else None,
            "cost_per_1k_ready_usd": round((spend / ready_n) * 1000, 2) if ready_n else None,
            "blitz_hit_rate": round(hits / attempts, 3) if attempts else None,
        },
        "excluded": {"emails": len(excl_emails), "linkedin": len(excl_li), "domains": len(excl_domains)},
        "rows": ready,
    }

    cols = [
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
        w.writerows(ready)
    (OUT_DIR / "pilot-report.json").write_text(json.dumps(report, indent=2))

    upload_info = None
    if do_upload and ready:
        print("=== SUPABASE bulk upload ===")
        upload_info = upload_supabase(ready, report)
        report["handoff"] = upload_info
        (OUT_DIR / "pilot-report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(upload_info, indent=2))

    summary = {
        k: report[k]
        for k in (
            "tam",
            "pulled",
            "ready",
            "coverage",
            "spend_usd",
            "quote_expected_usd",
            "quote_max_usd",
            "variance_usd",
            "unit_economics",
            "skipped_known",
            "email_attempts",
            "freemail_drop",
            "no_company_desc",
            "path",
        )
    }
    if upload_info:
        summary["handoff"] = upload_info
    print(json.dumps(summary, indent=2))


def main() -> None:
    if not TOKEN:
        print("Missing TREG_TOKEN / ~/.treg/config.json", file=sys.stderr)
        sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-only", action="store_true")
    ap.add_argument("--pull", type=int, default=0)
    ap.add_argument("--confirm-spend", type=float, default=None)
    ap.add_argument("--exclude-json", type=str, default=None)
    ap.add_argument("--upload-supabase", action="store_true")
    ap.add_argument(
        "--resume-pulled",
        type=str,
        default=None,
        help="Path to checkpoint-pulled.json — skip Icypeas search, Blitz only",
    )
    ap.add_argument(
        "--spend-already",
        type=float,
        default=0.0,
        help="USD already spent this wave (counts against --confirm-spend)",
    )
    args = ap.parse_args()
    if args.scope_only:
        scope_only(args.exclude_json)
        return
    if args.pull or args.resume_pulled:
        if args.confirm_spend is None:
            print("Paid run requires --confirm-spend USD", file=sys.stderr)
            sys.exit(2)
        run_pull(
            args.pull or 0,
            args.confirm_spend,
            args.exclude_json,
            args.upload_supabase,
            resume_pulled=args.resume_pulled,
            spend_already=args.spend_already,
        )
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
