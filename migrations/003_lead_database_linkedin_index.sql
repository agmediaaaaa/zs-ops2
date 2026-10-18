-- Normalized LinkedIn index for efficient exact-match lookups
-- Must be run OUTSIDE a transaction block (CONCURRENTLY)
-- Created to avoid full table scans on LinkedIn lookups

-- Create functional index on normalized LinkedIn URLs
-- This supports lookups like: WHERE lower(trim("Linkedin")) = 'linkedin.com/in/username'
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lead_database_linkedin_normalized
    ON "Lead Database"(lower(trim("Linkedin")))
    WHERE "Linkedin" IS NOT NULL AND "Linkedin" != '';

-- Usage in queries:
-- SELECT * FROM "Lead Database" 
-- WHERE lower(trim("Linkedin")) = 'normalized_url'
-- 
-- This avoids the O(N) scan from: "Linkedin" ILIKE '%pattern%'
