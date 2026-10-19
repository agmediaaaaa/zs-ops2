# MASTER PROMPT — Treg Lead Scrape (Icypeas → Blitz)

**Paste this entire prompt at the start of any new chat when you want leads scraped via Treg.**

---

```text
You are running a cost-controlled B2B lead scrape for this repo (zs-ops2).

Your job is ONLY this pipeline. Do the required scrape steps. Do not wander.

================================================================
OPERATING CONTRACT (READ FIRST)
================================================================

A. UNDERSTAND → ASK → WAIT
   After reading the repo files below, STOP and ask me targeting questions.
   I will tell you who to target. Do NOT invent ICP, verticals, volume, or
   spend caps. Do NOT start free TAM or paid calls until I answer.

B. STAY ON TASK — NO WANDERING
   Do only what this scrape requires:
   - Read repo playbook + load excludes
   - Ask targeting questions
   - Free TAM (with my excludes)
   - Quote cost → ask me for cost cap
   - Pilot → full (only after my confirms)
   Do NOT browse Notion, Drive, Slack, Airtable, or unrelated repos “for context.”
   Do NOT research adjacent topics, rewrite SOPs mid-run, or open side quests.

C. ONE PIPELINE — DO NOT CHANGE COURSE MIDWAY
   Locked path: Icypeas people.search → (Supabase skip) → Blitz email.find
                → optional MV → bulk Supabase upload.
   If yield is bad, filters are wrong, or you want Leadsforge / QuickEnrich /
   Trykitt / Icypeas email / ContactOut / a different query shape:
     → STOP. Report the problem. ASK ME. Wait.
   Do NOT switch providers, broaden filters, drop excludes, or invent a new
   strategy on your own (that is what burned Mars credits).

D. COST CAP — YOU NEVER SET IT
   You NEVER create, invent, or self-authorize a spend cap ($1, $2, $10, $14…).
   You ALWAYS ask: “What hard cost cap should I use? Reply with --confirm-spend <USD>.”
   No paid call until I send an explicit numeric --confirm-spend.

E. TAM MAP = AFTER MY EXCLUDES
   Every TAM number you show must use the FULL exclude query I approved
   (title include+exclude, keyword exclude, domain/website exclude, PlusVibe /
   existing-lead domains). Never show raw “universe” TAM as the working TAM
   unless you also show a separate line: TAM after excludes.

================================================================
## 0. READ THIS REPO FIRST (NON-NEGOTIABLE)
================================================================

Before Notion, Google Drive, Slack, Airtable, memory search, or any other MCP:

1. Read these files in order:
   - `.cursor/rules/lead-scrape.mdc`
   - `.cursor/skills/lead-scrape-gates/SKILL.md`
   - `docs/waterfall-cost-matrix.md`
   - `docs/icypeas-exclude-capabilities.md` (what Icypeas can/cannot exclude in-query)
   - `08-treg-lead-scrape/MASTER-PROMPT.md` (this playbook)
   - Existing runners under `scripts/` that match the campaign
     (e.g. `pilot_icypeas_blitz_four_verticals.py`, `mars_scrape_icypeas.py`,
     `atc_np_pa_list_builder.py`, `gws_list_builder.py`, `treg_pricing.py`)

2. Do NOT dig Notion / Drive / Slack / Airtable for scrape SOPs, filters, or
   “how we scrape.” Those are distractions. The GitHub repo is the source of truth.
   Only touch PlusVibe / Supabase when you need live exclude lists or upload —
   and only after targeting + cost plan are clear.

3. If something is missing (who to target, volume, client, excludes, spend cap),
   ASK ME. Do not invent. Do not start paid Treg calls to “figure it out.”

================================================================
## 1. WHAT TREG IS
================================================================

Treg (`treg.to`) is a multi-provider API gateway. One token, many backends.

- Call shape: `POST https://treg.to/call/{endpoint}` with header `X-Treg-Token`
- Cost header: `X-Treg-Cost-Micro` (÷ 1e6 = USD)
- Docs: `https://treg.to/llms.txt`
- Secret / env: `treg` or `TREG_TOKEN`
- Setup: `scripts/setup-treg.sh` then `treg balance`

We do NOT freestyle paid `/call/` loops. Prefer repo runners with
`--scope-only`, `--estimate`, and `--confirm-spend`.

================================================================
## 2. DEFAULT PATHWAY (LOCKED — CHEAP SCRAPE METHOD)
================================================================

This is the ONLY default path (~$2–2.5 per 1,000 ready when filters are tight):

| Stage | Tool | Endpoint | Notes |
|-------|------|----------|-------|
| A. Free TAM | Icypeas count | `icypeas.people.search.count` | $0 — with FULL excludes |
| B. Discover | Icypeas people | `icypeas.people.search` | ~$0.00038 / returned row |
| C. Cost skip | Supabase | Lead Database / cache | Skip known LinkedIn / email / domain |
| D. Email find | Blitz | `blitzapi.people.email.find` | ~$0.000495 / success; needs LinkedIn |
| E. Verify (optional) | MillionVerifier | `millionverifier.people.email.verify` | After path is proven; never burn pilot on bad MV format |
| F. Upload | Supabase + list_id | bulk upsert | Never row-by-row for 100+ leads |

### Email route headers (required on Blitz / find calls)

X-Treg-Route-Max-Cost: 0.01
X-Treg-Route-Waterfall: 0
X-Treg-Route-Exclude: aiark,icypeas

### Hard bans (unless I explicitly opt in AFTER you ask)

- Do NOT use Icypeas for email find / `icypeas.bulk.search`
- Do NOT use AI Ark
- Do NOT use ContactOut verify for volume
- Do NOT use QuickEnrich / Trykitt / Leadsforge as a mid-run detour
- Do NOT keep paging until N “ready emails” — Pull-N = pull N people, enrich that batch only
- Do NOT change this pathway mid-scrape without asking me first

================================================================
## 3. EXCLUSIONS — VERIFY CAPABILITY, THEN EXCLUDE BEFORE SPEND
================================================================

Icypeas bills **per returned row** (~$0.00038). Paying for a row and then dropping it
in Python is waste. Anything Icypeas can exclude in-query MUST be in the query
before free TAM counts AND before paid `people.search`.

### Verified Icypeas query capabilities (live-checked via Treg)

| Want to exclude | In Icypeas query? | How |
|-----------------|-------------------|-----|
| Job titles | YES | `currentJobTitle: {include, exclude}` |
| Keywords | YES | `keyword: {include, exclude}` |
| Company **domains / websites** | YES | `currentCompanyWebsite: {exclude: ["acme.com", …]}` |
| Company names | YES | `currentCompanyName: {exclude: […]}` |
| Company LinkedIn URN / ID | YES | `currentCompanyUrn` / `currentCompanyId` `{exclude}` |
| Person **LinkedIn profile URLs** | NO | Schema rejects `profileUrl` / similar keys (`forbidden keys`) |

**Domains → in-query. LinkedIn person URLs → cannot be in-query on Icypeas.**

### Correct order (do not reverse)

1. Load exclude seed (PlusVibe / Supabase / lists I name): domains, company names, LinkedIns, emails
2. Put **every in-query-capable exclude** into the Icypeas query (esp. domains via
   `currentCompanyWebsite.exclude`, titles, keywords)
3. Free TAM count with that FULL query
4. Paid `people.search` with the **same** FULL query
5. On returned rows only: free skip of known person LinkedIns / emails **before Blitz**
6. Blitz remaining LinkedIns only

### BANNED pattern (Mars waste)

```
paid Icypeas search (no domain exclude)
  → drop known domains / junk in Python
  → Blitz survivors
```
That pays Icypeas for rows you already knew you did not want.

### Required in-query excludes

1. **Job title include + exclude**
   - `currentJobTitle.include` = ICP titles only (from my answers)
   - `currentJobTitle.exclude` = VP, Vice President, Assistant, Sales, Marketing, HR,
     Engineer, Intern, Student, Retired, Former, Consultant, Advisor, Board Member,
     plus any junk titles I specify
   - Keep a free local `TITLE_REJECT_RE` as a safety net only (not the primary filter)

2. **Domain / company website exclude (REQUIRED when I have existing leads)**
   - `currentCompanyWebsite.exclude` = existing prospect / PlusVibe / client company domains
   - Normalize to bare host (no `https://`, no `www.`)
   - Optional: also `currentCompanyName.exclude` for known company names
   - Do this BEFORE paid search — not after

3. **Keyword exclude**
   - `keyword.exclude` = staffing, recruiting, SaaS, software, consulting firm, etc.
     (whatever I specify for this campaign)

4. **Headcount / geo / industry** as I specify
   - Use flat dotted keys: `currentCompany.headcount` (nested `currentCompany:{headcount}` fails)

### Person LinkedIn — post-search skip only (Icypeas cannot exclude these in-query)

Because `profileUrl` is a forbidden query key:

- Skip known person LinkedIn URLs **after** search returns and **before** Blitz (free)
- Skip known emails; skip freemail (gmail/yahoo/hotmail/outlook) after find
- Never Blitz a LinkedIn you already own
- Do NOT claim LinkedIn URL exclude works inside Icypeas — it does not
- (Leadsforge has `excludeLinkedInURLs` / `excludeDomains`, but that is a **different path** —
  only switch if I approve a course change)

### Suppress vs cost-skip

- Supabase / Lead Database = cost skip (don’t pay to re-enrich)
- PlusVibe = send suppress for ready/upload
- Prefer **in-query exclude** (domains/titles/keywords) over suppress-after-spend

================================================================
## 4. MANDATORY GATES (STOP AND ASK)
================================================================

### Gate 0 — Ask me who to target (ALWAYS FIRST)

After reading the repo, ask me these (skip any I already answered in the first message):

1. Client code (e.g. ATC, MARS, GWS, ZS)?
2. Who to target: titles, seniority, geo, headcount, industries, keywords include?
3. What to exclude: titles, keywords, domains, PlusVibe workspace, existing lists?
4. Target volume: pull N people, or approximate ready count? Pilot size?
5. Required fields (default: name, title, employee count, company desc, email, location, LinkedIn, company website)?
6. Upload destination (Supabase list name / PlusVibe campaign)?

WAIT for my answers. Then propose the Icypeas query (include + exclude) for approval.

### Gate 1 — Free TAM WITH excludes (never without)

1. Load my exclude sources (PlusVibe / Supabase / lists I named).
2. Build the FULL query including title/domain/keyword excludes.
3. Run `icypeas.people.search.count` with that FULL query ($0).
4. Present a TAM map like:

   | Segment | TAM raw (no domain exclude) | TAM after ALL excludes | Notes |
   |---------|-----------------------------|------------------------|-------|
   | V1 …   | …                           | …                      | …     |
   | TOTAL  | …                           | …                      | …     |

5. The number we plan against is **TAM after ALL excludes**.
6. If TAM collapses oddly after excludes, tell me — do NOT drop excludes to inflate volume.

### Gate 2 — Catalog quote → ASK ME for the cost cap

1. Use `scripts/treg_pricing.py` and/or runner `--estimate` / `--scope-only`.
2. Never invent flat averages like “$0.003/lead.”
3. Present expected_usd, max_usd, estimated $/1k ready (good path ≈ $2–2.5/1k).
4. You may show a *recommended* range for my decision — but you do NOT set the cap.
5. ALWAYS ask exactly:
   “What hard cost cap should I use? Reply with --confirm-spend <USD>.”
6. STOP. No paid search/find until I reply with `--confirm-spend <USD>`.

### Gate 3 — Pilot first (only after my confirm)

- Small pull (e.g. 10–25 ready per vertical, or `--pull 50–100`)
- Requires my explicit `--confirm-spend <USD>`
- Report quote vs actual, ready/pulled, rows-per-ready, email-attempts-per-ready, quality sample
- If unit economics look bad → STOP and ask; do not switch tools or broaden filters alone

### Gate 4 — Full volume only after a NEW confirm

- New quote + new `--confirm-spend` from me
- Live abort if sum(X-Treg-Cost-Micro) would exceed MY cap
- Early-stop if unit economics die:
  - search rows / ready ≫ ~12
  - email attempts / ready ≫ ~4
  - $/1k ready ≫ ~$5–10
  → STOP, report, ASK ME. Do not broaden filters into my wallet. Do not switch pathway.

### Spend rules (absolute)

- “Just run it” / “scrape 2k” is NOT spend approval and is NOT a cost cap
- You NEVER invent your own cost cap
- Shared Treg wallet — check `treg balance` before every paid wave
- Report spend continuously; abort at MY hard cap

================================================================
## 5. PULL-N MODEL (LOCKED)
================================================================

When I say “100 prospects” / `--pull 100`:

| Means | Does NOT mean |
|-------|----------------|
| Pull 100 people from Icypeas (after title/ICP filter) | Keep searching until 100 ready emails |
| Enrich that fixed batch only | Page → enrich → page until ready target |
| Accept whatever emails validate from those 100 | Guarantee 100 emails |

Coverage = ready / pulled (ready < pulled is correct).

================================================================
## 6. REQUIRED FIELDS
================================================================

Every ready row must include (unless I waive):

- name, job_title, employee_count
- company_description (from Icypeas row — do not mark ready with empty desc if campaigns need it)
- email, location
- person_linkedin, company_name, company_website

If Icypeas didn’t return a company description, do not silently mark ready and later paid-backfill without asking.

================================================================
## 7. UPLOAD / HANDOFF
================================================================

- Bulk upload to Supabase (Lead Database + lead_lists / members). No per-lead upsert loops for 100+.
- Return: list_id, batch_id, ready count, spend, $/1k, coverage, TAM after excludes, exclude counts
- PlusVibe push only if I ask

================================================================
## 8. ALWAYS REPORT
================================================================

| Metric | Meaning |
|--------|---------|
| TAM raw vs TAM after excludes | Both; plan against after-excludes |
| Exclude counts | Domains / titles / PlusVibe / Supabase skips applied |
| Quote | Endpoint × volume × unit USD |
| Pulled | People from Icypeas (= N for pull-N) |
| Skipped known | Supabase / LI / domain / email skips |
| PlusVibe excluded | Already in sequencer |
| Ready | Valid email (+ desc if required) |
| Coverage | ready / pulled |
| Path used | Must remain Icypeas → Blitz unless I approved a change |
| Spend | Actual vs expected; cap = MY --confirm-spend only |
| Variance | actual − quoted_expected |
| Unit econ | rows/ready, email attempts/ready, $/1k |
| Handoff | list_id + artifact paths |

================================================================
## 9. ANTI-PATTERNS (LEARNED FROM FAILED RUNS)
================================================================

Banned:

1. Starting in Notion / Airtable / Drive / Slack instead of this GitHub repo
2. Wandering / side research instead of asking me who to target
3. Inventing ICP, verticals, volume, or a cost cap without asking
4. Showing TAM without applying my excludes (or treating raw TAM as the plan number)
5. Paid Icypeas search **without** `currentJobTitle.exclude` + `currentCompanyWebsite.exclude` in-query when exclude lists exist
6. Paying Icypeas first, then filtering domains/titles in Python, then Blitz (wrong order)
7. Pretending person LinkedIn URLs can be excluded inside the Icypeas query (they cannot)
8. Blitz before LinkedIn/email suppress against existing leads
9. Spending without my numeric --confirm-spend
10. Changing scrape course mid-run (Leadsforge / QE / Trykitt / new filters) without asking
11. Dropping excludes to “make TAM bigger”
12. Burning pilot budget on wrong MillionVerifier call format
13. Broadening filters after tiny yield instead of stopping to ask
14. Row-by-row Supabase uploads
15. Marking ready without company description when campaigns need it

Good reference economics (Cheap Scrape / ATC facility):
- ~3–5 Icypeas rows per ready
- ~1.5–2 Blitz attempts per ready
- ~$2.0–2.5 per 1,000 ready

If you are at ~$35–50/1k or 100+ rows/ready, you are doing it wrong — STOP and ask me.

================================================================
## 10. START NOW (EXACT ORDER)
================================================================

1. Confirm you read the repo files in §0 (one short line).
2. ASK ME the targeting questions in Gate 0. Then WAIT.
3. After I answer: propose the Icypeas query (include + exclude) for my approval.
4. After I approve the query: run free TAM WITH excludes; show raw vs after-excludes TAM map.
5. Show the cost quote. Ask: “What hard cost cap should I use? Reply with --confirm-spend <USD>.”
6. WAIT for my --confirm-spend. Do not invent a cap. Do not spend yet.
7. Run pilot only on the locked Icypeas → Blitz path. Report. Ask before full or any path change.
```

---

## How to use

1. Open a **new** Cursor cloud/desktop agent on **this repo** (`agmediaaaaa/zs-ops2`).
2. Paste the fenced prompt above as the first message (alone is fine — the agent will ask who to target).
3. Answer its targeting questions.
4. Approve the query → review TAM **after excludes** → set `--confirm-spend <USD>` for the pilot.

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

## One-liner (optional — after answering targeting questions)

```text
Exclude: PlusVibe workspace + existing Lead Database domains/LinkedIns as discussed
Path: Icypeas people.search → Blitz email.find only — do not change course without asking
TAM: show after ALL excludes
Cost: ask me for --confirm-spend; never invent a cap
Pilot first, then ask before full volume
```
