-- Lead Lists Management Schema
-- Migration adds lead list tracking and many-to-many relationship between lists and leads
-- Safe for large tables: additive only, no blocking operations

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

-- Join table: many-to-many relationship between lists and leads
CREATE TABLE IF NOT EXISTS lead_list_members (
    list_id UUID NOT NULL REFERENCES lead_lists(list_id) ON DELETE CASCADE,
    lead_id UUID NOT NULL REFERENCES pipeline_leads(id) ON DELETE CASCADE,
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

-- Indexes for efficient queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_lists_client_status 
    ON lead_lists(client, status);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_lists_created_at 
    ON lead_lists(created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_lists_status 
    ON lead_lists(status) WHERE status IN ('scraped', 'enriching');

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_list_members_lead_id 
    ON lead_list_members(lead_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_list_members_status 
    ON lead_list_members(list_id, enrichment_status) 
    WHERE enrichment_status IN ('pending', 'in_progress');

-- Add list tracking columns to pipeline_leads (nullable for backwards compatibility)
ALTER TABLE pipeline_leads 
    ADD COLUMN IF NOT EXISTS list_ids UUID[] DEFAULT ARRAY[]::UUID[];

-- Index for finding leads by list membership
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pipeline_leads_list_ids 
    ON pipeline_leads USING GIN (list_ids) 
    WHERE list_ids IS NOT NULL AND array_length(list_ids, 1) > 0;

-- Function to update lead_lists counts and timestamps
CREATE OR REPLACE FUNCTION update_lead_list_counts()
RETURNS TRIGGER AS $$
BEGIN
    -- Update counts on the parent list
    UPDATE lead_lists
    SET 
        enriched_count = (
            SELECT COUNT(*) 
            FROM lead_list_members 
            WHERE list_id = NEW.list_id 
            AND enrichment_status = 'enriched'
        ),
        ready_count = (
            SELECT COUNT(*) 
            FROM lead_list_members llm
            JOIN pipeline_leads pl ON llm.lead_id = pl.id
            WHERE llm.list_id = NEW.list_id 
            AND llm.enrichment_status = 'enriched'
            AND pl.email IS NOT NULL
            AND pl.email NOT IN ('n/a', 'none', 'null', '')
        ),
        failed_count = (
            SELECT COUNT(*) 
            FROM lead_list_members 
            WHERE list_id = NEW.list_id 
            AND enrichment_status = 'failed'
        ),
        skipped_count = (
            SELECT COUNT(*) 
            FROM lead_list_members 
            WHERE list_id = NEW.list_id 
            AND enrichment_status = 'skipped'
        ),
        actual_cost_usd = (
            SELECT COALESCE(SUM(cost_micro) / 1000000.0, 0)
            FROM lead_list_members
            WHERE list_id = NEW.list_id
        ),
        updated_at = NOW()
    WHERE list_id = NEW.list_id;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to keep counts updated
CREATE TRIGGER trg_update_lead_list_counts
    AFTER INSERT OR UPDATE OF enrichment_status, cost_micro
    ON lead_list_members
    FOR EACH ROW
    EXECUTE FUNCTION update_lead_list_counts();

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at on lead_lists
CREATE TRIGGER trg_lead_lists_updated_at
    BEFORE UPDATE ON lead_lists
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Comments for documentation
COMMENT ON TABLE lead_lists IS 'Tracks lead scrape/import batches with enrichment status and cost accounting';
COMMENT ON TABLE lead_list_members IS 'Many-to-many join table linking leads to lists with per-lead enrichment tracking';
COMMENT ON COLUMN lead_lists.source IS 'Origin of leads: icypeas, treg.to, AI Ark, manual upload, etc.';
COMMENT ON COLUMN lead_lists.status IS 'Overall list status: scraped (raw), enriching (in progress), enriched (complete), exported (sent to client), failed';
COMMENT ON COLUMN lead_lists.run_report IS 'Detailed enrichment run report: searches, emails by source, cost by provider, batch stats, performance metrics';
COMMENT ON COLUMN lead_list_members.enrichment_status IS 'Per-lead enrichment state: pending, in_progress, enriched, failed, skipped';
COMMENT ON COLUMN lead_list_members.cost_micro IS 'Microdollars spent enriching this specific lead (for accurate per-list cost tracking)';
