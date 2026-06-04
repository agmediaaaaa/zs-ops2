"""Fetch UltraTalent PlusVibe variation stats and rank top performers."""
import json
import html
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

WORKSPACE = "694c1ae9ebef3b84192da7fc"
MIN_SENT = 20
CAMP_FILE = Path(
    r"C:\Users\Rohan\.cursor\projects\c-Users-Rohan-zs-operations-zs-ops\agent-tools\f0f2ec0a-5db7-4076-97d3-3ab3f361dd33.txt"
)
OUT_FILE = Path(__file__).resolve().parents[1] / "artifacts" / "ultratalent-top-scripts.json"


def load_api_key() -> str:
    mcp = json.loads(Path(r"C:\Users\Rohan\.cursor\mcp.json").read_text(encoding="utf-8"))
    plusvibe = mcp["mcpServers"]["plusvibe"]
    if "url" in plusvibe:
        url_mcp = plusvibe["url"]
    else:
        url_mcp = plusvibe["args"][-1]
    return urllib.parse.parse_qs(urllib.parse.urlparse(url_mcp).query)["api_key"][0]


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def main() -> None:
    key = load_api_key()
    raw = CAMP_FILE.read_text(encoding="utf-8")
    campaigns = json.loads(raw[raw.find("[") :])

    script_map: dict[str, dict] = {}
    for camp in campaigns:
        cid = camp.get("id")
        cmap: dict[tuple[int, str], dict] = {}
        for seq in camp.get("sequences") or []:
            step = seq.get("step")
            for var in seq.get("variations") or []:
                cmap[(step, var.get("variation"))] = {
                    "subject": var.get("subject") or "",
                    "name": var.get("name") or "",
                    "body": strip_html(var.get("body") or ""),
                }
        script_map[cid] = {
            "camp_name": camp.get("camp_name"),
            "lead_count": camp.get("lead_count", 0) or 0,
            "scripts": cmap,
        }

    rows: list[dict] = []
    errors = 0
    for i, camp in enumerate(campaigns):
        cid = camp.get("id")
        cname = camp.get("camp_name")
        lead_count = camp.get("lead_count") or 0
        qs = urllib.parse.urlencode(
            {"workspace_id": WORKSPACE, "campaign_id": cid, "api_key": key}
        )
        url = f"https://api.plusvibe.ai/api/v1/campaign/get/variation-stats?{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "x-api-key": key,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                steps = json.loads(resp.read().decode())
        except Exception:
            errors += 1
            continue

        for step_obj in steps or []:
            step = step_obj.get("step")
            for v in step_obj.get("variations") or []:
                sent = int(v.get("sent") or 0)
                if sent <= 0:
                    continue
                reply = int(v.get("reply") or 0)
                pos = int(v.get("pos_reply") or 0)
                var_label = v.get("variation")
                meta = script_map.get(cid, {}).get("scripts", {}).get((step, var_label), {})
                # Step 1 sent ≈ unique leads contacted on that variant; fall back when campaign lead_count is 0.
                leads_contacted = sent if step == 1 else lead_count
                if leads_contacted <= 0:
                    leads_contacted = lead_count or sent
                camp_leads = lead_count if lead_count > 0 else leads_contacted
                email_to_lead = (
                    round(sent / camp_leads, 2) if camp_leads > 0 else None
                )
                rows.append(
                    {
                        "campaign": cname,
                        "campaign_id": cid,
                        "step": step,
                        "variation": var_label,
                        "var_name": (
                            v.get("name")
                            if v.get("name") not in (None, "-", "")
                            else meta.get("name") or ""
                        ),
                        "emails_sent": sent,
                        "leads": leads_contacted,
                        "campaign_leads": lead_count,
                        "email_to_lead_ratio": email_to_lead,
                        "replies": reply,
                        "positive_replies": pos,
                        "reply_rate_pct": round(100 * reply / sent, 2),
                        "positive_reply_rate_pct": round(100 * pos / sent, 2),
                        "subject": meta.get("subject", ""),
                        "body": meta.get("body", ""),
                    }
                )
        if (i + 1) % 10 == 0:
            time.sleep(0.15)

    eligible = [r for r in rows if r["emails_sent"] >= MIN_SENT]
    by_positive = sorted(
        eligible,
        key=lambda r: (
            r["positive_replies"],
            r["positive_reply_rate_pct"],
            r["reply_rate_pct"],
            r["emails_sent"],
        ),
        reverse=True,
    )
    step1 = [r for r in eligible if r["step"] == 1 and r["emails_sent"] >= 50]
    by_pos_rate = sorted(
        step1,
        key=lambda r: (
            r["positive_reply_rate_pct"],
            r["positive_replies"],
            r["emails_sent"],
        ),
        reverse=True,
    )
    top = by_positive[:15]

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(
            {
                "workspace": "UltraTalent",
                "workspace_id": WORKSPACE,
                "min_sent_threshold": MIN_SENT,
                "total_variants_with_sends": len(rows),
                "eligible_variants": len(eligible),
                "fetch_errors": errors,
                "top15_by_positive_replies": top,
                "top15_step1_by_positive_reply_rate_min50_sent": by_pos_rate[:15],
                "all_eligible_ranked": by_positive,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"variants={len(rows)} eligible={len(eligible)} errors={errors}")
    for i, r in enumerate(top, 1):
        label = r["var_name"] or f"Step {r['step']} Var {r['variation']}"
        print(
            f"{i}. {r['campaign']} - {label} - sent={r['emails_sent']} "
            f"leads={r['leads']} e2l={r['email_to_lead_ratio']} "
            f"reply%={r['reply_rate_pct']} pos%={r['positive_reply_rate_pct']} pos={r['positive_replies']}"
        )


if __name__ == "__main__":
    main()
