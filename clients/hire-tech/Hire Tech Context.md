# Hire Tech — PlusVibe outbound

Tech hiring outbound using dynamic lead fields:

- `{{custom_company_type}}` — what the prospect is building
- `{{custom_talent_type}}` — role family they hire
- `{{custom_teaser}}` — candidate experience hook

**Subject line (all step-1 variants):** `{{first_name}}`

## Step 1 scripts (A–H)

Eight A/B variants on step 1. Campaign-level settings are copied from ZS (UltraTalent) workspace campaigns via `scripts/build_hire_tech_campaign_patch.py`.

| Var | Label |
|-----|-------|
| A | Version 1 — My Favorite |
| B | Version 2 |
| C | Version 3 |
| D | Version 4 |
| E | Version 5 |
| F | Version 6 — Most Consultative |
| G | Version 7 — Founder-Friendly |
| H | Version 8 — Simple |

See `hire-tech-step1-scripts.json` for full copy.

## PlusVibe setup

1. Set `workspace_id` and `campaign_id` in `plusvibe.config.json` (Hire Tech workspace + target campaign).
2. Optional: point `CAMP_FILE` at the ZS campaign export (`f0f2ec0a-…txt`) to pull live settings from a template campaign.
3. Run `python scripts/build_hire_tech_campaign_patch.py` → writes `clients/hire-tech/hire-tech-campaign-patch.json`.
4. Apply with `PLUSVIBE_API_KEY` set: `python scripts/apply_plusvibe_campaign_patch.py clients/hire-tech/hire-tech-campaign-patch.json`
