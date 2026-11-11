# Migration Steps for Codicen Enrichment Pipeline

## Manual Migration Required

The `codicen_enrichment_attempts` table cannot be created programmatically via Supabase Python client in this environment.

### Apply Migration via Supabase Dashboard

1. Go to https://supabase.com/dashboard/project/npkdhahdvilcctjwzdlf
2. Click **SQL Editor** in left sidebar
3. Click **New Query**
4. Copy-paste contents of `migrations/001_codicen_enrichment_attempts.sql`
5. Click **Run** (or Cmd/Ctrl+Enter)
6. Verify: Query should return "Success. No rows returned"

### Verify Migration Applied

```bash
python3 -c "
from supabase import create_client
import os
supabase = create_client(
    'https://npkdhahdvilcctjwzdlf.supabase.co',
    os.environ['SUPABASE_SERVICE_ROLE_KEY']
)
result = supabase.table('codicen_enrichment_attempts').select('id').limit(1).execute()
print(f'✓ Table exists! {len(result.data)} rows')
"
```

### Then Run Backfill

```bash
python3 scripts/backfill_enrichment_attempts.py \
    --outcome-files /home/ubuntu/.cursor/projects/agent-repos-zs-ops2/uploads/outcomes_*.jsonl
```

## Why Manual Step Required

- Supabase Python client (`supabase-py`) doesn't expose raw SQL execution
- `psql` not available in cloud agent environment
- Security: Supabase REST API doesn't allow arbitrary DDL for good reason
- DDL requires database owner privileges, not just service role

## Alternative: Docker/Local Development

If running locally with Docker:

```bash
docker run --rm -it -v $(pwd):/work postgres:15 psql "$DATABASE_URL" < migrations/001_codicen_enrichment_attempts.sql
```
