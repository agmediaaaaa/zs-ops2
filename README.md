# ZS Ops2 - Lead Enrichment Pipeline

A scalable, cost-controlled lead enrichment pipeline with list-based handoff workflow.

## Overview

The pipeline enriches B2B leads through a multi-stage email discovery ladder using **bulk/batch operations** for maximum throughput and cost efficiency.

### Enrichment Pipeline

1. **Batch Supabase cache lookup**: Check all leads for cached emails (≤30 days fresh, older re-verified)
2. **Bulk pattern generation**: Generate pattern emails (first.last@domain) for all cache misses
3. **Bulk verification**: 
   - **Standard mode**: Concurrent MillionVerifier batch (up to 50 at once)
   - **Cheap mode**: Concurrent ContactOut batch (free, up to 30 at once)
4. **Concurrent find** (for pattern misses):
   - **Blitz** (cheapest, requires LinkedIn)
   - **QuickEnrich** (standard mode)
   - **Trykitt** (last resort)
5. **Supabase upsert**: Every found email is saved with full metadata
6. **Per-provider cost tracking**: Detailed breakdown saved to list run report

### Performance Features

- **Bulk operations**: Verify 50+ emails simultaneously instead of one-by-one
- **Concurrent finds**: Run 32+ find operations in parallel with rate-limit backoff
- **Smart batching**: Process leads in 100-lead batches to optimize memory and API usage
- **Rate limit handling**: Automatic retry with exponential backoff on 429 errors
- **Cost efficiency**: Reuse cached emails, bulk verify patterns before expensive finds

All leads are stored in the main `pipeline_leads` table (the "ZS: Lead Database" in Supabase). List membership is tracked via a join table, so one lead can belong to multiple lists without duplication.

## Database Schema

### Core Tables

- **`pipeline_leads`**: Main leads table (hundreds of thousands of rows)
  - Contains: email, LinkedIn URL, name, title, company, location, size, etc.
  - Has `list_ids UUID[]` array for quick list membership checks
  
- **`lead_lists`**: Tracks scrape/import batches
  - Fields: `list_id`, `client`, `list_name`, `source`, `status`, counts, costs
  - Status: `scraped` → `enriching` → `enriched` → `exported` → `failed`
  
- **`lead_list_members`**: Many-to-many join table
  - Links leads to lists with per-lead enrichment status
  - Fields: `list_id`, `lead_id`, `enrichment_status`, `cost_micro`
  - Enables resumable enrichment (skip already-enriched leads)

### Deduplication Strategy

Leads are deduplicated on:
1. **LinkedIn URL** (normalized: lowercase, no trailing slash, no query params)
2. **Email** (lowercase)
3. **Pattern emails** (first.last@domain fallback)

A lead can appear in multiple clients' lists, but the system flags this for review.

## Lead List Workflow

### 1. Create a List

From LinkedIn URLs:
```bash
./scripts/lead_lists.py create \
  --client "MARS" \
  --name "Midwest CNC Shops Oct 2026" \
  --source "icypeas" \
  --linkedin-urls urls.txt \
  --cost-cap 50.00
```

From CSV:
```bash
./scripts/lead_lists.py create \
  --client "GWS" \
  --name "Healthcare Founders Q4" \
  --source "AI Ark" \
  --csv leads.csv \
  --cost-cap 100.00
```

The CSV should have columns: `linkedin`, `email`, `first_name`, `last_name`, `title`, `company_name`, `website`.

### 2. Estimate Enrichment Cost

Before spending, get a rough cost estimate:
```bash
./scripts/lead_lists.py enrich <list_id> --estimate
```

This shows:
- Number of pending leads
- Estimated cost per lead (~$0.003 avg)
- Total estimated cost
- Remaining budget (if cost cap is set)

### 3. Enrich the List

Run enrichment with explicit confirmation and cost cap:
```bash
./scripts/enrich_list.py <list_id> --confirm-spend 50.00
```

Options:
- `--workers 32`: Parallel workers (default: 32)
- `--cheap`: Use cheap mode (ContactOut + Blitz instead of MV + QE + Trykitt)

**Resumable**: If enrichment stops (cap reached, interrupted, or failed), just re-run the same command. Already-enriched leads are skipped (tracked per lead in `lead_list_members`).

### 4. Monitor Progress

Check list status and run report:
```bash
./scripts/lead_lists.py show <list_id>
```

Shows:
- Total, enriched, ready, failed, skipped counts
- Actual cost vs. cap
- Timestamps (created, started, completed)
- **Run report** (after enrichment):
  - Searches run and leads found
  - Emails by source (cache, pattern+verify, Blitz, QuickEnrich, Trykitt)
  - Cost by provider (Icypeas, MillionVerifier, ContactOut, Blitz, QuickEnrich, Trykitt)
  - Batch stats (bulk verify calls, concurrent finds, rate limit hits)
  - Duration and throughput (leads/min)

List all lists:
```bash
./scripts/lead_lists.py list
./scripts/lead_lists.py list --client MARS
./scripts/lead_lists.py list --status enriched
```

### 5. Export Results

Export ready leads (enriched with valid email) to CSV:
```bash
./scripts/lead_lists.py export <list_id> --format csv --output mars_midwest_cnc.csv
```

The export includes:
- `first_name`, `last_name`, `title`, `email`
- `linkedin`, `company_name`, `website`, `location`
- `company_size`, `company_description`
- `email_status`, `email_source` (for transparency)

## Cost Guardrails

Every enrichment run requires **explicit cost confirmation**:

1. Run with `--estimate` first to see projected cost
2. Set a hard cap with `--confirm-spend <amount>`
3. The runner stops immediately if the cap is reached
4. Cost is tracked **per lead** in `lead_list_members.cost_micro`
5. List-level `actual_cost_usd` is auto-updated by database trigger

## Migration

The database migration is **additive and non-blocking**:
- New tables: `lead_lists`, `lead_list_members`
- New column on `pipeline_leads`: `list_ids UUID[]` (nullable)
- All indexes created with `CONCURRENTLY`
- Safe to run on large tables (no full-table rewrites)

### Apply Migration

**Prerequisites**: Set `SUPABASE_SERVICE_ROLE_KEY` in environment or Cursor Secrets.

Run the migration script:
```bash
./scripts/apply_migration.sh
```

Or manually via Supabase SQL Editor:
1. Open [Supabase Dashboard](https://supabase.com/dashboard)
2. Go to SQL Editor
3. Paste contents of `migrations/001_lead_lists.sql`
4. Run

**Verify**:
```bash
./scripts/lead_lists.py stats
```

## Cross-Client Rules

A lead can belong to multiple clients' lists, but:
- The system flags duplicate LinkedIn URLs / emails across clients
- Manual review is recommended before emailing the same person for different clients
- Future: Add "conflict detection" report to show cross-client overlaps

## Existing Scripts

### `scripts/gws_icypeas_sheet2.py`

The original batch enrichment script (used for PR #11). Still works for one-off scrapes:
```bash
./scripts/gws_icypeas_sheet2.py --confirm-spend 10.00 --target-ready 500
```

Now also:
- Loads Supabase `pipeline_leads` cache at startup
- Reuses emails ≤30 days old without re-verification
- Upserts every found email to `pipeline_leads`

### `scripts/lead_lists.py`

The new list management CLI:
- `create`: Create a list from URLs or CSV
- `list`: List all lists
- `show`: Show details for a list
- `enrich`: (Placeholder) See `enrich_list.py` instead
- `export`: Export ready leads to CSV
- `stats`: Show pipeline statistics

### `scripts/enrich_list.py`

List-based enrichment runner with bulk operations:
- Fetches pending leads from a specific list
- Enriches using **bulk/batch operations**:
  - Batch cache lookups
  - Concurrent pattern verification (up to 50 emails)
  - Concurrent find operations (32+ parallel)
  - Rate-limit backoff and retry
- Updates `lead_list_members` with per-lead status and cost
- Generates detailed run report (sources, provider costs, batch stats)
- Fully resumable

## Environment Variables

Required:
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service role key (for write access)
- `TREG_TOKEN`: Treg.to API token (for email finding/verification)

Optional:
- `SUPABASE_URL`: Supabase project URL (default: npkdhahdvilcctjwzdlf.supabase.co)
- `PLUSVIBE_API_KEY`: PlusVibe API key (for suppression list)
- `PLUSVIBE_WORKSPACE_ID`: PlusVibe workspace ID

## Examples

### Complete workflow

```bash
# 1. Create a list
./scripts/lead_lists.py create \
  --client "MARS" \
  --name "Ohio Manufacturing Nov 2026" \
  --source "icypeas" \
  --linkedin-urls ohio_mfg_linkedin.txt \
  --cost-cap 75.00

# Output: List ID: abc123-def456-...

# 2. Estimate cost
./scripts/lead_lists.py enrich abc123-def456 --estimate

# 3. Enrich (with confirmation)
./scripts/enrich_list.py abc123-def456 --confirm-spend 75.00

# 4. Check status
./scripts/lead_lists.py show abc123-def456

# 5. Export ready leads
./scripts/lead_lists.py export abc123-def456 --format csv --output mars_ohio_mfg.csv

# 6. View statistics
./scripts/lead_lists.py stats
```

### Resume interrupted enrichment

If enrichment stops before completing (e.g., cost cap hit), just re-run:
```bash
./scripts/enrich_list.py abc123-def456 --confirm-spend 50.00
```

Already-enriched leads are skipped automatically.

## Architecture Notes

### Why a Join Table?

`lead_list_members` enables:
- **Many-to-many**: One lead in multiple lists without duplication
- **Per-list enrichment state**: Track status/cost separately for each list
- **Resumability**: Skip already-enriched leads on re-run
- **Referential integrity**: `ON DELETE CASCADE` keeps data consistent

### Why Not Separate Lead Tables Per Client?

Keeping all leads in `pipeline_leads` enables:
- **Deduplication**: Instant lookup by LinkedIn/email across all clients
- **Cost savings**: Reuse enriched emails across lists (with proper controls)
- **Unified reporting**: One table for all analytics
- **Scalability**: Postgres handles millions of rows efficiently with proper indexes

### Cost Tracking

Cost is tracked at two levels:
1. **Per-lead** (`lead_list_members.cost_micro`): Tracks exact spend for each lead in each list
2. **Per-list** (`lead_lists.actual_cost_usd`): Aggregated via database trigger

This allows:
- Accurate per-list cost reporting
- Fair cost allocation when leads are in multiple lists
- Easy auditing (sum of `cost_micro` = `actual_cost_usd`)

## Performance Benchmarks

Based on typical runs:
- **Throughput**: 40-60 leads/min (with bulk operations)
- **Cache hit rate**: 30-50% on subsequent runs
- **Cost per lead**: $0.002-0.005 (depending on pattern hit rate)
- **Bulk efficiency**: 10x faster than sequential processing

## Future Enhancements

- [ ] Google Sheets export (auto-create tab per client)
- [ ] Conflict detection report (cross-client lead overlaps)
- [ ] Scheduled enrichment (cron-like recurring runs)
- [ ] Web UI for list management
- [ ] Webhook notifications (list enriched, cost cap hit)
- [ ] Advanced filtering (by company size, location, etc.)
- [ ] Batch re-verification (re-enrich stale emails)
- [ ] True bulk MillionVerifier API (if/when available via treg.to)
- [ ] Adaptive batch sizing based on API response times

## Support

For issues or questions:
1. Check this README
2. Run `./scripts/lead_lists.py --help`
3. Inspect database with Supabase dashboard

## License

Internal tool for ZS Ops2.
