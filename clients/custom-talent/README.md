# Custom talent outbound scripts

Shared step-1 scripts for Hire Tech Partners and Pro-Recruiting PlusVibe workspaces.

**Canonical copy:** `custom-talent-step1-scripts.json` (paragraphs normalized for PlusVibe HTML + spam guard).

**Merge fields:** `{{custom_company_type}}`, `{{custom_talent_type}}`, `{{custom_teaser}}`  
**Subject (all variants):** `{{first_name}}`

## Deploy

```bash
export PLUSVIBE_API_KEY='your-key-with-hyphens'
python scripts/deploy_custom_talent_campaigns.py
```

Deploy one workspace:

```bash
python scripts/deploy_custom_talent_campaigns.py "Pro-Recruiting"
python scripts/deploy_custom_talent_campaigns.py "Hire Tech Partners"
```

## Workspaces

| Workspace | Campaign | Settings template |
|-----------|----------|-------------------|
| Hire Tech Partners | Hire Tech - Custom Scripts (8 variants) | ZS `v2 SaaS(11-50)-Csuite-Google` |
| Pro-Recruiting | Custom Talent Scripts (8 variants) | Pro-Recruiting `v2 Sales` |

Configured in `workspaces.json`.
