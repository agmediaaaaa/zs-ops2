"""Create/update Hire Tech campaign with step-1 scripts and ZS campaign settings."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_FILE = ROOT / "clients" / "hire-tech" / "hire-tech-step1-scripts.json"
OUT_FILE = ROOT / "clients" / "hire-tech" / "hire-tech-campaign-patch.json"

HIRE_TECH_WS = "6a13348c960455ee22ae829d"
ZS_WS = "69a5b2169433a45c6f6d7d1c"
ZS_TEMPLATE_CAMP = "69fae9c435ed857458d57321"  # v2 SaaS(11-50)-Csuite-Google
NEW_CAMP_NAME = "Hire Tech - Custom Scripts (8 variants)"

DAY_NAME_TO_NUM = {
    "monday": "1",
    "tuesday": "2",
    "wednesday": "3",
    "thursday": "4",
    "friday": "5",
    "saturday": "6",
    "sunday": "7",
}


def api_key() -> str:
    key = os.environ.get("PLUSVIBE_API_KEY") or os.environ.get("PLUSVIBE_KEY") or ""
    return key.strip()


def request(method: str, path: str, body: dict | None = None) -> Any:
    url = f"https://api.plusvibe.ai/api/v1{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "x-api-key": api_key(),
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
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {exc.read().decode()}") from exc


def yn(value: Any) -> str | None:
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
    if not days_out:
        days_out = {"1": True, "2": True, "3": True, "4": True, "5": True}
    tz = schedule.get("tz") or schedule.get("timezone") or "America/New_York"
    from_time = schedule.get("from_time") or "10:00"
    to_time = schedule.get("to_time") or "17:00"
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


def fetch_template_campaign() -> dict:
    camps = request(
        "GET",
        f"/campaign/list-all?workspace_id={ZS_WS}&campaign_id={ZS_TEMPLATE_CAMP}",
    )
    if isinstance(camps, list):
        return camps[0] if camps else {}
    return camps if isinstance(camps, dict) else {}


def extract_settings(camp: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
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
    ):
        if key not in camp:
            continue
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

    step1_wait = 2
    for seq in camp.get("sequences") or []:
        if seq.get("step") == 1:
            step1_wait = seq.get("wait_time", 2)
            break
    out["step1_wait_time"] = step1_wait
    return out


def find_existing_campaign() -> str | None:
    camps = request("GET", f"/campaign/list-all?workspace_id={HIRE_TECH_WS}&limit=100")
    if not isinstance(camps, list):
        return None
    for c in camps:
        if (c.get("camp_name") or "") == NEW_CAMP_NAME:
            return c.get("id")
    return None


def create_campaign() -> str:
    res = request(
        "POST",
        "/campaign/add/campaign",
        {"workspace_id": HIRE_TECH_WS, "camp_name": NEW_CAMP_NAME},
    )
    cid = res.get("id")
    if not cid:
        raise SystemExit(f"create campaign failed: {res}")
    return cid


def build_patch(campaign_id: str) -> dict:
    scripts_doc = json.loads(SCRIPTS_FILE.read_text(encoding="utf-8"))
    subject = scripts_doc.get("subject") or "{{first_name}}"
    zs = extract_settings(fetch_template_campaign())
    step1_wait = zs.pop("step1_wait_time", 2)

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

    payload: dict[str, Any] = {
        "workspace_id": HIRE_TECH_WS,
        "campaign_id": campaign_id,
        "sequences": [{"step": 1, "wait_time": step1_wait, "variations": variations}],
    }
    payload.update({k: v for k, v in zs.items() if k != "schedules"})
    if "schedules" in zs:
        payload["schedules"] = zs["schedules"]
    return payload


def main() -> None:
    if not api_key():
        raise SystemExit("Set PLUSVIBE_API_KEY")

    campaign_id = find_existing_campaign() or create_campaign()
    print("campaign_id", campaign_id)

    payload = build_patch(campaign_id)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT_FILE)

    res = request("PATCH", "/campaign/update/campaign", payload)
    print("applied", json.dumps(res)[:400])


if __name__ == "__main__":
    main()
