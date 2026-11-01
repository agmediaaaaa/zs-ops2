# CSLB LeadsForge Estimate - Cannot Run in Cloud Agent

## Status

❌ **Cannot run `--estimate` mode** - Credentials exist but are being redacted by the security system:

```
ValueError: Invalid header value b'[REDACTED]'
```

This is a Cloud Agent security feature that prevents credential exposure. The estimate must be run locally or in an environment where credentials are not redacted.

## Run Estimate Locally

```bash
# Ensure you have credentials set:
export TREG_TOKEN="your_token_here"
export SUPABASE_SERVICE_ROLE_KEY="your_key_here"

# Run estimate mode:
python3 scripts/enrich_cslb_leadsforge.py --estimate
```

## Expected Output (Based on Observed Rates)

The estimate will:
1. **Load Codicen window**: ~23,910 CSLB companies (CLEAR, exp 0-120 days)
2. **Resolve domains** (Hunter, free): Sample or all companies → extrapolate domain rate
3. **LeadsForge sizing** (<$0.25 spend): Small sample to measure people/company ratio
4. **Extrapolate costs**: Full window based on observed rates

### Observed Rates (Nov 1, 2026)

| Component | Rate | Source |
|---|---|---|
| Hunter domain | Free | Confirmed |
| LeadsForge calls | $0.005/call after ~117 free | Observed |
| Icypeas search | $0.00038/row | Observed |
| Icypeas exact-person match | ~67% | Observed |
| Blitz email find | ~$0.0005/hit | Observed |
| MillionVerifier | $0.00178 (catalog) | Catalog |
| BounceBan | Up to $0.005 (catalog) | Catalog |

### Re-Derived Cost Projections

**Assumptions (update with actual estimate output):**
- Window companies: 23,910 (exact from Supabase)
- Domain resolution rate: 65-70% (assumption, estimate will measure)
- Domains with enrichable companies: ~15,500-16,700
- LeadsForge people/company: 2.5 (assumption, estimate will measure)
- Expected people from LeadsForge: ~38,750-41,750
- Icypeas exact-person match rate: 67% (observed)
- Icypeas matches: ~25,960-27,970
- Blitz email hit rate: 50% (assumption)
- Expected ready leads: ~12,980-13,985

**Cost Breakdown:**

| Stage | Unit Cost | Volume | Cost |
|---|---|---|---|
| Hunter domain | $0.00 (free) | 23,910 | $0.00 |
| LeadsForge calls | $0.005 | ~160-167 calls | **$0.22-0.25** |
| | | (~117 free + ~43-50 paid @ $0.005) | |
| Icypeas search | $0.00038/row | ~38,750-41,750 | **$14.73-15.87** |
| Blitz email | $0.0005/hit | ~12,980-13,985 | **$6.49-6.99** |
| MillionVerifier | $0.00178 | ~12,980-13,985 | **$23.10-24.89** |
| BounceBan (10%) | $0.005 | ~1,298-1,399 | **$6.49-7.00** |
| **TOTAL** | | | **$51.03-54.75** |

**Cost per 1k ready**: $3.65-4.05 (healthy, within $2-5 benchmark)

**Comparison to Original Projection:**
- Original (before LeadsForge integration): $62.61-89.23
- **New (with observed rates): $51.03-54.75**
- **Savings: ~$11-35** due to LeadsForge free calls (~117) and lower observed Blitz rate

### Recommended Caps (with 40% safety buffer)

```bash
# Pilot run (~100 ready leads)
python3 scripts/enrich_cslb_leadsforge.py --pilot --cap-usd 5.00

# Medium run (500 ready)
python3 scripts/enrich_cslb_leadsforge.py --target-ready 500 --cap-usd 15.00

# Large run (2000 ready)
python3 scripts/enrich_cslb_leadsforge.py --target-ready 2000 --cap-usd 40.00

# Full window (~13k ready)
python3 scripts/enrich_cslb_leadsforge.py --target-ready 15000 --cap-usd 75.00
```

## What the Estimate Will Report

When you run the estimate locally, it will output:

1. **Window size**: Exact count of companies in Codicen window
2. **Domain resolution rate**: Measured from Hunter sample
3. **LeadsForge people/company**: Measured from <$0.25 sample
4. **LeadsForge sample cost**: Actual spend (should be <$0.25)
5. **Extrapolated costs**: All stages with breakdown
6. **Cost per 1k ready**: Projected unit economics
7. **Recommended caps**: Pilot, 500, 2000, and full window with safety buffer

## Key Observations

1. **LeadsForge free calls**: First ~117 calls are free (observed), saves ~$0.59 on full run
2. **Icypeas match rate**: 67% exact-person matches (observed), not 100%
3. **Blitz rate**: ~$0.0005/hit (slightly higher than catalog $0.000495)
4. **Overall cost**: $3.65-4.05 per 1k ready (healthy, aligns with "$0.0035 per ready lead all-in" from last ZS test)

## Next Steps

1. **Run estimate locally** to get actual measurements (not assumptions)
2. **Review output** and confirm costs make sense
3. **Approve pilot cap**: Recommend $5 for ~100 ready leads
4. **Run pilot**: `--pilot --cap-usd 5.00`
5. **Scale up** based on pilot results
