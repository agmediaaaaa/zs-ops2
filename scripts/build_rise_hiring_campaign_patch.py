"""Build PlusVibe patch for Rise Hiring Sales - SaaS (11-50) campaign."""
import json
import re
from pathlib import Path

WORKSPACE_ID = "69fe1815f40c0fa0e5494e8a"
CAMPAIGN_ID = "6a169e8633ec34ed7b19f3e9"
CAMP_FILE = Path(
    r"C:\Users\Rohan\.cursor\projects\c-Users-Rohan-zs-operations-zs-ops\agent-tools\f0f2ec0a-5db7-4076-97d3-3ab3f361dd33.txt"
)

# Selected top-15 entries: (source campaign name, step, variation, display name)
VARIANTS = [
    ("Csuite (11-50) - Google", 1, "H", "Csuite first-sales profiles"),
    ("v2 Sales - CAT", 1, "F", "Presidents Club network"),
    ("UT - Csuite - Google", 1, "F", "AE quota-proven"),
    ("v2 Sales", 1, "A", "Quiet wave of AEs"),
    ("UT- Gen (51-100) - Google", 2, "C", "Painful sales hire pattern"),
    ("Sales (50-200) - Google - CAT", 2, "D", "First sales hires drag"),
    ("UT- New leaders - Google", 1, "A", "New leader congrats"),
    ("Sales (50-200) - Google - CAT", 1, "E", "Short bench"),
    ("UT- Gen (Sales) - Google - II", 1, "A", "Sales coverage headcount"),
    ("v2 C suite - CAT", 1, "M", "Pipeline priority quarter"),
]

LABELS = "ABCDEFGHIJ"


def load_campaigns():
    raw = CAMP_FILE.read_text(encoding="utf-8")
    return json.loads(raw[raw.find("[") :])


def find_variation(campaigns, camp_name, step, variation):
    for camp in campaigns:
        if camp.get("camp_name") != camp_name:
            continue
        for seq in camp.get("sequences") or []:
            if seq.get("step") != step:
                continue
            for var in seq.get("variations") or []:
                if var.get("variation") == variation:
                    return var
    raise KeyError(f"Not found: {camp_name} step {step} var {variation}")


def main():
    campaigns = load_campaigns()
    variations = []
    for label, (cname, step, var, name) in zip(LABELS, VARIANTS):
        src = find_variation(campaigns, cname, step, var)
        subject = src.get("subject") or ""
        if subject.strip().lower().startswith("(empty"):
            subject = ""
        body = src.get("body") or ""
        # Rebrand UltraTalent -> Rise Hiring where present in copy
        body = body.replace("UltraTalent", "Rise Hiring").replace("Ultra Talent", "Rise Hiring")
        variations.append(
            {
                "variation": label,
                "name": name,
                "subject": subject,
                "body": body,
            }
        )

    payload = {
        "workspace_id": WORKSPACE_ID,
        "campaign_id": CAMPAIGN_ID,
        "first_wait_time": 0,
        "opportunity_val": 10000,
        "is_pause_on_bouncerate": "yes",
        "bounce_rate_limit": 2.5,
        "send_as_txt": "yes",
        "stop_on_lead_replied": "yes",
        "sequences": [
            {
                "step": 1,
                "wait_time": 2,
                "variations": variations,
            }
        ],
    }
    out = Path(__file__).resolve().parents[1] / "artifacts" / "rise-hiring-sales-saas-patch.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    print("variations", len(variations))


if __name__ == "__main__":
    main()
