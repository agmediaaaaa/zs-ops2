# Healthscope Services — PlusVibe

Basic placeholder campaign with ZS workspace settings and subject-only personalization.

| Field | Value |
|-------|-------|
| Workspace | Healthscope Services (`6a1334c74be1e70c4918deab`) |
| Campaign | Basic Outreach (`6a23d05c89340604384ff7fd`) |
| Subject | `{{first_name}}` |
| Body | Empty placeholder (add copy in PlusVibe) |
| Settings template | ZS `v2 SaaS(11-50)-Csuite-Google` |

## Deploy / refresh

```bash
export PLUSVIBE_API_KEY='your-key-with-hyphens'
python scripts/deploy_healthscope_basic_campaign.py
```

## Transfer NOT_CONTACTED leads

Move leads from **Basic Outreach** to the destination campaign (`6a2acf75f0d8168dbe5ee131`):

```bash
export PLUSVIBE_API_KEY='your-key-with-hyphens'
python scripts/transfer_healthscope_leads.py --limit 4000
```

Dry run (counts only, no API writes):

```bash
python scripts/transfer_healthscope_leads.py --limit 4000 --dry-run
```

Keep leads in source after copying:

```bash
python scripts/transfer_healthscope_leads.py --limit 4000 --no-delete-source
```
