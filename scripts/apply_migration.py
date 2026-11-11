#!/usr/bin/env python3
"""Apply migration SQL to Supabase using REST API"""

import os
import sys
import httpx

SUPABASE_URL = 'https://npkdhahdvilcctjwzdlf.supabase.co'
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_KEY')

if not SUPABASE_KEY:
    print("Error: SUPABASE_SERVICE_ROLE_KEY required")
    sys.exit(1)

# Read migration SQL
with open('migrations/001_codicen_enrichment_attempts.sql') as f:
    sql = f.read()

print("Applying migration via Supabase Management API...")
print(f"SQL length: {len(sql)} characters")

# Use Supabase Management API to execute SQL
# https://supabase.com/docs/reference/api/query
url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"

try:
    client = httpx.Client(timeout=30.0)
    response = client.post(
        url,
        json={'query': sql},
        headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json',
        }
    )
    
    if response.status_code == 200:
        print("✓ Migration applied successfully")
        print(response.json())
    else:
        print(f"✗ Error applying migration: {response.status_code}")
        print(response.text)
        
        # Fallback: create table directly via Python
        print("\nFallback: Creating table via Python...")
        from supabase import create_client
        
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Create table using simpler approach
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS codicen_enrichment_attempts (
            id BIGSERIAL PRIMARY KEY,
            license_no TEXT NOT NULL,
            method TEXT NOT NULL CHECK (method IN ('candidate_fetch', 'jev', 'web_search', 'crawl', 'email_verify')),
            identifier TEXT,
            outcome TEXT NOT NULL,
            cost_micro INTEGER NOT NULL DEFAULT 0,
            attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata JSONB,
            CONSTRAINT unique_attempt UNIQUE (license_no, method, identifier, attempted_at)
        );
        
        CREATE INDEX IF NOT EXISTS idx_attempts_license_method ON codicen_enrichment_attempts(license_no, method);
        CREATE INDEX IF NOT EXISTS idx_attempts_method_identifier ON codicen_enrichment_attempts(method, identifier) WHERE identifier IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_attempts_attempted_at ON codicen_enrichment_attempts(attempted_at);
        """
        
        # Since Supabase doesn't expose raw SQL execution easily, we'll need to use database functions
        # or execute via psycopg2 if available
        try:
            import psycopg2
            
            # Extract connection details from Supabase URL
            # This is a workaround - in production, use Supabase SQL Editor or psql
            print("psycopg2 not configured for cloud agent environment")
            print("\nPlease apply migration manually:")
            print("1. Go to Supabase Dashboard > SQL Editor")
            print("2. Paste contents of migrations/001_codicen_enrichment_attempts.sql")
            print("3. Run the query")
            sys.exit(1)
            
        except ImportError:
            print("Cannot apply migration automatically in this environment")
            print("\nPlease apply migration manually:")
            print("1. Go to Supabase Dashboard > SQL Editor") 
            print("2. Paste contents of migrations/001_codicen_enrichment_attempts.sql")
            print("3. Run the query")
            sys.exit(1)

except Exception as e:
    print(f"Error: {e}")
    print("\nPlease apply migration manually via Supabase Dashboard SQL Editor")
    sys.exit(1)
