# Treg lead scrape playbook

This folder holds the **paste-ready master prompt** and the **safe terminal wizard** for Treg scrapes.

| File | Use |
|------|-----|
| [HOW-TO-RUN-SAFE.md](./HOW-TO-RUN-SAFE.md) | **Start here if you are non-technical** — terminal wizard |
| [MASTER-PROMPT.md](./MASTER-PROMPT.md) | Paste into a new agent chat (planning only; spend via wizard) |
| [../scripts/scrape_wizard.py](../scripts/scrape_wizard.py) | Interactive Q&A — won’t spend until you type a dollar cap |
| [../scripts/treg_icypeas_blitz.py](../scripts/treg_icypeas_blitz.py) | Locked Icypeas→Blitz runner (`--confirm-spend` required) |
| [../.cursor/rules/lead-scrape.mdc](../.cursor/rules/lead-scrape.mdc) | Always-on rule so agents load GitHub first |
| [../.cursor/skills/lead-scrape-gates/SKILL.md](../.cursor/skills/lead-scrape-gates/SKILL.md) | Hard gates (free TAM → quote → ask cap → pilot → full) |
| [../docs/waterfall-cost-matrix.md](../docs/waterfall-cost-matrix.md) | Catalog rates |

**Default path:** Icypeas people search (title / domain / keyword excludes **in-query**) → skip known person LinkedIns → Blitz → bulk Supabase upload.

**Exclude reality check:** domains/titles/keywords go in the Icypeas query before any paid rows. Person LinkedIn URLs cannot be excluded in Icypeas (schema rejects `profileUrl`) — skip those only before Blitz. See `docs/icypeas-exclude-capabilities.md`.

**Prefer the wizard for spend:** `python3 scripts/scrape_wizard.py` (see HOW-TO-RUN-SAFE.md).

**If using chat:** ask who to target → ask **ready-target vs pull-N** → stay on this pipeline → show TAM **after** in-query excludes → ask for `--confirm-spend` (never invent a cost cap).

**Volume modes:** “2000 ready leads” = keep going until 2000 have email + fields. “Scrape 2000 Icypeas leads” = pull 2000 people from Icypeas, Blitz that batch only.

**Benchmark:** ~$2–2.5 per 1,000 ready when filters are tight (Cheap Scrape / ATC facility). If you see $35–50/1k, stop — excludes or gates are wrong.
