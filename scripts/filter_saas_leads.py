"""Filter SaaS lead CSVs into 50+ employees (non-funded) and qualifying-funded lists."""

from __future__ import annotations

import csv
import re
from pathlib import Path

INPUT_FILES = [
    Path(r"c:\Users\Rohan\Downloads\SaaS-Founders(51-200)-Apr 06.2026.csv"),
    Path(r"c:\Users\Rohan\Downloads\Saas Founders-May 14 (1).csv"),
    Path(r"c:\Users\Rohan\Downloads\Saas Founders-May 14.csv"),
    Path(r"c:\Users\Rohan\Downloads\Csuite-saas-May 12.csv"),
    Path(r"c:\Users\Rohan\Downloads\Founders-SaaS(11-50)-May 11.2026.csv"),
    Path(r"c:\Users\Rohan\Downloads\Founders- SaaS (b2b)(11-50)-May 06.2026.csv"),
    Path(r"c:\Users\Rohan\Downloads\SaaS-Founders(51-200)-Apr 06.2026 (1).csv"),
    Path(r"c:\Users\Rohan\Downloads\Csuite- SaaS- (11-200).csv"),
]

OUT_50_PLUS = Path(r"c:\Users\Rohan\Downloads\SaaS-leads-50plus-employees.csv")
OUT_FUNDED = Path(r"c:\Users\Rohan\Downloads\SaaS-leads-funded-series-vc-pe.csv")

# Positive match: Series rounds, venture/VC, private equity.
QUALIFYING_FUNDING_RE = re.compile(
    r"^(SERIES_[A-Z0-9_]+|VENTURE_ROUND|PRIVATE_EQUITY(_ROUND)?)(_|$)",
    re.IGNORECASE,
)

# Explicit exclusions even if they look like equity (debt, grants, early stage, etc.).
EXCLUDED_FUNDING_RE = re.compile(
    r"(DEBT|GRANT|SEED|PRE_SEED|CONVERTIBLE|ANGEL|CROWDFUND|ICO|"
    r"NON_EQUITY|SECONDARY|UNDISCLOSED|CORPORATE_ROUND|FUNDING_ROUND|"
    r"POST_IPO|ASSISTANCE|EQUITY_CROWD)",
    re.IGNORECASE,
)

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
]


def parse_emp_bucket(value: str) -> tuple[int | None, int | None]:
    s = (value or "").strip().lower()
    if not s or s in {"null+", "null"}:
        return None, None
    if "+" in s and "-" not in s:
        digits = re.sub(r"[^\d]", "", s.replace("+", ""))
        return (int(digits), None) if digits else (None, None)
    if "-" in s:
        left, right = s.split("-", 1)
        left_digits = re.sub(r"[^\d]", "", left)
        right_digits = re.sub(r"[^\d]", "", right)
        lo = int(left_digits) if left_digits else None
        hi = int(right_digits) if right_digits else None
        return lo, hi
    digits = re.sub(r"[^\d]", "", s)
    if digits:
        n = int(digits)
        return n, n
    return None, None


def is_50_plus_employees(row: dict[str, str]) -> bool:
    size_raw = (row.get("Company Size") or "").strip()
    if size_raw:
        try:
            if float(size_raw) >= 50:
                return True
        except ValueError:
            pass

    lo, _hi = parse_emp_bucket(row.get("Company Employee Count", ""))
    return lo is not None and lo >= 50


def is_qualifying_funded(row: dict[str, str]) -> bool:
    funding_type = (row.get("Company Last Funding Type") or "").strip()
    if not funding_type:
        return False
    if EXCLUDED_FUNDING_RE.search(funding_type):
        return False
    return bool(QUALIFYING_FUNDING_RE.match(funding_type))


def row_key(row: dict[str, str]) -> str:
    email = (row.get("Email Business") or "").strip().lower()
    if email:
        return f"email:{email}"
    linkedin = (row.get("LinkedIn") or "").strip().lower()
    if linkedin:
        return f"linkedin:{linkedin}"
    first = (row.get("First Name") or "").strip().lower()
    last = (row.get("Last Name") or "").strip().lower()
    company = (row.get("Company Name") or "").strip().lower()
    return f"name:{first}|{last}|{company}"


def load_rows() -> list[dict[str, str]]:
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for path in INPUT_FILES:
        if not path.exists():
            raise FileNotFoundError(path)
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                key = row_key(row)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STANDARD_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    all_rows = load_rows()
    funded_rows = [r for r in all_rows if is_qualifying_funded(r)]
    funded_keys = {row_key(r) for r in funded_rows}
    plus_50_rows = [
        r
        for r in all_rows
        if is_50_plus_employees(r) and row_key(r) not in funded_keys
    ]

    write_csv(OUT_FUNDED, funded_rows)
    write_csv(OUT_50_PLUS, plus_50_rows)

    print(f"Unique leads loaded: {len(all_rows)}")
    print(f"Qualifying funded: {len(funded_rows)} -> {OUT_FUNDED}")
    print(f"50+ employees (excluding funded): {len(plus_50_rows)} -> {OUT_50_PLUS}")

    ft_counts: dict[str, int] = {}
    for r in funded_rows:
        ft = (r.get("Company Last Funding Type") or "").strip()
        ft_counts[ft] = ft_counts.get(ft, 0) + 1
    print("\nFunded breakdown by type:")
    for ft, n in sorted(ft_counts.items(), key=lambda x: -x[1]):
        print(f"  {ft}: {n}")


if __name__ == "__main__":
    main()
