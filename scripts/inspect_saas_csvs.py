import csv
from pathlib import Path

files = [
    r"c:\Users\Rohan\Downloads\SaaS-Founders(51-200)-Apr 06.2026.csv",
    r"c:\Users\Rohan\Downloads\Saas Founders-May 14 (1).csv",
    r"c:\Users\Rohan\Downloads\Saas Founders-May 14.csv",
    r"c:\Users\Rohan\Downloads\Csuite-saas-May 12.csv",
    r"c:\Users\Rohan\Downloads\Founders-SaaS(11-50)-May 11.2026.csv",
    r"c:\Users\Rohan\Downloads\Founders- SaaS (b2b)(11-50)-May 06.2026.enriched10.no-upload.csv",
    r"c:\Users\Rohan\Downloads\Founders- SaaS (b2b)(11-50)-May 06.2026.csv",
    r"c:\Users\Rohan\Downloads\SaaS-Founders(51-200)-Apr 06.2026 (1).csv",
    r"c:\Users\Rohan\Downloads\Csuite- SaaS- (11-200).csv",
]

for f in files:
    p = Path(f)
    if not p.exists():
        print(f"MISSING: {f}")
        continue
    with open(p, newline="", encoding="utf-8-sig", errors="replace") as fh:
        r = csv.reader(fh)
        headers = next(r)
        rows = [next(r, None) for _ in range(3)]

    print(f"\n=== {p.name} ===")
    print("Columns:", len(headers))
    for i, h in enumerate(headers):
        hl = h.lower()
        if any(x in hl for x in ["size", "fund", "employee", "headcount", "series", "invest"]):
            print(f"  [{i}] {h}")
    print("All headers:", headers)
    for row in rows:
        if not row:
            continue
        for i, h in enumerate(headers):
            hl = h.lower()
            if any(x in hl for x in ["size", "fund", "employee", "headcount", "series", "invest"]):
                val = row[i] if i < len(row) else ""
                print(f"  sample {h}: {val[:120]}")
