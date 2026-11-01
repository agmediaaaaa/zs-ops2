#!/usr/bin/env python3
"""Upload Apify Google Maps emails into Codicen/CSLB tables.

Does NOT write to public."Lead Database".

Inputs (default /tmp/cslb_apify):
  UPLOAD_PAIRS_FILTERED.jsonl
  UPLOAD_SUMMARY_FILTERED.jsonl

Targets:
  cslb_companies.dm_* + emails jsonb
  codicen_campaign_leads (one row per license+email)
  codicen_email_leads (Codicen multi-email list)
  lead_lists metadata only
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_LIST_ID = "d5348f8b-a86e-47e7-8e3c-b9f839030824"
DEFAULT_CAMPAIGN = "codicen_apify_maps_wave1"


def req(url: str, key: str, method: str, path: str, body=None, prefer: str | None = None):
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} HTTP {e.code}: {e.read().decode()[:1500]}") from e


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/cslb_apify")
    ap.add_argument("--list-id", default=DEFAULT_LIST_ID)
    ap.add_argument("--campaign-id", default=DEFAULT_CAMPAIGN)
    args = ap.parse_args()

    base = Path(args.dir)
    url = (os.environ.get("SUPABASE_URL") or "https://npkdhahdvilcctjwzdlf.supabase.co").strip()
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
    now = datetime.now(timezone.utc).isoformat()

    pairs = [json.loads(l) for l in (base / "UPLOAD_PAIRS_FILTERED.jsonl").read_text().splitlines()]
    summaries = [
        json.loads(l) for l in (base / "UPLOAD_SUMMARY_FILTERED.jsonl").read_text().splitlines()
    ]
    print(f"pairs={len(pairs)} licenses={len(summaries)}")

    for i in range(0, len(summaries), 40):
        chunk = summaries[i : i + 40]
        payload = []
        for s in chunk:
            payload.append(
                {
                    "license_no": s["license_no"],
                    "dm_first_name": s.get("first_name") or None,
                    "dm_last_name": s.get("last_name") or None,
                    "dm_title": s.get("title") or None,
                    "dm_email": s["primary_email"],
                    "dm_email_source": "apify_google_maps_email",
                    "dm_email_status": f"{s['best_quality']}_matched",
                    "emails": s["emails"],
                    "emails_count": s["email_count"],
                    "website": s.get("website"),
                    "company_domain": s.get("company_domain"),
                    "client": "Codicen",
                    "updated_at": now,
                }
            )
        req(
            url,
            key,
            "POST",
            "/rest/v1/cslb_companies?on_conflict=license_no",
            payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print(f"  cslb_companies {min(i + 40, len(summaries))}/{len(summaries)}")
        time.sleep(0.05)

    camp = []
    for p in pairs:
        camp.append(
            {
                "campaign_id": args.campaign_id,
                "batch_id": args.list_id,
                "client": "Codicen",
                "license_no": p["license_no"],
                "company_name": p.get("business_name"),
                "city": p.get("city"),
                "state": "CA",
                "website": p.get("website"),
                "company_domain": p.get("company_domain"),
                "first_name": p.get("first_name") or "Office",
                "last_name": p.get("last_name") or "",
                "email": p["email"],
                "title": p.get("title") or "Office",
                "email_source": "apify_google_maps_email",
                "email_status": f"{p['quality']}_matched",
                "location": f"{p['city']}, CA" if p.get("city") else "CA",
                "plusvibe_ready": p["quality"] == "phone",
                "handoff_status": "ready" if p["quality"] == "phone" else "staged",
                "raw": {
                    "quality": p["quality"],
                    "place_title": p.get("place_title"),
                    "maps_phone": p.get("maps_phone"),
                    "multi_email": True,
                },
            }
        )
    for i in range(0, len(camp), 80):
        req(
            url,
            key,
            "POST",
            "/rest/v1/codicen_campaign_leads?on_conflict=license_no,email",
            camp[i : i + 80],
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print(f"  campaign_leads {min(i + 80, len(camp))}/{len(camp)}")
        time.sleep(0.05)

    email_leads = []
    for p in pairs:
        email_leads.append(
            {
                "list_id": args.list_id,
                "campaign_id": args.campaign_id,
                "batch_id": args.list_id,
                "license_no": p["license_no"],
                "company_name": p.get("business_name"),
                "city": p.get("city"),
                "state": "CA",
                "website": p.get("website"),
                "company_domain": p.get("company_domain"),
                "email": p["email"],
                "first_name": p.get("first_name") or "Office",
                "last_name": p.get("last_name") or "",
                "title": p.get("title") or "Office",
                "match_quality": p["quality"],
                "email_source": "apify_google_maps_email",
                "email_status": f"{p['quality']}_matched",
                "plusvibe_ready": p["quality"] == "phone",
                "handoff_status": "ready" if p["quality"] == "phone" else "staged",
                "raw": {"place_title": p.get("place_title"), "maps_phone": p.get("maps_phone")},
                "updated_at": now,
            }
        )
    for i in range(0, len(email_leads), 80):
        req(
            url,
            key,
            "POST",
            "/rest/v1/codicen_email_leads?on_conflict=license_no,email",
            email_leads[i : i + 80],
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print(f"  email_leads {min(i + 80, len(email_leads))}/{len(email_leads)}")
        time.sleep(0.05)

    phone_n = sum(1 for p in pairs if p["quality"] == "phone")
    req(
        url,
        key,
        "PATCH",
        f"/rest/v1/lead_lists?list_id=eq.{args.list_id}",
        {
            "status": "enriched",
            "total_leads": len(pairs),
            "enriched_count": len(pairs),
            "ready_count": phone_n,
            "metadata": {
                "companies_with_email": len(summaries),
                "email_rows": len(pairs),
                "unique_emails": len({p["email"] for p in pairs}),
                "phone_matched_rows": phone_n,
                "storage": {
                    "codicen_email_leads": True,
                    "codicen_campaign_leads": True,
                    "cslb_companies.emails": True,
                    "Lead Database": "not modified",
                },
            },
        },
        prefer="return=minimal",
    )
    print("done", len(pairs), "emails /", len(summaries), "companies")


if __name__ == "__main__":
    main()
