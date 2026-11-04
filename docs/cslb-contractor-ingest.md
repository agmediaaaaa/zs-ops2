# CSLB California contractors — ingest + decision-maker emails

## Source of truth

CSLB Public Data Portal: https://www.cslb.ca.gov/onlineservices/dataportal/

**Do not ZIP/city scrape.** Use the official free statewide files:

| File | URL |
|------|-----|
| License Master (CSV) | `https://www.cslb.ca.gov/OnlineServices/DataPortal/DownLoadFile.ashx?fName=MasterLicenseData&type=C` |
| Personnel (CSV) | `https://www.cslb.ca.gov/OnlineServices/DataPortal/DownLoadFile.ashx?fName=PersonnelData&type=C` |
| UI | [MASTER LIST of CONTRACTORS](https://www.cslb.ca.gov/OnlineServices/DataPortal/ContractorList) |

~245k renewed / expired-but-renewable licenses. Cancelled, revoked, and expired-non-renewable are excluded by CSLB.

**Emails are never in CSLB** (Business & Professions Code §27). Company phones are on Master (`BusinessPhone`).

## Scripts

### 1. Ingest — `scripts/ingest_cslb_master_list.py`

Downloads Master + Personnel, joins on license number, normalizes principals, writes:

- `data/cslb/raw/MasterLicenseData_*.csv`
- `data/cslb/raw/PersonnelData_*.csv`
- `data/cslb/normalized/cslb_licenses_latest.csv`
- `data/cslb/normalized/cslb_principals_latest.jsonl`
- `data/cslb/normalized/ingest_meta_latest.json`

```bash
# Full statewide download + normalize (CA default)
python scripts/ingest_cslb_master_list.py --download

# High-intent sales slice
python scripts/ingest_cslb_master_list.py --from-raw data/cslb/raw \
  --status CLEAR --expires-within 120 --class B,C10 \
  --business-type "Sole Owner" --slice-name licensing_pilot

# Optional Supabase upsert (requires env + table)
python scripts/ingest_cslb_master_list.py --from-raw data/cslb/raw \
  --status CLEAR --expires-within 120 --upsert-supabase
```

#### CLI filters

| Flag | Meaning |
|------|---------|
| `--status` | Comma PrimaryStatus (e.g. `CLEAR`) |
| `--class` | Classifications (`B,C10,C33`) |
| `--business-type` | e.g. `Sole Owner,Corporation` |
| `--county` | County names |
| `--state` | Default `CA`; empty string = all |
| `--expires-within N` | Days to expiration in `[0, N]` |
| `--expires-after N` | Days to expiration `>= N` |
| `--limit` | Cap rows after filters |

#### Normalized columns (selected)

`license_no`, business names, address/city/state/county/zip, `business_phone`, `business_type`, issue/expiration (+ `days_to_expiration`, `expires_within_30/90/120`), status, `classifications`, WC/bond fields, `primary_principal_*`, `principals_json`, empty `email` / `company_domain` / `website` (filled later by enrich).

### 2. DM email enrich — `scripts/enrich_cslb_decision_makers.py`

Cheap Scrape path via Treg:

1. Resolve domain — `hunter.x.domain-finder` (free); optional `--with-paid-domain` → `blitzapi.companies.enrich`
2. Free TAM — `icypeas.people.search.count`
3. Discover — `icypeas.people.search` (Owner/CEO/Founder/President/Principal/Partner/Officer)
4. Email — `blitzapi.people.email.find` with route headers  
   `X-Treg-Route-Max-Cost: 0.01`, `Waterfall: 0`, `Exclude: aiark,icypeas`
5. Optional `--with-web-extract` — `treg.web.extract` on contact pages; only keeps emails matching CSLB principal last name (not bare `info@`)

**Gates (hard stop):**

```bash
# Free scope on a filtered CSV
python scripts/enrich_cslb_decision_makers.py \
  --licenses data/cslb/normalized/cslb_licenses_latest.csv \
  --companies 25 --pull 50 --scope-only

# Catalog quote only
python scripts/enrich_cslb_decision_makers.py \
  --licenses data/cslb/normalized/cslb_licenses_latest.csv \
  --pull 100 --estimate

# Paid Pull-N (requires explicit cap)
python scripts/enrich_cslb_decision_makers.py \
  --licenses data/cslb/normalized/cslb_licenses_latest.csv \
  --companies 50 --pull 50 --confirm-spend 0.50
```

Outputs under `artifacts/cslb-dm-enrich/`: `pulled_*.csv`, `ready_*.csv`, `report_*.json`, `scope_summary.json`.

Never enrich all ~245k without a filtered slice + `--confirm-spend`. See [waterfall-cost-matrix.md](waterfall-cost-matrix.md) and `.cursor/skills/lead-scrape-gates/SKILL.md`.

Pilot gate artifact: [cslb-pilot-gate-report.json](cslb-pilot-gate-report.json) (estimate + hard stop; live `/call/` needs a valid team agent token via `treg login --token`).

Normalized CSV/JSONL under `data/cslb/` are gitignored (large). Re-download with `--download` after clone.

### Phones

| Need | Source |
|------|--------|
| Company phone | CSLB `business_phone` (free) |
| DM mobile | Optional later via `treg.people.phone.find` / Blitz phone — separate spend cap |

## Supabase (optional)

Env: `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`.

Suggested table (run in SQL editor before `--upsert-supabase`):

```sql
create table if not exists public.cslb_licenses (
  license_no text primary key,
  last_update text,
  business_name text,
  full_business_name text,
  mailing_address text,
  city text,
  state text,
  county text,
  zip_code text,
  business_phone text,
  business_type text,
  issue_date date,
  expiration_date date,
  days_to_expiration int,
  primary_status text,
  secondary_status text,
  classifications text,
  primary_principal_name text,
  primary_principal_first text,
  primary_principal_last text,
  primary_principal_titles text,
  principals jsonb default '[]'::jsonb,
  company_domain text,
  website text,
  email text,
  ingested_at timestamptz
);
```

Upsert uses `on_conflict=license_no` in batches of 500.

## Compliance

Public CSLB data; license status can change anytime — use Instant License Check for point-in-time verification. No CSLB endorsement. Treg emails are provider best-effort — verify before send.
