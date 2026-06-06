"""List PlusVibe workspaces (GET /authenticate) to resolve workspace IDs."""
from __future__ import annotations

import json
import urllib.request

from apply_plusvibe_campaign_patch import load_api_key


def main() -> None:
    api_key = load_api_key()
    req = urllib.request.Request(
        "https://api.plusvibe.ai/api/v1/authenticate",
        headers={"x-api-key": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    for ws in data.get("workspaces") or []:
        print(f"{ws.get('_id')}\t{ws.get('name')}")


if __name__ == "__main__":
    main()
