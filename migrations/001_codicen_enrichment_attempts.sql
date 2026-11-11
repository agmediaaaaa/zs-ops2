-- Migration: Add codicen_enrichment_attempts table for duplicate-proof enrichment
-- 
-- Purpose: Record every enrichment attempt per company/method to prevent:
-- - Re-searching companies already web-searched
-- - Re-calling Jev on domains already checked
-- - Re-crawling domains already crawled or failed
-- - Re-verifying emails already checked or in suppression/recent lists
--
-- Methods:
--   candidate_fetch: Free Clearbit/Hunter candidate discovery (per company)
--   jev: Paid Jev domain verification (per domain)
--   web_search: Paid web search for domains (per company)
--   crawl: Paid Crawl4AI email extraction (per domain)
--   email_verify: Paid MV/BB email verification (per email)

CREATE TABLE IF NOT EXISTS codicen_enrichment_attempts (
    id BIGSERIAL PRIMARY KEY,
    license_no TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('candidate_fetch', 'jev', 'web_search', 'crawl', 'email_verify')),
    identifier TEXT,  -- domain for jev/crawl, email for email_verify, null for candidate_fetch/web_search
    outcome TEXT NOT NULL,  -- confirmed, rejected, failed, skipped, etc.
    cost_micro INTEGER NOT NULL DEFAULT 0,  -- cost in microdollars (1/1,000,000 USD)
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB,  -- extra details: markers, scores, errors, etc.
    
    -- Prevent exact duplicates
    CONSTRAINT unique_attempt UNIQUE (license_no, method, identifier, attempted_at)
);

-- Indexes for fast skip checks
CREATE INDEX idx_attempts_license_method ON codicen_enrichment_attempts(license_no, method);
CREATE INDEX idx_attempts_method_identifier ON codicen_enrichment_attempts(method, identifier) WHERE identifier IS NOT NULL;
CREATE INDEX idx_attempts_attempted_at ON codicen_enrichment_attempts(attempted_at);

-- View: Latest attempt per company/method
CREATE OR REPLACE VIEW codicen_latest_attempts AS
SELECT DISTINCT ON (license_no, method, identifier)
    license_no,
    method,
    identifier,
    outcome,
    cost_micro,
    attempted_at,
    metadata
FROM codicen_enrichment_attempts
ORDER BY license_no, method, identifier, attempted_at DESC;

-- Helper function: Check if company/method was already attempted
CREATE OR REPLACE FUNCTION codicen_was_attempted(
    p_license_no TEXT,
    p_method TEXT,
    p_identifier TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM codicen_enrichment_attempts
        WHERE license_no = p_license_no
          AND method = p_method
          AND (p_identifier IS NULL OR identifier = p_identifier)
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON TABLE codicen_enrichment_attempts IS 'Ledger of all enrichment attempts to prevent duplicate work and spending';
COMMENT ON COLUMN codicen_enrichment_attempts.method IS 'candidate_fetch | jev | web_search | crawl | email_verify';
COMMENT ON COLUMN codicen_enrichment_attempts.identifier IS 'domain (jev/crawl), email (email_verify), or null (candidate_fetch/web_search)';
COMMENT ON COLUMN codicen_enrichment_attempts.cost_micro IS 'Cost in microdollars (1e-6 USD)';
COMMENT ON COLUMN codicen_enrichment_attempts.metadata IS 'JSON: markers, scores, errors, source_url, etc.';
