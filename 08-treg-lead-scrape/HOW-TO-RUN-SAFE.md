# How to scrape leads safely (no chat hallucinations)

You do **not** need to be technical. Use the **wizard** in the terminal.
It asks questions in plain English and **will not spend money** until you type a dollar cap.

Chat agents can invent steps. This script cannot change path mid-run.

## One-time: open the terminal

In Cursor: **Terminal → New Terminal** (or the bottom panel).

You should see a line you can type into.

## Run the wizard

Copy this, paste it, press Enter:

```bash
python3 scripts/scrape_wizard.py
```

Then answer the questions:

1. Who to target (titles, location, company size)
2. What to exclude (junk titles; optional exclude file with domains)
3. **Ready leads** vs **Icypeas pull**
4. Pilot size (start small)
5. It shows **free TAM** (after domain excludes) — no spend
6. It shows a **cost estimate** — no spend
7. It asks **your** cost cap — type something like `2.50`, then type `confirm 2.50`

Only after step 7 does it call paid Icypeas → Blitz.

## What you get

Files land in `/workspace/artifacts/scrape-wizard/`:

| File | What it is |
|------|------------|
| `latest-ready.csv` | Leads with emails |
| `latest-report.json` | Spend, ready count, $/1k |
| `last-run-config.json` | Your answers (reusable) |

## Ready vs Icypeas pull (reminder)

| You want | Choose in wizard |
|----------|------------------|
| “2000 ready leads” (email + details) | Option **1 — READY** |
| “Scrape 2000 Icypeas people, take whatever emails hit” | Option **2 — ICYPEAS pull** |

## Domain excludes (wizard asks you)

The wizard asks you to pick **one**:

| Choice | What it skips |
|--------|----------------|
| **0** | No DB excludes |
| **1** | Past **15 days** leads in Supabase (Lead Database + pipeline_leads) |
| **2** | Past **7 days** leads in Supabase |
| **3** | Existing leads already in **PlusVibe campaigns** |

What happens:

- **Company domains** → injected into Icypeas `currentCompanyWebsite.exclude` **before** any paid search
- **Person LinkedIn URLs** → cannot go in the Icypeas query (API rejects them) → skipped **before Blitz** (free)
- Seed file written to `/workspace/artifacts/scrape-wizard/exclude-seed.json`

Manual build (optional):

```bash
python3 scripts/build_exclude_seed.py --source supabase_15d --out /workspace/artifacts/scrape-wizard/exclude-seed.json
python3 scripts/build_exclude_seed.py --source supabase_7d --out /workspace/artifacts/scrape-wizard/exclude-seed.json
python3 scripts/build_exclude_seed.py --source plusvibe --out /workspace/artifacts/scrape-wizard/exclude-seed.json --list-campaigns
python3 scripts/build_exclude_seed.py --source plusvibe --out /workspace/artifacts/scrape-wizard/exclude-seed.json
```

## If something looks wrong

- Stop (Ctrl+C). No further spend after cancel.
- Re-run the wizard. It never invents a cost cap.
- Do **not** ask a chat agent to “just finish the scrape” without `--confirm-spend`.

## Advanced (optional)

Same gates, without the Q&A:

```bash
# Free TAM
python3 scripts/treg_icypeas_blitz.py --scope-only --config /workspace/artifacts/scrape-wizard/last-run-config.json

# Quote only
python3 scripts/treg_icypeas_blitz.py --quote-only --pull 100 --config /workspace/artifacts/scrape-wizard/last-run-config.json

# Paid pull-N
python3 scripts/treg_icypeas_blitz.py --pull 100 --confirm-spend 1.50 --config /workspace/artifacts/scrape-wizard/last-run-config.json
```
