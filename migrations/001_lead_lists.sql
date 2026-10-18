-- Lead Lists Management Schema
-- Migration adds lead list tracking and many-to-many relationship between lists and the main "Lead Database" table
-- Safe for large tables: additive only, nullable columns, no volatile defaults
-- Run in transaction; concurrent indexes are in a separate file

-- Enable search_path for functions
SET search_path TO public;

-- NOTE ON pipeline_leads TABLE:
-- pipeline_leads (~1k rows) remains as a staging table for PR #11's gws_icypeas_sheet2.py script.
-- The main "Lead Database" table (441k+ rows) is the canonical source of truth.
-- Enrichment results are upserted to "Lead Database" based on normalized Linkedin → Email deduplication.
-- This migration does NOT modify or depend on pipeline_leads.

-- Lead lists table: tracks scrape/import batches with metadata and status
CREATE TABLE IF NOT EXISTS lead_lists (
    list_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client TEXT NOT NULL,
    list_name TEXT NOT NULL,
    source TEXT NOT NULL, -- 'icypeas', 'treg.to', 'AI Ark', 'manual', etc.
    status TEXT NOT NULL DEFAULT 'scraped', -- 'scraped', 'enriching', 'enriched', 'exported', 'failed'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Counts (updated as enrichment progresses)
    total_leads INTEGER DEFAULT 0,
    enriched_count INTEGER DEFAULT 0,
    ready_count INTEGER DEFAULT 0, -- leads with valid emails
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    
    -- Cost tracking
    estimated_cost_usd NUMERIC(10, 6),
    actual_cost_usd NUMERIC(10, 6) DEFAULT 0.0,
    cost_cap_usd NUMERIC(10, 6),
    
    -- Additional metadata
    enrichment_started_at TIMESTAMPTZ,
    enrichment_completed_at TIMESTAMPTZ,
    exported_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Run report: detailed breakdown of enrichment results and costs
    run_report JSONB DEFAULT NULL,
    -- Structure: {
    --   "searches_run": 150,
    --   "leads_found": 145,
    --   "emails_by_source": {
    --     "supabase_cache": 50,
    --     "supabase_mv_reverify": 20,
    --     "pattern_mv": 30,
    --     "pattern_contactout": 10,
    --     "blitz": 15,
    --     "quickenrich": 10,
    --     "trykitt": 10
    --   },
    --   "cost_by_provider": {
    --     "icypeas": 0.50,
    --     "millionverifier": 0.80,
    --     "contactout": 0.00,
    --     "blitz": 0.20,
    --     "quickenrich": 0.60,
    --     "trykitt": 0.70
    --   },
    --   "batch_stats": {
    --     "bulk_verify_calls": 5,
    --     "concurrent_finds": 32,
    --     "rate_limit_hits": 3
    --   },
    --   "duration_sec": 185.4,
    --   "throughput_per_min": 47.2
    -- }
    
    -- Constraints
    CONSTRAINT valid_status CHECK (status IN ('scraped', 'enriching', 'enriched', 'exported', 'failed')),
    CONSTRAINT positive_counts CHECK (
        total_leads >= 0 AND
        enriched_count >= 0 AND
        ready_count >= 0 AND
        failed_count >= 0 AND
        skipped_count >= 0
    ),
    CONSTRAINT positive_costs CHECK (
        (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0) AND
        actual_cost_usd >= 0 AND
        (cost_cap_usd IS NULL OR cost_cap_usd >= 0)
    )
);

-- Join table: many-to-many relationship between lists and the main "Lead Database" table
CREATE TABLE IF NOT EXISTS lead_list_members (
    list_id UUID NOT NULL REFERENCES lead_lists(list_id) ON DELETE CASCADE,
    lead_id BIGINT NOT NULL REFERENCES "Lead Database"(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Per-lead enrichment status within this list
    enrichment_status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'in_progress', 'enriched', 'failed', 'skipped'
    enrichment_attempted_at TIMESTAMPTZ,
    enrichment_completed_at TIMESTAMPTZ,
    cost_micro INTEGER DEFAULT 0, -- Cost to enrich this specific lead in this list
    
    -- Prevent duplicate leads in same list
    PRIMARY KEY (list_id, lead_id),
    
    CONSTRAINT valid_enrichment_status CHECK (
        enrichment_status IN ('pending', 'in_progress', 'enriched', 'failed', 'skipped')
    )
);

-- Indexes for lead_lists (small table, can create in transaction)
CREATE INDEX IF NOT EXISTS idx_lead_lists_client_status 
    ON lead_lists(client, status);

CREATE INDEX IF NOT EXISTS idx_lead_lists_created_at 
    ON lead_lists(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lead_lists_status 
    ON lead_lists(status) WHERE status IN ('scraped', 'enriching');

-- Indexes for lead_list_members (can grow large, but starts small)
CREATE INDEX IF NOT EXISTS idx_lead_list_members_list_id 
    ON lead_list_members(list_id);

CREATE INDEX IF NOT EXISTS idx_lead_list_members_lead_id 
    ON lead_list_members(lead_id);

CREATE INDEX IF NOT EXISTS idx_lead_list_members_status 
    ON lead_list_members(list_id, enrichment_status) 
    WHERE enrichment_status IN ('pending', 'in_progress');

-- Add enrichment tracking columns to "Lead Database" (nullable, no defaults)
-- These support the 30-day cache and enrichment status tracking
ALTER TABLE "Lead Database" 
    ADD COLUMN IF NOT EXISTS company_size TEXT,
    ADD COLUMN IF NOT EXISTS company_description TEXT,
    ADD COLUMN IF NOT EXISTS location TEXT,
    ADD COLUMN IF NOT EXISTS email_source TEXT,
    ADD COLUMN IF NOT EXISTS email_status TEXT,
    ADD COLUMN IF NOT EXISTS enrichment_updated_at TIMESTAMPTZ;

-- NOTE: Count updates are handled by the enrichment runner, not triggers
-- This avoids O(N²) recount on bulk operations and keeps the migration simple

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_lead_lists_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql 
SECURITY DEFINER
SET search_path = public;

-- Trigger to auto-update updated_at on lead_lists
DROP TRIGGER IF EXISTS trg_lead_lists_updated_at ON lead_lists;
CREATE TRIGGER trg_lead_lists_updated_at
    BEFORE UPDATE ON lead_lists
    FOR EACH ROW
    EXECUTE FUNCTION update_lead_lists_updated_at();

-- Enable Row Level Security (service role only for now)
ALTER TABLE lead_lists ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_list_members ENABLE ROW LEVEL SECURITY;

-- Service role can do everything (policies can be refined later)
CREATE POLICY IF NOT EXISTS "Service role full access to lead_lists"
    ON lead_lists
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY IF NOT EXISTS "Service role full access to lead_list_members"
    ON lead_list_members
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Comments for documentation
COMMENT ON TABLE lead_lists IS 'Tracks lead scrape/import batches with enrichment status and cost accounting';
COMMENT ON TABLE lead_list_members IS 'Many-to-many join table linking Lead Database rows to lists with per-lead enrichment tracking';
COMMENT ON COLUMN lead_lists.source IS 'Origin of leads: icypeas, treg.to, AI Ark, manual upload, etc.';
COMMENT ON COLUMN lead_lists.status IS 'Overall list status: scraped (raw), enriching (in progress), enriched (complete), exported (sent to client), failed';
COMMENT ON COLUMN lead_lists.run_report IS 'Detailed enrichment run report: searches, emails by source, cost by provider, batch stats';
COMMENT ON COLUMN lead_list_members.enrichment_status IS 'Per-lead enrichment state: pending, in_progress, enriched, failed, skipped';
COMMENT ON COLUMN lead_list_members.cost_micro IS 'Microdollars spent enriching this specific lead (for accurate per-list cost tracking)';
COMMENT ON COLUMN "Lead Database".company_size IS 'Company employee count (for 30-day cache and enrichment tracking)';
COMMENT ON COLUMN "Lead Database".company_description IS 'Company description (for 30-day cache and enrichment tracking)';
COMMENT ON COLUMN "Lead Database".location IS 'Lead location (for 30-day cache and enrichment tracking)';
COMMENT ON COLUMN "Lead Database".email_source IS 'How email was found: supabase_cache, pattern_mv, blitz, quickenrich, trykitt, etc.';
COMMENT ON COLUMN "Lead Database".email_status IS 'Email verification status: valid, smtp_valid, catch_all, etc.';
COMMENT ON COLUMN "Lead Database".enrichment_updated_at IS 'When email/enrichment was last updated (for 30-day cache)';
