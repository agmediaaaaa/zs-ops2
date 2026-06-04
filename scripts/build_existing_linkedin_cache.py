"""Build existing_linkedin.json from Supabase execute_sql batch exports."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "healthcare-export" / "existing_linkedin.json"
AGENT_TOOLS = Path(r"C:\Users\Rohan\.cursor\projects\c-Users-Rohan-zs-operations-zs-ops\agent-tools")

BATCH_FILES = [
    "388df752-db80-4d96-8704-17a5ffc6e160.txt",
    "48ad8b35-d590-41bb-a9b8-9c9ae01c14b2.txt",
    "f32e726f-0359-4024-ad57-3751ef58ef41.txt",
    "82ee55d3-49d7-4bfd-a658-f920d7c12cbf.txt",
    "ec904e5a-f147-4ace-8a0e-1459aaa5432f.txt",
]

LINKEDIN_RE = re.compile(r"https://www\.linkedin\.com/in/[^\"\\]+")


def norm(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    return re.sub(r"\?.*$", "", u)


def extract_rows(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return LINKEDIN_RE.findall(text)


def main() -> None:
    urls: set[str] = set()
    for name in BATCH_FILES:
        path = AGENT_TOOLS / name
        if not path.exists():
            prefix = name.split("-")[0]
            matches = sorted(AGENT_TOOLS.glob(f"{prefix}*.txt"))
            if not matches:
                print(f"skip missing {name}")
                continue
            path = matches[-1]
        found = extract_rows(path)
        for u in found:
            n = norm(u)
            if n:
                urls.add(n)
        print(f"{path.name}: +{len(found)} rows, unique total {len(urls)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sorted(urls), ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(urls)} linkedin URLs to {OUT}")


if __name__ == "__main__":
    main()
