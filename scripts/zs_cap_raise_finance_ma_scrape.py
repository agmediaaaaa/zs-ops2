#!/usr/bin/env python3
"""ZS Cap Raise / Finance / M&A — Pull-N Icypeas → Blitz Cheap Scrape.

Gates:
  --scope-only          free Icypeas TAM only
  --pull N              pull N people, enrich that batch only (requires --confirm-spend)
  --confirm-spend USD   hard spend cap
  --exclude-json PATH   {emails,linkedin,domains} from PlusVibe finance campaigns
  --upload-supabase     bulk upsert ready rows + create lead_lists entry

Example:
  python scripts/zs_cap_raise_finance_ma_scrape.py --scope-only \\
      --exclude-json artifacts/zs-cap-raise-finance-ma-oct21/exclude.json
  python scripts/zs_cap_raise_finance_ma_scrape.py --pull 100 --confirm-spend 0.25 \\
      --exclude-json artifacts/zs-cap-raise-finance-ma-oct21/exclude.json \\
      --upload-supabase
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

OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/zs-cap-raise-finance-ma-oct21"))
LIST_NAME = "ZS Cap Raise / Finance / M&A Oct 21"
CLIENT = "ZS"

TITLE_INCLUDE = [
    "Founder",
    "Co-Founder",
    "Owner",
    "CEO",
    "President",
    "Managing Partner",
    "Managing Director",
    "Partner",
    "Principal",
    "Managing Member",
]

TITLE_EXCLUDE = [
    "Associate",
    "Analyst",
    "Vice President",
    "VP",
    "Director of",
    "Compliance",
    "Operations",
    "Controller",
    "Accountant",
    "Bookkeeper",
    "Tax",
    "Loan Officer",
    "Mortgage",
    "Underwriter",
    "Wealth",
    "Financial Advisor",
    "Insurance",
    "Recruiter",
    "Intern",
    "Assistant",
    "Sales",
    "Marketing",
    "HR",
    "Engineer",
    "Student",
    "Retired",
    "Former",
    "Consultant",
    "Advisor",
    "Board Member",
    "Account Executive",
]

KEYWORD_INCLUDE = [
    "M&A advisory",
    "mergers and acquisitions",
    "sell-side",
    "buy-side",
    "investment bank",
    "boutique investment bank",
    "middle market",
    "lower middle market",
    "business broker",
    "exit planning",
    "capital raising",
    "capital advisory",
    "private placement",
    "growth capital",
    "equity raise",
    "debt advisory",
    "debt placement",
    "structured finance",
    "recapitalization",
    "fundraising advisory",
    "placement agent",
    "corporate finance advisory",
]

KEYWORD_EXCLUDE = [
    "bookkeeping",
    "accounting",
    "CPA",
    "tax",
    "payroll",
    "fractional CFO",
    "lending",
    "lender",
    "loans",
    "merchant cash advance",
    "MCA",
    "SBA loan",
    "equipment financing",
    "factoring",
    "mortgage",
    "real estate",
    "wealth management",
    "financial planning",
    "insurance",
    "credit repair",
    "staffing",
    "recruiting",
]

INDUSTRY_INCLUDE = [
    "Investment Banking",
    "Capital Markets",
    "Venture Capital and Private Equity Principals",
    "Financial Services",
    "Business Consulting and Services",
]

INDUSTRY_EXCLUDE = [
    "Accounting",
    "Banking",
    "Credit Intermediation",
    "Loan Brokers",
    "Insurance",
    "Insurance Agencies and Brokerages",
    "Real Estate",
    "Commercial Real Estate",
    "Investment Management",
    "Investment Advice",
    "Staffing and Recruiting",
]

FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "live.com", "msn.com"}

# Safety net only — ICP is in-query
TITLE_REJECT_RE = re.compile(
    r"\b(vice\s+president|\bvp\b|associate|analyst|intern|recruiter|accountant|"
    r"bookkeeper|loan\s+officer|underwriter|financial\s+advisor)\b",
    re.I,
)


def base_query() -> dict:
    return {
        "currentJobTitle": {"include": TITLE_INCLUDE, "exclude": TITLE_EXCLUDE},
        "profileLocation": {"include": ["US"]},
        "currentCompany.location": {"include": ["US"]},
        "currentCompany.headcount": {">=": 2, "<=": 50},
        "currentCompany.industry": {"include": INDUSTRY_INCLUDE, "exclude": INDUSTRY_EXCLUDE},
        "keyword": {"include": KEYWORD_INCLUDE, "exclude": KEYWORD_EXCLUDE},
    }


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


def bare_domain(w: str) -> str | None:
    if not w:
        return None
    w = w.strip().lower()
    if not w:
        return None
    if "://" not in w:
        w = "http://" + w
    try:
        host = urlparse(w).hostname or ""
    except Exception:
        return None
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    return host


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


def title_ok(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if TITLE_REJECT_RE.search(t):
        return False
    return True


def emp_ok(n) -> bool:
    try:
        n = int(n)
        return 2 <= n <= 50
    except Exception:
        return False


def scope_only(exclude_path: str | None = None) -> None:
    _, _, domains = load_exclude(exclude_path)
    q = with_domain_exclude(base_query(), domains)
    print("=== FREE TAM (icypeas.people.search.count) ===")
    if domains:
        print(f"  excluding {len(domains)} finance-campaign domains")
    out, cost = call("icypeas.people.search.count", {"query": q})
    assert cost == 0, cost
    print(f"  TAM: {out.get('total') or 0:,}")


def supabase_headers() -> dict:
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip().strip('"').strip("'")
    url = (os.environ.get("SUPABASE_URL") or "https://npkdhahdvilcctjwzdlf.supabase.co").strip()
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY missing")
    return {"url": url.rstrip("/"), "key": key, "headers": {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }}


def supabase_rest(method: str, path: str, body=None, prefer: str | None = None) -> list | dict:
    sb = supabase_headers()
    hdrs = dict(sb["headers"])
    if prefer:
        hdrs["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(sb["url"] + path, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else []


def upload_supabase(rows: list[dict], report: dict, hard_cap: float) -> str:
    """Bulk insert Lead Database + lead_lists + members. Returns list_id."""
    # Create list
    lists = supabase_rest(
        "POST",
        "/rest/v1/lead_lists",
        {
            "client": CLIENT,
            "list_name": LIST_NAME,
            "source": "icypeas->blitz",
            "status": "enriched",
            "total_leads": len(rows),
            "enriched_count": len(rows),
            "ready_count": len(rows),
            "failed_count": 0,
            "skipped_count": int(report.get("skipped_known") or 0),
            "estimated_cost_usd": report.get("quote_expected_usd"),
            "actual_cost_usd": report.get("spend_usd"),
            "cost_cap_usd": hard_cap,
            "enrichment_started_at": report.get("started_at"),
            "enrichment_completed_at": report.get("at"),
            "metadata": {
                "path": "icypeas.people.search -> blitzapi.people.email.find",
                "pull": report.get("pulled"),
                "coverage": report.get("coverage"),
                "unit_economics": report.get("unit_economics"),
                "exclude_counts": report.get("excluded"),
                "tam": report.get("tam"),
            },
            "run_report": {k: v for k, v in report.items() if k != "rows"},
        },
    )
    list_id = lists[0]["list_id"] if isinstance(lists, list) else lists["list_id"]

    # Bulk insert leads (chunked). id is IDENTITY BY DEFAULT — omit and read back.
    lead_payloads = []
    for r in rows:
        name = (r.get("name") or "").strip()
        parts = name.split(None, 1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""
        lead_payloads.append(
            {
                "First Name": first,
                "Last Name": last,
                "Email": r.get("email"),
                "Linkedin": r.get("person_linkedin"),
                "Company Name": r.get("company_name"),
                "Website": r.get("company_website"),
                "company_size": str(r.get("employee_count") or ""),
                "company_description": r.get("company_desc") or "",
                "location": r.get("location"),
                "email_source": "blitzapi.people.email.find",
                "email_status": "found",
                "enrichment_updated_at": datetime.now(timezone.utc).isoformat(),
                "title": r.get("job_title"),
                "company_industry": r.get("company_industry"),
            }
        )

    inserted_ids: list[int] = []
    for i in range(0, len(lead_payloads), 100):
        chunk = lead_payloads[i : i + 100]
        inserted = supabase_rest(
            "POST",
            "/rest/v1/Lead%20Database",
            chunk,
            prefer="return=representation",
        )
        if not isinstance(inserted, list):
            raise RuntimeError(f"unexpected Lead Database insert response: {type(inserted)}")
        inserted_ids.extend(int(row["id"]) for row in inserted)

    if len(inserted_ids) != len(rows):
        raise RuntimeError(f"inserted {len(inserted_ids)} leads but had {len(rows)} ready rows")

    for r, lid in zip(rows, inserted_ids):
        r["_lead_id"] = lid

    members = [
        {
            "list_id": list_id,
            "lead_id": r["_lead_id"],
            "enrichment_status": "enriched",
            "enrichment_completed_at": datetime.now(timezone.utc).isoformat(),
        }
        for r in rows
    ]
    for i in range(0, len(members), 100):
        supabase_rest(
            "POST",
            "/rest/v1/lead_list_members",
            members[i : i + 100],
            prefer="return=minimal",
        )

    return list_id


def run(pull: int, hard_cap: float, exclude_path: str | None, do_upload: bool) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    excl_emails, excl_li, excl_domains = load_exclude(exclude_path)
    seen_li = set(excl_li)
    seen_email = set(excl_emails)
    spend_micro = 0

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

    print(
        f"Exclude: emails={len(excl_emails)} linkedin={len(excl_li)} domains={len(excl_domains)}"
    )
    print(f"Pull-N={pull}  cap=${hard_cap}  path=Icypeas→Blitz")

    q = with_domain_exclude(base_query(), excl_domains)
    print("=== FREE TAM ===")
    tam_out = pay("icypeas.people.search.count", {"query": q})
    tam = tam_out.get("total") or 0
    print(f"  TAM: {tam:,}")

    # Pull-N: collect N ICP people from Icypeas, then enrich that fixed batch only.
    # Known LI/email are skipped before Blitz (not replaced by more search pages).
    page_size = min(100, max(pull, 25))
    pulled: list[dict] = []
    searched = 0
    skipped_known_li = 0
    title_or_emp_fail = 0
    token = None
    max_pages = max(3, (pull // page_size) + 2)

    print("=== PULL ===")
    for page_i in range(max_pages):
        if len(pulled) >= pull:
            break
        if spend_micro / 1e6 >= hard_cap * 0.95:
            print("  near hard cap — stop search")
            break
        need = pull - len(pulled)
        size = min(200, max(need, 1))
        body = {"query": q, "pagination": {"size": size}}
        if token:
            body["pagination"]["token"] = token
        try:
            out = pay("icypeas.people.search", body)
        except RuntimeError as e:
            print(f"  stop/search: {e}")
            break
        leads = out.get("leads") or []
        searched += len(leads)
        print(f"  page {page_i+1}: got {len(leads)} rows  pulled={len(pulled)}/{pull}  spend=${spend_micro/1e6:.4f}")
        for L in leads:
            if len(pulled) >= pull:
                break
            title = L.get("lastJobTitle") or L.get("headline") or ""
            if not title_ok(title) or not emp_ok(L.get("lastCompanySize")):
                title_or_emp_fail += 1
                continue
            li = norm_li(L.get("profileUrl") or "")
            if not li:
                continue
            pulled.append(L)
        token = (out.get("pagination") or {}).get("token")
        if not token or not leads:
            break
        time.sleep(0.2)

    print(f"Pulled {len(pulled)} people (searched rows={searched})")

    # Enrich fixed batch only
    ready: list[dict] = []
    attempts = hits = freemail = skipped_email = empty_desc = 0
    print("=== BLITZ EMAIL FIND ===")
    for L in pulled:
        if spend_micro / 1e6 >= hard_cap:
            print("  hard cap reached — stop email find")
            break
        li = norm_li(L.get("profileUrl") or "")
        if not li:
            continue
        if li in seen_li:
            skipped_known_li += 1
            continue
        seen_li.add(li)
        attempts += 1
        try:
            eout = pay("blitzapi.people.email.find", {"person_linkedin_url": L.get("profileUrl") or li})
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
            continue
        el = email.lower().strip()
        if el in seen_email:
            skipped_email += 1
            continue
        domain = el.split("@", 1)[-1] if "@" in el else ""
        if domain in FREEMAIL:
            freemail += 1
            continue
        desc = (L.get("lastCompanyDescription") or "").strip()
        if not desc:
            empty_desc += 1
            # campaigns need company desc — do not mark ready
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
        print(f"  ✓ {row['name']} <{email}> @ {row['company_name']}")
        time.sleep(0.08)

    spend = spend_micro / 1e6
    ready_n = len(ready)
    coverage = round(ready_n / len(pulled), 3) if pulled else 0.0
    # Quote reference for pull-N
    quote_expected = pull * 0.00038 + pull * 0.45 * 0.000495
    quote_max = pull * 0.00038 + pull * 0.000495

    unit = {
        "cost_per_ready_usd": round(spend / ready_n, 6) if ready_n else None,
        "cost_per_1k_ready_usd": round(spend / ready_n * 1000, 2) if ready_n else None,
        "search_rows_per_ready": round(searched / ready_n, 2) if ready_n else None,
        "email_attempts_per_ready": round(attempts / ready_n, 2) if ready_n else None,
        "blitz_hit_rate": round(hits / attempts, 3) if attempts else None,
    }

    # Early-stop warning (report only — batch already done)
    if ready_n and (
        (unit["search_rows_per_ready"] or 0) > 12
        or (unit["email_attempts_per_ready"] or 0) > 4
        or (unit["cost_per_1k_ready_usd"] or 0) > 10
    ):
        print("⚠ unit economics outside healthy band — review before full volume")

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "started_at": started,
        "client": CLIENT,
        "list_name": LIST_NAME,
        "path": "icypeas.people.search -> blitzapi.people.email.find",
        "hard_cap_usd": hard_cap,
        "spend_usd": round(spend, 6),
        "quote_expected_usd": round(quote_expected, 6),
        "quote_max_usd": round(quote_max, 6),
        "variance_usd": round(spend - quote_expected, 6),
        "tam": tam,
        "pulled": len(pulled),
        "searched_rows": searched,
        "skipped_known": skipped_known_li + skipped_email,
        "skipped_known_linkedin": skipped_known_li,
        "skipped_known_email": skipped_email,
        "title_or_emp_fail": title_or_emp_fail,
        "email_attempts": attempts,
        "email_hits": hits,
        "freemail_drop": freemail,
        "empty_desc_drop": empty_desc,
        "ready": ready_n,
        "coverage": coverage,
        "excluded": {"emails": len(excl_emails), "linkedin": len(excl_li), "domains": len(excl_domains)},
        "unit_economics": unit,
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

    list_id = None
    if do_upload and ready:
        print("=== SUPABASE BULK UPLOAD ===")
        list_id = upload_supabase(ready, report, hard_cap)
        report["list_id"] = list_id
        (OUT_DIR / "pilot-report.json").write_text(json.dumps(report, indent=2))
        print(f"  list_id={list_id}")
    elif do_upload and not ready:
        print("No ready rows — skip upload")

    summary = {
        "tam": tam,
        "pulled": len(pulled),
        "ready": ready_n,
        "coverage": coverage,
        "spend_usd": report["spend_usd"],
        "quote_expected_usd": report["quote_expected_usd"],
        "quote_max_usd": report["quote_max_usd"],
        "variance_usd": report["variance_usd"],
        "unit_economics": unit,
        "list_id": list_id,
        "artifacts": str(OUT_DIR),
    }
    print(json.dumps(summary, indent=2))


def main() -> None:
    if not TOKEN:
        print("Missing TREG_TOKEN / ~/.treg/config.json", file=sys.stderr)
        sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-only", action="store_true")
    ap.add_argument("--pull", type=int, default=0, help="Pull-N people to enrich")
    ap.add_argument("--confirm-spend", type=float, default=None)
    ap.add_argument("--exclude-json", type=str, default=None)
    ap.add_argument("--upload-supabase", action="store_true")
    args = ap.parse_args()
    if args.scope_only:
        scope_only(args.exclude_json)
        return
    if args.pull:
        if args.confirm_spend is None:
            print("Paid run requires --confirm-spend USD", file=sys.stderr)
            sys.exit(2)
        run(
            pull=args.pull,
            hard_cap=args.confirm_spend,
            exclude_path=args.exclude_json,
            do_upload=args.upload_supabase,
        )
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
