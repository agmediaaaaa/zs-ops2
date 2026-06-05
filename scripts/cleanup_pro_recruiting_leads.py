"""Remove all leads from Pro-Recruiting campaigns and blocklist bounced emails."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plusvibe_campaign_utils import plusvibe_request  # noqa: E402

PRO_RECRUITING_WS = "694c1ae9ebef3b84192da7fc"
BATCH_SIZE = 100


def fetch_leads(*, status: str | None = None) -> list[dict]:
    page = 1
    rows: list[dict] = []
    while True:
        path = (
            f"/lead/workspace-leads?workspace_id={PRO_RECRUITING_WS}"
            f"&limit=100&page={page}"
        )
        if status:
            path += f"&status={status}"
        batch = plusvibe_request("GET", path)
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page % 20 == 0:
            print(f"  fetched {len(rows)} leads...", flush=True)
    return rows


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def add_to_blocklist(emails: list[str]) -> dict:
    added = 0
    already = 0
    for batch in chunked(emails, BATCH_SIZE):
        res = plusvibe_request(
            "POST",
            "/blocklist/add/entries",
            {"workspace_id": PRO_RECRUITING_WS, "entries": batch},
        )
        added += int(res.get("entries_added") or 0)
        already += int(res.get("already_in_blocklist") or 0)
        time.sleep(0.05)
    return {"entries_added": added, "already_in_blocklist": already}


def delete_campaign_leads(campaign_id: str, emails: list[str]) -> int:
    deleted = 0
    for batch in chunked(emails, BATCH_SIZE):
        plusvibe_request(
            "POST",
            "/lead/delete",
            {
                "workspace_id": PRO_RECRUITING_WS,
                "campaign_id": campaign_id,
                "delete_list": batch,
            },
        )
        deleted += len(batch)
        time.sleep(0.05)
    return deleted


def main() -> None:
    print("Fetching bounced leads...")
    bounced = fetch_leads(status="BOUNCED")
    bounced_emails = sorted({(row.get("email") or "").strip().lower() for row in bounced if row.get("email")})
    print(f"bounced leads: {len(bounced)} unique emails: {len(bounced_emails)}")

    if bounced_emails:
        print("Adding bounced emails to workspace blocklist...")
        block_res = add_to_blocklist(bounced_emails)
        print(json.dumps(block_res))

    print("Fetching all workspace leads...")
    all_leads = fetch_leads()
    by_campaign: dict[str, list[str]] = defaultdict(list)
    for row in all_leads:
        email = (row.get("email") or "").strip()
        cid = row.get("campaign_id")
        if email and cid:
            by_campaign[cid].append(email)

    total = sum(len(v) for v in by_campaign.values())
    print(f"campaigns with leads: {len(by_campaign)} total lead rows: {total}")

    deleted_total = 0
    for i, (campaign_id, emails) in enumerate(by_campaign.items(), 1):
        # dedupe per campaign while preserving order
        seen: set[str] = set()
        unique_emails: list[str] = []
        for email in emails:
            key = email.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_emails.append(email)
        camp_name = next((r.get("camp_name") for r in all_leads if r.get("campaign_id") == campaign_id), campaign_id)
        print(f"[{i}/{len(by_campaign)}] deleting {len(unique_emails)} from {camp_name} ({campaign_id})")
        deleted_total += delete_campaign_leads(campaign_id, unique_emails)

    print(f"done: blocklisted={len(bounced_emails)} deleted={deleted_total}")


if __name__ == "__main__":
    main()
