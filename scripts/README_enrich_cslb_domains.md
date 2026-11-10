# CSLB Domain Enrichment Script

Automatically finds and verifies website domains for California State License Board (CSLB) contractor companies.

## Overview

This script operates in two phases:
1. **Discovery (free)**: Query Clearbit/Hunter APIs, save all candidates for review
2. **Verification (paid)**: Fetch webpages, check identity, run Jev classifier

All candidates are stored in `codicen_domain_candidates`. Only verified domains are written to `cslb_companies.company_domain`.

## Two-Phase Workflow

### Phase 1: Candidate Discovery (Free)

Uses free APIs to find domain candidates:
- **Clearbit Autocomplete** - Free, no key required
- **Hunter.io Domain Search** - Free tier available

**What it does:**
- Queries CLEAR companies in 90-day renewal window without domains
- Normalizes company names (strips LLC, INC, CORP, DBA, punctuation)
- Finds domains from Clearbit and Hunter
- Calculates name similarity scores (0.0-1.0)
- Saves ALL candidates to `codicen_domain_candidates` with `verification_status='pending'`
- Does NOT write to `cslb_companies.company_domain`

**Usage:**
```bash
# Test with 10 companies
python scripts/enrich_cslb_domains.py --limit 10 --dry-run

# Process 100 companies
python scripts/enrich_cslb_domains.py --limit 100

# Process all CLEAR companies in 90-day window
python scripts/enrich_cslb_domains.py

# Reprocess companies that already have candidates
python scripts/enrich_cslb_domains.py --refresh --limit 100
```

### Phase 2: Verification (Paid, Opt-In)

Verifies pending candidates using web scraping + AI classification:
1. Fetches homepage + one contact/about page
2. Checks for identity markers (license #, phone, or city+CA)
3. Calls Treg Jev classifier for contractor/California/identity probabilities
4. Applies calibrated thresholds based on which marker(s) matched
5. Marks candidates as confirmed/rejected
6. Writes only confirmed domains to `cslb_companies` with `domain_confidence='jev_confirmed'`

**Acceptance Criteria (calibrated on 200 companies):**
- **License match**: contractor≥0.65, CA≥0.60, identity≥0.65
- **Phone match**: contractor≥0.70, CA≥0.80, identity≥0.82
- **City+CA match**: contractor≥0.80, CA≥0.90, identity≥0.90

**Usage:**
```bash
# Test verification (dry run, no API calls or writes)
python scripts/enrich_cslb_domains.py --verify --max-spend-usd 5.00 --dry-run

# Verify 50 pending candidates (spend up to $5)
export TREG_API_KEY="your-key"
python scripts/enrich_cslb_domains.py --verify --max-spend-usd 5.00 --limit 50

# Verify more candidates (spend up to $50)
python scripts/enrich_cslb_domains.py --verify --max-spend-usd 50.00
```

## Database Tables

### cslb_companies
Main contractor table:
- `license_no` - CSLB license number (PK)
- `business_name` - Company name
- `business_phone` - Business phone (used for verification)
- `city`, `state` - Location
- `primary_status` - License status (must be 'CLEAR')
- `expiration_date_iso` - License expiration date
- `company_domain` - ✅ **Written only by verification step**
- `domain_source` - Source of domain (clearbit/hunter)
- `domain_confidence` - Confidence level ('jev_confirmed')

### codicen_domain_candidates
Stores all domain candidates:
- `license_no` - CSLB license number
- `company_name` - Company name
- `city` - City (for verification)
- `candidate_domain` - Found domain
- `source` - API source (clearbit/hunter)
- `candidate_name` - Company name returned by API
- `name_match_score` - Pure name similarity (0.0-1.0, no .com bonus)
- `verification_status` - pending/confirmed/rejected
- `verification_evidence` - JSON with reason, Jev scores, timestamp

## Command-Line Options

### Discovery Mode (Default)
```
--limit N              Process only N companies
--dry-run             Run without writing to database
--refresh             Reprocess companies that already have candidates
--hunter-api-key KEY  Hunter.io API key (optional)
```

### Verification Mode (--verify)
```
--verify                  Run verification instead of discovery
--max-spend-usd AMOUNT   Max spend in USD (required, unless --dry-run)
--limit N                Process only N candidates
--dry-run               Run without API calls or database writes
--treg-api-key KEY       Treg API key (required)
```

## Default Target Window

**Discovery mode filters:**
- `primary_status = 'CLEAR'`
- `expiration_date_iso` between today and today+90 days
- `company_domain IS NULL`
- Companies without existing candidates (unless `--refresh`)

This targets ~18,000-20,000 active contractors needing renewal outreach.

## Domain Exclusions

Directory and social sites are automatically excluded:
- yelp.com, facebook.com, instagram.com
- linkedin.com, bbb.org, houzz.com
- angi.com, angieslist.com, thumbtack.com
- yellowpages.com, buildzoom.com, mapquest.com
- homeadvisor.com, porch.com, nextdoor.com

## Identity Verification Logic

The verification step checks homepage + one contact/about page for:

1. **License match**: Exact CSLB license number on page
2. **Phone match**: Exact business phone in any format
3. **City+CA match**: City name + explicit "California" or "CA" within 50 chars

Must have at least one marker to proceed. Then calls Jev classifier and checks thresholds.

## Cost & Rate Limits

### Discovery (Free)
- **Clearbit**: 300 requests/minute (generous free tier)
- **Hunter**: 10 requests/minute (free tier, no key needed)
- **Cost**: $0

### Verification (Paid)
- **Jev classifier via Treg**: ~$0.00008 per check ($0.042/M input tokens)
- **Web scraping**: $0 (using plain HTTP, not Crawl4AI)
- **Reserve per request**: $0.0005 (held during call, released after settlement)
- **Example costs**:
  - 1,000 verifications: ~$0.08
  - 10,000 verifications: ~$0.80
  - 60,000 verifications: ~$5.00 (a $5 cap allows tens of thousands of checks)

## Environment Variables

```bash
# Required for both modes
export SUPABASE_KEY="your-service-role-key"

# Optional for discovery
export HUNTER_API_KEY="your-hunter-key"

# Required for verification (not dry run)
export TREG_API_KEY="your-treg-key"

# Optional
export SUPABASE_URL="https://npkdhahdvilcctjwzdlf.supabase.co"
```

## Example Workflows

### Initial Discovery Run
```bash
# 1. Test with dry run
python scripts/enrich_cslb_domains.py --limit 10 --dry-run

# 2. Process first 1000 companies
python scripts/enrich_cslb_domains.py --limit 1000

# 3. Review candidates in codicen_domain_candidates
```

### Verification Run
```bash
# 1. Test verification with dry run
export TREG_API_KEY="your-key"
python scripts/enrich_cslb_domains.py --verify --max-spend-usd 5.00 --dry-run --limit 10

# 2. Verify top 250 candidates (by score)
python scripts/enrich_cslb_domains.py --verify --max-spend-usd 5.00 --limit 250

# 3. Check confirmed domains in cslb_companies
```

### Full Production Run
```bash
# 1. Discover all candidates for CLEAR companies
python scripts/enrich_cslb_domains.py

# 2. Verify in batches (stay within spend limits)
python scripts/enrich_cslb_domains.py --verify --max-spend-usd 50.00

# Repeat step 2 as budget allows
```

## Output Examples

### Discovery Output
```
=== CSLB Domain Candidate Discovery (Free) ===
Mode: LIVE
Limit: 100
Refresh: No (skip companies with candidates)

Found 100 companies in query
Processing 100 companies

Inserting 156 candidates into codicen_domain_candidates...

======================================================================
FINAL REPORT
======================================================================
Companies processed:              100
Companies with new candidates:    87
Total new candidate pairs:        156

Clearbit API calls:               100
Hunter API calls:                 100
Errors:                           0

Elapsed time:                     94.3s
======================================================================
```

### Verification Output
```
=== CSLB Domain Verification (Paid) ===
Mode: LIVE
Max spend: $5.00
Limit: 250
Jev cost per call: $0.02

Found 250 pending candidates
Processing candidates (max spend: $5.00)...

[1/250] Verifying abcroofing.com for 12345...
  ✓ CONFIRMED: license_match+jev

[2/250] Verifying xyzplumbing.net for 67890...
  ✗ REJECTED: no_identity_markers

Spend limit reached: $5.00 / $5.00
Processed 250 candidates

======================================================================
FINAL REPORT
======================================================================
Candidates processed:             250
Candidates confirmed:             142
Candidates rejected:              108
Domains written to cslb_companies: 142

Jev API calls:                    250
Spend (USD):                      $5.00
Errors:                           0

Elapsed time:                     1847.2s
======================================================================
```

## Security Notes

- ❌ Never commit API keys to git
- ✅ Use environment variables for credentials
- ✅ Script never prints or logs API keys
- ✅ Use service role key only in trusted environments
- ✅ Verification requires explicit `--max-spend-usd` cap

## Troubleshooting

**"Error: supabase package not found"**
```bash
pip install -r requirements.txt
```

**"Error: Supabase key required"**
```bash
export SUPABASE_KEY="your-key-here"
```

**"Error: --max-spend-usd required for --verify"**
- Verification is opt-in and requires explicit spend cap
- Use `--dry-run` to test without spending

**"Hunter rate limit hit"**
- Normal with free tier (10 req/min)
- Script waits automatically
- Consider adding Hunter API key for better limits

**"Jev call failed"**
- Check TREG_API_KEY is set correctly
- Verify Treg account has credits
- Check network connectivity

**No candidates found**
- Check that companies have valid `business_name`
- Verify companies are in CLEAR status with 90-day window
- Use `--refresh` to reprocess companies with existing candidates

## Key Changes from v1

### ✅ What Changed
1. **Removed auto-write** based on name similarity alone
2. **Added verification step** with web scraping + Jev classifier  
3. **Split into two phases**: discovery (free) vs verification (paid)
4. **Added spend controls**: `--max-spend-usd` required for paid operations
5. **Improved filtering**: CLEAR status + 90-day window + skip existing
6. **Better scoring**: Name similarity for ranking, .com bonus for sort only
7. **Security**: Never prints API keys

### ❌ What Was Removed
- Automatic domain writes based on name score ≥0.75
- `--all-companies` flag (now always uses CLEAR + 90-day filter)

### 📊 Expected Results
Based on current data:
- **Discovery**: ~70-80% of companies get at least one candidate
- **Verification**: ~55-60% of candidates pass verification
- **Net result**: ~40-50% of companies get confirmed domains

## Related
- Builds on existing `codicen_domain_candidates` table (90,398+ existing pairs)
- Does NOT touch `codicen_campaign_leads` or PlusVibe
- Complements existing CSLB enrichment workflows
- Uses Treg Jev endpoint: `typesafe/jev-1.13`

## Support

For issues or questions:
1. Check `--help`: `python scripts/enrich_cslb_domains.py --help`
2. Review this README
3. Check Supabase logs for database errors
4. Check Treg dashboard for API usage/errors
5. Contact the data team
