---
name: lead-scrape-gates
description: >-
  Hard gates for Treg list builds: pull-N Icypeas people search, then staged
  email enrich (no Icypeas email), free-count scope first, catalog quote +
  explicit confirm before paid calls, pilot before full, Supabase skip for known
  identities (cost only), Plusvibe-only suppress for ready, always report.
  Use whenever scraping or enriching cold leads.
---

# Lead scrape gates (mandatory)

Apply these gates on every list-build / scrape / email-enrichment run (Treg,
Million Verifier, Trykitt, or equivalent). Do not skip because the user is in a hurry.

## 0. Pull-N model (locked for all future runs)

When the user asks for **N prospects** (e.g. “100 prospects”, `--pull 100`):

| Meaning | Not meaning |
|---------|-------------|
| Pull **N people** from `icypeas.people.search` (after title/ICP filters) | Keep searching until N **ready emails** |
| Enrich **that fixed batch** only | Page → enrich → page until ready target |
| Accept **any** valid emails from those N | Guarantee N emails |

**Pipeline stages (always, in order):**

1. **Discover** — Icypeas people search until `pulled == N` (or TAM exhausted).
2. **Cache** — Supabase LinkedIn/email/domain lookup on the whole batch (cost skip).
3. **Find** — concurrent email find on misses only: Blitz → QuickEnrich → Trykitt.
   - Exclude Icypeas from email routing (`X-Treg-Route-Exclude: aiark,icypeas`).
   - Do **not** call `icypeas.bulk.search` / Icypeas email find unless `--with-icypeas-email`.
4. **Verify** — concurrent MillionVerifier on found emails (≤50 workers; no Treg bulk MV).
5. **Upload** — bulk Supabase upsert (desc, loc, company fields) + batch `lead_list_members`.

Coverage report: `ready / pulled` (expect ready < pulled). That is correct.

```bash
# Example: 100 people pull, take whatever emails validate
python scripts/atc_np_pa_list_builder.py --pull 100 --confirm-spend 2.50
```

## 1. Scope first (free)

Before any paid call:

1. Run free people/company **counts** (e.g. `icypeas.companies.search.count`,
   `icypeas.people.search.count`, `leadsforge.people.search.count`).
2. Present a TAM table: campaign, filters, estimated available rows.
3. Build a **catalog quote** with endpoint IDs + unit prices (not `$0.003` averages):

```bash
python scripts/treg_pricing.py --companies 5000 --people 5000 --mode full
# or
python scripts/discover_companies.py --industry "..." --target 5000 --scope-only
python scripts/enrich_list.py <list_id> --estimate
```

Quote people volume = **pull N**, not assumed ready N.

## 2. Spend confirm (hard stop)

1. Print the quote table: stage, endpoint, unit USD, volume, line USD.
2. Print **expected_usd**, **max_usd**, and **recommended_cap_usd** (max × 1.4).
3. **Stop.** Do not call paid find/verify until the user explicitly confirms.
4. Runner must require `--confirm-spend <usd>` matching/above expected.
5. Abort if live spend (`X-Treg-Cost-Micro` sum) would exceed the confirmed cap.

Never treat “run the plan” alone as spend approval for a **full** volume run.

## 3. Pilot before full

1. Always run a pilot first (default: small **pull**, e.g. 25–100 people).
2. Deliver the report (section 6) including **quoted vs actual** variance and `ready/pulled`.
3. Full volume only after a **new** scope + spend confirm.

## 4. Supabase = cost skip, not suppress

- Lookup domain / LinkedIn / email in Supabase (`Lead Database`, cache) **before** paid find/verify.
- Skip paid enrich for known identities; record as `already_in_db` / cache hit.
- Do **not** use Supabase as the Plusvibe/send suppress list.

## 5. Plusvibe-only suppress for ready

- A lead is `plusvibe_ready` only if verified (or Blitz-found) **and** not already in the target Plusvibe workspace.
- Upload found leads to Supabase; flag ready separately.

## 6. Always report

End every run (scope-only, pilot, full) with:

| Metric | Meaning |
|--------|---------|
| Scope / TAM | Free-count per campaign |
| Quote | Endpoint unit prices × volumes |
| **Pulled** | People from Icypeas search (= N) |
| Skipped known (Supabase) | Paid enrich avoided |
| Plusvibe excluded | Already in sequencer |
| Ready | Valid email + not in Plusvibe |
| Coverage | ready / **pulled** |
| DB / email order used | Actual tools called (no Icypeas email by default) |
| Spend | Actual USD vs quoted expected/max/cap |
| Variance | actual − quoted_expected |
| Handoff | Supabase batch / list_id + Sheet URL |

## 7. Tool order (default)

**Discovery (people lists):** `icypeas.people.search` for pull-N. Prefer large pages (≤100). Cursor-paginated — finish discovery before Stage B.

**Company discovery:** free count → cheapest per-result search with **parallel pages**
(`aiark.companies.search` page numbers, or sharded `icypeas.companies.search`).
Skip Diffbot / PDL / Enrichlayer for volume.

**Email (find-first — default, no Icypeas email):**

1. Supabase cache (≤30d) — $0
2. Blitz find (~$0.000495/success) when LinkedIn present
3. QuickEnrich find (~$0.00483/success) + MV verify
4. Trykitt find (~$0.005/success) + MV verify

**Do not use ContactOut verify** for volume (free but 429-bound; wall-clock killer).

**Do not use Icypeas for email** unless the user passes `--with-icypeas-email`
(then `icypeas.bulk.search` spill is allowed).

**Optional cost mode:** `--with-pattern-mv` (pattern + MillionVerifier before find).
Still never ContactOut.

## Runners

| Job | Script |
|-----|--------|
| Catalog quote | `scripts/treg_pricing.py` |
| Company discovery | `scripts/discover_companies.py` |
| List enrich | `scripts/enrich_list.py` |
| GWS list builder | `scripts/gws_list_builder.py` |
| ATC NP/PA | `scripts/atc_np_pa_list_builder.py --pull N` |
| Cost matrix | `docs/waterfall-cost-matrix.md` |

```bash
# Scope only (free)
python scripts/discover_companies.py --industry "Software Development" --target 5000 --scope-only
python scripts/gws_list_builder.py --scope-only

# Pull-N pilot (people pulled, not ready target)
python scripts/atc_np_pa_list_builder.py --pull 100 --confirm-spend 2.50

# Enrich existing list
python scripts/enrich_list.py <list_id> --estimate
python scripts/enrich_list.py <list_id> --confirm-spend 4.03

# Full only after pilot report + new confirm
python scripts/gws_list_builder.py --full --confirm-spend 75
```
