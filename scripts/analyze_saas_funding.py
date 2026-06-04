import csv
from collections import Counter
from pathlib import Path

files = [
    r"c:\Users\Rohan\Downloads\SaaS-Founders(51-200)-Apr 06.2026.csv",
    r"c:\Users\Rohan\Downloads\Saas Founders-May 14 (1).csv",
    r"c:\Users\Rohan\Downloads\Saas Founders-May 14.csv",
    r"c:\Users\Rohan\Downloads\Csuite-saas-May 12.csv",
    r"c:\Users\Rohan\Downloads\Founders-SaaS(11-50)-May 11.2026.csv",
    r"c:\Users\Rohan\Downloads\Founders- SaaS (b2b)(11-50)-May 06.2026.csv",
    r"c:\Users\Rohan\Downloads\SaaS-Founders(51-200)-Apr 06.2026 (1).csv",
    r"c:\Users\Rohan\Downloads\Csuite- SaaS- (11-200).csv",
]

funding_types = Counter()
emp_counts = Counter()
sizes = []

for f in files:
    p = Path(f)
    with open(p, newline="", encoding="utf-8-sig", errors="replace") as fh:
        r = csv.DictReader(fh)
        for row in r:
            ft = (row.get("Company Last Funding Type") or "").strip()
            if ft:
                funding_types[ft] += 1
            ec = (row.get("Company Employee Count") or "").strip()
            if ec:
                emp_counts[ec] += 1
            try:
                sz = int(float((row.get("Company Size") or "").strip() or 0))
                if sz:
                    sizes.append(sz)
            except ValueError:
                pass

print("Funding types (non-empty):")
for k, v in funding_types.most_common():
    print(f"  {k}: {v}")

print("\nEmployee count buckets:")
for k, v in emp_counts.most_common():
    print(f"  {k}: {v}")

print(f"\nCompany Size numeric: min={min(sizes) if sizes else 0}, max={max(sizes) if sizes else 0}")
