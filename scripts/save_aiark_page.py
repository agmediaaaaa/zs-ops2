"""Copy AI Ark people_search MCP dump into page_XXX.json (content object only)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = ROOT / "artifacts" / "healthcare-export" / "aiark_pages"


def extract_payload(text: str) -> dict:
    # Full MCP tool JSON on one line
    try:
        outer = json.loads(text)
        if "content" in outer:
            return outer
    except json.JSONDecodeError:
        pass

    # Wrapped in tool result string with content array
    start = text.find('{"content":')
    if start == -1:
        start = text.find('"content":')
    if start == -1:
        raise ValueError("Could not find content in MCP dump")

    snippet = text[start:]
    # balance braces naively from first {
    if not snippet.startswith("{"):
        snippet = "{" + snippet.split("{", 1)[1]
    depth = 0
    end = 0
    for i, ch in enumerate(snippet):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    payload = json.loads(snippet[:end])
    return payload


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: save_aiark_page.py <page_number> <source_txt>")
        sys.exit(1)
    page = int(sys.argv[1])
    src = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8", errors="replace")
    payload = extract_payload(text)
    out = PAGES_DIR / f"page_{page:03d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    n = len(payload.get("content") or [])
    print(f"Saved page {page} with {n} contacts -> {out}")


if __name__ == "__main__":
    main()
