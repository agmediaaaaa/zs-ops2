"""Deploy normalized custom-talent step-1 scripts to configured PlusVibe workspaces."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIR = ROOT / "clients" / "custom-talent"
CONFIG_FILE = CLIENT_DIR / "workspaces.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plusvibe_campaign_utils import deploy_campaign, load_normalized_variations  # noqa: E402


def main() -> None:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    scripts_path = CLIENT_DIR / config["scripts_file"]
    _, variations = load_normalized_variations(scripts_path)

    targets = config.get("deployments") or []
    if len(sys.argv) > 1:
        wanted = {a.lower() for a in sys.argv[1:]}
        targets = [t for t in targets if t.get("label", "").lower() in wanted]

    for target in targets:
        label = target["label"]
        patch_rel = target.get("patch_file")
        patch_out = (CLIENT_DIR / patch_rel).resolve() if patch_rel else None
        campaign_id = deploy_campaign(
            workspace_id=target["workspace_id"],
            campaign_name=target["campaign_name"],
            template_workspace_id=target["template_workspace_id"],
            template_campaign_id=target["template_campaign_id"],
            variations=variations,
            patch_out=patch_out,
        )
        print(f"{label}: campaign_id={campaign_id}")
        if patch_out:
            print(f"  patch -> {patch_out}")


if __name__ == "__main__":
    main()
