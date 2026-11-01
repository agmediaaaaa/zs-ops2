# Codicen / CSLB tables in ZS Lead Database

**Project:** [ZS: Lead Database](https://supabase.com/dashboard/project/npkdhahdvilcctjwzdlf) (`npkdhahdvilcctjwzdlf`)

**Hard rule:** do **not** add columns to `public."Lead Database"`. People stay there as-is.

---

## Tables

| Table | Role |
|-------|------|
| `cslb_companies` | Company universe from CSLB Master + Personnel |
| `codicen_campaign_leads` | Campaign merge: company fields + people fields **copied** from Lead Database |
| `"Lead Database"` | People (unchanged schema). Enrichments land here as usual |

```
cslb_companies          "Lead Database"
     │                        │
     │   enrich people        │  (no schema changes)
     │   separately           │
     └──────────┬─────────────┘
                ▼
      codicen_campaign_leads
      (one row per license + email for Codicen campaigns)
```

Optional: `cslb_companies.dm_*` / `lead_database_id` can mirror the matched person for convenience **on the company table only** — still not altering Lead Database.

---

## What was loaded

Upload script: `scripts/upload_cslb_companies_supabase.py`

```bash
python scripts/upload_cslb_companies_supabase.py \
  --csv data/cslb/normalized/cslb_licenses_latest.csv \
  --slice-name expires120_clear
```

Wave 1 slice: CLEAR licenses with expiration within 120 days (~23.9k rows) → `cslb_companies`.

Full statewide (~245k): same script with `cslb_licenses_full_latest.csv` and `--slice-name full`.

---

## Merge into campaign table (people stay in Lead Database)

After people are enriched into `"Lead Database"`, copy into the merge table (example):

```sql
insert into public.codicen_campaign_leads (
  campaign_id, batch_id, license_no,
  business_name, full_business_name, city, state, county, zip_code,
  business_phone, business_type, classifications, primary_status,
  expiration_date, expiration_date_iso, days_to_expiration, expires_within_120,
  wc_coverage_type, wc_expiration_date, cb_surety_company, cb_effective_date,
  company_domain, website,
  lead_database_id, first_name, last_name, email, linkedin, title,
  email_source, email_status, company_size, company_description, location, company_industry,
  plusvibe_ready, handoff_status
)
select
  'codicen_wave1',
  'manual_merge',
  c.license_no,
  c.business_name, c.full_business_name, c.city, c.state, c.county, c.zip_code,
  c.business_phone, c.business_type, c.classifications, c.primary_status,
  c.expiration_date, c.expiration_date_iso, c.days_to_expiration, c.expires_within_120,
  c.wc_coverage_type, c.wc_expiration_date, c.cb_surety_company, c.cb_effective_date,
  c.company_domain, c.website,
  p.id,
  p."First Name", p."Last Name", p."Email", p."Linkedin", p.title,
  p.email_source, p.email_status, p.company_size, p.company_description, p.location, p.company_industry,
  true,
  'staged'
from public.cslb_companies c
join public."Lead Database" p
  on lower(p."Company Name") = lower(c.business_name)  -- replace with domain/license match when available
 and p."Email" is not null
on conflict (license_no, email) do update set
  lead_database_id = excluded.lead_database_id,
  first_name = excluded.first_name,
  last_name = excluded.last_name,
  linkedin = excluded.linkedin,
  title = excluded.title,
  updated_at = now();
```

Prefer matching on `company_domain` / website once enrich fills those on `cslb_companies`, not fuzzy company name alone for production.

---

## Dashboard links

- Companies: https://supabase.com/dashboard/project/npkdhahdvilcctjwzdlf/editor?schema=public&table=cslb_companies  
- Campaign merge: https://supabase.com/dashboard/project/npkdhahdvilcctjwzdlf/editor?schema=public&table=codicen_campaign_leads  
- People (unchanged): https://supabase.com/dashboard/project/npkdhahdvilcctjwzdlf/editor?schema=public&table=Lead%20Database  
