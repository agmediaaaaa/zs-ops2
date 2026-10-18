# Waterfall cost matrix (Treg)

Catalog rates as of last refresh via `scripts/treg_pricing.py --refresh`.
Re-quote before every paid run — prices move.

## Billing units

| Type | Meaning |
|------|---------|
| `free` | $0 always (counts, some BYOK searches) |
| `per_result` | Charged per returned row |
| `per_success` | Charged on hit; **miss = $0** |
| `per_call` | Charged every attempt regardless of hit |

## Stage A — Discovery

| Endpoint | Unit | USD | Shape |
|----------|------|-----|-------|
| `icypeas.companies.search.count` | call | $0 | free TAM |
| `icypeas.people.search.count` | call | $0 | free TAM |
| `icypeas.companies.search` | result | ~$0.00038 | prefer large pages; shard for parallel |
| `icypeas.people.search` | result | ~$0.00038 | same |
| `aiark.companies.search` | found | ~$0.000527 | **parallel page numbers** (default discover) |
| `leadsforge.people.search` | call | $0 (BYOK) | list builder default |
| Diffbot / PDL / Enrichlayer | result | $0.03–$0.38 | **never for volume** |

Example: 5,000 companies via Icypeas ≈ `5000 × $0.00038 = $1.90` (+ $0 count).

## Pull-N semantics

**N prospects = N Icypeas people-search rows**, then enrich that batch.
Ready emails ≤ N. Do not keep paging until N ready.

Stages: discover N → Supabase cache → find (no Icypeas email) → MV → bulk Supabase.

## Stage B — Email (default find-first)

ContactOut verify is **excluded** (free but rate-limit bound).
**Icypeas email find / `icypeas.bulk.search` is excluded by default** (opt-in `--with-icypeas-email`).

| Step | Endpoint | Unit | USD | Notes |
|------|----------|------|-----|-------|
| Cache | Supabase ≤30d | — | $0 | cost skip |
| Find 1 | `blitzapi.people.email.find` | success | ~$0.000495 | needs LinkedIn |
| Find 2 | `quickenrich.people.email.find` | success | ~$0.00483 | then MV |
| Find 3 | `trykitt.people.email.find` | success | ~$0.005 | then MV |
| Verify found | `millionverifier.people.email.verify` | success | ~$0.00178 | concurrent ≤50; no true bulk via Treg |
| Opt-in spill | `icypeas.bulk.search` | result | ~$0.019 | **only** with `--with-icypeas-email` |
| Alt bulk | `leadsforge.people.email.find.bulk` | success | ~$0.0245 | alternative spill |

### Optional `--with-pattern-mv`

| Step | Endpoint | Unit | USD |
|------|----------|------|-----|
| Pattern | local `first.last@domain` | — | $0 |
| Verify pattern | `millionverifier.people.email.verify` | success | ~$0.00178 |

Still never ContactOut.

## Quote vs actual

Every paid runner must:

1. Print a line-item quote from `treg_pricing.quote_run`.
2. Require `--confirm-spend`.
3. Sum live `X-Treg-Cost-Micro` into `run_report.cost_by_provider`.
4. Record `quoted_usd`, `quoted_max_usd`, `quote_variance_usd`.

```bash
python scripts/treg_pricing.py --pending-leads 500 --mode enrich
python scripts/treg_pricing.py --companies 5000 --people 5000 --mode full --refresh
```

## Throughput notes

- Discovery: parallel pages / shards — minutes for multi-k, not hours.
- Enrich: concurrent find (≤32), not pattern+ContactOut.
- True bulk only where catalog exposes async jobs (Icypeas bulk, LeadsForge bulk).
