"""Shared PlusVibe campaign helpers: API client, settings extraction, script normalization."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

DAY_NAME_TO_NUM = {
    "monday": "1",
    "tuesday": "2",
    "wednesday": "3",
    "thursday": "4",
    "friday": "5",
    "saturday": "6",
    "sunday": "7",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def api_key() -> str:
    key = os.environ.get("PLUSVIBE_API_KEY") or os.environ.get("PLUSVIBE_KEY") or ""
    return key.strip()


def plusvibe_request(method: str, path: str, body: dict | None = None) -> Any:
    if not api_key():
        raise SystemExit("Set PLUSVIBE_API_KEY or PLUSVIBE_KEY")
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
            "User-Agent": USER_AGENT,
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


def fetch_campaign(workspace_id: str, campaign_id: str) -> dict:
    camps = plusvibe_request(
        "GET",
        f"/campaign/list-all?workspace_id={workspace_id}&campaign_id={campaign_id}",
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


def paragraphs_to_plusvibe_body(paragraphs: list[str]) -> str:
    """Render paragraphs as PlusVibe HTML (div + blank line between blocks)."""
    parts: list[str] = []
    for i, para in enumerate(paragraphs):
        text = para.strip()
        if not text:
            continue
        parts.append(f"<div>{text}</div>")
        if i < len(paragraphs) - 1:
            parts.append("<div><br></div>")
    return "".join(parts)


def normalize_variation(item: dict, subject: str) -> dict:
    paragraphs = item.get("paragraphs")
    if paragraphs:
        body = paragraphs_to_plusvibe_body(paragraphs)
    else:
        raw = (item.get("body") or "").replace("\r\n", "\n")
        body = paragraphs_to_plusvibe_body([p for p in raw.split("\n") if p.strip()])
    return {
        "variation": item["variation"],
        "name": item["name"],
        "subject": subject,
        "body": body,
    }


def load_normalized_variations(scripts_path: Path) -> tuple[str, list[dict]]:
    doc = json.loads(scripts_path.read_text(encoding="utf-8"))
    subject = doc.get("subject") or "{{first_name}}"
    variations = [normalize_variation(item, subject) for item in doc["variations"]]
    return subject, variations


def find_campaign_by_name(workspace_id: str, camp_name: str) -> str | None:
    camps = plusvibe_request("GET", f"/campaign/list-all?workspace_id={workspace_id}&limit=100")
    if not isinstance(camps, list):
        return None
    for c in camps:
        if (c.get("camp_name") or "") == camp_name:
            return c.get("id")
    return None


def create_campaign(workspace_id: str, camp_name: str) -> str:
    res = plusvibe_request(
        "POST",
        "/campaign/add/campaign",
        {"workspace_id": workspace_id, "camp_name": camp_name},
    )
    cid = res.get("id")
    if not cid:
        raise SystemExit(f"create campaign failed: {res}")
    return cid


def build_patch(
    *,
    workspace_id: str,
    campaign_id: str,
    variations: list[dict],
    settings: dict[str, Any],
) -> dict[str, Any]:
    step1_wait = settings.pop("step1_wait_time", 2)
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "campaign_id": campaign_id,
        "sequences": [{"step": 1, "wait_time": step1_wait, "variations": variations}],
    }
    payload.update({k: v for k, v in settings.items() if k != "schedules"})
    if "schedules" in settings:
        payload["schedules"] = settings["schedules"]
    return payload


def deploy_campaign(
    *,
    workspace_id: str,
    campaign_name: str,
    template_workspace_id: str,
    template_campaign_id: str,
    variations: list[dict],
    patch_out: Path | None = None,
) -> str:
    campaign_id = find_campaign_by_name(workspace_id, campaign_name) or create_campaign(
        workspace_id, campaign_name
    )
    settings = extract_settings(fetch_campaign(template_workspace_id, template_campaign_id))
    payload = build_patch(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        variations=variations,
        settings=settings,
    )
    if patch_out:
        patch_out.parent.mkdir(parents=True, exist_ok=True)
        patch_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plusvibe_request("PATCH", "/campaign/update/campaign", payload)
    return campaign_id
