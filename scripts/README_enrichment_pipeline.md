# Codicen CSLB Enrichment Pipeline

Optimized, duplicate-proof pipeline for California CSLB contractor domain and email enrichment.

## Architecture

### Attempts Ledger (`codicen_enrichment_attempts`)

Prevents duplicate work by recording every enrichment attempt per company/method:

| Method | Identifier | Purpose |
|--------|-----------|---------|
| `candidate_fetch` | null | Clearbit/Hunter domain discovery |
| `jev` | domain | Jev domain identity verification |
| `web_search` | null | Web search for domains |
| `crawl` | domain | Crawl4AI email extraction |
| `email_verify` | email | MV/BB email verification |

**Skip logic**:
- Skip companies already attempted for a method
- Skip domains already Jev-checked (confirmed or rejected)
- Skip domains crawled or failed twice
- Skip emails in `pipeline_leads` within 30 days
- Skip emails in PlusVibe suppression list

### Pipeline Stages

1. **Discovery**: Free candidate domain discovery (Clearbit autocomplete, Hunter via Treg)
2. **Search**: Paid web search for remaining companies (~$0.00047/search)
3. **Fetch**: Free HTTP homepage + contact page fetching
4. **Verification**: Paid Jev identity verification (~$0.00008/check)
5. **Crawl**: Paid Crawl4AI email extraction (~$0.00015/domain)
6. **Email Verify**: Paid MV/BB email verification (~$0.0011-$0.004/email)

## Setup

### 1. Apply Migration

```bash
# Connect to Supabase and run migration
psql $DATABASE_URL < migrations/001_codicen_enrichment_attempts.sql
```

### 2. Backfill Attempts Ledger

```bash
# Dry-run to see counts
python3 scripts/backfill_enrichment_attempts.py --dry-run \
    --outcome-files /path/to/outcomes_*.jsonl

# Live backfill
python3 scripts/backfill_enrichment_attempts.py \
    --outcome-files /path/to/outcomes_6e5f.jsonl \
                   /path/to/outcomes_b20b.jsonl \
                   /path/to/outcomes_6a30.jsonl
```

Expected backfill counts (from prototypes):
- **Jev attempts**: ~25,000 (from codicen_domain_candidates + cslb_companies + outcome files)
- **Crawl attempts**: ~60 (from outcome files)
- **Email attempts**: ~230 (from pipeline_leads batches)

### 3. Required Environment Variables

Set in Cursor Cloud Agent Secrets:

```bash
SUPABASE_SERVICE_ROLE_KEY=eyJhbGc...  # Required
treg=sk_treg_...                        # Required for paid calls
SUPABASE_URL=https://npkd...supabase.co  # Optional, defaults to ZS Lead Database
```

## Usage

### Method 1: Candidate Verification (Existing Candidates)

Verify existing `codicen_domain_candidates` with Jev + crawl + email:

```bash
# Dry-run: see what would be processed
python3 scripts/enrich_cslb_domains.py --verify --limit 10 --max-spend-usd 1.00 --dry-run

# Live run with hard cap
python3 scripts/enrich_cslb_domains.py --verify --limit 100 --max-spend-usd 5.00

# Full run (all remaining candidates)
python3 scripts/enrich_cslb_domains.py --verify --max-spend-usd 50.00
```

**Performance** (from window pass prototype):
- **Throughput**: ~2,160 candidates/min (33,905 in 17 min)
- **Cost**: ~$0.38 per 10,915 companies → $0.00003/company avg
- **Yield**: ~1% confirmation rate (141 domains from 33,905 pairs)
- **Emails**: ~116 ready leads from 141 confirmed domains

### Method 2: Web Search (Companies Without Candidates)

Search Google for companies without candidates:

```bash
# Dry-run
python3 scripts/run_enrichment_pipeline.py --method web_search \
    --limit 10 --max-spend 1.00 --dry-run

# Live run
python3 scripts/run_enrichment_pipeline.py --method web_search \
    --limit 100 --max-spend 5.00
```

**Performance** (estimated with optimizations):
- **Baseline** (search pilot): 14 companies/min, 420 in 29.6 min
- **Target** (async+pipelined): 100+ companies/min, 10,000 in < 100 min
- **Cost**: ~$0.50 per 420 companies → $0.0012/company avg
- **Yield**: ~4% confirmation rate (17 domains from 420 companies)
- **Emails**: ~79 ready leads (72 from search snippets, 7 from crawl)

### Projected Full Run (Remaining ~10,354 Companies)

**After deduplication**:
- Web-search-attempted: 420 companies (from pilot)
- Candidate-verified: ~10,915 companies (from window pass)
- **Remaining eligible**: ~10,354 - (overlap) ≈ **~10,000 companies**

**Estimated optimized run**:
- **Time**: < 1 hour (100 companies/min)
- **Cost**: ~$12-15 for full run
- **Yield**: ~400 domains, ~800 ready emails

## Speed Optimizations

### Prototype Bottlenecks

1. **Serial batching**: Processed 40 companies, then blocked on verification
2. **Low concurrency**: 8 search workers, 12 fetch workers
3. **Synchronous verification**: Waited for MV/BB settlement before next batch

### Optimized Approach

1. **Async/await**: 100+ concurrent operations using `asyncio`
2. **Pipelined stages**: Search → fetch → jev → crawl → email can overlap
3. **Bulk writes**: Batch Supabase inserts (500 rows per chunk)
4. **Skip checks**: Query attempts ledger once, cache results
5. **Treg idempotency**: Safe retries without duplicate charges

**Measured improvements**:
- **Candidate verification**: 35 candidates/min → **2,160 candidates/min** (61x faster)
- **Web search** (estimated): 14 companies/min → **100+ companies/min** (7x faster)

## Crawl Coverage

### Current State (from prototypes)

**Window pass**:
- 141 domains confirmed
- 49 crawled (35% coverage)
- 47 had no email after crawl

**Search pilot**:
- 17 domains confirmed
- 8 crawled (47% coverage)

### Coverage Goals

1. **100% crawl of confirmed domains without free-page emails**
2. **Never recrawl**: Log every attempt in `codicen_enrichment_attempts`
3. **Report uncrawled**: Domains found via search but not Jev-confirmed

**Implementation**:
- Check `codicen_enrichment_attempts` for `method='crawl', identifier=domain`
- Skip if already crawled (success or failed twice)
- Record outcome immediately after crawl

## Hard Rules

- ✅ **Never spend** without checking attempts ledger first
- ✅ **Never overwrite** existing `cslb_companies.company_domain`
- ✅ **Never confirm** on city-only match (requires license or phone)
- ✅ **Never print** API keys or tokens
- ✅ **Never upload** to PlusVibe automatically
- ✅ **Never touch** `codicen_campaign_leads`
- ✅ **Hard spend cap** checked before every paid call (with reserve)
- ✅ **Jev thresholds** enforced per marker type

## Monitoring

### Real-time Stats

```bash
# Watch run log
tail -f /workspace/codicen_*/run.log

# Check Treg balance
curl -H "Authorization: Bearer $treg" https://api.treg.dev/balance
```

### Post-run Analysis

```sql
-- Attempts summary
SELECT method, outcome, COUNT(*), SUM(cost_micro)/1e6 AS cost_usd
FROM codicen_enrichment_attempts
GROUP BY method, outcome
ORDER BY method, outcome;

-- Crawl coverage
SELECT
  COUNT(*) AS confirmed_domains,
  COUNT(DISTINCT cea.identifier) AS crawled_domains,
  ROUND(100.0 * COUNT(DISTINCT cea.identifier) / COUNT(*), 1) AS crawl_pct
FROM cslb_companies cc
LEFT JOIN codicen_enrichment_attempts cea
  ON cea.method = 'crawl' AND cea.identifier = cc.company_domain
WHERE cc.company_domain IS NOT NULL;

-- Email yield by source
SELECT
  batch_id,
  COUNT(*) AS total_emails,
  COUNT(CASE WHEN status IN ('valid', 'ok', 'bounceban_deliverable') THEN 1 END) AS ready_emails,
  ROUND(100.0 * COUNT(CASE WHEN status IN ('valid', 'ok', 'bounceban_deliverable') THEN 1 END) / COUNT(*), 1) AS ready_pct
FROM pipeline_leads
WHERE batch_id LIKE 'codicen-%'
GROUP BY batch_id;
```

## Troubleshooting

### "Permission denied for table codicen_domain_candidates"

Use `SUPABASE_SERVICE_ROLE_KEY`, not anon key:

```bash
export SUPABASE_KEY="$SUPABASE_SERVICE_ROLE_KEY"
python3 scripts/enrich_cslb_domains.py --verify ...
```

### "Treg balance too low"

Check balance and add funds:

```bash
curl -H "Authorization: Bearer $treg" https://api.treg.dev/balance
# Add funds at https://treg.dev/dashboard
```

### "Spend limit reached"

Increase `--max-spend-usd`:

```bash
python3 scripts/enrich_cslb_domains.py --verify --limit 1000 --max-spend-usd 10.00
```

### Duplicate attempts despite ledger

Check backfill:

```bash
python3 scripts/backfill_enrichment_attempts.py --dry-run
```

## Files

```
scripts/
├── enrich_cslb_domains.py           # Main enrichment script (candidate verify)
├── run_enrichment_pipeline.py       # Async pipeline (web search)
├── backfill_enrichment_attempts.py  # Backfill attempts ledger
└── README_enrichment_pipeline.md    # This file

migrations/
└── 001_codicen_enrichment_attempts.sql  # Attempts ledger schema
```

## References

- [PR #37](https://github.com/agmediaaaaa/zs-ops2/pull/37) - Domain enrichment improvements
- Window pass results: `/uploads/FINAL_REPORT_8c4f.json`
- Search pilot results: `/uploads/FINAL_REPORT_e489.json`
- ZS Lead Database: https://npkdhahdvilcctjwzdlf.supabase.co
- Treg API: https://treg.dev
