# Hire Tech — PlusVibe outbound

Tech hiring outbound using dynamic lead fields:

- `{{custom_company_type}}` — what the prospect is building
- `{{custom_talent_type}}` — role family they hire
- `{{custom_teaser}}` — candidate experience hook

**Subject line (all step-1 variants):** `{{first_name}}`

## Step 1 scripts (A–H)

Eight A/B variants on step 1. Canonical normalized copy lives in `clients/custom-talent/custom-talent-step1-scripts.json`.

| Var | Label |
|-----|-------|
| A | Version 1 - My Favorite |
| B | Version 2 |
| C | Version 3 |
| D | Version 4 |
| E | Version 5 |
| F | Version 6 - Most Consultative |
| G | Version 7 - Founder-Friendly |
| H | Version 8 - Simple |

## PlusVibe setup

1. PlusVibe workspace **Hire Tech Partners** (`6a13348c960455ee22ae829d`), campaign **Hire Tech - Custom Scripts (8 variants)** (`6a21ce2c38749bf6ddf2cd89`).
2. Deploy both workspaces: `python scripts/deploy_custom_talent_campaigns.py`
