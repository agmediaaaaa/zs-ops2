#!/usr/bin/env python3
"""Safe Icypeas → Blitz lead scrape runner (locked Cheap Scrape path).

Gates (non-negotiable):
  --scope-only              free TAM only (domains/titles in-query)
  --pull N                  Pull-N: scrape N Icypeas people, Blitz that batch only
  --ready-target N          Ready-target: keep going until N ready (email+fields)
  --confirm-spend USD       REQUIRED for any paid run — you set the cap
  --exclude-json PATH       emails/linkedins/domains to exclude (domains go in-query)

Examples:
  python scripts/treg_icypeas_blitz.py --scope-only --config run.json
  python scripts/treg_icypeas_blitz.py --pull 100 --confirm-spend 1.50 --config run.json
  python scripts/treg_icypeas_blitz.py --ready-target 50 --confirm-spend 2.00 --config run.json

Prefer: python scripts/scrape_wizard.py  (asks questions in plain English)
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

ICY_ROW_USD = 0.00038
BLITZ_HIT_USD = 0.000495
# Cheap Scrape observed unit econ (for quotes only)
ROWS_PER_READY = 4.5
EMAIL_ATTEMPTS_PER_READY = 1.7

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
}

DEFAULT_TITLE_EXCLUDE = [
    "VP",
    "Vice President",
    "Assistant",
    "Sales",
    "Marketing",
    "Human Resources",
    "HR",
    "Intern",
    "Student",
    "Retired",
    "Former",
    "Consultant",
    "Advisor",
    "Board Member",
]

TITLE_REJECT_RE = re.compile(
    r"\b(vp|vice[\s-]?president|assistant|intern|student|retired|former)\b",
    re.I,
)


def treg_token() -> str:
    for name in ("treg", "TREG_TOKEN", "TREG_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    cfg = Path.home() / ".treg" / "config.json"
    if cfg.exists():
        try:
            v = (json.loads(cfg.read_text()).get("token") or "").strip()
            if v:
                return v
        except Exception:
            pass
    raise SystemExit(
        "No Treg token found. Set secret/env `treg` (or TREG_TOKEN), then retry."
    )


TOKEN = treg_token()


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


def norm_linkedin(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    if "?" in u:
        u = u.split("?", 1)[0]
    return u


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


def load_excludes(path: Path | None) -> dict[str, set[str]]:
    emails: set[str] = set()
    linkedins: set[str] = set()
    domains: set[str] = set()
    if path and path.exists():
        data = json.loads(path.read_text())
        emails = {e.strip().lower() for e in data.get("emails") or [] if e}
        linkedins = {norm_linkedin(x) for x in data.get("linkedins") or [] if x}
        domains = {norm_domain(x) for x in data.get("domains") or [] if x}
        domains -= FREEMAIL
    return {"emails": emails, "linkedins": linkedins, "domains": domains}


def website_exclude_list(domains: set[str] | list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for d in domains:
        host = norm_domain(d)
        if not host or host in FREEMAIL or host in seen:
            continue
        seen.add(host)
        out.append(host)
    return out


def build_query(cfg: dict, domain_excludes: list[str]) -> dict:
    titles = cfg.get("titles") or ["CEO", "Founder", "Owner", "President"]
    title_excl = cfg.get("title_exclude") or DEFAULT_TITLE_EXCLUDE
    q: dict = {
        "currentJobTitle": {"include": titles, "exclude": title_excl},
        "profileLocation": {"include": cfg.get("geo") or ["US"]},
    }
    lo = cfg.get("headcount_min")
    hi = cfg.get("headcount_max")
    if lo is not None or hi is not None:
        band: dict = {}
        if lo is not None:
            band[">="] = int(lo)
        if hi is not None:
            band["<="] = int(hi)
        q["currentCompany.headcount"] = band
    kw_inc = cfg.get("keyword_include") or []
    kw_exc = cfg.get("keyword_exclude") or []
    if kw_inc or kw_exc:
        kw: dict = {}
        if kw_inc:
            kw["include"] = kw_inc
        if kw_exc:
            kw["exclude"] = kw_exc
        q["keyword"] = kw
    if domain_excludes:
        q["currentCompanyWebsite"] = {"exclude": domain_excludes}
    return q


def extract_email(eout: dict) -> str | None:
    if not isinstance(eout, dict):
        return None
    email = eout.get("email")
    if email:
        return str(email).strip().lower()
    for item in eout.get("all_emails") or []:
        if isinstance(item, dict) and item.get("email"):
            return str(item["email"]).strip().lower()
        if isinstance(item, str) and "@" in item:
            return item.strip().lower()
    return None


def title_ok(title: str, include_titles: list[str]) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if TITLE_REJECT_RE.search(t):
        return False
    low = t.lower()
    return any(x.lower() in low for x in include_titles)


def quote_for(mode: str, n: int) -> dict:
    if mode == "pull":
        search_rows = n
        # expect ~60% of pulled to get a blitz attempt with LI; ~hits vary
        blitz_attempts = int(n * 0.85)
        expected_ready = int(n / ROWS_PER_READY * EMAIL_ATTEMPTS_PER_READY / 1.5)
        expected_ready = max(1, min(n, int(n * 0.45)))
    else:
        expected_ready = n
        search_rows = int(n * ROWS_PER_READY)
        blitz_attempts = int(n * EMAIL_ATTEMPTS_PER_READY)
    search_usd = search_rows * ICY_ROW_USD
    # per-success: estimate ~60% hit rate on attempts
    blitz_hits = int(blitz_attempts * 0.6)
    blitz_usd = blitz_hits * BLITZ_HIT_USD
    expected = search_usd + blitz_usd
    return {
        "mode": mode,
        "n": n,
        "search_rows": search_rows,
        "blitz_attempts_est": blitz_attempts,
        "blitz_hits_est": blitz_hits,
        "expected_ready_est": expected_ready if mode == "pull" else n,
        "expected_usd": round(expected, 4),
        "max_usd": round(expected * 1.4, 4),
        "recommended_ask_usd": max(0.01, round(expected * 1.4, 2)),
        "notes": (
            "Quote uses Cheap Scrape unit rates. You still choose the hard cap."
            if mode == "ready"
            else "Pull-N: ready count is whatever emails hit from the N people."
        ),
    }


def print_quote(q: dict) -> None:
    print("\n=== COST QUOTE (estimate — not a spend approval) ===")
    print(f"  Mode:              {q['mode']}")
    print(f"  Target N:          {q['n']}")
    print(f"  Est. Icypeas rows: {q['search_rows']} × ${ICY_ROW_USD} = ${q['search_rows'] * ICY_ROW_USD:.4f}")
    print(f"  Est. Blitz hits:   {q['blitz_hits_est']} × ${BLITZ_HIT_USD} = ${q['blitz_hits_est'] * BLITZ_HIT_USD:.4f}")
    print(f"  Expected USD:      ${q['expected_usd']:.4f}")
    print(f"  Max-ish USD:       ${q['max_usd']:.4f}")
    print(f"  Ask-for range:     ~${q['recommended_ask_usd']:.2f} (you choose the cap)")
    if q["mode"] == "pull":
        print(f"  Est. ready (not guaranteed): ~{q['expected_ready_est']}")
    print(f"  Note: {q['notes']}")
    print("  >>> No money spent yet. You must pass --confirm-spend <USD> to spend.\n")


def scope_only(cfg: dict, excl: dict[str, set[str]]) -> dict:
    domains = website_exclude_list(excl["domains"])
    q_raw = build_query(cfg, [])
    q_full = build_query(cfg, domains)
    raw, cost = call("icypeas.people.search.count", {"query": q_raw})
    assert cost == 0, cost
    full, cost = call("icypeas.people.search.count", {"query": q_full})
    assert cost == 0, cost
    tam_raw = int(raw.get("total") or 0)
    tam = int(full.get("total") or 0)
    print("=== FREE TAM (icypeas.people.search.count) ===")
    print(f"  Domain excludes in-query: {len(domains)}")
    print(f"  LinkedIn skips (pre-Blitz only): {len(excl['linkedins'])}")
    print(f"  Email skips (post-find): {len(excl['emails'])}")
    print(f"  TAM raw (no domain exclude):     {tam_raw:,}")
    print(f"  TAM after in-query excludes:     {tam:,}  ← plan against this")
    return {
        "tam_raw": tam_raw,
        "tam_after_excludes": tam,
        "domain_excludes": len(domains),
        "linkedin_skips": len(excl["linkedins"]),
        "query": q_full,
    }


def run(
    *,
    mode: str,
    n: int,
    hard_cap: float,
    cfg: dict,
    excl: dict[str, set[str]],
    out_dir: Path,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    domains = website_exclude_list(excl["domains"])
    query = build_query(cfg, domains)
    include_titles = cfg.get("titles") or ["CEO", "Founder", "Owner", "President"]

    spend_micro = 0
    rows: list[dict] = []
    seen_li: set[str] = set(excl["linkedins"])
    seen_email: set[str] = set(excl["emails"])
    searched = 0
    candidates = 0
    email_attempts = 0
    email_hits = 0
    skipped_li = 0
    skipped_email = 0
    freemail_skip = 0
    token = None
    stopped_reason = ""

    def pay(endpoint: str, body: dict) -> dict:
        nonlocal spend_micro, stopped_reason
        if spend_micro / 1e6 >= hard_cap:
            stopped_reason = f"hard cap ${hard_cap} reached"
            raise RuntimeError(stopped_reason)
        try:
            out, cost = call(endpoint, body)
        except urllib.error.HTTPError as e:
            stopped_reason = f"HTTP {e.code}"
            raise
        spend_micro += cost
        if spend_micro / 1e6 > hard_cap:
            stopped_reason = f"hard cap ${hard_cap} exceeded (spent ${spend_micro / 1e6:.4f})"
            raise RuntimeError(stopped_reason)
        return out

    print(f"=== PAID RUN mode={mode} n={n} cap=${hard_cap:.2f} ===")
    print(f"In-query domain excludes: {len(domains)}")

    # Phase A: discover candidates from Icypeas
    want_people = n if mode == "pull" else max(n * 6, n + 50)
    people: list[dict] = []
    while len(people) < want_people:
        if spend_micro / 1e6 >= hard_cap:
            stopped_reason = "cap before more search"
            break
        body: dict = {"query": query, "pagination": {"size": 50}}
        if token:
            body["pagination"]["token"] = token
        try:
            out = pay("icypeas.people.search", body)
        except RuntimeError:
            break
        leads = out.get("leads") or []
        if not leads:
            stopped_reason = stopped_reason or "no more Icypeas pages"
            break
        searched += len(leads)
        for L in leads:
            title = L.get("lastJobTitle") or L.get("headline") or ""
            if not title_ok(title, include_titles):
                continue
            li = norm_linkedin(L.get("profileUrl") or "")
            if not li:
                continue
            if li in seen_li:
                skipped_li += 1
                continue
            people.append(L)
            candidates += 1
            if mode == "pull" and len(people) >= n:
                break
            if mode == "ready" and len(people) >= want_people:
                break
        token = (out.get("pagination") or {}).get("token")
        if not token:
            stopped_reason = stopped_reason or "pagination exhausted"
            break
        if mode == "pull" and len(people) >= n:
            break
        time.sleep(0.05)

    if mode == "pull":
        people = people[:n]

    print(f"Discovered candidates: {len(people)} (searched rows={searched})")

    # Phase B: Blitz
    for L in people:
        if mode == "ready" and len(rows) >= n:
            break
        if spend_micro / 1e6 >= hard_cap:
            stopped_reason = stopped_reason or "cap before more Blitz"
            break
        li = norm_linkedin(L.get("profileUrl") or "")
        if not li or li in seen_li:
            skipped_li += 1
            continue
        email_attempts += 1
        try:
            eout = pay("blitzapi.people.email.find", {"person_linkedin_url": li})
        except RuntimeError:
            break
        email = extract_email(eout)
        if not email:
            continue
        if email in seen_email:
            skipped_email += 1
            continue
        host = email.split("@")[-1] if "@" in email else ""
        if host in FREEMAIL:
            freemail_skip += 1
            continue
        email_hits += 1
        seen_li.add(li)
        seen_email.add(email)
        desc = (L.get("lastCompanyDescription") or "").strip()
        row = {
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
        # Ready requires company desc unless waived in config
        if not cfg.get("allow_empty_desc") and not desc:
            continue
        rows.append(row)
        print(f"  ✓ [{len(rows)}] {row['name']} <{email}> | {row['job_title']} @ {row['company_name']}")
        if mode == "ready" and len(rows) >= n:
            break

    spend = spend_micro / 1e6
    ready = len(rows)
    pulled = len(people) if mode == "pull" else searched
    report = {
        "mode": mode,
        "n": n,
        "ready": ready,
        "pulled_or_searched": pulled,
        "searched_rows": searched,
        "candidates": candidates,
        "email_attempts": email_attempts,
        "email_hits": email_hits,
        "skipped_linkedin": skipped_li,
        "skipped_email": skipped_email,
        "freemail_skip": freemail_skip,
        "domain_excludes": len(domains),
        "spend_usd": round(spend, 6),
        "confirm_spend_usd": hard_cap,
        "rows_per_ready": round(searched / ready, 2) if ready else None,
        "attempts_per_ready": round(email_attempts / ready, 2) if ready else None,
        "usd_per_1k_ready": round(spend / ready * 1000, 2) if ready else None,
        "stopped_reason": stopped_reason,
        "client": cfg.get("client"),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    csv_path = out_dir / f"ready-{stamp}.csv"
    cols = list(rows[0].keys()) if rows else [
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
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    report_path = out_dir / f"report-{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2))
    (out_dir / "latest-report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "latest-ready.csv").write_text(csv_path.read_text())

    print("\n=== REPORT ===")
    for k, v in report.items():
        print(f"  {k}: {v}")
    print(f"  csv: {csv_path}")
    print(f"  report: {report_path}")
    return report


def load_config(path: Path | None, args: argparse.Namespace) -> dict:
    cfg: dict = {}
    if path and path.exists():
        cfg = json.loads(path.read_text())
    # CLI overrides
    if args.titles:
        cfg["titles"] = [t.strip() for t in args.titles.split("|") if t.strip()]
    if args.title_exclude:
        cfg["title_exclude"] = [t.strip() for t in args.title_exclude.split("|") if t.strip()]
    if args.geo:
        cfg["geo"] = [g.strip() for g in args.geo.split("|") if g.strip()]
    if args.headcount_min is not None:
        cfg["headcount_min"] = args.headcount_min
    if args.headcount_max is not None:
        cfg["headcount_max"] = args.headcount_max
    if args.keyword_include:
        cfg["keyword_include"] = [k.strip() for k in args.keyword_include.split("|") if k.strip()]
    if args.keyword_exclude:
        cfg["keyword_exclude"] = [k.strip() for k in args.keyword_exclude.split("|") if k.strip()]
    if args.client:
        cfg["client"] = args.client
    if args.allow_empty_desc:
        cfg["allow_empty_desc"] = True
    # defaults
    cfg.setdefault("titles", ["CEO", "Founder", "Owner", "President"])
    cfg.setdefault("title_exclude", DEFAULT_TITLE_EXCLUDE)
    cfg.setdefault("geo", ["US"])
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description="Safe Icypeas→Blitz scrape (confirm-spend required)")
    ap.add_argument("--scope-only", action="store_true", help="Free TAM only")
    ap.add_argument("--pull", type=int, default=0, help="Pull-N: number of Icypeas people")
    ap.add_argument("--ready-target", type=int, default=0, help="Ready-target: number of ready leads")
    ap.add_argument("--confirm-spend", type=float, default=None, help="Hard USD cap YOU set")
    ap.add_argument("--quote-only", action="store_true", help="Print quote then exit (no spend)")
    ap.add_argument("--config", type=Path, help="JSON config from scrape_wizard")
    ap.add_argument("--exclude-json", type=Path, help="JSON with emails/linkedins/domains")
    ap.add_argument("--out-dir", type=Path, default=Path("/workspace/artifacts/scrape-wizard"))
    ap.add_argument("--client", type=str, default=None)
    ap.add_argument("--titles", type=str, help="Pipe-separated titles")
    ap.add_argument("--title-exclude", type=str, help="Pipe-separated title excludes")
    ap.add_argument("--geo", type=str, default=None, help="Pipe-separated geos, default US")
    ap.add_argument("--headcount-min", type=int, default=None)
    ap.add_argument("--headcount-max", type=int, default=None)
    ap.add_argument("--keyword-include", type=str, default=None)
    ap.add_argument("--keyword-exclude", type=str, default=None)
    ap.add_argument("--allow-empty-desc", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config, args)
    excl_path = args.exclude_json or (
        Path(cfg["exclude_json"]) if cfg.get("exclude_json") else None
    )
    excl = load_excludes(excl_path)

    if args.pull and args.ready_target:
        ap.error("Pick either --pull or --ready-target, not both")
    if not (args.scope_only or args.pull or args.ready_target or args.quote_only):
        ap.error("Pick one: --scope-only | --pull N | --ready-target N | --quote-only")

    if args.scope_only and not args.quote_only and not args.pull and not args.ready_target:
        scope_only(cfg, excl)
        return

    if args.pull:
        mode, n = "pull", args.pull
    elif args.ready_target:
        mode, n = "ready", args.ready_target
    else:
        mode = cfg.get("mode") or "ready"
        n = int(cfg.get("n") or 0)

    if args.quote_only or args.pull or args.ready_target:
        if not n:
            ap.error("Need --pull N or --ready-target N (or config n)")
        q = quote_for(mode, n)
        print_quote(q)
        if args.quote_only:
            return

    if args.confirm_spend is None:
        print(
            "REFUSING TO SPEND: pass --confirm-spend <USD> with YOUR cost cap.\n"
            "Example: --confirm-spend 2.50",
            file=sys.stderr,
        )
        sys.exit(2)

    # Always show TAM before spend
    scope_only(cfg, excl)
    run(
        mode=mode,
        n=n,
        hard_cap=float(args.confirm_spend),
        cfg=cfg,
        excl=excl,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
