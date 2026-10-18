# Lead Lists Schema Documentation

## Entity Relationship Diagram

```
┌─────────────────────────┐
│     lead_lists          │
├─────────────────────────┤
│ list_id (PK)           │◄───┐
│ client                  │    │
│ list_name               │    │
│ source                  │    │
│ status                  │    │
│ total_leads             │    │
│ enriched_count          │    │
│ ready_count             │    │
│ failed_count            │    │
│ skipped_count           │    │
│ estimated_cost_usd      │    │
│ actual_cost_usd         │    │
│ cost_cap_usd            │    │
│ created_at              │    │
│ updated_at              │    │
│ enrichment_started_at   │    │
│ enrichment_completed_at │    │
│ exported_at             │    │
│ metadata                │    │
│ run_report              │◄───┼─── Detailed enrichment metrics
└─────────────────────────┘    │
                               │
                               │ Many-to-Many
                               │
┌─────────────────────────┐    │
│  lead_list_members      │    │
├─────────────────────────┤    │
│ list_id (FK)           │────┘
│ lead_id (FK)           │────┐
│ added_at                │    │
│ enrichment_status       │    │
│ enrichment_attempted_at │    │
│ enrichment_completed_at │    │
│ cost_micro              │    │
└─────────────────────────┘    │
                               │
                               │
┌─────────────────────────┐    │
│    pipeline_leads       │    │
├─────────────────────────┤    │
│ id (PK)                │◄───┘
│ email                   │
│ linkedin                │
│ first_name              │
│ last_name               │
│ title                   │
│ company_name            │
│ website                 │
│ company_domain          │
│ location                │
│ company_size            │
│ company_description     │
│ employees               │
│ mv_status               │
│ email_source            │
│ plusvibe_ready          │
│ client                  │
│ batch_id                │
│ source_run              │
│ handoff_status          │
│ list_ids[]              │◄─── Quick membership check
│ created_at              │
│ updated_at              │
│ raw                     │
└─────────────────────────┘
```

## Table Details

### `lead_lists`

Tracks scrape/import batches with status and cost accounting.

**Key Fields:**
- `list_id`: UUID primary key
- `status`: `scraped` → `enriching` → `enriched` → `exported` | `failed`
- `*_count`: Auto-updated by triggers (from `lead_list_members`)
- `actual_cost_usd`: Auto-calculated from member `cost_micro` sum
- `run_report`: JSONB with detailed enrichment metrics

**Status Flow:**
```
scraped (initial)
  ↓
enriching (during enrichment run)
  ↓
enriched (all pending leads processed)
  ↓
exported (CSV/sheet exported)
```

### `lead_list_members`

Many-to-many join table linking leads to lists with per-lead enrichment state.

**Key Fields:**
- `(list_id, lead_id)`: Composite primary key
- `enrichment_status`: `pending` → `in_progress` → `enriched` | `failed` | `skipped`
- `cost_micro`: Microdollars spent enriching this specific lead

**Enrichment Status Flow:**
```
pending (initial)
  ↓
in_progress (enrichment started)
  ↓
enriched (email found) | failed (no email) | skipped (invalid data)
```

**Why a Join Table?**
- One lead can belong to multiple lists (no duplication)
- Per-list enrichment state (resumable)
- Per-list cost tracking (fair allocation)
- Cascade delete (clean up when list deleted)

### `pipeline_leads`

Main leads table (existing, with new columns added).

**New Fields:**
- `list_ids UUID[]`: Array of list IDs this lead belongs to (for quick membership checks)

**Deduplication:**
1. Normalized LinkedIn URL (lowercase, no trailing slash, no query params)
2. Email (lowercase)
3. Pattern email fallback (first.last@domain)

## Indexes

All indexes created with `CONCURRENTLY` (non-blocking):

```sql
-- lead_lists
idx_lead_lists_client_status      ON (client, status)
idx_lead_lists_created_at         ON (created_at DESC)
idx_lead_lists_status             ON (status) WHERE status IN ('scraped', 'enriching')

-- lead_list_members
idx_lead_list_members_lead_id     ON (lead_id)
idx_lead_list_members_status      ON (list_id, enrichment_status) 
                                   WHERE status IN ('pending', 'in_progress')

-- pipeline_leads
idx_pipeline_leads_list_ids       ON (list_ids) USING GIN 
                                   WHERE list_ids IS NOT NULL
```

## Triggers

### `update_lead_list_counts()`

Auto-updates `lead_lists` counts on `lead_list_members` changes:
- `enriched_count`: Count of `enriched` members
- `ready_count`: Count of `enriched` members with valid email
- `failed_count`: Count of `failed` members
- `skipped_count`: Count of `skipped` members
- `actual_cost_usd`: Sum of `cost_micro / 1000000`

### `update_updated_at()`

Auto-updates `updated_at` timestamp on `lead_lists` changes.

## Run Report Schema

Saved to `lead_lists.run_report` after each enrichment run:

```json
{
  "list_id": "abc-123-...",
  "list_name": "MARS Midwest CNC Oct 18",
  "searches_run": 150,
  "leads_found": 142,
  
  "emails_by_source": {
    "supabase_cache": 45,          // Cached, <30 days old
    "supabase_mv_reverify": 18,    // Cached, re-verified (>30 days)
    "pattern_mv": 35,               // Pattern + MillionVerifier
    "pattern_contactout": 12,       // Pattern + ContactOut (cheap mode)
    "blitz": 22,                    // Blitz find
    "quickenrich": 15,              // QuickEnrich find
    "trykitt": 7                    // Trykitt find
  },
  
  "cost_by_provider": {
    "icypeas": 0.00,                // Free count calls
    "millionverifier": 1.24,        // Pattern verify + QE verify
    "contactout": 0.00,             // Free (cheap mode)
    "blitz": 0.18,                  // Cheapest paid find
    "quickenrich": 0.95,            // Mid-tier find
    "trykitt": 0.52                 // Last resort find
  },
  
  "batch_stats": {
    "bulk_verify_calls": 3,         // Number of bulk verify batches
    "concurrent_finds": 48,         // Number of concurrent find ops
    "rate_limit_hits": 2,           // 429 errors encountered
    "avg_batch_size": 46.7          // Avg emails per bulk verify
  },
  
  "duration_sec": 185.4,
  "throughput_per_min": 45.9,
  "total_cost_usd": 2.89
}
```

## Data Flow

### List Creation
```
User provides:
  - LinkedIn URLs OR CSV
  - Client, name, source
  - Cost cap
    ↓
For each lead:
  - Look up in pipeline_leads (by LinkedIn or email)
  - Create if not found
  - Insert into lead_list_members (status: pending)
    ↓
List created with total_leads count
```

### Enrichment (Bulk Operations)
```
Fetch all pending leads
    ↓
Batch 1: Supabase cache lookup (all leads at once)
    ↓
Batch 2: Generate pattern emails (all cache misses)
    ↓
Batch 3: Bulk verify patterns (50+ concurrent)
    ↓
Batch 4: Concurrent find (32+ parallel)
  - Blitz (cheapest, requires LinkedIn)
  - QuickEnrich (standard mode)
  - Trykitt (last resort)
    ↓
For each result:
  - Update lead_list_members (status, cost_micro)
  - Upsert pipeline_leads (email, metadata)
    ↓
Generate run report
Update lead_lists (status: enriched, run_report)
```

### Export
```
Fetch enriched members with valid email
    ↓
Join with pipeline_leads for full data
    ↓
Write to CSV
    ↓
Update lead_lists (status: exported, exported_at)
```

## Query Examples

### Find all lists for a client
```sql
SELECT list_id, list_name, status, ready_count, actual_cost_usd
FROM lead_lists
WHERE client = 'MARS'
ORDER BY created_at DESC;
```

### Get pending leads for enrichment
```sql
SELECT 
  llm.lead_id,
  pl.first_name,
  pl.last_name,
  pl.linkedin,
  pl.company_name
FROM lead_list_members llm
JOIN pipeline_leads pl ON llm.lead_id = pl.id
WHERE llm.list_id = 'abc-123-...'
  AND llm.enrichment_status = 'pending';
```

### Calculate list cost breakdown
```sql
SELECT 
  llm.enrichment_status,
  COUNT(*) as count,
  SUM(llm.cost_micro) / 1000000.0 as cost_usd
FROM lead_list_members llm
WHERE llm.list_id = 'abc-123-...'
GROUP BY llm.enrichment_status;
```

### Find leads in multiple lists
```sql
SELECT 
  pl.id,
  pl.email,
  pl.first_name,
  pl.last_name,
  array_agg(ll.list_name) as lists
FROM pipeline_leads pl
JOIN lead_list_members llm ON pl.id = llm.lead_id
JOIN lead_lists ll ON llm.list_id = ll.list_id
GROUP BY pl.id, pl.email, pl.first_name, pl.last_name
HAVING COUNT(DISTINCT llm.list_id) > 1;
```

### Extract emails by source from run report
```sql
SELECT 
  list_name,
  run_report->'emails_by_source'->>'supabase_cache' as cache_hits,
  run_report->'emails_by_source'->>'pattern_mv' as pattern_hits,
  run_report->'emails_by_source'->>'blitz' as blitz_hits,
  run_report->>'total_cost_usd' as cost
FROM lead_lists
WHERE status = 'enriched'
ORDER BY created_at DESC;
```

## Migration Safety

The migration is **safe for production** because:

1. **Additive only**: No columns dropped, no data modified
2. **Nullable columns**: `list_ids` is nullable (backwards compatible)
3. **Concurrent indexes**: All indexes created with `CONCURRENTLY`
4. **Small DDL**: Table creation is fast (no existing data)
5. **Separate tables**: `lead_lists` and `lead_list_members` don't touch existing data

The only change to `pipeline_leads` is adding a nullable `list_ids` column, which:
- Does NOT rewrite the table (just updates metadata)
- Does NOT lock the table (nullable column addition is non-blocking in Postgres 11+)
- Does NOT affect existing queries (column is optional)

## Performance Characteristics

**Table Sizes (expected):**
- `pipeline_leads`: 100K-1M rows (existing)
- `lead_lists`: 100-1000 rows (one per scrape/import)
- `lead_list_members`: 10K-100K rows (members × lists)

**Query Performance:**
- List creation: O(n) where n = leads in list (1-10K typical)
- Enrichment: O(n) with bulk operations (10x faster than sequential)
- Export: O(m) where m = ready leads (filtered)
- Stats: O(l) where l = number of lists (100s)

**Bottlenecks:**
- API rate limits (handled with backoff)
- Supabase cache load (indexed on LinkedIn/email)
- Bulk verify size (limited to 50 concurrent)

**Optimizations:**
- GIN index on `list_ids` for fast membership checks
- Partial indexes on status fields (only pending/in_progress)
- Concurrent bulk operations (50+ emails verified at once)
- Rate-limit backoff (automatic retry on 429)
