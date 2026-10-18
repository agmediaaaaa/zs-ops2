-- Concurrent indexes for "Lead Database" table (441k+ rows)
-- Must be run OUTSIDE a transaction block
-- Run after 001_lead_lists.sql is applied

-- Run these one at a time in separate statements, not in a transaction:

-- Index for enrichment_updated_at (for 30-day cache queries)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_database_enrichment_updated_at 
    ON "Lead Database"(enrichment_updated_at) 
    WHERE enrichment_updated_at IS NOT NULL;

-- Index for normalized linkedin lookup (add when normalized_linkedin column exists)
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_database_normalized_linkedin 
--     ON "Lead Database"(lower(trim("Linkedin"))) 
--     WHERE "Linkedin" IS NOT NULL;

-- Index for email lookup (lowercase for deduplication)
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_database_email_lower 
--     ON "Lead Database"(lower("Email")) 
--     WHERE "Email" IS NOT NULL AND "Email" NOT IN ('', 'n/a', 'none', 'null');

-- Instructions:
-- 1. Apply 001_lead_lists.sql first (in transaction)
-- 2. Run each CREATE INDEX CONCURRENTLY statement above separately (NOT in a transaction)
-- 3. Monitor index creation: SELECT * FROM pg_stat_progress_create_index;
-- 4. Each index takes ~30-60 seconds on a 441k-row table
