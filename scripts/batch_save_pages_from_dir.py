"""Save all unsaved agent-tools people_search dumps into page files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

AGENT_TOOLS = Path(r"C:\Users\Rohan\.cursor\projects\c-Users-Rohan-zs-operations-zs-ops\agent-tools")
PAGES_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "healthcare-export" / "aiark_pages"
SAVE = Path(__file__).resolve().parent / "save_aiark_page.py"


def is_people_search_dump(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:5000]
    except OSError:
        return False
    return '"content":' in head and "profile" in head


def existing_pages() -> set[int]:
    nums = set()
    for p in PAGES_DIR.glob("page_*.json"):
        m = re.search(r"page_(\d+)", p.name)
        if m:
            nums.add(int(m.group(1)))
    return nums


def main() -> None:
    existing = existing_pages()
    next_page = max(existing) + 1 if existing else 0
    dumps = sorted(
        [p for p in AGENT_TOOLS.glob("*.txt") if is_people_search_dump(p)],
        key=lambda p: p.stat().st_mtime,
    )
    saved = 0
    for dump in dumps:
        if next_page in existing:
            next_page += 1
            continue
        out = PAGES_DIR / f"page_{next_page:03d}.json"
        if out.exists():
            next_page += 1
            continue
        subprocess.run([sys.executable, str(SAVE), str(next_page), str(dump)], check=True)
        existing.add(next_page)
        print(f"page {next_page} <- {dump.name}")
        next_page += 1
        saved += 1
    print(f"Saved {saved} new pages; total pages {len(list(PAGES_DIR.glob('page_*.json')))}")


if __name__ == "__main__":
    main()
