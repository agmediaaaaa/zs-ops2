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

## Exclude file (optional but recommended)

Create a JSON file of people/companies you already have:

```json
{
  "emails": ["jane@acme.com"],
  "linkedins": ["https://www.linkedin.com/in/jane"],
  "domains": ["acme.com", "othercustomer.com"]
}
```

- **Domains** go into the Icypeas query **before** any paid search (so you don’t pay for them).
- **LinkedIn URLs** cannot be excluded inside Icypeas — the script skips them **before Blitz** (free).

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
