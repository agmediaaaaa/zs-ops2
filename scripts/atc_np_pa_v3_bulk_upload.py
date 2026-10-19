#!/usr/bin/env python3
"""TRUE BULK upload of ATC NP/PA v3 full-ready.csv into Supabase.

No unique constraint on Email → fetch existing via Email=in.(...), then
batch POST new rows + PATCH existing in chunks. Creates one lead_lists row
and bulk-inserts lead_list_members.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://npkdhahdvilcctjwzdlf.supabase.co"
)
CSV_PATH = Path(
    os.environ.get(
        "ATC_V3_CSV", "/workspace/artifacts/atc-np-pa-v3/full-ready.csv"
    )
)
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/atc-np-pa-v3"))
CLIENT = "ATC"
SOURCE = "treg.to / icypeas→blitz"
CAMPAIGN = "v3 generic"
LIST_NAME = "ATC NP/PA v3 generic Oct 19 $7 2k"
BATCH = 75  # 50–100
MEMBER_BATCH = 100
SCRAPE_COST = float(os.environ.get("ATC_V3_SCRAPE_COST", "3.8223"))
PILOT_COST = float(os.environ.get("ATC_V3_PILOT_COST", "0.0768"))


def supabase_key() -> str:
    raw = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
    key = "".join(c for c in raw if 32 <= ord(c) < 127)
    if not key:
        raise SystemExit("Set SUPABASE_SERVICE_ROLE_KEY")
    return key


KEY = supabase_key()


def sb_request(
    method: str,
    table: str,
    payload: Any | None = None,
    query: dict | None = None,
    prefer: str = "return=representation",
    timeout: int = 120,
) -> Any:
    path = urllib.parse.quote(table, safe="")
    qs = f"?{urllib.parse.urlencode(query)}" if query else ""
    url = f"{SUPABASE_URL}/rest/v1/{path}{qs}"
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "apikey": KEY,
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode()) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")[:800]
        raise RuntimeError(f"{method} {table} HTTP {e.code}: {err}") from e


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        if not email:
            skipped.append({"reason": "no_email", "row": r})
            continue
        if email in seen:
            skipped.append({"reason": "dup_email_in_csv", "email": email})
            continue
        seen.add(email)
        out.append(r)
    return out, skipped


def payload_from_row(row: dict, now: str) -> dict:
    email = (row.get("email") or "").strip().lower()
    payload = {
        "First Name": (row.get("first_name") or "").strip() or None,
        "Last Name": (row.get("last_name") or "").strip() or None,
        "Email": email or None,
        "Linkedin": (row.get("linkedin") or "").strip() or None,
        "Company Name": (row.get("company_name") or "").strip() or None,
        "Website": (row.get("website") or "").strip() or None,
        "company_size": (row.get("company_size") or "").strip() or None,
        "company_description": (row.get("company_description") or "").strip() or None,
        "location": (row.get("location") or "").strip() or None,
        "title": (row.get("title") or "").strip() or None,
        "email_source": (row.get("email_source") or "").strip() or None,
        "email_status": (row.get("email_status") or "").strip() or None,
        "enrichment_updated_at": now,
    }
    return {k: v for k, v in payload.items() if v is not None and v != ""}


def fetch_existing_by_emails(emails: list[str]) -> dict[str, int]:
    """Map lowercased email → lead id via batched Email=in.(...)."""
    found: dict[str, int] = {}
    for i in range(0, len(emails), BATCH):
        chunk = emails[i : i + BATCH]
        # PostgREST in.(...) needs double-quoted values
        in_list = "(" + ",".join(f'"{e}"' for e in chunk) + ")"
        rows = (
            sb_request(
                "GET",
                "Lead Database",
                query={"select": "id,Email", "Email": f"in.{in_list}"},
            )
            or []
        )
        for r in rows:
            em = (r.get("Email") or "").strip().lower()
            if em:
                found[em] = int(r["id"])
        print(f"  lookup {min(i + BATCH, len(emails))}/{len(emails)} found={len(found)}", flush=True)
    return found


def batch_insert(payloads: list[dict]) -> list[int]:
    ids: list[int] = []
    for i in range(0, len(payloads), BATCH):
        chunk = payloads[i : i + BATCH]
        created = sb_request(
            "POST",
            "Lead Database",
            chunk,
            prefer="return=representation",
        )
        if not created:
            raise RuntimeError(f"empty insert response at offset {i}")
        for row in created:
            ids.append(int(row["id"]))
        print(f"  inserted {min(i + BATCH, len(payloads))}/{len(payloads)}", flush=True)
    return ids


def batch_patch(updates: list[tuple[int, dict]]) -> int:
    """PATCH existing leads one-id-at-a-time but only for rows that need refresh.
    Kept sequential; typically few if scrape already partially uploaded."""
    n = 0
    for lead_id, payload in updates:
        sb_request(
            "PATCH",
            "Lead Database",
            payload,
            query={"id": f"eq.{lead_id}"},
            prefer="return=minimal",
        )
        n += 1
        if n % 50 == 0:
            print(f"  patched {n}/{len(updates)}", flush=True)
    return n


def main() -> int:
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, skipped = load_csv(CSV_PATH)
    bands = Counter((r.get("band") or "").strip() for r in rows)
    print(f"csv={CSV_PATH} rows={len(rows)} skipped={len(skipped)} bands={dict(bands)}", flush=True)

    now = datetime.now(timezone.utc).isoformat()
    emails = [(r.get("email") or "").strip().lower() for r in rows]
    print("=== FETCH EXISTING ===", flush=True)
    existing = fetch_existing_by_emails(emails)

    to_insert: list[dict] = []
    to_patch: list[tuple[int, dict]] = []
    email_to_id: dict[str, int] = {}
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        payload = payload_from_row(r, now)
        if email in existing:
            email_to_id[email] = existing[email]
            # Refresh enrichment fields on existing (already partially uploaded ok)
            to_patch.append((existing[email], payload))
        else:
            to_insert.append(payload)

    print(
        f"existing={len(existing)} to_insert={len(to_insert)} to_patch={len(to_patch)}",
        flush=True,
    )

    # Skip PATCH for speed when leads were already written by the slow uploader
    # with the same CSV fields. Only insert missing, then attach all to list.
    # Still PATCH is optional — env ATC_V3_SKIP_PATCH=1 (default) for speed.
    skip_patch = os.environ.get("ATC_V3_SKIP_PATCH", "1") not in ("0", "false", "False")
    patched = 0
    if to_patch and not skip_patch:
        print("=== PATCH EXISTING ===", flush=True)
        patched = batch_patch(to_patch)
    else:
        print(f"=== SKIP PATCH ({len(to_patch)} existing) ===", flush=True)

    print("=== INSERT NEW ===", flush=True)
    if to_insert:
        new_ids = batch_insert(to_insert)
        # Map back by position (order preserved)
        insert_emails = [
            (p.get("Email") or "").strip().lower() for p in to_insert
        ]
        for em, lid in zip(insert_emails, new_ids):
            email_to_id[em] = lid
    else:
        print("  nothing to insert", flush=True)

    missing = [e for e in emails if e not in email_to_id]
    if missing:
        print(f"WARN missing ids for {len(missing)} emails — re-fetching", flush=True)
        extra = fetch_existing_by_emails(missing)
        email_to_id.update(extra)
        missing = [e for e in emails if e not in email_to_id]

    lead_ids = [email_to_id[e] for e in emails if e in email_to_id]
    ready_count = len(lead_ids)
    print(f"lead_ids={ready_count} missing={len(missing)}", flush=True)

    total_cost = round(SCRAPE_COST + PILOT_COST, 6)
    report = {
        "mode": "full",
        "campaign": CAMPAIGN,
        "ready_target": 2000,
        "ready": ready_count,
        "csv_rows": len(rows),
        "skipped_rows": len(skipped),
        "missing_ids": len(missing),
        "spend_usd": SCRAPE_COST,
        "pilot_cost_usd": PILOT_COST,
        "total_cost_usd": total_cost,
        "cost_per_1k_ready": round((SCRAPE_COST / ready_count) * 1000, 4)
        if ready_count
        else None,
        "bands": {
            "csuite_lt200": bands.get("csuite_lt200", 0),
            "ops_200_500": bands.get("ops_200_500", 0),
        },
        "path": "icypeas.people.search → blitzapi.people.email.find",
        "max_per_company": None,
        "csv": str(CSV_PATH),
        "upload": {
            "existing": len(existing),
            "inserted": len(to_insert),
            "patched": patched,
            "skip_patch": skip_patch,
            "elapsed_sec": None,
        },
    }

    print("=== CREATE LIST ===", flush=True)
    list_row = sb_request(
        "POST",
        "lead_lists",
        {
            "client": CLIENT,
            "list_name": LIST_NAME,
            "source": SOURCE,
            "status": "enriched" if ready_count else "scraped",
            "total_leads": ready_count,
            "enriched_count": ready_count,
            "ready_count": ready_count,
            "estimated_cost_usd": 7.0,
            "actual_cost_usd": round(SCRAPE_COST, 6),
            "cost_cap_usd": 7.0,
            "enrichment_completed_at": now,
            "metadata": {
                "campaign": CAMPAIGN,
                "max_per_company": None,
                "size_split": "csuite_<200 / ops_200_500",
                "mode": "full",
                "path": "icypeas.people.search → blitzapi.people.email.find",
                "pilot_list_id": "08e969ae-babd-45c0-a4d5-0260c3deb42d",
                "pilot_cost_usd": PILOT_COST,
                "total_cost_usd": total_cost,
            },
            "run_report": report,
        },
    )
    list_id = list_row[0]["list_id"]
    print(f"list_id={list_id}", flush=True)

    print("=== INSERT MEMBERS ===", flush=True)
    members = [
        {
            "list_id": list_id,
            "lead_id": lid,
            "enrichment_status": "enriched",
            "enrichment_completed_at": now,
        }
        for lid in lead_ids
    ]
    for i in range(0, len(members), MEMBER_BATCH):
        sb_request(
            "POST",
            "lead_list_members",
            members[i : i + MEMBER_BATCH],
            prefer="return=minimal,resolution=merge-duplicates",
        )
        print(f"  members {min(i + MEMBER_BATCH, len(members))}/{len(members)}", flush=True)

    # Verify member count
    # PostgREST Prefer: count=exact with Range
    verify_url = (
        f"{SUPABASE_URL}/rest/v1/lead_list_members"
        f"?select=lead_id&list_id=eq.{list_id}"
    )
    req = urllib.request.Request(
        verify_url,
        method="HEAD",
        headers={
            "apikey": KEY,
            "Authorization": f"Bearer {KEY}",
            "Prefer": "count=exact",
        },
    )
    member_count = None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            cr = resp.headers.get("Content-Range") or ""
            # e.g. */1923 or 0-0/1923
            if "/" in cr:
                member_count = int(cr.split("/")[-1])
    except Exception as e:
        print(f"HEAD count failed: {e}; falling back to GET", flush=True)
        counted = 0
        offset = 0
        while True:
            page = (
                sb_request(
                    "GET",
                    "lead_list_members",
                    query={
                        "select": "lead_id",
                        "list_id": f"eq.{list_id}",
                        "limit": "1000",
                        "offset": str(offset),
                    },
                )
                or []
            )
            counted += len(page)
            if len(page) < 1000:
                break
            offset += 1000
        member_count = counted

    elapsed = round(time.time() - t0, 2)
    report["upload"]["elapsed_sec"] = elapsed
    report["list_id"] = list_id
    report["list_name"] = LIST_NAME
    report["member_count"] = member_count

    upload_meta = {
        "list_id": list_id,
        "list_name": LIST_NAME,
        "ready_count": ready_count,
        "member_count": member_count,
        "csv_rows": len(rows),
        "skipped": skipped[:20],
        "skipped_count": len(skipped),
        "missing_ids": missing[:20],
        "missing_count": len(missing),
        "scrape_cost_usd": SCRAPE_COST,
        "pilot_cost_usd": PILOT_COST,
        "total_cost_usd": total_cost,
        "cost_per_1k_ready": report["cost_per_1k_ready"],
        "bands": report["bands"],
        "existing": len(existing),
        "inserted": len(to_insert),
        "patched": patched,
        "elapsed_sec": elapsed,
        "ok": member_count == ready_count,
    }

    (OUT_DIR / "full-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (OUT_DIR / "supabase-upload.json").write_text(
        json.dumps(upload_meta, indent=2) + "\n"
    )
    print(json.dumps(upload_meta, indent=2), flush=True)
    if member_count != ready_count:
        print(
            f"ERROR member_count={member_count} != ready_count={ready_count}",
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
