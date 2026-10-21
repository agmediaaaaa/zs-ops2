"""Apply a PlusVibe campaign patch JSON via PATCH /campaign/update/campaign."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_api_key() -> str:
    for name in ("PLUSVIBE_API_KEY", "PLUSVIBE_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    mcp_path = Path.home() / ".cursor" / "mcp.json"
    if mcp_path.exists():
        import urllib.parse

        mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        plusvibe = mcp.get("mcpServers", {}).get("plusvibe", {})
        url_mcp = plusvibe.get("url") or (plusvibe.get("args") or [None])[-1]
        if url_mcp:
            return urllib.parse.parse_qs(urllib.parse.urlparse(url_mcp).query)["api_key"][0]
    raise SystemExit(
        "Set PLUSVIBE_API_KEY (or PLUSVIBE_KEY), or configure plusvibe in ~/.cursor/mcp.json"
    )


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <patch.json>")

    patch_path = Path(sys.argv[1])
    payload = json.loads(patch_path.read_text(encoding="utf-8"))
    workspace_id = (payload.get("workspace_id") or "").strip()
    campaign_id = (payload.get("campaign_id") or "").strip()
    if not workspace_id or not campaign_id:
        raise SystemExit(
            "patch.json must include workspace_id and campaign_id before applying"
        )

    api_key = load_api_key()
    url = "https://api.plusvibe.ai/api/v1/campaign/update/campaign"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PATCH",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {err_body}") from exc

    print("applied patch to campaign", campaign_id)
    print(body[:500])


if __name__ == "__main__":
    main()
