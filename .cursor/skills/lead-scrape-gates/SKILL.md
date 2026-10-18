---
name: lead-scrape-gates
description: >-
  Hard gates for Treg list builds: free-count scope first, catalog-priced spend
  quote + explicit confirm before paid calls, pilot before full, Supabase skip
  for known identities (cost only), Plusvibe-only suppress for ready, always
  report. Default email path is find-first (no ContactOut). Use whenever
  scraping or enriching cold leads.
---

# Lead scrape gates (mandatory)

Apply these gates on every list-build / scrape / email-enrichment run (Treg,
Million Verifier, Trykitt, or equivalent). Do not skip because the user is in a hurry.

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

## 2. Spend confirm (hard stop)

1. Print the quote table: stage, endpoint, unit USD, volume, line USD.
2. Print **expected_usd**, **max_usd**, and **recommended_cap_usd** (max × 1.4).
3. **Stop.** Do not call paid find/verify until the user explicitly confirms.
4. Runner must require `--confirm-spend <usd>` matching/above expected.
5. Abort if live spend (`X-Treg-Cost-Micro` sum) would exceed the confirmed cap.

Never treat “run the plan” alone as spend approval for a **full** volume run.

## 3. Pilot before full

1. Always run a pilot first (default: small ready target, e.g. 500 or 10×N campaigns).
2. Deliver the report (section 6) including **quoted vs actual** variance.
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
| Searched | People/companies pulled |
| Skipped known (Supabase) | Paid enrich avoided |
| Plusvibe excluded | Already in sequencer |
| Ready | Verified + not in Plusvibe |
| Coverage | ready / searched |
| DB / email order used | Actual tools called |
| Spend | Actual USD vs quoted expected/max/cap |
| Variance | actual − quoted_expected |
| Handoff | Supabase batch / list_id + Sheet URL |

## 7. Tool order (default)

**Discovery:** free count → cheapest per-result search with **parallel pages**
(`aiark.companies.search` page numbers, or sharded `icypeas.companies.search`).
Skip Diffbot / PDL / Enrichlayer for volume.

**Email (find-first — default):**

1. Supabase cache (≤30d) — $0
2. Blitz find (~$0.000495/success) when LinkedIn present
3. QuickEnrich find (~$0.00483/success) + MV verify
4. Trykitt find (~$0.005/success) + MV verify
5. Bulk spill (≥100 misses): `icypeas.bulk.search` (~$0.019/result)

**Do not use ContactOut verify** for volume (free but 429-bound; wall-clock killer).

**Optional cost mode:** `--with-pattern-mv` (pattern + MillionVerifier before find).
Still never ContactOut.

People extract (list builder): `leadsforge` → `icypeas` (if thin). Skip AI Ark by default for people extract.

## Runners

| Job | Script |
|-----|--------|
| Catalog quote | `scripts/treg_pricing.py` |
| Company discovery | `scripts/discover_companies.py` |
| List enrich | `scripts/enrich_list.py` |
| GWS list builder | `scripts/gws_list_builder.py` |
| Cost matrix | `docs/waterfall-cost-matrix.md` |

```bash
# Scope only (free)
python scripts/discover_companies.py --industry "Software Development" --target 5000 --scope-only
python scripts/gws_list_builder.py --scope-only

# Pilot after user confirms spend
python scripts/enrich_list.py <list_id> --estimate
python scripts/enrich_list.py <list_id> --confirm-spend 4.03

# Full only after pilot report + new confirm
python scripts/gws_list_builder.py --full --confirm-spend 75
```
