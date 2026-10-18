-- Add company industry to canonical "Lead Database"
-- Matches pipeline_leads.company_industry and builder ready-row company_industry
-- Applied to production as 005_lead_database_company_industry

SET search_path TO public;
SET lock_timeout = '5s';

ALTER TABLE "Lead Database"
    ADD COLUMN IF NOT EXISTS company_industry TEXT;

COMMENT ON COLUMN "Lead Database".company_industry IS 'Company industry (from Icypeas lastCompanyIndustry, Blitz/company enrich, etc.)';
