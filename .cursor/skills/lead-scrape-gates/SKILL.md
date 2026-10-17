---
name: lead-scrape-gates
description: >-
  Hard gates for Treg/MV/Trykitt list builds: free-count scope first, spend
  estimate + explicit confirm before paid calls, pilot before full, Supabase
  skip for known identities (cost only), Plusvibe-only suppress for ready,
  always report. Use whenever scraping or enriching cold leads.
---

# Lead scrape gates (mandatory)

Apply these gates on every list-build / scrape / email-enrichment run (Treg, Million Verifier, Trykitt, or equivalent). Do not skip because the user is in a hurry.

## 1. Scope first (free)

Before any paid call:

1. Run free people-search **counts** per campaign / ICP slice (e.g. `leadsforge.people.search.count`).
2. Present a TAM table: campaign, filters, estimated available people, headcount band.
3. Estimate paid spend for the intended run (pilot or full): search $ + email find $ + verify $.

## 2. Spend confirm (hard stop)

1. Print **estimated spend USD** and a **hard cap**.
2. **Stop.** Do not call paid email find/verify until the user explicitly confirms the amount.
3. Runner must require an explicit flag, e.g. `--confirm-spend 2.50` matching the approved cap.
4. Abort if live spend would exceed the confirmed cap.

Never treat “run the plan” alone as spend approval for a **full** volume run. Pilot may proceed only after a numeric confirm for that pilot’s cap.

## 3. Pilot before full

1. Always run a pilot first (default: small ready target per campaign, e.g. 10×N).
2. Deliver the report (section 6).
3. Full volume only after a **new** scope + spend confirm.

## 4. Supabase = cost skip, not suppress

- Lookup domain / LinkedIn / email in Supabase (`Lead Database`, `email_cache`, `pipeline_leads`) **before** paid email find/verify.
- Skip paid enrich for known identities; still record them in the run report as `already_in_db`.
- Do **not** use Supabase as the Plusvibe/send suppress list.

## 5. Plusvibe-only suppress for ready

- A lead is `plusvibe_ready` only if MV-valid (or equivalent) **and** not already present in the target Plusvibe workspace (any status / unsub / reply).
- Upload **all** found leads to Supabase staging (`pipeline_leads`) with `campaign_id`; flag ready separately.

## 6. Always report

End every run (scope-only, pilot, full) with:

| Metric | Meaning |
|--------|---------|
| Scope / TAM | Free-count per campaign |
| Searched | People pulled |
| Skipped known (Supabase) | Paid enrich avoided |
| Plusvibe excluded | Already in sequencer |
| Ready | MV-valid + not in Plusvibe |
| Coverage | ready / searched |
| DB / email order used | Actual tools called |
| Spend | USD spent vs confirmed cap |
| Handoff | Supabase `batch_id` + Google Sheet URL |

## 7. Tool order (default)

People extract: `leadsforge` → `icypeas` (if thin) → `dropleads` / `quickenrich` discovery. Skip AI Ark by default.

Email: extract → MV/Trykitt verify; if missing → cheap find (`quickenrich` / `trykitt.people.email.find`) with `X-Treg-Route-Exclude: aiark`, max-cost ≈ `$0.006`, waterfall off.

## Runner

Canonical script: `scripts/gws_list_builder.py`

```bash
# Scope only (free)
python scripts/gws_list_builder.py --scope-only

# Pilot after user confirms spend
python scripts/gws_list_builder.py --pilot --confirm-spend 2.50

# Full only after pilot report + new confirm
python scripts/gws_list_builder.py --full --confirm-spend 75
```
