"""Build PlusVibe patch for Hire Tech step-1 scripts (8 variants).

Copies campaign-level settings from a ZS (UltraTalent) workspace campaign export,
then applies Hire Tech step-1 copy with subject {{first_name}}.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "clients" / "hire-tech" / "plusvibe.config.json"
SCRIPTS_FILE = ROOT / "clients" / "hire-tech" / "hire-tech-step1-scripts.json"
OUT_FILE = ROOT / "clients" / "hire-tech" / "hire-tech-campaign-patch.json"
ZS_SETTINGS_FALLBACK = ROOT / "clients" / "hire-tech" / "zs-campaign-settings-template.json"

DEFAULT_CAMP_FILE = Path(
    os.environ.get(
        "CAMP_FILE",
        r"C:\Users\Rohan\.cursor\projects\c-Users-Rohan-zs-operations-zs-ops"
        r"\agent-tools\f0f2ec0a-5db7-4076-97d3-3ab3f361dd33.txt",
    )
)

DAY_NAME_TO_NUM = {
    "monday": "1",
    "tuesday": "2",
    "wednesday": "3",
    "thursday": "4",
    "friday": "5",
    "saturday": "6",
    "sunday": "7",
}

# Fields copied from ZS campaigns onto the Hire Tech patch (when present).
SETTINGS_KEYS = (
    "first_wait_time",
    "opportunity_val",
    "is_pause_on_bouncerate",
    "bounce_rate_limit",
    "send_as_txt",
    "stop_on_lead_replied",
    "is_emailopened_tracking",
    "is_unsubscribed_link",
    "exclude_ooo",
    "is_acc_based_sending",
    "send_risky_email",
    "unsub_blocklist",
    "other_email_acc",
    "is_esp_match",
    "send_priority",
    "daily_limit",
    "interval_limit_in_min",
    "email_accounts",
    "var_sel_type",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_campaigns(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw[raw.find("[") :])


def find_campaign(campaigns: list[dict], camp_name: str) -> dict:
    for camp in campaigns:
        if camp.get("camp_name") == camp_name:
            return camp
    names = [c.get("camp_name") for c in campaigns[:20]]
    raise KeyError(f"Campaign not found: {camp_name!r}. Sample names: {names}")


def yn(value: Any) -> str | None:
    """Normalize PlusVibe yes/no flags to 'yes'/'no' strings."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("yes", "no"):
            return v
        if v in ("1", "true"):
            return "yes"
        if v in ("0", "false"):
            return "no"
    if isinstance(value, (int, float)):
        return "yes" if value else "no"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return None


def schedule_to_schedules(schedule: dict | None, daily_limit: int | None) -> list[dict] | None:
    if not schedule:
        return None
    days_in = schedule.get("days") or []
    days_out: dict[str, bool] = {}
    if isinstance(days_in, list):
        for day in days_in:
            num = DAY_NAME_TO_NUM.get(str(day).strip().lower())
            if num:
                days_out[num] = True
    elif isinstance(days_in, dict):
        days_out = {str(k): bool(v) for k, v in days_in.items()}
    if not days_out:
        days_out = {"1": True, "2": True, "3": True, "4": True, "5": True}
    tz = schedule.get("tz") or schedule.get("timezone") or "America/New_York"
    from_time = schedule.get("from_time") or schedule.get("timing", {}).get("from") or "09:00"
    to_time = schedule.get("to_time") or schedule.get("timing", {}).get("to") or "17:00"
    from datetime import date

    return [
        {
            "daily_limit": daily_limit or 500,
            "start_date": date.today().isoformat(),
            "end_date": "",
            "days": days_out,
            "timezone": tz,
            "timing": {"from": from_time, "to": to_time},
        }
    ]


def extract_settings(camp: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SETTINGS_KEYS:
        if key in camp and camp[key] is not None:
            val = camp[key]
            if key in (
                "is_pause_on_bouncerate",
                "send_as_txt",
                "stop_on_lead_replied",
                "is_emailopened_tracking",
                "is_unsubscribed_link",
                "exclude_ooo",
                "is_acc_based_sending",
                "send_risky_email",
                "unsub_blocklist",
                "other_email_acc",
                "is_esp_match",
            ):
                normalized = yn(val)
                if normalized:
                    out[key] = normalized
            else:
                out[key] = val

    schedules = schedule_to_schedules(camp.get("schedule"), camp.get("daily_limit"))
    if schedules:
        out["schedules"] = schedules

    # Step 1 wait_time from first sequence step when available.
    sequences = camp.get("sequences") or []
    for seq in sequences:
        if seq.get("step") == 1:
            out["step1_wait_time"] = seq.get("wait_time", 2)
            break
    return out


def load_zs_settings(template_name: str) -> dict[str, Any]:
    if DEFAULT_CAMP_FILE.exists():
        campaigns = load_campaigns(DEFAULT_CAMP_FILE)
        camp = find_campaign(campaigns, template_name)
        return extract_settings(camp)
    if ZS_SETTINGS_FALLBACK.exists():
        return load_json(ZS_SETTINGS_FALLBACK)
    return {
        "first_wait_time": 0,
        "opportunity_val": 10000,
        "is_pause_on_bouncerate": "yes",
        "bounce_rate_limit": 2.5,
        "send_as_txt": "yes",
        "stop_on_lead_replied": "yes",
        "step1_wait_time": 2,
    }


def build_variations(scripts_doc: dict, subject: str) -> list[dict]:
    variations = []
    for item in scripts_doc["variations"]:
        variations.append(
            {
                "variation": item["variation"],
                "name": item["name"],
                "subject": subject,
                "body": item["body"],
            }
        )
    return variations


def main() -> None:
    config = load_json(CONFIG_FILE)
    scripts_doc = load_json(SCRIPTS_FILE)
    subject = config.get("subject_line") or scripts_doc.get("subject") or "{{first_name}}"

    zs_template = config.get("zs_template_campaign") or "v2 Sales"
    zs_settings = load_zs_settings(zs_template)
    step1_wait = zs_settings.pop("step1_wait_time", 2)

    workspace_id = (config.get("workspace_id") or os.environ.get("HIRE_TECH_WORKSPACE_ID") or "").strip()
    campaign_id = (config.get("campaign_id") or os.environ.get("HIRE_TECH_CAMPAIGN_ID") or "").strip()

    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "campaign_id": campaign_id,
        "sequences": [
            {
                "step": 1,
                "wait_time": step1_wait,
                "variations": build_variations(scripts_doc, subject),
            }
        ],
    }
    payload.update({k: v for k, v in zs_settings.items() if k != "schedules"})
    if "schedules" in zs_settings:
        payload["schedules"] = zs_settings["schedules"]

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT_FILE)
    print("variations", len(payload["sequences"][0]["variations"]))
    print("zs_template", zs_template)
    if not workspace_id or not campaign_id:
        print(
            "note: set workspace_id and campaign_id in plusvibe.config.json "
            "before applying the patch"
        )


if __name__ == "__main__":
    main()
