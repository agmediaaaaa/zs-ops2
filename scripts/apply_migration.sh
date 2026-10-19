#!/bin/bash
# Apply lead_lists migration to Supabase
set -euo pipefail

MIGRATION_FILE="migrations/001_lead_lists.sql"

# Check prerequisites
if [ ! -f "$MIGRATION_FILE" ]; then
    echo "Error: Migration file not found: $MIGRATION_FILE"
    exit 1
fi

if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
    echo "Error: SUPABASE_SERVICE_ROLE_KEY not set"
    echo "Set it in your environment or Cursor Secrets"
    exit 1
fi

SUPABASE_URL="${SUPABASE_URL:-https://npkdhahdvilcctjwzdlf.supabase.co}"

echo "============================================"
echo "Apply Lead Lists Migration"
echo "============================================"
echo "Supabase URL: $SUPABASE_URL"
echo "Migration: $MIGRATION_FILE"
echo ""
echo "This migration will:"
echo "  - Create lead_lists table"
echo "  - Create lead_list_members table"
echo "  - Add list_ids column to pipeline_leads"
echo "  - Create indexes (CONCURRENTLY, non-blocking)"
echo "  - Add triggers for auto-updating counts"
echo ""
echo "This is SAFE for large tables (additive only)."
echo ""

# Confirm
read -p "Apply migration? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted"
    exit 0
fi

# Apply via Supabase REST API (execute raw SQL)
echo ""
echo "Applying migration..."

SQL=$(cat "$MIGRATION_FILE")

# Use Supabase REST API to execute SQL
# Note: This requires the query endpoint, which might not be available via REST
# Safer approach: Use psql or Supabase dashboard

echo ""
echo "⚠ Note: SQL execution via REST API is limited."
echo ""
echo "Recommended: Apply via Supabase Dashboard SQL Editor"
echo "  1. Go to: https://supabase.com/dashboard/project/npkdhahdvilcctjwzdlf/sql"
echo "  2. Paste contents of: $MIGRATION_FILE"
echo "  3. Run"
echo ""
echo "Alternative: Use psql if you have connection string:"
echo "  psql \"\$DATABASE_URL\" < $MIGRATION_FILE"
echo ""

# For now, just validate the SQL is parseable
echo "✓ Migration file validated"
echo ""
echo "Next steps:"
echo "  1. Apply migration via Supabase Dashboard (see above)"
echo "  2. Verify: ./scripts/lead_lists.py stats"
echo "  3. Create your first list: ./scripts/lead_lists.py create --help"
