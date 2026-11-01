#!/usr/bin/env python3
"""Upload normalized CSLB company CSV → public.cslb_companies (ZS Lead Database).

Does NOT modify public.\"Lead Database\" columns or rows.
People enrichments stay in Lead Database; campaign merges use codicen_campaign_leads.

Env:
  SUPABASE_URL                 default https://npkdhahdvilcctjwzdlf.supabase.co
  SUPABASE_SERVICE_ROLE_KEY    required (trailing whitespace stripped)

Usage:
  python scripts/upload_cslb_companies_supabase.py \\
    --csv data/cslb/normalized/cslb_licenses_full_latest.csv \\
    --slice-name full

Query days_to_expiration via view public.cslb_companies_live (formula from
expiration_date_iso - current_date), not the base table.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://npkdhahdvilcctjwzdlf.supabase.co"
TABLE = "cslb_companies"

# days_to_expiration / expires_within_* are formulas on view cslb_companies_live
# (expiration_date_iso - current_date). Do not upsert static snapshots.
BOOL_COLS: set[str] = set()
INT_COLS = {"principal_count"}
DATE_COLS = {"expiration_date_iso"}
JSON_COLS = {"principals_json"}
RENAME = {"principals_json": "principals", "email": "dm_email"}
SKIP_COLS = {
    "days_to_expiration",
    "expires_within_30",
    "expires_within_90",
    "expires_within_120",
}

ALLOWED = {
    "license_no",
    "last_update",
    "business_name",
    "business_name_2",
    "full_business_name",
    "mailing_address",
    "city",
    "state",
    "county",
    "zip_code",
    "country",
    "business_phone",
    "business_type",
    "issue_date",
    "reissue_date",
    "expiration_date",
    "expiration_date_iso",
    "inactivation_date",
    "reactivation_date",
    "primary_status",
    "secondary_status",
    "classifications",
    "asbestos_reg",
    "wc_coverage_type",
    "wc_insurance_company",
    "wc_policy_number",
    "wc_effective_date",
    "wc_expiration_date",
    "cb_surety_company",
    "cb_number",
    "cb_effective_date",
    "cb_amount",
    "primary_principal_name",
    "primary_principal_first",
    "primary_principal_last",
    "primary_principal_titles",
    "principals",
    "principal_count",
    "company_domain",
    "website",
    "dm_email",
    "client",
    "source",
    "slice_name",
}


def parse_bool(v):
    if v is None or v == "":
        return None
    return str(v).strip().lower() in {"1", "true", "t", "yes"}


def parse_int(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def parse_date(v):
    if v is None or str(v).strip() == "":
        return None
    return str(v).strip()[:10]


def parse_json(v):
    if v is None or str(v).strip() == "":
        return []
    try:
        return json.loads(str(v).strip())
    except json.JSONDecodeError:
        return []


def row_to_payload(row: dict, *, slice_name: str) -> dict:
    out: dict = {}
    for k, v in row.items():
        if k in SKIP_COLS:
            continue
        dbk = RENAME.get(k, k)
        if k in BOOL_COLS:
            out[dbk] = parse_bool(v)
        elif k in INT_COLS:
            out[dbk] = parse_int(v)
        elif k in DATE_COLS:
            out[dbk] = parse_date(v)
        elif k in JSON_COLS:
            out[dbk] = parse_json(v)
        elif k == "email":
            out["dm_email"] = (str(v).strip() or None) if v else None
        else:
            if v is None or str(v).strip() == "":
                out[dbk] = None
            else:
                out[dbk] = str(v).strip()
    out["client"] = "Codicen"
    out["source"] = "cslb_master"
    out["slice_name"] = slice_name
    return {k: v for k, v in out.items() if k in ALLOWED}


def upsert(url: str, key: str, batch: list[dict]) -> None:
    body = json.dumps(batch).encode()
    req = urllib.request.Request(
        f"{url}/rest/v1/{TABLE}?on_conflict=license_no",
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            _ = resp.status
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:1500]
        raise SystemExit(f"HTTP {e.code}: {err}") from e


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--slice-name", default="full")
    p.add_argument("--batch", type=int, default=500)
    args = p.parse_args()

    url = (os.environ.get("SUPABASE_URL") or DEFAULT_URL).strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        raise SystemExit("SUPABASE_SERVICE_ROLE_KEY required")

    rows: list[dict] = []
    with args.csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("license_no"):
                continue
            rows.append(row_to_payload(row, slice_name=args.slice_name))

    print(f"Prepared {len(rows):,} rows from {args.csv}")
    sent = 0
    t0 = time.time()
    for i in range(0, len(rows), args.batch):
        chunk = rows[i : i + args.batch]
        upsert(url, key, chunk)
        sent += len(chunk)
        if sent % 2000 == 0 or sent == len(rows):
            print(f"  upserted {sent:,}/{len(rows):,} ({time.time() - t0:.1f}s)")
        time.sleep(0.03)
    print(f"DONE → {TABLE}")


if __name__ == "__main__":
    main()
