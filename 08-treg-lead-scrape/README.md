# Treg lead scrape playbook

This folder holds the **paste-ready master prompt** for any new chat that scrapes leads via Treg.

| File | Use |
|------|-----|
| [MASTER-PROMPT.md](./MASTER-PROMPT.md) | Copy the fenced block into a new agent chat |
| [../.cursor/rules/lead-scrape.mdc](../.cursor/rules/lead-scrape.mdc) | Always-on rule so agents load GitHub first |
| [../.cursor/skills/lead-scrape-gates/SKILL.md](../.cursor/skills/lead-scrape-gates/SKILL.md) | Hard gates (free TAM → quote → ask cap → pilot → full) |
| [../docs/waterfall-cost-matrix.md](../docs/waterfall-cost-matrix.md) | Catalog rates |

**Default path:** Icypeas people search (title / domain / keyword excludes **in-query**) → skip known person LinkedIns → Blitz → bulk Supabase upload.

**Exclude reality check:** domains/titles/keywords go in the Icypeas query before any paid rows. Person LinkedIn URLs cannot be excluded in Icypeas (schema rejects `profileUrl`) — skip those only before Blitz. See `docs/icypeas-exclude-capabilities.md`.

**Agent must:** ask who to target → stay on this pipeline (no mid-run course changes) → show TAM **after** in-query excludes → ask you for `--confirm-spend` (never invent a cost cap).

**Benchmark:** ~$2–2.5 per 1,000 ready when filters are tight (Cheap Scrape / ATC facility). If you see $35–50/1k, stop — excludes or gates are wrong.
