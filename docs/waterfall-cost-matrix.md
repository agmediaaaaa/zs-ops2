# Treg waterfall cost matrix (Cheap Scrape defaults)

Catalog rates from `treg catalog get` (verify live before quoting).  
Rule: **quote from catalog × planned volume**, never invent flat “$/lead” averages.

## Default pathway (locked)

| Stage | Endpoint | Billing unit | Catalog USD (verify) | Notes |
|-------|----------|--------------|----------------------|-------|
| Free TAM | `icypeas.people.search.count` | — | **free** | Always first; full exclude query |
| Discover | `icypeas.people.search` | /result returned | **$0.00038** | `pagination.size` is the price dial (max 200) |
| Email find | `blitzapi.people.email.find` | /success | **$0.000495** | Misses free; needs LinkedIn URL |
| Verify (optional) | `millionverifier.people.email.verify` | /success | **$0.00178** | After path proven; not on first pilot |

### Blitz / find route headers (required)

```
X-Treg-Route-Max-Cost: 0.01
X-Treg-Route-Waterfall: 0
X-Treg-Route-Exclude: aiark,icypeas
```

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
