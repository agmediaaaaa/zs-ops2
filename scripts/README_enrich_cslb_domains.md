# CSLB Domain Enrichment Script

Automatically finds website domains for California State License Board (CSLB) contractor companies using free API lookups.

## Overview

This script enriches the `cslb_companies` table with company domains by querying:
- **Clearbit Autocomplete API** (free, no key required)
- **Hunter.io Domain Search** (free tier available)

All candidate domains are saved to `codicen_domain_candidates` for review. Only high-confidence matches are automatically written to `cslb_companies.company_domain`.

## Database Tables

### cslb_companies
Main contractor table with columns:
- `license_no` - CSLB license number (PK)
- `business_name` - Company name
- `city`, `state` - Location
- `company_domain` - Confirmed company website (enriched by this script)
- `domain_source` - Source of domain (clearbit/hunter)
- `domain_confidence` - Confidence level (high/medium/low)

### codicen_domain_candidates
Stores all domain candidates for review:
- `license_no` - CSLB license number
- `company_name` - Company name from lookup
- `candidate_domain` - Found domain
- `source` - API source (clearbit/hunter)
- `candidate_name` - Company name returned by API
- `name_match_score` - Similarity score (0.0-1.0)
- `verification_status` - pending/verified/rejected

## Usage

### Quick Start

```bash
# Install dependencies
pip install supabase

# Set environment variables
export SUPABASE_KEY="your-supabase-service-key"
export HUNTER_API_KEY="your-hunter-key"  # Optional

# Test with 10 companies (dry run)
python scripts/enrich_cslb_domains.py --limit 10 --dry-run

# Process 100 companies
python scripts/enrich_cslb_domains.py --limit 100

# Process all companies in 90-day renewal window
python scripts/enrich_cslb_domains.py
```

### Command-Line Options

```
--limit N              Process only N companies (default: all)
--dry-run             Run without writing to database
--all-companies       Process all companies, not just 90-day window
--supabase-url URL    Supabase project URL (default: ZS Lead Database)
--supabase-key KEY    Supabase service role key (required)
--hunter-api-key KEY  Hunter.io API key (optional)
```

## How It Works

### 1. Company Name Normalization
Business names are normalized before lookup:
- Strips: LLC, INC, CORP, DBA, etc.
- Removes punctuation
- Normalizes whitespace

Example: `"ABC ROOFING, INC."` → `"ABC ROOFING"`

### 2. API Lookups
For each company:
- **Clearbit**: Queries company name
- **Hunter**: Queries company name + city/state (if CA)

### 3. Candidate Scoring
Each candidate is scored based on:
- **Name similarity**: Uses SequenceMatcher (0.0-1.0)
- **TLD bonus**: .com domains get +0.05
- **Exclusions**: Filters out yelp.com, facebook.com, bbb.org, etc.

### 4. High-Confidence Matching
A domain is written to `cslb_companies` only if:
- Name similarity ≥ 0.75 (75% match)
- Domain not in exclusion list

All other candidates go to `codicen_domain_candidates` for manual review.

## Rate Limits

- **Clearbit**: 300 requests/minute (generous free tier)
- **Hunter**: 10 requests/minute (free tier without API key)

The script automatically throttles to respect these limits.

## Domain Exclusions

These domains are automatically excluded (low-quality directory sites):
- yelp.com, facebook.com, linkedin.com
- bbb.org, houzz.com, angi.com
- yellowpages.com, buildzoom.com
- thumbtack.com, homeadvisor.com
- And more...

## Output

The script provides a detailed report:

```
=============================================================
FINAL REPORT
=============================================================
Companies processed:              1000
Companies with new candidates:    842
Total new candidate pairs:        1,523
Domains written to cslb_companies: 614
Companies still without domain:   386

Clearbit API calls:               1000
Hunter API calls:                 1000
Errors:                           0

Elapsed time:                     185.3s
=============================================================
```

## Error Handling

- **API failures**: Logged but don't stop the process
- **Rate limiting**: Automatic backoff
- **Invalid data**: Skipped with warning
- **Database errors**: Logged per-batch

## Examples

### Test Mode (No DB Writes)
```bash
python scripts/enrich_cslb_domains.py --limit 5 --dry-run
```

### Small Batch
```bash
python scripts/enrich_cslb_domains.py --limit 500
```

### Full Run (90-Day Window)
```bash
# ~19,000 companies without domains in 90-day renewal window
python scripts/enrich_cslb_domains.py
```

### Process All Companies
```bash
# ~241,000 companies without domains total
python scripts/enrich_cslb_domains.py --all-companies
```

## API Keys

### Supabase (Required)
Get from: https://supabase.com/dashboard/project/npkdhahdvilcctjwzdlf/settings/api
- Use the `service_role` key (secret, server-side only)
- Store in environment: `export SUPABASE_KEY="..."`

### Hunter.io (Optional)
Get from: https://hunter.io/api-keys
- Free tier: 50 searches/month
- With API key: Better rate limits
- Without key: Works but slower
- Store in environment: `export HUNTER_API_KEY="..."`

## Security Notes

- Never commit API keys to git
- Use environment variables or command-line args
- The script does not log or print API keys
- Use service role key only in trusted environments

## Troubleshooting

**"Error: supabase package not found"**
```bash
pip install supabase
```

**"Error: Supabase key required"**
```bash
export SUPABASE_KEY="your-key-here"
```

**"Hunter rate limit hit"**
- Normal with free tier (10 req/min)
- Consider adding Hunter API key
- Or use `--limit` to process in smaller batches

**No domains found**
- Check that companies have valid `business_name`
- Try with `--dry-run` to see API responses
- Some companies may not have public websites

## Future Enhancements

Possible improvements:
- Add more domain sources (e.g., Google Search)
- Implement domain verification (HTTP checks)
- Add machine learning for better matching
- Support batch resume from last checkpoint
- Add Slack/email notifications for large runs

## Related Tables

- `cslb_companies` - Main contractor table
- `codicen_domain_candidates` - All domain candidates
- `codicen_campaign_leads` - Final lead list (not touched by this script)

## Support

For issues or questions:
1. Check the script's help: `python scripts/enrich_cslb_domains.py --help`
2. Review this README
3. Check Supabase logs for database errors
4. Contact the data team
