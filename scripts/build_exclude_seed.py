#!/usr/bin/env python3
"""Build exclude seed JSON for Icypeas in-query domain excludes.

Sources (pick via --source):
  none          empty seed
  supabase_7d   Lead Database + pipeline_leads from last 7 days
  supabase_15d  Lead Database + pipeline_leads from last 15 days
  plusvibe      leads already in PlusVibe workspace campaigns

Output JSON shape (used by treg_icypeas_blitz / scrape_wizard):
  {"emails": [...], "linkedins": [...], "domains": [...], "meta": {...}}

Domains are normalized bare hosts and go into Icypeas
currentCompanyWebsite.exclude BEFORE paid search.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
).rstrip("/")
PLUSVIBE_API = "https://api.plusvibe.ai/api/v1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
    "googlemail.com",
}
DEFAULT_PLUSVIBE_WS = os.environ.get(
    "PLUSVIBE_WORKSPACE_ID", "6a8d53c5977bb5537e41fcf2"
)


def supabase_key() -> str:
    raw = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
    key = "".join(c for c in raw if 32 <= ord(c) < 127)
    if not key:
        raise SystemExit("Set SUPABASE_SERVICE_ROLE_KEY")
    return key


def plusvibe_key() -> str:
    v = (os.environ.get("PLUSVIBE_API_KEY") or os.environ.get("PLUSVIBE_KEY") or "").strip()
    if not v:
        raise SystemExit("Set PLUSVIBE_API_KEY")
    return v


def norm_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    if not d:
        return ""
    if "@" in d and "://" not in d and not d.startswith("www."):
        # email → host
        d = d.split("@", 1)[-1]
    if "://" not in d and "/" not in d and " " not in d:
        host = d
    else:
        if "://" not in d:
            d = "http://" + d
        try:
            host = urlparse(d).hostname or ""
        except Exception:
            host = ""
    if host.startswith("www."):
        host = host[4:]
    host = host.strip(".")
    if not host or "." not in host or host in FREEMAIL:
        return ""
    return host


def norm_linkedin(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    if "?" in u:
        u = u.split("?", 1)[0]
    return u


def domain_from_email(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return ""
    return norm_domain(e.split("@", 1)[1])


def sb_get(table: str, params: dict) -> list[dict]:
    enc = urllib.parse.quote(table, safe="")
    qs = urllib.parse.urlencode(params, doseq=True)
    url = f"{SUPABASE_URL}/rest/v1/{enc}?{qs}"
    key = supabase_key()
    req = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode() or "[]")


def _add_domain(ordered: list[str], seen: set[str], raw: str) -> None:
    d = norm_domain(raw)
    if d and d not in seen:
        seen.add(d)
        ordered.append(d)


def fetch_supabase_window(days: int) -> dict[str, set[str]]:
    """Newest-first so domain caps keep the most recent companies."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    emails: set[str] = set()
    linkedins: set[str] = set()
    domain_ordered: list[str] = []
    domain_seen: set[str] = set()

    # Lead Database (capitalized columns)
    page_size = 1000
    offset = 0
    while True:
        rows = sb_get(
            "Lead Database",
            {
                "select": "Email,Linkedin,Website,created_at",
                "created_at": f"gte.{since}",
                "order": "created_at.desc",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        if not rows:
            break
        for r in rows:
            em = (r.get("Email") or "").strip().lower()
            if em:
                emails.add(em)
                _add_domain(domain_ordered, domain_seen, em)
            li = norm_linkedin(r.get("Linkedin") or "")
            if li:
                linkedins.add(li)
            _add_domain(domain_ordered, domain_seen, r.get("Website") or "")
        if len(rows) < page_size:
            break
        offset += page_size
        if offset > 200_000:
            break

    # pipeline_leads
    offset = 0
    while True:
        rows = sb_get(
            "pipeline_leads",
            {
                "select": "email,linkedin,website,company_domain,created_at",
                "created_at": f"gte.{since}",
                "order": "created_at.desc",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        if not rows:
            break
        for r in rows:
            em = (r.get("email") or "").strip().lower()
            if em:
                emails.add(em)
                _add_domain(domain_ordered, domain_seen, em)
            li = norm_linkedin(r.get("linkedin") or "")
            if li:
                linkedins.add(li)
            for key in ("company_domain", "website"):
                _add_domain(domain_ordered, domain_seen, r.get(key) or "")
        if len(rows) < page_size:
            break
        offset += page_size
        if offset > 200_000:
            break

    return {
        "emails": emails,
        "linkedins": linkedins,
        "domains": set(domain_ordered),
        "_domains_ordered": domain_ordered,  # type: ignore[dict-item]
    }


def fetch_plusvibe(workspace_id: str, campaign_ids: list[str] | None = None) -> dict[str, set[str]]:
    emails: set[str] = set()
    linkedins: set[str] = set()
    domains: set[str] = set()
    camp_filter = set(campaign_ids or [])
    page = 1
    page_size = 100
    key = plusvibe_key()
    while True:
        path = (
            f"{PLUSVIBE_API}/lead/workspace-leads"
            f"?workspace_id={urllib.parse.quote(workspace_id)}"
            f"&limit={page_size}&page={page}"
        )
        req = urllib.request.Request(
            path,
            headers={
                "x-api-key": key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                batch = json.loads(resp.read().decode() or "[]")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"PlusVibe error {e.code}: {e.read().decode()[:300]}") from e
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            if camp_filter and (row.get("campaign_id") or "") not in camp_filter:
                continue
            em = (row.get("email") or "").strip().lower()
            if em:
                emails.add(em)
                d = domain_from_email(em)
                if d:
                    domains.add(d)
            li = norm_linkedin(row.get("linkedin_person_url") or "")
            if li:
                linkedins.add(li)
            d = norm_domain(row.get("company_website") or "")
            if d:
                domains.add(d)
        if len(batch) < page_size:
            break
        page += 1
        if page % 25 == 0:
            print(f"  PlusVibe page={page} emails={len(emails)} domains={len(domains)}", flush=True)
        time.sleep(0.03)
    return {"emails": emails, "linkedins": linkedins, "domains": domains}


def list_plusvibe_campaigns(workspace_id: str) -> list[dict]:
    key = plusvibe_key()
    url = f"{PLUSVIBE_API}/campaign/list?workspace_id={urllib.parse.quote(workspace_id)}"
    req = urllib.request.Request(
        url,
        headers={"x-api-key": key, "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode() or "[]")
    return data if isinstance(data, list) else []


def merge_seeds(*seeds: dict[str, set[str]]) -> dict[str, set[str]]:
    out = {"emails": set(), "linkedins": set(), "domains": set()}
    for s in seeds:
        out["emails"] |= s.get("emails") or set()
        out["linkedins"] |= s.get("linkedins") or set()
        out["domains"] |= s.get("domains") or set()
    out["domains"] -= FREEMAIL
    return out


def write_seed(
    path: Path,
    seed: dict,
    meta: dict,
    max_domains: int = 5000,
) -> dict:
    ordered = seed.get("_domains_ordered")
    if isinstance(ordered, list) and ordered:
        domains = [d for d in ordered if d not in FREEMAIL]
    else:
        domains = sorted((seed.get("domains") or set()) - FREEMAIL)
    truncated = False
    if max_domains and len(domains) > max_domains:
        domains = domains[:max_domains]
        truncated = True
        meta = {**meta, "domains_truncated_to": max_domains}
    payload = {
        "emails": sorted(seed.get("emails") or []),
        "linkedins": sorted(seed.get("linkedins") or []),
        "domains": domains,
        "meta": meta,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    if truncated:
        print(
            f"  Note: domain list capped at {max_domains} (newest-first) "
            "so Icypeas query stays reliable."
        )
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Build domain/email/LinkedIn exclude seed")
    ap.add_argument(
        "--source",
        choices=["none", "supabase_7d", "supabase_15d", "plusvibe"],
        default=None,
    )
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--plusvibe-workspace", default=DEFAULT_PLUSVIBE_WS)
    ap.add_argument(
        "--plusvibe-campaigns",
        default="",
        help="Optional comma-separated campaign IDs (default: all campaigns in workspace)",
    )
    ap.add_argument("--list-campaigns", action="store_true")
    ap.add_argument(
        "--max-domains",
        type=int,
        default=5000,
        help="Cap domains injected into Icypeas (newest-first). 0 = no cap.",
    )
    args = ap.parse_args()

    if args.list_campaigns:
        camps = list_plusvibe_campaigns(args.plusvibe_workspace)
        print(f"PlusVibe campaigns in workspace {args.plusvibe_workspace}:")
        for c in camps:
            print(f"  {c.get('id') or c.get('_id')}\t{c.get('status')}\t{c.get('name')}")
        return

    if not args.source or not args.out:
        ap.error("--source and --out are required (unless --list-campaigns)")

    meta = {
        "source": args.source,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    if args.source == "none":
        seed = {"emails": set(), "linkedins": set(), "domains": set()}
    elif args.source == "supabase_7d":
        print("Loading Supabase leads from last 7 days…")
        seed = fetch_supabase_window(7)
        meta["days"] = 7
    elif args.source == "supabase_15d":
        print("Loading Supabase leads from last 15 days…")
        seed = fetch_supabase_window(15)
        meta["days"] = 15
    else:
        camps = [c.strip() for c in args.plusvibe_campaigns.split(",") if c.strip()]
        print(
            f"Loading PlusVibe workspace leads ({args.plusvibe_workspace})"
            + (f" campaigns={camps}" if camps else " — all campaigns")
            + "…"
        )
        seed = fetch_plusvibe(args.plusvibe_workspace, camps or None)
        meta["plusvibe_workspace"] = args.plusvibe_workspace
        meta["plusvibe_campaigns"] = camps or "ALL"

    payload = write_seed(args.out, seed, meta, max_domains=args.max_domains)
    print(
        f"Wrote {args.out}\n"
        f"  domains={len(payload['domains'])}  "
        f"linkedins={len(payload['linkedins'])}  "
        f"emails={len(payload['emails'])}\n"
        f"  Domains will be injected into Icypeas currentCompanyWebsite.exclude"
    )


if __name__ == "__main__":
    main()
