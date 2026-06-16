# Healthscope Services — PlusVibe

| Field | Value |
|-------|-------|
| Workspace | Healthscope Services (`6a1334c74be1e70c4918deab`) |
| Campaign | v3 Outcome Outreach (`6a3128c4bfcb0d66add3f8fd`) |
| Settings copied from | v2 Basic Outreach (`6a2acf75f0d8168dbe5ee131`) |
| Scripts | `healthscope-step1-scripts-reframed.json` (6 variants A–F) |

## Deploy / refresh

```bash
export PLUSVIBE_API_KEY='your-key'
python scripts/deploy_healthscope_outcome_campaign.py
```

Creates or updates **v3 Outcome Outreach** with the same sending settings and mailboxes as v2 Basic Outreach, plus the outcome-led step-1 scripts.
