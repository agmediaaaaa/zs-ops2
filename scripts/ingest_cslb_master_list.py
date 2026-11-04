#!/usr/bin/env python3
"""Download + normalize CSLB statewide contractor Master (+ Personnel) lists.

Official free bulk files from the CSLB Public Data Portal — no ZIP scrape.

  Master:     DownLoadFile.ashx?fName=MasterLicenseData&type=C
  Personnel:  DownLoadFile.ashx?fName=PersonnelData&type=C

Examples:
  python scripts/ingest_cslb_master_list.py --download
  python scripts/ingest_cslb_master_list.py --download --expires-within 120 \\
      --status CLEAR --class B,C10 --business-type "Sole Owner" --limit 5000
  python scripts/ingest_cslb_master_list.py --from-raw data/cslb/raw --upsert-supabase
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

MASTER_URL = (
    "https://www.cslb.ca.gov/OnlineServices/DataPortal/DownLoadFile.ashx"
    "?fName=MasterLicenseData&type=C"
)
PERSONNEL_URL = (
    "https://www.cslb.ca.gov/OnlineServices/DataPortal/DownLoadFile.ashx"
    "?fName=PersonnelData&type=C"
)

UA = "Mozilla/5.0 (compatible; zs-ops2-cslb-ingest/1.0)"
DEFAULT_OUT = Path("data/cslb")

# Titles we treat as decision-maker / qualifier signal from Personnel EMP-Titl-CDE
DM_TITLE_HINTS = (
    "officer",
    "responsible managing officer",
    "responsible managing employee",
    "responsible managing member",
    "partner",
    "owner",
    "member",
    "manager",
    "president",
    "ceo",
    "qualifier",
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def download(url: str, dest: Path, *, retries: int = 5) -> Path:
    """Download with curl (preferred) then urllib retries — CSLB chunked transfers often drop."""
    import shutil
    import subprocess
    import time

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    print(f"  → {dest}")

    if shutil.which("curl"):
        tmp = dest.with_suffix(dest.suffix + ".curlpart")
        cmd = [
            "curl",
            "-fsSL",
            "--retry",
            "5",
            "--retry-all-errors",
            "--connect-timeout",
            "30",
            "--max-time",
            "1200",
            "-A",
            UA,
            "-o",
            str(tmp),
            url,
        ]
        try:
            subprocess.run(cmd, check=True)
            size = tmp.stat().st_size
            if size < 1_000_000:
                raise RuntimeError(f"download too small ({size} bytes)")
            tmp.replace(dest)
            print(f"  done {dest.stat().st_size / 1e6:.2f} MB (curl)")
            return dest
        except Exception as e:
            print(f"  curl failed ({e}); falling back to urllib…", flush=True)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        tmp = dest.with_suffix(dest.suffix + f".part{attempt}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Connection": "close"})
            with urllib.request.urlopen(req, timeout=900) as resp, tmp.open("wb") as out:
                total = 0
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    total += len(chunk)
                    if total % (10 * 1024 * 1024) < 256 * 1024:
                        print(f"  … {total / 1e6:.1f} MB (attempt {attempt})", flush=True)
            size = tmp.stat().st_size
            if size < 1_000_000:
                raise RuntimeError(f"download too small ({size} bytes)")
            tmp.replace(dest)
            print(f"  done {dest.stat().st_size / 1e6:.2f} MB")
            return dest
        except Exception as e:
            last_err = e
            print(f"  attempt {attempt}/{retries} failed: {e}", flush=True)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"Failed to download after {retries} attempts: {last_err}")


def parse_date(s: str | None) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def split_classes(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[|,;/]+", raw.replace(" ", ""))
    return [p for p in parts if p]


def parse_person_name(raw: str) -> dict[str, str]:
    """CSLB personnel Name is often LAST FIRST MIDDLE (fixed-ish spacing)."""
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s:
        return {"full_name": "", "first_name": "", "last_name": "", "middle_name": ""}
    toks = s.split(" ")
    if len(toks) == 1:
        return {"full_name": toks[0].title(), "first_name": "", "last_name": toks[0].title(), "middle_name": ""}
    last = toks[0].title()
    first = toks[1].title() if len(toks) > 1 else ""
    middle = " ".join(toks[2:]).title() if len(toks) > 2 else ""
    full = " ".join(x for x in [first, middle, last] if x)
    return {"full_name": full, "first_name": first, "last_name": last, "middle_name": middle}


def is_dm_title(emp_title: str) -> bool:
    t = (emp_title or "").lower()
    return any(h in t for h in DM_TITLE_HINTS)


def load_master(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    return rows


def load_personnel_by_license(path: Path) -> dict[str, list[dict]]:
    by_lic: dict[str, list[dict]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for r in reader:
            row = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            lic = (row.get("LIC-NO") or "").strip()
            if not lic:
                continue
            name_tp = (row.get("Name-TP") or "").strip().lower()
            # Prefer Principal rows; still keep others tagged
            parsed = parse_person_name(row.get("Name") or "")
            titles = (row.get("EMP-Titl-CDE") or "").strip()
            rec = {
                "license_no": lic,
                "name_type": (row.get("Name-TP") or "").strip(),
                "raw_name": (row.get("Name") or "").strip(),
                **parsed,
                "emp_titles": titles,
                "is_principal": "principal" in name_tp,
                "is_decision_maker_title": is_dm_title(titles),
                "class_codes": (row.get("CL-CDE") or "").strip(),
                "assoc_dates": (row.get("ASSN-DT") or "").strip(),
                "disassoc_dates": (row.get("DIS-ASSN-DT") or "").strip(),
                "last_updated": (row.get("LastUpdated") or "").strip(),
                "rec_type": (row.get("REC-TP") or "").strip(),
                "seq_no": (row.get("SEQ-NO") or "").strip(),
            }
            by_lic[lic].append(rec)
    return by_lic


def pick_primary_principal(people: list[dict]) -> dict | None:
    if not people:
        return None
    # Prefer principal + DM title, then principal, then DM title, else first
    ranked = sorted(
        people,
        key=lambda p: (
            0 if p.get("is_principal") and p.get("is_decision_maker_title") else 1,
            0 if p.get("is_principal") else 1,
            0 if p.get("is_decision_maker_title") else 1,
            p.get("full_name") or "",
        ),
    )
    return ranked[0]


def normalize_license(row: dict, people: list[dict], today: date) -> dict:
    lic = (row.get("LicenseNo") or "").strip()
    exp = parse_date(row.get("ExpirationDate"))
    days_to_exp = (exp - today).days if exp else None
    classes = split_classes(row.get("Classifications(s)") or row.get("Classifications") or "")
    primary = pick_primary_principal(people)
    principals = [
        {
            "full_name": p["full_name"],
            "first_name": p["first_name"],
            "last_name": p["last_name"],
            "emp_titles": p["emp_titles"],
            "is_principal": p["is_principal"],
            "is_decision_maker_title": p["is_decision_maker_title"],
        }
        for p in people
        if p.get("is_principal") or p.get("is_decision_maker_title")
    ]
    # de-dupe by full_name
    seen = set()
    uniq_principals = []
    for p in principals:
        key = (p["full_name"] or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq_principals.append(p)

    return {
        "license_no": lic,
        "last_update": (row.get("LastUpdate") or "").strip(),
        "business_name": (row.get("BusinessName") or "").strip(),
        "business_name_2": (row.get("BUS-NAME-2") or "").strip(),
        "full_business_name": (row.get("FullBusinessName") or "").strip(),
        "mailing_address": (row.get("MailingAddress") or "").strip(),
        "city": (row.get("City") or "").strip(),
        "state": (row.get("State") or "").strip(),
        "county": (row.get("County") or "").strip(),
        "zip_code": (row.get("ZIPCode") or "").strip(),
        "country": (row.get("country") or "").strip(),
        "business_phone": (row.get("BusinessPhone") or "").strip(),
        "business_type": (row.get("BusinessType") or "").strip(),
        "issue_date": (row.get("IssueDate") or "").strip(),
        "reissue_date": (row.get("ReissueDate") or "").strip(),
        "expiration_date": (row.get("ExpirationDate") or "").strip(),
        "expiration_date_iso": exp.isoformat() if exp else "",
        "days_to_expiration": days_to_exp if days_to_exp is not None else "",
        "expires_within_30": bool(days_to_exp is not None and 0 <= days_to_exp <= 30),
        "expires_within_90": bool(days_to_exp is not None and 0 <= days_to_exp <= 90),
        "expires_within_120": bool(days_to_exp is not None and 0 <= days_to_exp <= 120),
        "inactivation_date": (row.get("InactivationDate") or "").strip(),
        "reactivation_date": (row.get("ReactivationDate") or "").strip(),
        "primary_status": (row.get("PrimaryStatus") or "").strip(),
        "secondary_status": (row.get("SecondaryStatus") or "").strip(),
        "classifications": "|".join(classes),
        "classifications_list": classes,
        "asbestos_reg": (row.get("AsbestosReg") or "").strip(),
        "wc_coverage_type": (row.get("WorkersCompCoverageType") or "").strip(),
        "wc_insurance_company": (row.get("WCInsuranceCompany") or "").strip(),
        "wc_policy_number": (row.get("WCPolicyNumber") or "").strip(),
        "wc_effective_date": (row.get("WCEffectiveDate") or "").strip(),
        "wc_expiration_date": (row.get("WCExpirationDate") or "").strip(),
        "cb_surety_company": (row.get("CBSuretyCompany") or "").strip(),
        "cb_number": (row.get("CBNumber") or "").strip(),
        "cb_effective_date": (row.get("CBEffectiveDate") or "").strip(),
        "cb_amount": (row.get("CBAmount") or "").strip(),
        "primary_principal_name": (primary or {}).get("full_name") or "",
        "primary_principal_first": (primary or {}).get("first_name") or "",
        "primary_principal_last": (primary or {}).get("last_name") or "",
        "primary_principal_titles": (primary or {}).get("emp_titles") or "",
        "principals_json": json.dumps(uniq_principals, ensure_ascii=False),
        "principal_count": len(uniq_principals),
        # email never provided by CSLB
        "email": "",
        "company_domain": "",
        "website": "",
    }


def apply_filters(
    rows: list[dict],
    *,
    status: list[str] | None,
    classes: list[str] | None,
    business_types: list[str] | None,
    counties: list[str] | None,
    states: list[str] | None,
    expires_within: int | None,
    expires_after: int | None,
    limit: int | None,
) -> list[dict]:
    out: list[dict] = []
    status_set = {s.lower() for s in (status or [])}
    class_set = {c.upper().replace(" ", "") for c in (classes or [])}
    bt_set = {b.lower() for b in (business_types or [])}
    county_set = {c.lower() for c in (counties or [])}
    state_set = {s.upper() for s in (states or [])}

    for r in rows:
        if status_set and (r.get("primary_status") or "").lower() not in status_set:
            continue
        if state_set and (r.get("state") or "").upper() not in state_set:
            continue
        if county_set and (r.get("county") or "").lower() not in county_set:
            continue
        if bt_set and (r.get("business_type") or "").lower() not in bt_set:
            continue
        if class_set:
            row_classes = {c.upper().replace(" ", "") for c in (r.get("classifications_list") or [])}
            # also accept concatenated forms like B|C10 already split
            if not row_classes.intersection(class_set):
                continue
        days = r.get("days_to_expiration")
        if expires_within is not None:
            if days == "" or days is None:
                continue
            if not (0 <= int(days) <= expires_within):
                continue
        if expires_after is not None:
            if days == "" or days is None:
                continue
            if int(days) < expires_after:
                continue
        out.append(r)
        if limit is not None and len(out) >= limit:
            break
    return out


CSV_COLUMNS = [
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
    "days_to_expiration",
    "expires_within_30",
    "expires_within_90",
    "expires_within_120",
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
    "principals_json",
    "principal_count",
    "email",
    "company_domain",
    "website",
]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            flat = dict(r)
            for bkey in ("expires_within_30", "expires_within_90", "expires_within_120"):
                flat[bkey] = "true" if r.get(bkey) else "false"
            w.writerow(flat)
    print(f"Wrote {path} ({len(rows):,} rows)")


def write_jsonl_principals(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            try:
                principals = json.loads(r.get("principals_json") or "[]")
            except json.JSONDecodeError:
                principals = []
            for p in principals:
                rec = {
                    "license_no": r["license_no"],
                    "business_name": r.get("business_name") or "",
                    "city": r.get("city") or "",
                    "state": r.get("state") or "",
                    "expiration_date_iso": r.get("expiration_date_iso") or "",
                    "primary_status": r.get("primary_status") or "",
                    "classifications": r.get("classifications") or "",
                    **p,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    print(f"Wrote {path} ({n:,} principal rows)")


def supabase_config() -> tuple[str, str] | None:
    url = (
        os.environ.get("SUPABASE_URL")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
        or os.environ.get("SUPABASE_PROJECT_URL")
        or ""
    ).rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    )
    if url and key:
        return url, key
    return None


def upsert_supabase(rows: list[dict], table: str = "cslb_licenses", batch: int = 500) -> None:
    cfg = supabase_config()
    if not cfg:
        raise SystemExit(
            "Supabase env not set. Need SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY "
            "(optional: create table cslb_licenses first — see docs/cslb-contractor-ingest.md)."
        )
    url, key = cfg
    endpoint = f"{url}/rest/v1/{table}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload_rows = []
    for r in rows:
        issue = parse_date(r.get("issue_date"))
        payload_rows.append(
            {
                "license_no": r["license_no"],
                "last_update": r.get("last_update") or None,
                "business_name": r.get("business_name") or None,
                "full_business_name": r.get("full_business_name") or None,
                "mailing_address": r.get("mailing_address") or None,
                "city": r.get("city") or None,
                "state": r.get("state") or None,
                "county": r.get("county") or None,
                "zip_code": r.get("zip_code") or None,
                "business_phone": r.get("business_phone") or None,
                "business_type": r.get("business_type") or None,
                "issue_date": issue.isoformat() if issue else None,
                "expiration_date": r.get("expiration_date_iso") or None,
                "days_to_expiration": r.get("days_to_expiration") if r.get("days_to_expiration") != "" else None,
                "primary_status": r.get("primary_status") or None,
                "secondary_status": r.get("secondary_status") or None,
                "classifications": r.get("classifications") or None,
                "primary_principal_name": r.get("primary_principal_name") or None,
                "primary_principal_first": r.get("primary_principal_first") or None,
                "primary_principal_last": r.get("primary_principal_last") or None,
                "primary_principal_titles": r.get("primary_principal_titles") or None,
                "principals": json.loads(r.get("principals_json") or "[]"),
                "company_domain": r.get("company_domain") or None,
                "website": r.get("website") or None,
                "email": r.get("email") or None,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    # PostgREST upsert needs on_conflict
    endpoint = f"{endpoint}?on_conflict=license_no"
    sent = 0
    for i in range(0, len(payload_rows), batch):
        chunk = payload_rows[i : i + batch]
        body = json.dumps(chunk).encode()
        req = urllib.request.Request(endpoint, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", "replace")[:800]
            raise SystemExit(f"Supabase upsert failed HTTP {e.code}: {err}") from e
        sent += len(chunk)
        print(f"  upserted {sent:,}/{len(payload_rows):,}")
    print(f"Supabase upsert complete → {table} ({sent:,} rows)")


def find_latest_raw(raw_dir: Path, prefix: str) -> Path | None:
    files = sorted(raw_dir.glob(f"{prefix}*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ingest CSLB Master + Personnel statewide lists")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT, help="Output root (default data/cslb)")
    p.add_argument("--download", action="store_true", help="Download fresh Master (+ Personnel unless skipped)")
    p.add_argument("--skip-personnel", action="store_true", help="Do not download/join Personnel")
    p.add_argument("--from-raw", type=Path, help="Use existing raw dir instead of downloading")
    p.add_argument("--master-csv", type=Path, help="Explicit Master CSV path")
    p.add_argument("--personnel-csv", type=Path, help="Explicit Personnel CSV path")
    # filters
    p.add_argument("--status", help="Comma-separated PrimaryStatus values (e.g. CLEAR)")
    p.add_argument("--class", dest="classes", help="Comma-separated classifications (e.g. B,C10,C33)")
    p.add_argument("--business-type", help='Comma-separated BusinessType (e.g. "Sole Owner,Corporation")')
    p.add_argument("--county", help="Comma-separated counties")
    p.add_argument("--state", default="CA", help="Comma-separated states (default CA; empty = all)")
    p.add_argument("--expires-within", type=int, help="Keep licenses expiring within N days (and not past)")
    p.add_argument("--expires-after", type=int, help="Keep licenses with days_to_expiration >= N")
    p.add_argument("--limit", type=int, help="Max normalized rows after filters")
    p.add_argument("--upsert-supabase", action="store_true", help="Bulk upsert to Supabase cslb_licenses")
    p.add_argument("--supabase-table", default="cslb_licenses")
    p.add_argument("--slice-name", default="", help="Optional name suffix for filtered export files")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    out_dir: Path = args.out_dir
    raw_dir = out_dir / "raw"
    norm_dir = out_dir / "normalized"
    stamp = utc_stamp()

    master_path = args.master_csv
    personnel_path = args.personnel_csv

    if args.download:
        import shutil

        master_path = download(MASTER_URL, raw_dir / f"MasterLicenseData_{stamp}.csv")
        shutil.copy2(master_path, raw_dir / "MasterLicenseData_latest.csv")
        if not args.skip_personnel:
            personnel_path = download(PERSONNEL_URL, raw_dir / f"PersonnelData_{stamp}.csv")
            shutil.copy2(personnel_path, raw_dir / "PersonnelData_latest.csv")
    elif args.from_raw:
        raw_dir = args.from_raw
        master_path = master_path or find_latest_raw(raw_dir, "MasterLicenseData")
        if not args.skip_personnel:
            personnel_path = personnel_path or find_latest_raw(raw_dir, "PersonnelData")
    else:
        # default: use latest under out_dir/raw if present
        master_path = master_path or find_latest_raw(raw_dir, "MasterLicenseData")
        if not args.skip_personnel:
            personnel_path = personnel_path or find_latest_raw(raw_dir, "PersonnelData")

    if not master_path or not Path(master_path).exists():
        print("No Master CSV found. Pass --download or --master-csv / --from-raw.", file=sys.stderr)
        return 2

    print(f"Loading master: {master_path}")
    master_rows = load_master(Path(master_path))
    print(f"  master rows: {len(master_rows):,}")

    by_lic: dict[str, list[dict]] = {}
    if personnel_path and Path(personnel_path).exists() and not args.skip_personnel:
        print(f"Loading personnel: {personnel_path}")
        by_lic = load_personnel_by_license(Path(personnel_path))
        print(f"  licenses with personnel: {len(by_lic):,}")
    elif not args.skip_personnel:
        print("WARNING: Personnel CSV missing — principals will be empty", file=sys.stderr)

    today = date.today()
    print("Normalizing…")
    normalized = [
        normalize_license(r, by_lic.get((r.get("LicenseNo") or "").strip(), []), today) for r in master_rows
    ]

    status = [s.strip() for s in (args.status or "").split(",") if s.strip()] or None
    classes = [c.strip() for c in (args.classes or "").split(",") if c.strip()] or None
    business_types = [b.strip() for b in (args.business_type or "").split(",") if b.strip()] or None
    counties = [c.strip() for c in (args.county or "").split(",") if c.strip()] or None
    if args.state.strip() == "":
        states = None
    else:
        states = [s.strip() for s in args.state.split(",") if s.strip()] or None

    filtered = apply_filters(
        normalized,
        status=status,
        classes=classes,
        business_types=business_types,
        counties=counties,
        states=states,
        expires_within=args.expires_within,
        expires_after=args.expires_after,
        limit=args.limit,
    )
    print(f"After filters: {len(filtered):,} / {len(normalized):,}")

    suffix = f"_{args.slice_name}" if args.slice_name else ""
    if args.expires_within and not args.slice_name:
        suffix = f"_expires{args.expires_within}d"
    full_path = norm_dir / f"cslb_licenses_{stamp}{suffix}.csv"
    latest_path = norm_dir / "cslb_licenses_latest.csv"
    write_csv(full_path, filtered)
    import shutil

    shutil.copy2(full_path, latest_path)
    print(f"Also wrote {latest_path}")

    principals_path = norm_dir / f"cslb_principals_{stamp}{suffix}.jsonl"
    write_jsonl_principals(principals_path, filtered)
    shutil.copy2(principals_path, norm_dir / "cslb_principals_latest.jsonl")

    meta = {
        "stamp": stamp,
        "master_source": str(master_path),
        "personnel_source": str(personnel_path) if personnel_path else None,
        "master_rows": len(master_rows),
        "normalized_rows": len(normalized),
        "filtered_rows": len(filtered),
        "filters": {
            "status": status,
            "classes": classes,
            "business_types": business_types,
            "counties": counties,
            "states": states,
            "expires_within": args.expires_within,
            "expires_after": args.expires_after,
            "limit": args.limit,
        },
        "outputs": {
            "licenses_csv": str(full_path),
            "licenses_latest": str(latest_path),
            "principals_jsonl": str(principals_path),
        },
        "note": "CSLB does not provide email addresses (B&P Code §27).",
    }
    meta_path = norm_dir / f"ingest_meta_{stamp}{suffix}.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    (norm_dir / "ingest_meta_latest.json").write_text(json.dumps(meta, indent=2))
    print(f"Wrote {meta_path}")

    if args.upsert_supabase:
        upsert_supabase(filtered, table=args.supabase_table)

    # summary for sales slices
    clear_n = sum(1 for r in filtered if (r.get("primary_status") or "").upper() == "CLEAR")
    exp120 = sum(1 for r in filtered if r.get("expires_within_120"))
    with_principal = sum(1 for r in filtered if r.get("primary_principal_name"))
    print(
        f"Summary: CLEAR={clear_n:,} expires≤120d={exp120:,} "
        f"with_principal={with_principal:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
