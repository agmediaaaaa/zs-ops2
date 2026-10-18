-- Concurrent indexes for "Lead Database" table (441k+ rows)
-- Must be run OUTSIDE a transaction block
-- Run after 001_lead_lists.sql is applied

-- Index for enrichment_updated_at (for 30-day cache queries)
-- Applied as of 2026-10-18
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_database_enrichment_updated_at 
    ON "Lead Database"(enrichment_updated_at) 
    WHERE enrichment_updated_at IS NOT NULL;

-- Note: lead_database_email_lower_idx on lower(btrim("Email")) already exists
-- Do NOT create additional email indexes

-- Instructions:
-- 1. Apply 001_lead_lists.sql first (in transaction)
-- 2. Run CREATE INDEX CONCURRENTLY above separately (NOT in a transaction)
-- 3. Monitor: SELECT * FROM pg_stat_progress_create_index;
