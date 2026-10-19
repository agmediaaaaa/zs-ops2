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
│   "Lead Database"       │    │
├─────────────────────────┤    │
│ id (PK) bigint         │◄───┘
│ created_at              │
│ "First Name"            │
│ "Last Name"             │
│ "Email"                 │
│ "Linkedin"              │
│ "Company Name"          │
│ "Website"               │
│ company_size            │◄─── New
│ company_description     │◄─── New
│ location                │◄─── New
│ email_source            │◄─── New
│ email_status            │◄─── New
│ enrichment_updated_at   │◄─── New (30-day cache)
└─────────────────────────┘

NOTE: pipeline_leads (~1k rows) remains as staging
      for PR #11. NOT used by lead list system.
```

## Table Details

### `lead_lists`

Tracks scrape/import batches with status and cost accounting.

**Key Fields:**
- `list_id`: UUID primary key
- `status`: `scraped` → `enriching` → `enriched` → `exported` | `failed`
- `*_count`: Updated by enrichment runner (not triggers)
- `actual_cost_usd`: Aggregated by enrichment runner
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

### `"Lead Database"`

Main leads table (441k+ rows, existing, with new columns added).

**Existing Fields:**
- `id` (bigint): Primary key
- `created_at`: Timestamp
- `"First Name"`, `"Last Name"`: Lead name
- `"Email"`: Lead email
- `"Linkedin"`: LinkedIn profile URL
- `"Company Name"`: Company name
- `"Website"`: Company website

**New Fields (nullable, no defaults):**
- `company_size`: Company employee count
- `company_description`: Company description
- `location`: Lead location
- `email_source`: How email was found (supabase_cache, pattern_mv, blitz, etc.)
- `email_status`: Verification status (valid, smtp_valid, catch_all, etc.)
- `enrichment_updated_at`: When enrichment was last updated (for 30-day cache)

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
idx_lead_list_members_list_id     ON (list_id)
idx_lead_list_members_lead_id     ON (lead_id)
idx_lead_list_members_status      ON (list_id, enrichment_status) 
                                   WHERE status IN ('pending', 'in_progress')

-- "Lead Database" (concurrent, separate file)
idx_lead_database_enrichment_updated_at ON (enrichment_updated_at) 
                                         WHERE enrichment_updated_at IS NOT NULL
```

## Triggers

### `update_lead_lists_updated_at()`

Auto-updates `updated_at` timestamp on `lead_lists` changes.

**Note on count updates**: List counts (`enriched_count`, `ready_count`, etc.) are updated by the enrichment runner, not by triggers. This avoids O(N²) recount overhead on bulk operations.

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

**Table Sizes:**
- `"Lead Database"`: 441k rows (existing, growing)
- `lead_lists`: Grows with each scrape/import
- `lead_list_members`: Grows with list membership

**Query Performance:**
- List creation: O(n) where n = leads in list
- Enrichment: O(n) with concurrent operations
- Export: O(m) where m = ready leads
- Stats: O(l) where l = number of lists

**Considerations:**
- API rate limits (handled with backoff)
- Cache lookups on large table (indexed on enrichment_updated_at)
- Concurrent operation limits (tunable)

**Optimizations:**
- Partial indexes on status fields (only pending/in_progress)
- Concurrent operations with rate-limit backoff
- Batch processing to reduce round-trips
