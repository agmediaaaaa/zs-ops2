#!/usr/bin/env python3
"""Enrich a CSLB license slice with decision-maker LinkedIn + work emails via Treg.

Path (Cheap Scrape):
  domain resolve (Hunter free / company enrich)
  → icypeas.people.search.count (free TAM)
  → icypeas.people.search (Owner/Officer titles)
  → blitzapi.people.email.find (LinkedIn)
  → optional treg.web.extract fallback (--with-web-extract)

Gates (mandatory):
  --scope-only          free/cheap domain+TAM probes only (no paid search/email by default)
  --estimate            catalog quote for --pull N (no paid calls)
  --confirm-spend USD   required for any paid search/email/crawl
  --pull N              Pull-N people from Icypeas (not “until N ready”)

Examples:
  python scripts/enrich_cslb_decision_makers.py \\
      --licenses data/cslb/normalized/cslb_licenses_latest.csv --scope-only --pull 50
  python scripts/enrich_cslb_decision_makers.py \\
      --licenses data/cslb/normalized/cslb_licenses_latest.csv --estimate --pull 100
  python scripts/enrich_cslb_decision_makers.py \\
      --licenses data/cslb/normalized/cslb_licenses_latest.csv --pull 50 --confirm-spend 0.50
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

# Catalog defaults (verify with `treg catalog get` before large runs)
ICYPEAS_SEARCH_PER_RESULT = 0.00038
BLITZ_EMAIL_PER_SUCCESS = 0.000495
COMPANY_ENRICH_PER_SUCCESS = 0.000495
WEB_EXTRACT_PER_CALL = 0.005  # conservative upper for routed extract

DM_TITLES = [
    "Owner",
    "CEO",
    "Chief Executive Officer",
    "Founder",
    "Co-Founder",
    "President",
    "Principal",
    "Partner",
    "Managing Partner",
    "Managing Member",
    "Officer",
    "Responsible Managing Officer",
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
    "Recruiter",
    "Account Executive",
]


def load_token() -> str | None:
    cfg = Path.home() / ".treg" / "config.json"
    if cfg.exists():
        try:
            tok = json.loads(cfg.read_text()).get("token")
            if tok:
                return tok
        except Exception:
            pass
    return os.environ.get("TREG_TOKEN") or os.environ.get("treg")


def call(endpoint: str, body: dict | None = None, *, email_route: bool = False) -> tuple[dict | list, int]:
    token = load_token()
    if not token:
        raise SystemExit("No Treg token. Set treg / TREG_TOKEN or ~/.treg/config.json")
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"X-Treg-Token": token, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if email_route or "email.find" in endpoint:
        hdrs["X-Treg-Route-Max-Cost"] = "0.01"
        hdrs["X-Treg-Route-Waterfall"] = "0"
        hdrs["X-Treg-Route-Exclude"] = "aiark,icypeas"
    req = urllib.request.Request(
        f"https://treg.to/call/{endpoint}",
        data=data,
        method="POST" if body is not None else "GET",
        headers=hdrs,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
            raw = resp.read()
            return (json.loads(raw.decode()) if raw else {}), cost
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", "replace")[:500]
        if e.code == 401:
            raise RuntimeError(
                "Treg /call/ HTTP 401 invalid token. Catalog may still work; "
                "use a team agent key: `treg login --token <key>`. "
                f"Detail: {body_txt}"
            ) from e
        raise RuntimeError(f"Treg HTTP {e.code} on {endpoint}: {body_txt}") from e


def norm_domain(value: str | None) -> str:
    if not value:
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    if "://" not in v:
        v = "https://" + v
    try:
        host = urlparse(v).hostname or ""
    except Exception:
        host = ""
    host = host.lower().removeprefix("www.")
    return host


def norm_li(u: str) -> str:
    return (u or "").lower().split("?")[0].rstrip("/")


def title_ok(title: str) -> bool:
    t = (title or "").lower()
    if "vice president" in t or t.startswith("vp ") or " assistant" in t or "recruit" in t:
        return False
    return any(
        x in t
        for x in [
            "ceo",
            "chief executive",
            "owner",
            "founder",
            "president",
            "principal",
            "partner",
            "managing member",
            "officer",
        ]
    )


def load_licenses(path: Path, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
            if limit is not None and len(rows) >= limit:
                break
    return rows


def company_query_name(row: dict) -> str:
    return (row.get("full_business_name") or row.get("business_name") or "").strip()


def resolve_domain(row: dict, spend: dict, hard_cap: float | None, allow_paid: bool) -> str:
    """Try free Hunter domain-finder, then optional paid enrich."""
    existing = norm_domain(row.get("company_domain") or row.get("website") or "")
    if existing:
        return existing
    name = company_query_name(row)
    if not name:
        return ""

    # Free: hunter.x.domain-finder
    try:
        out, cost = call("hunter.x.domain-finder", {"company": name})
        spend["micro"] += cost
        if hard_cap is not None and spend["micro"] / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded")
        # response shapes vary
        domain = ""
        if isinstance(out, dict):
            domain = (
                out.get("domain")
                or (out.get("data") or {}).get("domain")
                or (out.get("output") or {}).get("domain")
                or ""
            )
            if not domain and isinstance(out.get("domains"), list) and out["domains"]:
                d0 = out["domains"][0]
                domain = d0 if isinstance(d0, str) else (d0.get("domain") or "")
        domain = norm_domain(domain)
        if domain:
            return domain
    except Exception as e:
        print(f"  domain-finder miss/err ({name[:40]}): {e}")

    if not allow_paid:
        return ""

    # Paid-ish: blitz company enrich by name
    try:
        if hard_cap is not None and spend["micro"] / 1e6 + COMPANY_ENRICH_PER_SUCCESS > hard_cap:
            return ""
        out, cost = call("blitzapi.companies.enrich", {"name": name})
        spend["micro"] += cost
        if hard_cap is not None and spend["micro"] / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded")
        if isinstance(out, dict):
            website = (
                out.get("website")
                or out.get("domain")
                or (out.get("company") or {}).get("website")
                or (out.get("output") or {}).get("website")
                or ""
            )
            return norm_domain(website)
    except Exception as e:
        print(f"  company.enrich miss/err ({name[:40]}): {e}")
    return ""


def people_query(domain: str | None, company_name: str | None, person: dict | None = None) -> dict:
    q: dict = {
        "currentJobTitle": {"include": DM_TITLES, "exclude": TITLE_EXCLUDE},
        "profileLocation": {"include": ["US", "California, US", "CA, US"]},
    }
    if domain:
        q["currentCompanyWebsite"] = {"include": [domain]}
    elif company_name:
        q["currentCompanyName"] = {"include": [company_name]}
    if person:
        fn = (person.get("first_name") or "").strip()
        ln = (person.get("last_name") or "").strip()
        if fn:
            q["firstname"] = {"include": [fn]}
        if ln:
            q["lastname"] = {"include": [ln]}
    return q


def extract_leads(out: dict) -> list[dict]:
    if not isinstance(out, dict):
        return []
    for key in ("leads", "people", "results", "data"):
        v = out.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and isinstance(v.get("leads"), list):
            return v["leads"]
    return []


def lead_linkedin(L: dict) -> str:
    return (
        L.get("linkedin")
        or L.get("linkedinUrl")
        or L.get("linkedin_url")
        or L.get("profileUrl")
        or (L.get("link") or {}).get("linkedin")
        or ""
    )


def lead_title(L: dict) -> str:
    return L.get("lastJobTitle") or L.get("title") or L.get("headline") or ""


def lead_name(L: dict) -> tuple[str, str, str]:
    first = L.get("firstname") or L.get("first_name") or L.get("firstName") or ""
    last = L.get("lastname") or L.get("last_name") or L.get("lastName") or ""
    full = L.get("full_name") or L.get("name") or " ".join(x for x in [first, last] if x)
    return full, first, last


def freemail(email: str) -> bool:
    e = (email or "").lower()
    return any(
        e.endswith(d)
        for d in (
            "@gmail.com",
            "@yahoo.com",
            "@hotmail.com",
            "@outlook.com",
            "@aol.com",
            "@icloud.com",
            "@mail.com",
        )
    )


def quote_pull(n: int, hit_rate: float = 0.45, with_domain_paid_frac: float = 0.3) -> dict:
    search_usd = n * ICYPEAS_SEARCH_PER_RESULT
    expected_hits = n * hit_rate
    email_usd = expected_hits * BLITZ_EMAIL_PER_SUCCESS
    domain_usd = n * with_domain_paid_frac * COMPANY_ENRICH_PER_SUCCESS
    expected = search_usd + email_usd + domain_usd
    max_usd = n * ICYPEAS_SEARCH_PER_RESULT + n * BLITZ_EMAIL_PER_SUCCESS + n * COMPANY_ENRICH_PER_SUCCESS
    return {
        "model": "cslb_dm_pull_n",
        "pull": n,
        "hit_rate_assumed": hit_rate,
        "expected_ready": round(expected_hits, 1),
        "search_usd": round(search_usd, 6),
        "email_usd": round(email_usd, 6),
        "domain_enrich_usd": round(domain_usd, 6),
        "expected_usd": round(expected, 6),
        "max_usd": round(max_usd, 6),
        "recommended_cap_usd": round(max_usd * 1.4, 6),
        "est_cost_per_1k_ready_usd": round((expected / max(expected_hits, 1e-9)) * 1000, 2),
        "units": {
            "icypeas.people.search": ICYPEAS_SEARCH_PER_RESULT,
            "blitzapi.people.email.find": BLITZ_EMAIL_PER_SUCCESS,
            "blitzapi.companies.enrich": COMPANY_ENRICH_PER_SUCCESS,
        },
        "note": "Coverage = ready/pulled. Ask for --confirm-spend. Page crawl not included.",
    }


def web_extract_emails(domain: str, spend: dict, hard_cap: float) -> list[str]:
    urls = [f"https://{domain}", f"https://{domain}/contact", f"https://www.{domain}/contact"]
    found: list[str] = []
    email_re = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    for url in urls:
        if spend["micro"] / 1e6 + WEB_EXTRACT_PER_CALL > hard_cap:
            break
        try:
            out, cost = call("treg.web.extract", {"url": url})
            spend["micro"] += cost
            text = json.dumps(out) if not isinstance(out, str) else out
            for m in email_re.findall(text):
                em = m.lower()
                if not freemail(em) and domain.split(".")[-2:] == em.split("@")[-1].split(".")[-2:]:
                    found.append(em)
                elif not freemail(em) and em.endswith("@" + domain):
                    found.append(em)
        except Exception as e:
            print(f"  web.extract fail {url}: {e}")
        time.sleep(0.3)
    # de-dupe preserve order
    seen = set()
    uniq = []
    for e in found:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def write_rows(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {path} ({len(rows)} rows)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CSLB → Treg decision-maker email enrichment")
    ap.add_argument("--licenses", type=Path, required=True, help="Normalized CSLB licenses CSV")
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/cslb-dm-enrich"))
    ap.add_argument("--pull", type=int, default=50, help="Pull-N Icypeas people (fixed batch)")
    ap.add_argument("--companies", type=int, default=50, help="Max CSLB companies to attempt domain+search")
    ap.add_argument("--scope-only", action="store_true", help="Free TAM / domain probes; no paid search/email")
    ap.add_argument("--estimate", action="store_true", help="Print catalog quote for --pull and exit")
    ap.add_argument("--confirm-spend", type=float, help="Hard USD spend cap (required for paid run)")
    ap.add_argument("--with-web-extract", action="store_true", help="Fallback: crawl contact pages for emails")
    ap.add_argument("--with-paid-domain", action="store_true", help="Allow blitzapi.companies.enrich if Hunter misses")
    ap.add_argument("--page-size", type=int, default=10, help="Icypeas pagination.size (price dial)")
    ap.add_argument("--exclude-json", type=Path, help="Optional {emails,linkedin,domains} skip set")
    args = ap.parse_args(argv)

    if args.estimate:
        q = quote_pull(args.pull)
        print(json.dumps(q, indent=2))
        print("\nHard stop: reply with --confirm-spend <USD> to run paid enrichment (recommended_cap_usd above).")
        return 0

    licenses = load_licenses(args.licenses, limit=args.companies)
    if not licenses:
        print("No licenses loaded", file=sys.stderr)
        return 2

    excl_emails: set[str] = set()
    excl_li: set[str] = set()
    excl_domains: set[str] = set()
    if args.exclude_json and args.exclude_json.exists():
        data = json.loads(args.exclude_json.read_text())
        excl_emails = {e.lower().strip() for e in data.get("emails") or [] if e}
        excl_li = {norm_li(u) for u in data.get("linkedin") or [] if u}
        excl_domains = {norm_domain(d) for d in data.get("domains") or [] if d}

    # ---- scope-only: domain resolve (free) + Icypeas counts ----
    if args.scope_only:
        print("=== SCOPE-ONLY (free domain finder + icypeas.people.search.count) ===")
        print(f"Companies in slice (capped): {len(licenses)}")
        spend = {"micro": 0}
        with_domain = 0
        tam_total = 0
        samples = []
        for i, row in enumerate(licenses[: min(len(licenses), args.companies)]):
            domain = resolve_domain(row, spend, hard_cap=None, allow_paid=False)
            name = company_query_name(row)
            if domain:
                with_domain += 1
            q = people_query(domain or None, None if domain else name)
            try:
                out, cost = call("icypeas.people.search.count", {"query": q})
                assert cost == 0 or cost is not None
                n = int(out.get("total") or 0) if isinstance(out, dict) else 0
            except Exception as e:
                n = 0
                print(f"  count fail {name[:40]}: {e}")
            tam_total += n
            if i < 15:
                samples.append(
                    {
                        "license_no": row.get("license_no"),
                        "business_name": name,
                        "domain": domain,
                        "tam": n,
                        "principal": row.get("primary_principal_name") or "",
                    }
                )
            print(f"  [{i+1}/{len(licenses)}] {name[:50]} | domain={domain or '-'} | TAM={n}")
            time.sleep(0.5)
        summary = {
            "companies": len(licenses),
            "with_domain": with_domain,
            "domain_rate": round(with_domain / max(len(licenses), 1), 3),
            "sum_tam_over_companies": tam_total,
            "spend_usd": round(spend["micro"] / 1e6, 6),
            "samples": samples,
            "quote": quote_pull(args.pull),
            "next": "Re-run with --estimate then --confirm-spend <USD> --pull N for paid enrichment.",
        }
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "scope_summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps({k: summary[k] for k in summary if k != "samples"}, indent=2))
        print("STOP: no paid search/email without --confirm-spend.")
        return 0

    if args.confirm_spend is None:
        print(
            "Paid enrichment requires --confirm-spend <USD>. "
            "Run --scope-only and/or --estimate first.",
            file=sys.stderr,
        )
        q = quote_pull(args.pull)
        print(json.dumps(q, indent=2))
        print('Ask: What hard cost cap should I use? Reply with --confirm-spend <USD>.')
        return 2

    hard_cap = float(args.confirm_spend)
    spend = {"micro": 0}
    allow_paid_domain = bool(args.with_paid_domain)

    print(f"=== PAID RUN pull={args.pull} companies≤{args.companies} cap=${hard_cap} ===")
    pulled: list[dict] = []
    ready: list[dict] = []
    company_stats = []

    def pay(endpoint, body, email_route=False):
        if spend["micro"] / 1e6 >= hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} reached")
        if endpoint == "icypeas.people.search":
            size = int(((body or {}).get("pagination") or {}).get("size") or 0)
            projected = spend["micro"] / 1e6 + size * ICYPEAS_SEARCH_PER_RESULT
            if size and projected > hard_cap:
                raise RuntimeError(
                    f"hard cap ${hard_cap} would be exceeded by next page "
                    f"(projected ${projected:.4f} for size={size})"
                )
        out, cost = call(endpoint, body, email_route=email_route)
        spend["micro"] += cost
        if spend["micro"] / 1e6 > hard_cap:
            raise RuntimeError(f"hard cap ${hard_cap} exceeded (spent ${spend['micro']/1e6:.4f})")
        return out

    seen_li: set[str] = set(excl_li)
    seen_email: set[str] = set(excl_emails)

    for i, row in enumerate(licenses):
        if len(pulled) >= args.pull:
            break
        if spend["micro"] / 1e6 >= hard_cap * 0.95:
            print("Near hard cap — stopping company loop")
            break
        name = company_query_name(row)
        domain = resolve_domain(row, spend, hard_cap, allow_paid=allow_paid_domain)
        if domain and domain in excl_domains:
            company_stats.append({"license_no": row.get("license_no"), "skipped": "domain_excluded"})
            continue

        person = {
            "first_name": row.get("primary_principal_first") or "",
            "last_name": row.get("primary_principal_last") or "",
        }
        # Prefer company website query; optionally bias with principal name on a second pass
        q = people_query(domain or None, None if domain else name)
        try:
            # free count first (informational)
            try:
                cout = pay("icypeas.people.search.count", {"query": q})
                tam = int(cout.get("total") or 0) if isinstance(cout, dict) else 0
            except Exception:
                tam = -1
            remaining = args.pull - len(pulled)
            size = min(args.page_size, remaining)
            if size <= 0:
                break
            out = pay("icypeas.people.search", {"query": q, "pagination": {"size": size}})
            leads = extract_leads(out if isinstance(out, dict) else {})
        except RuntimeError as e:
            print(f"  stop: {e}")
            break
        except Exception as e:
            print(f"  search fail {name[:40]}: {e}")
            company_stats.append({"license_no": row.get("license_no"), "error": str(e)})
            continue

        company_hit = 0
        for L in leads:
            if len(pulled) >= args.pull:
                break
            title = lead_title(L)
            if not title_ok(title):
                continue
            li = norm_li(lead_linkedin(L))
            full, first, last = lead_name(L)
            pulled.append(
                {
                    "license_no": row.get("license_no"),
                    "business_name": name,
                    "business_phone": row.get("business_phone") or "",
                    "city": row.get("city") or "",
                    "state": row.get("state") or "",
                    "county": row.get("county") or "",
                    "expiration_date": row.get("expiration_date") or "",
                    "primary_status": row.get("primary_status") or "",
                    "classifications": row.get("classifications") or "",
                    "company_domain": domain,
                    "person_name": full,
                    "first_name": first,
                    "last_name": last,
                    "title": title,
                    "linkedin": li,
                    "cslb_principal": row.get("primary_principal_name") or "",
                    "tam_at_company": tam,
                }
            )
            company_hit += 1
        company_stats.append(
            {
                "license_no": row.get("license_no"),
                "domain": domain,
                "tam": tam,
                "pulled": company_hit,
            }
        )
        print(
            f"  [{i+1}] {name[:45]} domain={domain or '-'} tam={tam} "
            f"pulled+={company_hit} total_pulled={len(pulled)} spend=${spend['micro']/1e6:.4f}"
        )
        time.sleep(0.4)

    print(f"Pulled people: {len(pulled)} — Blitz email.find…")
    for p in pulled:
        li = p.get("linkedin") or ""
        if not li:
            p["email"] = ""
            p["email_status"] = "no_linkedin"
            continue
        if norm_li(li) in seen_li:
            p["email"] = ""
            p["email_status"] = "linkedin_skipped_known"
            continue
        try:
            out = pay("blitzapi.people.email.find", {"linkedin_url": li}, email_route=True)
        except RuntimeError as e:
            print(f"  email stop: {e}")
            p["email"] = ""
            p["email_status"] = f"stopped:{e}"
            break
        except Exception as e:
            p["email"] = ""
            p["email_status"] = f"error:{e}"
            continue

        email = ""
        if isinstance(out, dict):
            email = (
                out.get("email")
                or (out.get("data") or {}).get("email")
                or (out.get("output") or {}).get("email")
                or ""
            )
            if not email and isinstance(out.get("emails"), list) and out["emails"]:
                e0 = out["emails"][0]
                email = e0 if isinstance(e0, str) else (e0.get("email") or "")
        email = (email or "").lower().strip()
        seen_li.add(norm_li(li))
        if not email:
            p["email"] = ""
            p["email_status"] = "miss"
            continue
        if freemail(email):
            p["email"] = email
            p["email_status"] = "freemail_dropped"
            continue
        if email in seen_email:
            p["email"] = email
            p["email_status"] = "email_known_skip"
            continue
        seen_email.add(email)
        p["email"] = email
        p["email_status"] = "ready"
        ready.append(p)

    # Optional web extract fallback for companies with domain but no ready person email
    if args.with_web_extract:
        print("Web extract fallback for companies still without ready email…")
        ready_lic = {r["license_no"] for r in ready}
        for row in licenses:
            if row.get("license_no") in ready_lic:
                continue
            if spend["micro"] / 1e6 >= hard_cap * 0.95:
                break
            domain = norm_domain(row.get("company_domain") or "")
            if not domain:
                # try free resolve only
                domain = resolve_domain(row, spend, hard_cap, allow_paid=False)
            if not domain:
                continue
            emails = web_extract_emails(domain, spend, hard_cap)
            # Prefer non-generic local parts if principal last name matches
            last = (row.get("primary_principal_last") or "").lower()
            chosen = ""
            for em in emails:
                local = em.split("@")[0]
                if last and last in local:
                    chosen = em
                    break
            if not chosen:
                # skip generic-only without person match (plan: don't treat info@ as DM)
                continue
            if chosen in seen_email or freemail(chosen):
                continue
            seen_email.add(chosen)
            rec = {
                "license_no": row.get("license_no"),
                "business_name": company_query_name(row),
                "business_phone": row.get("business_phone") or "",
                "city": row.get("city") or "",
                "state": row.get("state") or "",
                "county": row.get("county") or "",
                "expiration_date": row.get("expiration_date") or "",
                "primary_status": row.get("primary_status") or "",
                "classifications": row.get("classifications") or "",
                "company_domain": domain,
                "person_name": row.get("primary_principal_name") or "",
                "first_name": row.get("primary_principal_first") or "",
                "last_name": row.get("primary_principal_last") or "",
                "title": row.get("primary_principal_titles") or "CSLB Principal",
                "linkedin": "",
                "cslb_principal": row.get("primary_principal_name") or "",
                "email": chosen,
                "email_status": "ready_web_extract_name_match",
            }
            ready.append(rec)
            print(f"  web-extract ready: {chosen} @ {domain}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "license_no",
        "business_name",
        "business_phone",
        "city",
        "state",
        "county",
        "expiration_date",
        "primary_status",
        "classifications",
        "company_domain",
        "person_name",
        "first_name",
        "last_name",
        "title",
        "linkedin",
        "cslb_principal",
        "email",
        "email_status",
        "tam_at_company",
    ]
    write_rows(args.out_dir / f"pulled_{stamp}.csv", pulled, fields)
    write_rows(args.out_dir / f"ready_{stamp}.csv", ready, fields)
    write_rows(args.out_dir / "ready_latest.csv", ready, fields)

    report = {
        "stamp": stamp,
        "pull_target": args.pull,
        "companies_attempted": len(company_stats),
        "pulled": len(pulled),
        "ready": len(ready),
        "coverage_ready_over_pulled": round(len(ready) / max(len(pulled), 1), 3),
        "spend_usd": round(spend["micro"] / 1e6, 6),
        "hard_cap_usd": hard_cap,
        "path": "hunter.domain-finder → icypeas.people.search → blitzapi.people.email.find"
        + (" → treg.web.extract(name-match)" if args.with_web_extract else ""),
        "company_stats": company_stats[:50],
    }
    (args.out_dir / f"report_{stamp}.json").write_text(json.dumps(report, indent=2))
    (args.out_dir / "report_latest.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in report if k != "company_stats"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
