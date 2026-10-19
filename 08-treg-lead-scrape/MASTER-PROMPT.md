# MASTER PROMPT — Treg Lead Scrape (Icypeas → Blitz)

**Paste this entire prompt at the start of any new chat when you want leads scraped via Treg.**

---

```text
You are running a cost-controlled B2B lead scrape for this repo (zs-ops2).

## 0. READ THIS REPO FIRST (NON-NEGOTIABLE)

Before Notion, Google Drive, Slack, Airtable, memory search, or any other MCP:

1. Read these files in order:
   - `.cursor/rules/lead-scrape.mdc`
   - `.cursor/skills/lead-scrape-gates/SKILL.md`
   - `docs/waterfall-cost-matrix.md`
   - `08-treg-lead-scrape/MASTER-PROMPT.md` (this playbook)
   - Existing runners under `scripts/` that match the campaign
     (e.g. `pilot_icypeas_blitz_four_verticals.py`, `mars_scrape_icypeas.py`,
     `atc_np_pa_list_builder.py`, `gws_list_builder.py`, `treg_pricing.py`)

2. Do NOT dig Notion / Drive / Slack / Airtable for scrape SOPs, filters, or
   “how we scrape.” Those are distractions. The GitHub repo is the source of truth.
   Only touch PlusVibe / Supabase when you need live exclude lists or upload —
   and only after the query + cost plan are clear.

3. If something is missing (ICP filters, volume, client code, spend cap), ASK ME.
   Do not invent spend caps. Do not start paid Treg calls to “figure it out.”

## 1. WHAT TREG IS

Treg (`treg.to`) is a multi-provider API gateway. One token, many backends.

- Call shape: `POST https://treg.to/call/{endpoint}` with header `X-Treg-Token`
- Cost header: `X-Treg-Cost-Micro` (÷ 1e6 = USD)
- Docs: `https://treg.to/llms.txt`
- Secret / env: `treg` or `TREG_TOKEN`
- Setup: `scripts/setup-treg.sh` then `treg balance`

We do NOT freestyle paid `/call/` loops. Prefer repo runners with
`--scope-only`, `--estimate`, and `--confirm-spend`.

## 2. DEFAULT PATHWAY (LOCKED — CHEAP SCRAPE METHOD)

This is the proven cheap path (~$2–2.5 per 1,000 ready emails when filters are tight):

| Stage | Tool | Endpoint | Notes |
|-------|------|----------|-------|
| A. Free TAM | Icypeas count | `icypeas.people.search.count` | $0 — always first |
| B. Discover | Icypeas people | `icypeas.people.search` | ~$0.00038 / returned row |
| C. Cost skip | Supabase | Lead Database / cache | Skip known LinkedIn / email / domain |
| D. Email find | Blitz | `blitzapi.people.email.find` | ~$0.000495 / success; needs LinkedIn |
| E. Verify (optional) | MillionVerifier | `millionverifier.people.email.verify` | After path is proven; never burn pilot on bad MV format |
| F. Upload | Supabase + list_id | bulk upsert | Never row-by-row for 100+ leads |

### Email route headers (required on Blitz / find calls)

```
X-Treg-Route-Max-Cost: 0.01
X-Treg-Route-Waterfall: 0
X-Treg-Route-Exclude: aiark,icypeas
```

### Hard bans (unless I explicitly opt in)

- Do NOT use Icypeas for email find / `icypeas.bulk.search` (use `--with-icypeas-email` only if I ask)
- Do NOT use AI Ark (`X-Treg-Route-Exclude` must include `aiark`)
- Do NOT use ContactOut verify for volume (free but 429-bound; wall-clock killer)
- Do NOT use QuickEnrich / Trykitt / Leadsforge as the default path when LinkedIn + company desc are available from Icypeas
- Do NOT keep paging until N “ready emails” — Pull-N means pull N people, enrich that batch only

## 3. EXCLUSIONS — IN THE INITIAL ICYPEAS QUERY (NOT AFTER)

Icypeas bills per returned row. Post-filtering junk after search = paying for trash.
Put excludes IN the query before any paid search.

### Required in-query excludes

1. **Job title include + exclude**
   - `currentJobTitle.include` = ICP titles only
   - `currentJobTitle.exclude` = VP, Vice President, Assistant, Sales, Marketing, HR,
     Engineer, Intern, Student, Retired, Former, Consultant, Advisor, Board Member,
     and any other junk for this ICP
   - Keep a free local `TITLE_REJECT_RE` as a safety net only

2. **Domain / company website exclude**
   - `currentCompanyWebsite.exclude` = existing prospect / PlusVibe / client company domains
   - Load from PlusVibe workspace + Supabase before search
   - Normalize to bare host (no `https://`, no `www.`)

3. **Keyword exclude**
   - `keyword.exclude` = staffing, recruiting, SaaS, software, consulting firm, etc.
     (campaign-specific)

4. **Headcount / geo / industry** as required for the ICP
   - Use flat dotted keys: `currentCompany.headcount` (nested `currentCompany: {headcount}` fails)

### Pre-email skips (free, after search returns)

- Skip LinkedIn URLs already in PlusVibe / Supabase / exclude seed (before Blitz)
- Skip known emails; skip freemail (gmail/yahoo/hotmail/outlook) after find
- Never Blitz a LinkedIn you already own

### Suppress vs cost-skip

- Supabase / Lead Database = **cost skip** (don’t pay to re-enrich)
- PlusVibe = **send suppress** for ready/upload (don’t email people already in the sequencer)
- Prefer exclude-before-search over suppress-after-spend

## 4. MANDATORY GATES (STOP AND ASK)

You MUST stop and ask me before any paid find/search beyond free counts.

### Gate sequence

1. **Clarify (ask me if missing)**
   - Client code (e.g. ATC, MARS, GWS, ZS)
   - ICP: titles, geo, headcount, industries, keywords include/exclude
   - Target: pull N people OR approximate ready volume
   - Required output fields (default: name, title, employee count, company desc, email, location, LinkedIn, company website)
   - Where to upload (Supabase list name, PlusVibe campaign?)

2. **Free TAM only**
   - Run `icypeas.people.search.count` (and company count if needed) with the FULL exclude query
   - Report TAM table per vertical / segment
   - If TAM collapses strangely after excludes, tell me — do not drop excludes to “make volume work”

3. **Catalog quote + cost plan**
   - Use `scripts/treg_pricing.py` and/or runner `--estimate` / `--scope-only`
   - Never invent flat averages like “$0.003/lead”
   - Present:
     - expected_usd
     - max_usd
     - recommended_cap_usd (≈ max × 1.4)
     - estimated $/1k ready (benchmark good path ≈ $2–2.5/1k)
   - Ask me: **“What hard cost cap should I use? Reply with `--confirm-spend <USD>`.”**

4. **Pilot first**
   - Small pull (e.g. 10–25 ready per vertical, or `--pull 50–100`)
   - Requires my explicit `--confirm-spend <USD>`
   - Report quote vs actual, ready/pulled, rows-per-ready, email-attempts-per-ready, quality sample

5. **Full volume only after new confirm**
   - New quote + new `--confirm-spend`
   - Live abort if `sum(X-Treg-Cost-Micro)` would exceed cap
   - Early-stop if unit economics die:
     - search rows / ready ≫ ~12
     - email attempts / ready ≫ ~4
     - $/1k ready ≫ ~$5–10
     → STOP, report, ask me. Do not broaden filters into my wallet.

### Spend rules

- “Just run it” / “scrape 2k” is NOT spend approval for full volume
- Never invent your own $10 / $12 / $14 caps
- Shared Treg wallet — check `treg balance` before every paid wave
- Report spend continuously; abort at hard cap

## 5. PULL-N MODEL (LOCKED)

When I say “100 prospects” / `--pull 100`:

| Means | Does NOT mean |
|-------|----------------|
| Pull 100 people from Icypeas (after title/ICP filter) | Keep searching until 100 ready emails |
| Enrich that fixed batch only | Page → enrich → page until ready target |
| Accept whatever emails validate from those 100 | Guarantee 100 emails |

Coverage = `ready / pulled` (ready < pulled is correct).

## 6. REQUIRED FIELDS

Every ready row must include (unless I waive):

- name, job_title, employee_count
- company_description (from Icypeas row — do not mark ready with empty desc if campaigns need it)
- email, location
- person_linkedin, company_name, company_website

If Icypeas didn’t return a company description, do not silently mark ready and later paid-backfill without asking.

## 7. UPLOAD / HANDOFF

- Bulk upload to Supabase (Lead Database + `lead_lists` / members). No per-lead upsert loops for 100+.
- Return: `list_id`, batch_id, ready count, spend, $/1k, coverage, TAM, exclude counts
- PlusVibe push only if I ask (`--upload-plusvibe` or equivalent)

## 8. ALWAYS REPORT

End every scope / pilot / full run with:

| Metric | Meaning |
|--------|---------|
| Scope / TAM | Free counts with excludes applied |
| Quote | Endpoint × volume × unit USD |
| Pulled | People from Icypeas (= N for pull-N) |
| Skipped known | Supabase / LI / domain / email skips |
| PlusVibe excluded | Already in sequencer |
| Ready | Valid email (+ desc if required) |
| Coverage | ready / pulled |
| Path used | Must be Icypeas → Blitz (default) |
| Spend | Actual vs expected / max / cap |
| Variance | actual − quoted_expected |
| Unit econ | rows/ready, email attempts/ready, $/1k |
| Handoff | list_id + artifact paths |

## 9. ANTI-PATTERNS (LEARNED FROM FAILED RUNS)

Banned:

1. Starting in Notion / Airtable / Drive / Slack instead of this GitHub repo
2. Paid Icypeas search without `currentJobTitle.exclude` + domain exclude in-query
3. Blitz before LinkedIn/email suppress against existing leads
4. Spending without my numeric `--confirm-spend`
5. Switching to Leadsforge / QuickEnrich / Trykitt mid-run without re-quote + re-confirm
6. Treating free TAM count as enrichment cost or as “people left”
7. Burning pilot budget on wrong MillionVerifier call format
8. Broadening filters after tiny yield instead of stopping to ask
9. Row-by-row Supabase uploads
10. Marking ready without company description when campaigns need it

Good reference economics (Cheap Scrape / ATC facility):
- ~3–5 Icypeas rows per ready
- ~1.5–2 Blitz attempts per ready
- ~$2.0–2.5 per 1,000 ready

If you are at ~$35–50/1k or 100+ rows/ready, you are doing it wrong — stop.

## 10. START NOW

1. Confirm you read the repo files in §0
2. Ask me any missing ICP / volume / client / cap questions
3. Propose the Icypeas query (include + exclude) for my approval
4. Run free TAM (`--scope-only` / `.count`) and show the table
5. Show the cost quote and ask for `--confirm-spend <USD>`
6. Wait for my confirm before any paid search or email find
```

---

## How to use

1. Open a **new** Cursor cloud/desktop agent on **this repo** (`agmediaaaaa/zs-ops2`).
2. Paste the fenced prompt above as the first message.
3. Fill in your ICP in the follow-up (or include it under the paste):
   - Client, titles, geo, headcount, industries, keywords
   - Target volume
   - Any extra domain/title excludes
4. Wait for free TAM + cost quote, then reply with e.g. `--confirm-spend 2.50` for a pilot.

## Companion files (agents must load these)

| File | Role |
|------|------|
| `.cursor/rules/lead-scrape.mdc` | Always-on rule for scrape chats in this repo |
| `.cursor/skills/lead-scrape-gates/SKILL.md` | Hard gates + Pull-N + tool order |
| `docs/waterfall-cost-matrix.md` | Catalog rates / billing units |
| `scripts/treg_pricing.py` | Catalog quote helper (when present on branch) |
| `scripts/pilot_icypeas_blitz_four_verticals.py` | Cheap Scrape reference runner |
| `scripts/mars_scrape_icypeas.py` | Mars runner with in-query title/domain excludes |
| `scripts/atc_np_pa_list_builder.py` | ATC reference with PlusVibe suppress |

## One-liner kickoff (after the master prompt is pasted)

```text
Client: <CODE>
ICP: US, headcount 5–100, titles <...>, industries/keywords <...>
Exclude: PlusVibe workspace + existing Lead Database domains/LinkedIns
Need: name, title, employee count, company desc, email, location
Target: pilot first (~10–25 ready), then discuss full volume
Path: Icypeas people.search → Blitz email.find only
Do free TAM + quote, then ask me for --confirm-spend. Do not spend yet.
```
