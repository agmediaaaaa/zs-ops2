# Zillion Systems Lead-List Pipeline

B2B lead scrape pipeline via Treg API → Supabase Lead Database.

## Pipeline Architecture (Oct 30, 2026)

### Enforced Sourcing Path: LeadsForge → Icypeas → Blitz

**The ONLY supported people-sourcing workflow:**

```
1. LeadsForge people search (free count, then paginated search)
   ├─ treg endpoint: leadsforge.people.search
   ├─ cost: varies by query complexity, includes free count
   └─ outputs: first name, last name, company domain
   
2. Icypeas exact-person match (batched by name+domain)
   ├─ treg endpoint: icypeas.people.search  
   ├─ cost: ~$0.00038/row returned
   ├─ batch: ~25 people per query (firstname/lastname/domain arrays)
   └─ outputs: LinkedIn URL, headline, job title, company profile
   
3. Always-On Suppression Check (**MANDATORY**, separate from NOFILTER)
   ├─ LinkedIn URL suppression (from Supabase + PlusVibe)
   ├─ Email suppression (after finding)
   └─ must never be disabled by any config flag
   
4. Supabase Pipeline Leads Cache (30-day reuse window)
   ├─ skip enrichment for emails updated within 30 days
   ├─ reuse valid/bounceban_deliverable statuses
   └─ cost skip = $0
   
5. Pattern Email Generation + ContactOut Verify (best effort, free)
   ├─ generate f.l@domain and f@domain patterns
   ├─ treg endpoint: contactout.people.email.verify
   ├─ short timeouts (skip on timeout/429, don't block)
   └─ cost: free tier, skip if rate-limited
   
6. Blitz Email Find (primary enrichment, ~$0.0005/hit)
   ├─ treg endpoint: blitzapi.people.email.find
   ├─ route headers: X-Treg-Route-Max-Cost: 0.01
   │                 X-Treg-Route-Waterfall: 0
   │                 X-Treg-Route-Exclude: aiark,icypeas
   └─ LinkedIn URL → email
   
7. Optional QuickEnrich/TryKitt Fallback (~$0.005/hit, config-gated)
   ├─ behind config switch: ENABLE_FALLBACK_ENRICH=true
   ├─ per-run cap: MAX_FALLBACK_ENRICH_COUNT
   └─ only when Blitz fails
   
8. MillionVerifier + BounceBan
   ├─ millionverifier.people.email.verify (~$0.00178/success)
   ├─ bounceban.people.email.verify for catch-alls
   └─ async polling (never blocks other workers)
   
9. Bulk Supabase Upload
   ├─ pipeline_leads table (upsert by LinkedIn/email)
   └─ lead_lists attachment (list_id + batch_id)
```

### Critical Design Principles

1. **Concurrency & Speed**: Run ~70-75 ready leads/min
   - Per-provider worker pools with configurable limits
   - Pipeline enrichment per-person (not sequential batches)
   - ContactOut: best-effort with short timeout, skip on slow response
   - Catch-all/BounceBan polling: never blocks other workers
   
2. **Always-On Suppression**: Separate `SUPPRESS` flag
   - LinkedIn URL check before any enrichment
   - Email check after finding
   - MUST NOT be disabled by NOFILTER or any other setting
   - Fail loudly if suppression sets are empty
   
3. **Never Pay Twice**: Dedupe and cache
   - Check Supabase 30-day cache before any paid step
   - Cache all provider results (success and failure)
   - Never call a paid endpoint twice for same person
   
4. **Economic Gates**
   - Free LeadsForge + Icypeas count first (TAM)
   - Catalog quote before spend confirmation
   - Hard cap enforcement at runtime
   - Early-stop if economics fail (~>$5-10/1k ready, ≫12 search rows/ready, ≫4 email attempts/ready)

## Removed/Disabled Paths

### ❌ Direct Icypeas → Blitz (REMOVED)

The following workflow is **NO LONGER SUPPORTED**:

- ~~`scripts/pilot_icypeas_blitz_four_verticals.py`~~ → disabled (refuses to run)
- Direct icypeas.people.search → blitzapi.people.email.find without LeadsForge
- Reason: LeadsForge provides better targeting and lower cost per ready lead

If you need to run an old Icypeas-direct workflow, you must migrate to LeadsForge → Icypeas.

## File Structure

```
/workspace
├── scripts/
│   ├── pilot_icypeas_blitz_four_verticals.py  # DISABLED - use unified_engine.py
│   ├── unified_engine.py                       # NEW: LeadsForge → Icypeas → Blitz
│   ├── treg_pricing.py                         # Cost calculator
│   └── ...
├── 08-treg-lead-scrape/
│   └── MASTER-PROMPT.md                        # Updated workflow documentation
├── docs/
│   └── waterfall-cost-matrix.md                # Updated cost matrix
├── .cursor/
│   ├── rules/lead-scrape.mdc                   # Always-on scrape rules
│   └── skills/lead-scrape-gates/SKILL.md       # Gates and controls
└── README.md                                    # This file
```

## Usage

### Quick Start: Scope + Pilot

```bash
# 1. Free TAM count
python scripts/unified_engine.py --client ZS --scope-only --exclude-json suppress.json

# 2. Review TAM, then pilot (requires explicit spend approval)
python scripts/unified_engine.py --client ZS --pilot --confirm-spend 2.50 --exclude-json suppress.json

# 3. Review pilot economics, then full run
python scripts/unified_engine.py --client ZS --full 1000 --confirm-spend 45.00 --exclude-json suppress.json
```

### Configuration

Environment variables:
- `TREG_TOKEN`: Treg API token (or `~/.treg/config.json`)
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_KEY`: Supabase service key
- `PLUSVIBE_API_KEY`: PlusVibe workspace API key (optional)
- `NWORK`: Worker pool size (default: 64)
- `ENABLE_FALLBACK_ENRICH`: Enable QuickEnrich/TryKitt fallback (default: false)
- `MAX_FALLBACK_ENRICH_COUNT`: Cap fallback calls per run (default: 100)

### Dry-Run / Test Mode

```bash
# Test without spending (mocks paid calls)
python scripts/unified_engine.py --client TEST --scope-only --dry-run
```

## Cost Benchmarks

| Metric | Good | Stop & Ask |
|--------|------|-----------|
| Search rows / ready | 3-5 | >12 |
| Email attempts / ready | 1.5-2 | >4 |
| Cost / 1k ready | $2.0-2.5 | >$5-10 |

## Migration Guide

### From Icypeas-Direct

If you have existing Icypeas-direct configs:

1. Extract title/keyword/industry filters from Icypeas query
2. Map to LeadsForge query schema (see `build_lf_queries.py`)
3. Map industries using `ind_map.json`
4. Run new unified_engine.py with `--scope-only` first

### Industry Mapping

LeadsForge uses different industry names than Icypeas. Use the provided `ind_map.json`:

```json
{
  "Accounting": "accounting",
  "Insurance": "insurance",
  "Software Development": "software development",
  ...
}
```

## References

- Treg docs: `https://treg.to/llms.txt`
- Waterfall cost matrix: `docs/waterfall-cost-matrix.md`
- Master prompt: `08-treg-lead-scrape/MASTER-PROMPT.md`
- Gates skill: `.cursor/skills/lead-scrape-gates/SKILL.md`
