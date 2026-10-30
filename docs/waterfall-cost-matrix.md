# Treg waterfall cost matrix (Cheap Scrape defaults)

Catalog rates from `treg catalog get` (verify live before quoting).  
Rule: **quote from catalog × planned volume**, never invent flat “$/lead” averages.

## Default pathway (Oct 30, 2026: LeadsForge → Icypeas → Blitz)

**As of Oct 30, 2026, the ONLY supported people-sourcing path:**

| Stage | Endpoint | Billing unit | Catalog USD (verify) | Notes |
|-------|----------|--------------|----------------------|-------|
| Free TAM | `leadsforge.people.search` (count) | — | **free** | Free count first; full exclude query |
| Discover | `leadsforge.people.search` | varies | **varies** | Paginated search with suppression in-query |
| Exact match | `icypeas.people.search` | /result returned | **$0.00038** | Batched 25 people (firstname/lastname/domain arrays); match by name+domain |
| Pattern verify | `contactout.people.email.verify` | /success | **free tier** | Best effort; short timeout (3s); skip on 429 |
| Email find | `blitzapi.people.email.find` | /success | **$0.000495** | Misses free; needs LinkedIn URL |
| Fallback (opt) | `quickenrich.*` or `trykitt.*` | /hit | **$0.005** | Config-gated; per-run cap; only when Blitz fails |
| Verify | `millionverifier.people.email.verify` | /success | **$0.00178** | After email found |
| Catch-all | `bounceban.people.email.verify` | /success | **up to $0.005** | For MV catch_all results; async polling |

### Blitz / find route headers (required)

```
X-Treg-Route-Max-Cost: 0.01
X-Treg-Route-Waterfall: 0
X-Treg-Route-Exclude: aiark,icypeas
```

## Enrichment concurrency & speed (Oct 30, 2026)

**Target: ~70-75 ready leads/min**

### Per-provider worker pools:

| Provider | Workers | Timeout | Notes |
|----------|---------|---------|-------|
| ContactOut | 8 | 3s | Best effort; skip on timeout/429; don't block |
| Blitz | 32 | 60s | Primary enrichment; retry on 429 |
| Fallback | 4 | 45s | QuickEnrich/TryKitt; config-gated |
| MillionVerifier | 16 | 120s | After email found |

### Pipeline per person (not sequential batches):

```
Person → Cache check → Pattern+ContactOut (skip on slow) → Blitz → Fallback (if enabled) → MV → BB (async)
```

- As soon as a person fails one step, they go to the next
- Each provider has its own concurrency limit
- Rate limiting: backoff on 429, skip ContactOut on timeout
- Catch-all/BounceBan polling never blocks other workers
- Never call a paid step twice for the same person (dedupe + cache)

## Reference economics (tight filters)

When filters are good:

| Metric | Healthy | Stop / ask |
|--------|---------|------------|
| Icypeas rows / ready | ~3–5 | ≫ ~12 |
| Blitz attempts / ready | ~1.5–2 | ≫ ~4 |
| USD / 1k ready | ~$2.0–2.5 | ≫ ~$5–10 |

### Quote sketch (Pull-N)

For `--pull N` people (not “until N ready”):

```
search_usd   = N × $0.00038          # every returned row bills
email_usd    = (N × hit_rate) × $0.000495   # only successes bill; use prior hit_rate or 0.4–0.6
expected_usd = search_usd + email_usd
max_usd      = N × $0.00038 + N × $0.000495  # if every row finds email
recommended_cap_usd ≈ max_usd × 1.4
```

Coverage = `ready / pulled` (ready < pulled is correct).

## Hard bans (unless user opts in)

| Avoid | Why |
|-------|-----|
| `aiark.*` | Expensive; exclude via route header |
| Icypeas email find / bulk search | Not the cheap path |
| ContactOut verify for volume | Free but 429 / wall-clock |
| QuickEnrich / Trykitt / Leadsforge as default when Icypeas already returns LinkedIn + company desc | Re-quote + re-confirm if switching |

## Cost-skip vs suppress

| Source | Role |
|--------|------|
| Supabase (`Lead Database`, `email_cache`, `pipeline_leads`) | **Cost skip** — don’t pay to re-enrich |
| PlusVibe workspace | **Send suppress** — don’t mark ready / don’t sequence people already there |
| Domains from both | Put in `currentCompanyWebsite.exclude` **before** paid Icypeas search |

## Quote helper

```bash
python scripts/treg_pricing.py --pull 100 --hit-rate 0.45
python scripts/treg_pricing.py --endpoints icypeas.people.search,blitzapi.people.email.find
```

Re-check catalog if rates look stale:

```bash
treg catalog get icypeas.people.search
treg catalog get blitzapi.people.email.find
```

## Always-on suppression (Oct 30, 2026)

**Critical**: Suppression is now a separate `SUPPRESS` flag that **cannot be disabled** by `NOFILTER` or any other setting.

Bug fixed Oct 30: NOFILTER was silently disabling all suppression. New behavior:

- `SUPPRESS` flag is always checked (LinkedIn URLs + emails)
- Fails loudly if suppression sets are empty
- Counters track suppression hits separately from filtration
- LinkedIn suppression check happens before any enrichment
- Email suppression check happens after finding email
- Supabase cache check (30-day window) happens before any paid enrichment step
