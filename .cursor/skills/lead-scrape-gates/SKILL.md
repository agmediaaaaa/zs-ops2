---
name: lead-scrape-gates
description: >-
  Hard gates for Treg list builds: GitHub-first context, pull-N Icypeas people
  search with in-query title/domain/keyword excludes, then Blitz email enrich
  (no Icypeas email), free-count scope first, catalog quote + ask for
  --confirm-spend before paid calls, pilot before full, early-stop bad unit
  economics, Supabase skip for known identities (cost only), Plusvibe-only
  suppress for ready, always report. Use whenever scraping or enriching cold leads.
---

# Lead scrape gates (mandatory)

Apply these gates on every list-build / scrape / email-enrichment run (Treg,
Million Verifier, Trykitt, or equivalent). Do not skip because the user is in a hurry.

User-facing master prompt (paste into new chats): `08-treg-lead-scrape/MASTER-PROMPT.md`

## -1. GitHub first, ask targeting, stay on task

1. Read this skill, `.cursor/rules/lead-scrape.mdc`, `docs/waterfall-cost-matrix.md`,
   and `08-treg-lead-scrape/MASTER-PROMPT.md`.
2. Do **not** start in Notion / Google Drive / Slack / Airtable / memory search
   for scrape SOPs or filters. Do not wander — only the scrape pipeline.
3. **Ask who to target** (client, titles, geo, headcount, industries, keywords,
   excludes, volume). Wait for answers. Do not invent ICP.
4. Use PlusVibe / Supabase only for live exclude lists and upload after the plan is clear.
5. **Do not change course mid-scrape** (provider / filters / pathway) without asking.

## 0. Pull-N model (locked for all future runs)

When the user asks for **N prospects** (e.g. “100 prospects”, `--pull 100`):

| Meaning | Not meaning |
|---------|-------------|
| Pull **N people** from `icypeas.people.search` (after title/ICP filters) | Keep searching until N **ready emails** |
| Enrich **that fixed batch** only | Page → enrich → page until ready target |
| Accept **any** valid emails from those N | Guarantee N emails |

**Pipeline stages (always, in order):**

1. **Discover** — Icypeas people search until `pulled == N` (or TAM exhausted), with
   **in-query** `currentJobTitle.include` + `.exclude`, `keyword.exclude`,
   `currentCompanyWebsite.exclude`.
2. **Cache** — Supabase LinkedIn/email/domain lookup on the whole batch (cost skip).
3. **Pre-email skip** — drop known LinkedIn / email against PlusVibe + seed **before** Blitz.
4. **Find** — concurrent email find on misses only: Blitz → QuickEnrich → Trykitt.
   - Prefer **Blitz only** when LinkedIn is present (Cheap Scrape path).
   - Exclude Icypeas from email routing (`X-Treg-Route-Exclude: aiark,icypeas`).
   - Do **not** call `icypeas.bulk.search` / Icypeas email find unless `--with-icypeas-email`.
5. **Verify** — concurrent MillionVerifier on found emails (≤50 workers; no Treg bulk MV).
   Do not burn a pilot on an untested MV call format.
6. **Upload** — bulk Supabase upsert (desc, loc, company fields) + batch `lead_list_members`.

Coverage report: `ready / pulled` (expect ready < pulled). That is correct.

```bash
# Example: 100 people pull, take whatever emails validate
python scripts/atc_np_pa_list_builder.py --pull 100 --confirm-spend 2.50
```

## 1. Scope first (free) — TAM AFTER excludes

Before any paid call:

1. Build the **full** Icypeas query including title/domain/keyword excludes the user asked for.
2. Run free people/company **counts** (`icypeas.people.search.count`, etc.) with that full query.
3. Present a TAM map with **both** (if useful) but plan only against after-excludes:
   - TAM raw (optional)
   - **TAM after ALL excludes** ← the number that matters
4. Never drop excludes to inflate TAM. Never present raw TAM as the working universe.
5. Build a **catalog quote** with endpoint IDs + unit prices (not `$0.003` averages):

```bash
python scripts/treg_pricing.py --companies 5000 --people 5000 --mode full
# or
python scripts/discover_companies.py --industry "..." --target 5000 --scope-only
python scripts/enrich_list.py <list_id> --estimate
python scripts/pilot_icypeas_blitz_four_verticals.py --scope-only
```

Quote people volume = **pull N**, not assumed ready N.

Then **ask the user** for the hard cost cap. Do not invent one.

## 2. Spend confirm (hard stop) — user owns the cap

1. Print the quote table: stage, endpoint, unit USD, volume, line USD.
2. Print **expected_usd**, **max_usd**, and optionally a *recommended range* for the user’s decision.
3. Print expected **$/1k ready** (good path ≈ $2–2.5/1k).
4. **Stop.** Ask: “What hard cost cap should I use? Reply with `--confirm-spend <USD>`.”
5. You **never** create or self-authorize a cost cap. The user always sets it.
6. Do not call paid find/verify until the user explicitly confirms with `--confirm-spend`.
7. Runner must require `--confirm-spend <usd>` matching/above expected.
8. Abort if live spend (`X-Treg-Cost-Micro` sum) would exceed the user-confirmed cap.
9. Early-stop and ask if rows/ready ≫ ~12, email attempts/ready ≫ ~4, or $/1k ≫ ~$5–10.
   Do **not** switch providers or broaden filters without asking.

Never treat “run the plan” / “scrape 2k” alone as spend approval or as a cost cap.
Never self-authorize $1 / $2 / $10 / $14 caps.

## 3. Pilot before full

1. Always run a pilot first (default: small **pull**, e.g. 25–100 people or ~10 ready × verticals).
2. Deliver the report (section 6) including **quoted vs actual** variance and `ready/pulled`.
3. Full volume only after a **new** scope + spend confirm.

## 4. Supabase = cost skip, not suppress

- Lookup domain / LinkedIn / email in Supabase (`Lead Database`, cache) **before** paid find/verify.
- Skip paid enrich for known identities; record as `already_in_db` / cache hit.
- Inject known **company domains** into `currentCompanyWebsite.exclude` before search.
- Do **not** use Supabase as the Plusvibe/send suppress list.

## 5. Plusvibe-only suppress for ready

- A lead is `plusvibe_ready` only if verified (or Blitz-found) **and** not already in the target Plusvibe workspace.
- Load PlusVibe emails / LinkedIns / domains into exclude seed **before** search and before Blitz.
- Upload found leads to Supabase; flag ready separately.

## 6. Always report

End every run (scope-only, pilot, full) with:

| Metric | Meaning |
|--------|---------|
| Scope / TAM | Free-count per campaign (with excludes) |
| Quote | Endpoint unit prices × volumes |
| **Pulled** | People from Icypeas search (= N) |
| Skipped known (Supabase) | Paid enrich avoided |
| Plusvibe excluded | Already in sequencer |
| Ready | Valid email + not in Plusvibe (+ company desc if required) |
| Coverage | ready / **pulled** |
| Unit econ | rows/ready, email attempts/ready, $/1k |
| DB / email order used | Actual tools called (default: Icypeas → Blitz) |
| Spend | Actual USD vs quoted expected/max/cap |
| Variance | actual − quoted_expected |
| Handoff | Supabase batch / list_id + Sheet URL |

## 7. Tool order (default)

**Discovery (people lists):** `icypeas.people.search` for pull-N. Prefer large pages (≤100).
Cursor-paginated — finish discovery before Stage B.

**Company discovery:** free count → cheapest per-result search with **parallel pages**
(`aiark.companies.search` page numbers, or sharded `icypeas.companies.search`).
Skip Diffbot / PDL / Enrichlayer for volume.

**Email (find-first — default, no Icypeas email):**

1. Supabase cache (≤30d) — $0
2. Blitz find (~$0.000495/success) when LinkedIn present ← **preferred default**
3. QuickEnrich find (~$0.00483/success) + MV verify
4. Trykitt find (~$0.005/success) + MV verify

**Do not use ContactOut verify** for volume (free but rate-limit bound; wall-clock killer).

**Do not use Icypeas for email** unless the user passes `--with-icypeas-email`
(then `icypeas.bulk.search` spill is allowed).

**Required Blitz / find headers:**

```
X-Treg-Route-Max-Cost: 0.01
X-Treg-Route-Waterfall: 0
X-Treg-Route-Exclude: aiark,icypeas
```

**Optional cost mode:** `--with-pattern-mv` (pattern + MillionVerifier before find).
Still never ContactOut.

## Runners

| Job | Script |
|-----|--------|
| Catalog quote | `scripts/treg_pricing.py` |
| Company discovery | `scripts/discover_companies.py` |
| List enrich | `scripts/enrich_list.py` |
| GWS list builder | `scripts/gws_list_builder.py` |
| Cheap Scrape (Icypeas→Blitz) | `scripts/pilot_icypeas_blitz_four_verticals.py` |
| Mars Icypeas | `scripts/mars_scrape_icypeas.py` |
| ATC NP/PA | `scripts/atc_np_pa_list_builder.py --pull N` |
| Cost matrix | `docs/waterfall-cost-matrix.md` |
| Master paste prompt | `08-treg-lead-scrape/MASTER-PROMPT.md` |

```bash
# Scope only (free)
python scripts/discover_companies.py --industry "Software Development" --target 5000 --scope-only
python scripts/pilot_icypeas_blitz_four_verticals.py --scope-only
python scripts/gws_list_builder.py --scope-only

# Pull-N pilot (people pulled, not ready target)
python scripts/atc_np_pa_list_builder.py --pull 100 --confirm-spend 2.50
python scripts/mars_scrape_icypeas.py --pilot --confirm-spend 1.00

# Enrich existing list
python scripts/enrich_list.py <list_id> --estimate
python scripts/enrich_list.py <list_id> --confirm-spend 4.03

# Full only after pilot report + new confirm
python scripts/gws_list_builder.py --full --confirm-spend 75
```
