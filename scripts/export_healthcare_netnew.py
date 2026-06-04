"""Merge AI Ark people_search page JSON + dedupe vs Lead DB -> Csuite healthcare CSV."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = ROOT / "artifacts" / "healthcare-export" / "aiark_pages"
EXISTING_LINKEDIN = ROOT / "artifacts" / "healthcare-export" / "existing_linkedin.json"
OUT_CSV = ROOT / "artifacts" / "healthcare-export" / "Csuite-healthcare-netnew-3000.csv"

LABEL = "Csuite healthcare"
TARGET = 3000

STANDARD_HEADERS = [
    "First Name",
    "Last Name",
    "Title",
    "Org",
    "Headline",
    "Summary",
    "Creator",
    "MX Records",
    "Email Business",
    "Business Status",
    "Domain Settings",
    "Mobile Phone",
    "Country",
    "State",
    "City",
    "Seniority",
    "Department",
    "LinkedIn",
    "Company Name",
    "Company Employee Count",
    "Company Size",
    "Company Industry",
    "Company Product and Services",
    "Company Description",
    "Company Website",
    "Company LinkedIn",
    "Company Type",
    "Company Number Of Locations",
    "Company Annual Revenue",
    "Company Total Funding",
    "Company Last Funding Type",
    "Domain",
    "Email Status",
    "Domain Type",
    "Label",
]


def norm_linkedin(url: str | None) -> str:
    if not url:
        return ""
    u = url.strip().lower().rstrip("/")
    u = re.sub(r"\?.*$", "", u)
    return u


def load_existing() -> set[str]:
    if not EXISTING_LINKEDIN.exists():
        return set()
    data = json.loads(EXISTING_LINKEDIN.read_text(encoding="utf-8"))
    return {norm_linkedin(x) for x in data if x}


def staff_fields(staff: dict | None) -> tuple[str, str]:
    if not staff:
        return "", ""
    total = staff.get("total")
    rng = staff.get("range") or {}
    lo, hi = rng.get("start"), rng.get("end")
    if lo is not None and hi is not None:
        bucket = f"{lo}-{hi}"
    elif lo is not None:
        bucket = f"{lo}+"
    else:
        bucket = ""
    size = str(total) if total is not None else ""
    return bucket, size


def revenue_str(fin: dict | None) -> str:
    if not fin:
        return ""
    rev = (fin.get("revenue") or {}).get("annual") or {}
    return rev.get("amount") or ""


def funding_fields(fin: dict | None) -> tuple[str, str]:
    if not fin:
        return "", ""
    fund = fin.get("funding") or {}
    total = fund.get("total_amount")
    ftype = fund.get("type")
    return (str(total) if total is not None else ""), (ftype or "")


def _org_name(item: dict, csum: dict) -> str:
    groups = item.get("position_groups") or []
    if groups:
        company = groups[0].get("company") or {}
        name = company.get("name")
        if name:
            return name
    return csum.get("name") or ""


def person_to_row(item: dict) -> dict[str, str]:
    profile = item.get("profile") or {}
    link = item.get("link") or {}
    loc = item.get("location") or {}
    dept = item.get("department") or {}
    company = item.get("company") or {}
    csum = company.get("summary") or {}
    clink = company.get("link") or {}
    cfin = company.get("financial") or {}
    cloc = company.get("location") or {}

    emp_count_bucket, emp_size = staff_fields(csum.get("staff"))
    rev = revenue_str(cfin)
    total_fund, last_fund = funding_fields(cfin)

    industries = csum.get("industries") or []
    if isinstance(industries, list):
        industry = ", ".join(industries) if industries else (csum.get("industry") or "")
    else:
        industry = csum.get("industry") or ""

    keywords = csum.get("keywords") or []
    products = ", ".join(keywords) if isinstance(keywords, list) else ""

    departments = dept.get("departments") or []
    dept_str = ", ".join(departments) if isinstance(departments, list) else ""

    domain = clink.get("domain_ltd") or clink.get("domain") or ""
    if domain and "://" in domain:
        domain = re.sub(r"^https?://", "", domain).split("/")[0]

    sub_orgs = csum.get("sub_organizations") or []
    num_locs = str(len(sub_orgs)) if sub_orgs else "0"

    badges = item.get("member_badges") or {}
    creator = "Yes" if badges.get("creator") else "No"

    return {
        "First Name": profile.get("first_name") or "",
        "Last Name": profile.get("last_name") or "",
        "Title": profile.get("title") or "",
        "Org": _org_name(item, csum),
        "Headline": profile.get("headline") or "",
        "Summary": profile.get("summary") or "",
        "Creator": creator,
        "MX Records": "",
        "Email Business": link.get("email") or item.get("email") or "",
        "Business Status": "",
        "Domain Settings": "",
        "Mobile Phone": link.get("phone") or "",
        "Country": loc.get("country") or (cloc.get("headquarter") or {}).get("country") or "",
        "State": loc.get("state") or (cloc.get("headquarter") or {}).get("state") or "",
        "City": loc.get("city") or (cloc.get("headquarter") or {}).get("city") or "",
        "Seniority": dept.get("seniority") or "",
        "Department": dept_str,
        "LinkedIn": link.get("linkedin") or "",
        "Company Name": csum.get("name") or "",
        "Company Employee Count": emp_count_bucket,
        "Company Size": emp_size,
        "Company Industry": industry,
        "Company Product and Services": products,
        "Company Description": csum.get("description") or "",
        "Company Website": clink.get("website") or clink.get("domain") or "",
        "Company LinkedIn": clink.get("linkedin") or "",
        "Company Type": csum.get("type") or "",
        "Company Number Of Locations": num_locs,
        "Company Annual Revenue": rev,
        "Company Total Funding": total_fund,
        "Company Last Funding Type": last_fund,
        "Domain": domain,
        "Email Status": "",
        "Domain Type": "",
        "Label": LABEL,
    }


def iter_page_files() -> list[Path]:
    return sorted(PAGES_DIR.glob("page_*.json"))


def main() -> None:
    existing = load_existing()
    seen: set[str] = set()
    rows: list[dict[str, str]] = []

    for path in iter_page_files():
        payload = json.loads(path.read_text(encoding="utf-8"))
        content = payload.get("content") or []
        for item in content:
            li = norm_linkedin((item.get("link") or {}).get("linkedin"))
            if not li or li in existing or li in seen:
                continue
            seen.add(li)
            rows.append(person_to_row(item))
            if len(rows) >= TARGET:
                break
        if len(rows) >= TARGET:
            break

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STANDARD_HEADERS)
        writer.writeheader()
        writer.writerows(rows[:TARGET])

    print(f"Wrote {len(rows[:TARGET])} rows to {OUT_CSV}")
    print(f"Pages scanned: {len(list(iter_page_files()))}")
    print(f"Existing linkedin loaded: {len(existing)}")


if __name__ == "__main__":
    main()
