-- Add job title to canonical "Lead Database"
-- Matches pipeline_leads.title and CSV/Sheet export "title" / "Title"
-- Applied to production as 004_lead_database_title

SET search_path TO public;
SET lock_timeout = '5s';

ALTER TABLE "Lead Database"
    ADD COLUMN IF NOT EXISTS title TEXT;

COMMENT ON COLUMN "Lead Database".title IS 'Job title / current role (from Icypeas lastJobTitle, headline, etc.)';
