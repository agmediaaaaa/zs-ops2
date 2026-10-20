---
name: lead-scrape-gates
description: >-
  Hard gates for Treg Cheap Scrape (Icypeas → Blitz): free TAM first, catalog
  quote + explicit --confirm-spend, Pull-N, in-query excludes, Supabase cost-skip,
  PlusVibe send-suppress, early-stop on bad unit economics. Use whenever scraping
  or enriching cold leads.
---

# Lead scrape gates (mandatory)

Full playbook: `08-treg-lead-scrape/MASTER-PROMPT.md`  
Cost matrix: `docs/waterfall-cost-matrix.md`  
Always-on rule: `.cursor/rules/lead-scrape.mdc`

Apply these gates on every list-build / scrape / email-enrichment run. Do not skip because the user is in a hurry. **GitHub repo is source of truth** — do not dig Notion / Drive / Slack / Airtable for scrape SOPs.

## 0. Read repo first

Before any MCP rabbit hole: load the playbook, this skill, the cost matrix, and the matching `scripts/` runner.

## 1. Scope first (free)

Before any paid call:

1. Build the **full** Icypeas query with title include/exclude, domain exclude (PlusVibe + Supabase), keyword exclude, headcount, geo.
2. Run `icypeas.people.search.count` (free) per campaign / ICP slice.
3. Present TAM table. If TAM collapses after excludes, report it — do **not** drop excludes to invent volume.

## 2. Catalog quote + spend confirm (hard stop)

1. Quote with `scripts/treg_pricing.py` and/or live `treg catalog get` — never invent flat “$0.003/lead”.
2. Present expected_usd, max_usd, recommended_cap_usd (≈ max × 1.4), est $/1k ready.
3. Ask: **“What hard cost cap should I use? Reply with `--confirm-spend <USD>`.”**
4. **Stop.** No paid search/email find until numeric confirm.
5. Abort if live `sum(X-Treg-Cost-Micro)` would exceed the confirmed cap.

Never treat “run the plan” / “scrape 2k” alone as spend approval for full volume. Never invent $10/$12/$14 caps.

## 3. Pilot → full

1. Pilot first (Pull-N small, e.g. `--pull 50–100`, or 10–25 ready/vertical).
2. Report quote vs actual, coverage, rows/ready, email attempts/ready, quality sample.
3. Full volume only after a **new** quote + **new** `--confirm-spend`.

## 4. Pull-N (locked)

| Means | Does NOT mean |
|-------|----------------|
| Pull N people from Icypeas | Keep searching until N ready emails |
| Enrich that fixed batch only | Page until ready target |
| Accept whatever emails validate | Guarantee N emails |

Coverage = `ready / pulled`.

## 5. Locked pathway

`icypeas.people.search.count` → `icypeas.people.search` → cost-skip → `blitzapi.people.email.find` → bulk Supabase.

Blitz headers:

```
X-Treg-Route-Max-Cost: 0.01
X-Treg-Route-Waterfall: 0
X-Treg-Route-Exclude: aiark,icypeas
```

Hard bans unless user opts in: AI Ark, Icypeas email find, ContactOut verify for volume, switching to QuickEnrich/Trykitt/Leadsforge mid-run without re-quote.

## 6. Excludes in-query (not after)

Icypeas bills per returned row. Put excludes **in** the query:

- `currentJobTitle.include` + `.exclude`
- `currentCompanyWebsite.exclude` = PlusVibe + Supabase domains (bare host)
- `keyword.exclude` (campaign-specific)
- Flat dotted keys: `currentCompany.headcount`

Pre-Blitz: skip known LinkedIn / email. Freemail after find = drop.

## 7. Supabase = cost skip · PlusVibe = send suppress

- **Supabase** (`Lead Database`, `email_cache`, `pipeline_leads`): skip paid enrich for known identities.
- **PlusVibe**: a lead is `plusvibe_ready` only if not already in the target workspace (any status). Prefer domain/LI exclude-before-search.
- Do **not** use Supabase as the PlusVibe/send suppress list.

## 8. Early-stop (bad economics)

Stop and ask if:

- search rows / ready ≫ ~12
- email attempts / ready ≫ ~4
- $/1k ready ≫ ~$5–10

Do not broaden filters into the wallet.

Healthy reference: ~3–5 rows/ready, ~1.5–2 email attempts/ready, ~$2.0–2.5 per 1k ready.

## 9. Always report

| Metric | Meaning |
|--------|---------|
| Scope / TAM | Free counts with excludes applied |
| Quote | Endpoint × volume × unit USD |
| Pulled | People from Icypeas (= N for pull-N) |
| Skipped known | Supabase / LI / domain / email skips |
| PlusVibe excluded | Already in sequencer |
| Ready | Valid email (+ company desc if required) |
| Coverage | ready / pulled |
| Path used | Must be Icypeas → Blitz (default) |
| Spend | Actual vs expected / max / cap |
| Unit econ | rows/ready, email attempts/ready, $/1k |
| Handoff | list_id + artifact paths |

## 10. Runners

Prefer repo runners with `--scope-only` / `--estimate` / `--confirm-spend` / `--pull`:

- `scripts/pilot_icypeas_blitz_four_verticals.py` — Cheap Scrape reference
- `scripts/treg_pricing.py` — catalog quote helper
- `scripts/gws_list_builder.py`, `mars_scrape_icypeas.py`, `atc_np_pa_list_builder.py` — when present on branch
