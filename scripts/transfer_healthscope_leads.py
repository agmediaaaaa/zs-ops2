"""Transfer NOT_CONTACTED leads between Healthscope PlusVibe campaigns."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plusvibe_campaign_utils import plusvibe_request  # noqa: E402

HEALTHSCOPE_WS = "6a1334c74be1e70c4918deab"
DEFAULT_SOURCE_CAMPAIGN = "6a23d05c89340604384ff7fd"
DEFAULT_DEST_CAMPAIGN = "6a2acf75f0d8168dbe5ee131"
PAGE_SIZE = 100
ADD_BATCH_SIZE = 50
DELETE_BATCH_SIZE = 100
RATE_SLEEP = 0.22  # ~4.5 req/s, under PlusVibe 5 req/s limit

LEAD_FIELDS = (
    "email",
    "first_name",
    "last_name",
    "notes",
    "address_line",
    "city",
    "state",
    "country",
    "country_code",
    "phone_number",
    "job_title",
    "department",
    "company_name",
    "company_website",
    "industry",
    "linkedin_person_url",
    "linkedin_company_url",
)


def fetch_not_contacted(
    workspace_id: str,
    campaign_id: str,
    *,
    limit: int,
) -> list[dict]:
    page = 1
    rows: list[dict] = []
    while len(rows) < limit:
        batch_limit = min(PAGE_SIZE, limit - len(rows))
        path = (
            f"/lead/workspace-leads?workspace_id={workspace_id}"
            f"&campaign_id={campaign_id}&status=NOT_CONTACTED"
            f"&limit={batch_limit}&page={page}"
        )
        batch = plusvibe_request("GET", path)
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_limit:
            break
        page += 1
        if page % 10 == 0:
            print(f"  fetched {len(rows)} NOT_CONTACTED leads...", flush=True)
        time.sleep(RATE_SLEEP)
    return rows[:limit]


def lead_to_add_payload(row: dict) -> dict:
    out: dict = {}
    for key in LEAD_FIELDS:
        val = row.get(key)
        if val not in (None, ""):
            out[key] = val
    email = (out.get("email") or "").strip()
    if not email:
        return {}
    return out


def chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def add_leads(
    workspace_id: str,
    campaign_id: str,
    leads: list[dict],
    *,
    dry_run: bool,
) -> dict:
    totals = {
        "total_sent": 0,
        "leads_uploaded": 0,
        "skipped": 0,
        "duplicate_email_count": 0,
        "already_in_campaign": 0,
        "invalid_email_count": 0,
    }
    if dry_run:
        totals["total_sent"] = len(leads)
        return totals

    for i, batch in enumerate(chunked(leads, ADD_BATCH_SIZE), 1):
        res = plusvibe_request(
            "POST",
            "/lead/add",
            {
                "workspace_id": workspace_id,
                "campaign_id": campaign_id,
                "skip_if_in_workspace": False,
                "skip_lead_in_active_pause_camp": False,
                "skip_lead_for_active_only_camp": False,
                "resume_camp_if_completed": False,
                "is_overwrite": True,
                "leads": batch,
            },
        )
        for key in totals:
            totals[key] += int(res.get(key) or 0)
        if i % 10 == 0:
            print(f"  added batch {i}, uploaded so far={totals['leads_uploaded']}", flush=True)
        time.sleep(RATE_SLEEP)
    return totals


def delete_from_source(
    workspace_id: str,
    campaign_id: str,
    emails: list[str],
    *,
    dry_run: bool,
) -> int:
    if dry_run:
        return len(emails)
    deleted = 0
    for batch in chunked(emails, DELETE_BATCH_SIZE):
        plusvibe_request(
            "POST",
            "/lead/delete",
            {
                "workspace_id": workspace_id,
                "campaign_id": campaign_id,
                "delete_list": batch,
            },
        )
        deleted += len(batch)
        time.sleep(RATE_SLEEP)
    return deleted


def count_not_contacted(workspace_id: str, campaign_id: str) -> int:
    rows = plusvibe_request(
        "GET",
        f"/lead/count/lead-status?workspace_id={workspace_id}&campaign_id={campaign_id}",
    )
    if not isinstance(rows, list):
        return 0
    for row in rows:
        if row.get("status") == "NOT_CONTACTED":
            return int(row.get("count") or 0)
    return 0


def campaign_name(workspace_id: str, campaign_id: str) -> str:
    camps = plusvibe_request(
        "GET",
        f"/campaign/list-all?workspace_id={workspace_id}&campaign_id={campaign_id}",
    )
    if isinstance(camps, list) and camps:
        return camps[0].get("camp_name") or campaign_id
    return campaign_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transfer NOT_CONTACTED leads between Healthscope campaigns"
    )
    parser.add_argument("--workspace-id", default=HEALTHSCOPE_WS)
    parser.add_argument("--source-campaign", default=DEFAULT_SOURCE_CAMPAIGN)
    parser.add_argument("--dest-campaign", default=DEFAULT_DEST_CAMPAIGN)
    parser.add_argument("--limit", type=int, default=4000)
    parser.add_argument(
        "--no-delete-source",
        action="store_true",
        help="Add to destination but keep leads in source campaign",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ws = args.workspace_id
    src = args.source_campaign
    dst = args.dest_campaign

    src_name = campaign_name(ws, src)
    dst_name = campaign_name(ws, dst)
    available = count_not_contacted(ws, src)

    print(f"workspace: Healthscope Services ({ws})")
    print(f"source:    {src_name} ({src}) — NOT_CONTACTED available: {available}")
    print(f"dest:      {dst_name} ({dst})")
    print(f"transfer:  up to {args.limit} leads")
    if args.dry_run:
        print("mode:      DRY RUN")

    if available == 0:
        print("No NOT_CONTACTED leads in source campaign.")
        return

    transfer_count = min(args.limit, available)
    print(f"\nFetching {transfer_count} NOT_CONTACTED leads from source...")
    raw_rows = fetch_not_contacted(ws, src, limit=transfer_count)
    leads = [payload for row in raw_rows if (payload := lead_to_add_payload(row))]
    emails = sorted({(row.get("email") or "").strip() for row in raw_rows if row.get("email")})

    print(f"ready: {len(leads)} leads with email ({len(raw_rows)} fetched)")

    print(f"\nAdding to {dst_name}...")
    add_result = add_leads(ws, dst, leads, dry_run=args.dry_run)
    print(json.dumps(add_result, indent=2))

    deleted = 0
    if not args.no_delete_source:
        print(f"\nRemoving {len(emails)} leads from {src_name}...")
        deleted = delete_from_source(ws, src, emails, dry_run=args.dry_run)
        print(f"deleted from source: {deleted}")

    remaining = count_not_contacted(ws, src) if not args.dry_run else available - len(emails)
    print(
        f"\ndone: transferred={len(leads)} deleted_from_source={deleted} "
        f"source_NOT_CONTACTED_remaining={remaining}"
    )


if __name__ == "__main__":
    main()
