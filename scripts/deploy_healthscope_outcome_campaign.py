"""Create Healthscope v3 Outcome Outreach campaign from v2 Basic Outreach settings + reframed scripts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plusvibe_campaign_utils import (  # noqa: E402
    build_patch,
    create_campaign,
    extract_settings,
    fetch_campaign,
    find_campaign_by_name,
    load_normalized_variations,
    plusvibe_request,
)

HEALTHSCOPE_WS = "6a1334c74be1e70c4918deab"
SOURCE_CAMP = "6a2acf75f0d8168dbe5ee131"  # v2 Basic Outreach
CAMPAIGN_NAME = "v3 Outcome Outreach"
SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "clients"
    / "healthscope"
    / "healthscope-step1-scripts-reframed.json"
)
PATCH_OUT = (
    Path(__file__).resolve().parents[1]
    / "clients"
    / "healthscope"
    / "outcome-outreach-campaign-patch.json"
)
CONFIG_OUT = Path(__file__).resolve().parents[1] / "clients" / "healthscope" / "plusvibe.config.json"


def main() -> None:
    campaign_id = find_campaign_by_name(HEALTHSCOPE_WS, CAMPAIGN_NAME) or create_campaign(
        HEALTHSCOPE_WS, CAMPAIGN_NAME
    )
    source = fetch_campaign(HEALTHSCOPE_WS, SOURCE_CAMP)
    settings = extract_settings(source)
    _, variations = load_normalized_variations(SCRIPTS)
    payload = build_patch(
        workspace_id=HEALTHSCOPE_WS,
        campaign_id=campaign_id,
        variations=variations,
        settings=settings,
    )
    if source.get("email_accounts"):
        payload["email_accounts"] = source["email_accounts"]

    PATCH_OUT.parent.mkdir(parents=True, exist_ok=True)
    PATCH_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plusvibe_request("PATCH", "/campaign/update/campaign", payload)

    config = json.loads(CONFIG_OUT.read_text(encoding="utf-8")) if CONFIG_OUT.exists() else {}
    config.update(
        {
            "workspace_name": "Healthscope Services",
            "workspace_id": HEALTHSCOPE_WS,
            "campaign_id": campaign_id,
            "campaign_name": CAMPAIGN_NAME,
            "source_campaign_id": SOURCE_CAMP,
            "source_campaign_name": source.get("camp_name"),
            "scripts_file": str(SCRIPTS.relative_to(SCRIPTS.parents[2])),
        }
    )
    CONFIG_OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("workspace_id", HEALTHSCOPE_WS)
    print("campaign_id", campaign_id)
    print("campaign_name", CAMPAIGN_NAME)
    print("variations", len(variations))
    print("email_accounts", len(payload.get("email_accounts") or []))
    print("patch", PATCH_OUT)


if __name__ == "__main__":
    main()
