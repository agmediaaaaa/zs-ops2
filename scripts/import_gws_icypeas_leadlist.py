#!/usr/bin/env python3
"""Import GWS Icypeas ready batch from pipeline_leads into lead_lists."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
).rstrip("/")
BATCH_ID = "gws-icypeas-20261017-212902-b6717e59"
CLIENT = "GWS"
LIST_NAME = "GWS Icypeas cheap1k Oct 17"
SOURCE = "Icypeas via treg.to"
SOURCE_RUN = "gws_icypeas_sheet2:cheap1k_backfill"


def supabase_key() -> str:
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    raise SystemExit("SUPABASE_SERVICE_ROLE_KEY not set")


def sb_headers(prefer: str = "return=representation") -> dict[str, str]:
    key = supabase_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": prefer,
    }


def sb_request(
    method: str,
    path: str,
    body: Any | None = None,
    query: dict | None = None,
    prefer: str = "return=representation",
) -> Any:
    encoded_path = urllib.parse.quote(path.lstrip("/"), safe="/?&=")
    url = f"{SUPABASE_URL}/rest/v1/{encoded_path}"
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query, doseq=True)
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers=sb_headers(prefer=prefer), method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"Supabase {method} {path} failed ({e.code}): {err[:800]}")


def normalize_linkedin(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    if "/in/" in u:
        return u.split("?")[0]
    return u


def fetch_batch_rows() -> list[dict]:
    rows: list[dict] = []
    offset = 0
    page = 1000
    while True:
        chunk = sb_request(
            "GET",
            "pipeline_leads",
            query={
                "batch_id": f"eq.{BATCH_ID}",
                "select": (
                    "id,first_name,last_name,title,email,linkedin,company_name,website,"
                    "company_domain,employees,country,mv_status,email_source,"
                    "plusvibe_ready,campaign_id,company_description,location,"
                    "company_size,raw,created_at"
                ),
                "order": "id.asc",
                "limit": str(page),
                "offset": str(offset),
            },
        )
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    return rows


def find_existing_lead(email: str, linkedin: str) -> dict | None:
    if email:
        found = sb_request(
            "GET",
            "Lead Database",
            query={
                "Email": f"ilike.{email}",
                "select": 'id,"Email","Linkedin"',
                "limit": "1",
            },
        )
        if found:
            return found[0]
    slug = normalize_linkedin(linkedin)
    if slug:
        # Prefer exact normalized match via ilike without wildcards when possible
        found = sb_request(
            "GET",
            "Lead Database",
            query={
                "Linkedin": f"ilike.*{slug.split('/in/')[-1]}*",
                "select": 'id,"Email","Linkedin"',
                "limit": "5",
            },
        )
        if found:
            for lead in found:
                if normalize_linkedin(lead.get("Linkedin") or "") == slug:
                    return lead
            return found[0]
    return None


def upsert_lead(row: dict) -> int:
    email = (row.get("email") or "").strip().lower()
    linkedin = (row.get("linkedin") or "").strip()
    if linkedin and not linkedin.startswith("http"):
        linkedin = f"https://{linkedin}"

    payload: dict[str, Any] = {
        "First Name": row.get("first_name") or None,
        "Last Name": row.get("last_name") or None,
        "Email": email or None,
        "Linkedin": linkedin or None,
        "Company Name": row.get("company_name") or None,
        "Website": row.get("website") or row.get("company_domain") or None,
        "company_size": row.get("company_size") or row.get("employees") or None,
        "company_description": row.get("company_description") or None,
        "location": row.get("location") or row.get("country") or None,
        "email_source": row.get("email_source") or None,
        "email_status": row.get("mv_status") or None,
        "enrichment_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload = {k: v for k, v in payload.items() if v not in (None, "")}

    existing = find_existing_lead(email, linkedin)
    if existing:
        sb_request(
            "PATCH",
            "Lead Database",
            body=payload,
            query={"id": f"eq.{existing['id']}"},
            prefer="return=minimal",
        )
        return int(existing["id"])

    created = sb_request("POST", "Lead Database", body=payload)
    if not created:
        raise RuntimeError(f"Failed to create lead for {email or linkedin}")
    return int(created[0]["id"])


def main() -> None:
    # Idempotency: skip if list already exists for this batch
    existing_lists = sb_request(
        "GET",
        "lead_lists",
        query={
            "client": f"eq.{CLIENT}",
            "metadata->>batch_id": f"eq.{BATCH_ID}",
            "select": "list_id,list_name,total_leads,ready_count,status",
            "limit": "1",
        },
    )
    if existing_lists:
        print(f"List already exists: {json.dumps(existing_lists[0])}")
        return

    rows = fetch_batch_rows()
    if not rows:
        raise SystemExit(f"No pipeline_leads for batch {BATCH_ID}")

    print(f"Loaded {len(rows)} pipeline_leads for {BATCH_ID}")
    lead_ids: list[int] = []
    for i, row in enumerate(rows, 1):
        lead_id = upsert_lead(row)
        lead_ids.append(lead_id)
        if i % 50 == 0 or i == len(rows):
            print(f"  upserted {i}/{len(rows)}", flush=True)

    # Dedupe lead_ids while preserving order
    seen: set[int] = set()
    unique_ids: list[int] = []
    for lid in lead_ids:
        if lid not in seen:
            seen.add(lid)
            unique_ids.append(lid)

    now = datetime.now(timezone.utc).isoformat()
    pv_ready = sum(1 for r in rows if r.get("plusvibe_ready"))
    by_campaign: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_mv: dict[str, int] = {}
    for r in rows:
        cid = r.get("campaign_id") or "unknown"
        by_campaign[cid] = by_campaign.get(cid, 0) + 1
        src = r.get("email_source") or "unknown"
        by_source[src] = by_source.get(src, 0) + 1
        mv = r.get("mv_status") or "unknown"
        by_mv[mv] = by_mv.get(mv, 0) + 1

    list_body = {
        "client": CLIENT,
        "list_name": LIST_NAME,
        "source": SOURCE,
        "status": "enriched",
        "total_leads": len(unique_ids),
        "enriched_count": len(unique_ids),
        "ready_count": len(unique_ids),
        "failed_count": 0,
        "skipped_count": 0,
        "actual_cost_usd": 2.001,
        "cost_cap_usd": 2.0,
        "enrichment_completed_at": now,
        "metadata": {
            "batch_id": BATCH_ID,
            "source_run": SOURCE_RUN,
            "mode": "ready_csv_import",
            "pipeline_rows": len(rows),
            "plusvibe_ready_flag": pv_ready,
            "campaigns": by_campaign,
            "emails_by_source": by_source,
            "mv_status": by_mv,
            "github_ref_note": (
                "CSV path in user link was not in git; imported from "
                "pipeline_leads durable copy"
            ),
        },
        "run_report": {
            "batch_id": BATCH_ID,
            "imported_at": now,
            "ready_count": len(unique_ids),
            "pipeline_rows": len(rows),
        },
    }
    created_list = sb_request("POST", "lead_lists", body=list_body)
    if not created_list:
        raise RuntimeError("Failed to create lead_lists row")
    list_id = created_list[0]["list_id"]
    print(f"Created lead_lists {list_id}")

    members = [
        {
            "list_id": list_id,
            "lead_id": lid,
            "enrichment_status": "enriched",
            "enrichment_completed_at": now,
        }
        for lid in unique_ids
    ]
    for i in range(0, len(members), 100):
        chunk = members[i : i + 100]
        sb_request(
            "POST",
            "lead_list_members",
            body=chunk,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print(f"  members {min(i + 100, len(members))}/{len(members)}", flush=True)

    verify = sb_request(
        "GET",
        "lead_list_members",
        query={
            "list_id": f"eq.{list_id}",
            "select": "lead_id",
            "limit": "1",
        },
        prefer="count=exact",
    )
    print(
        json.dumps(
            {
                "list_id": list_id,
                "list_name": LIST_NAME,
                "total_leads": len(unique_ids),
                "pipeline_rows": len(rows),
                "status": "enriched",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
