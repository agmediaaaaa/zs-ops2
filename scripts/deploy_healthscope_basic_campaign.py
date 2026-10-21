"""Create a basic Healthscope campaign: ZS settings, subject {{first_name}} only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plusvibe_campaign_utils import (  # noqa: E402
    build_patch,
    create_campaign,
    deploy_campaign,
    extract_settings,
    fetch_campaign,
    find_campaign_by_name,
    plusvibe_request,
)

HEALTHSCOPE_WS = "6a1334c74be1e70c4918deab"
ZS_WS = "69a5b2169433a45c6f6d7d1c"
ZS_TEMPLATE_CAMP = "69fae9c435ed857458d57321"  # v2 SaaS(11-50)-Csuite-Google
CAMPAIGN_NAME = "Basic Outreach"
OUT = Path(__file__).resolve().parents[1] / "clients" / "healthscope" / "basic-campaign-patch.json"

VARIATIONS = [
    {
        "variation": "A",
        "name": "Basic",
        "subject": "{{first_name}}",
        "body": "<div><br></div>",
    }
]


def main() -> None:
    campaign_id = find_campaign_by_name(HEALTHSCOPE_WS, CAMPAIGN_NAME) or create_campaign(
        HEALTHSCOPE_WS, CAMPAIGN_NAME
    )
    settings = extract_settings(fetch_campaign(ZS_WS, ZS_TEMPLATE_CAMP))
    payload = build_patch(
        workspace_id=HEALTHSCOPE_WS,
        campaign_id=campaign_id,
        variations=VARIATIONS,
        settings=settings,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plusvibe_request("PATCH", "/campaign/update/campaign", payload)
    print("workspace_id", HEALTHSCOPE_WS)
    print("campaign_id", campaign_id)
    print("campaign_name", CAMPAIGN_NAME)
    print("patch", OUT)


if __name__ == "__main__":
    main()
