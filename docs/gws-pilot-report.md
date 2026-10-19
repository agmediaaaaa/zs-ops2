# GWS Treg pilot report

**batch_id:** `gws-pilot-20261017-172238-9b8b15fa`  
**mode:** pilot (10 ready × 8 campaigns)  
**confirm_spend_usd:** $3.00  
**spent_usd:** $0.4515 (balance 9.92 → 9.47)  
**ready_total:** 80 / searched 120 (coverage 0.6667)  

## Sheet handoff

[GWS Pilot 2026-10-17 All Found (batch gws-pilot-20261017-172238-9b8b15fa)](https://docs.google.com/spreadsheets/d/1tqLmo4vm8CIyQo3x-kJY2hiUvYxTvBbIQhcFPEplH_I/edit) — 120 all-found rows, Campaign column A1–C.

## Supabase

- project: `npkdhahdvilcctjwzdlf`
- table: `pipeline_leads` where `batch_id = 'gws-pilot-20261017-172238-9b8b15fa'`
- handoff_status: `sheet` (120 rows)
- Plusvibe ready filter: `plusvibe_ready = true AND campaign_id = '…'`

## Per-campaign

| Campaign | Searched | Ready | Coverage | Plusvibe excl | Spent |
|----------|----------|-------|----------|---------------|-------|
| A1 | 18 | 10 | 0.5556 | 0 | $0.0000 |
| A2 | 12 | 10 | 0.8333 | 0 | $0.0629 |
| A3 | 16 | 10 | 0.625 | 0 | $0.0671 |
| A4 | 18 | 10 | 0.5556 | 1 | $0.0715 |
| A5 | 16 | 10 | 0.625 | 0 | $0.0661 |
| B1 | 13 | 10 | 0.7692 | 0 | $0.0613 |
| B2 | 13 | 10 | 0.7692 | 0 | $0.0610 |
| C | 14 | 10 | 0.7143 | 0 | $0.0616 |

## Tool order

- People: leadsforge.people.search
- Email: extract_or_trykitt.people.email.find, millionverifier.people.email.verify

## Quality note

Leadsforge title/keyword matching is loose — many VP / off-niche titles in pilot. Tighten title filters before full 8–10k.

## Next gate

Full volume needs a new spend confirm after this report.
