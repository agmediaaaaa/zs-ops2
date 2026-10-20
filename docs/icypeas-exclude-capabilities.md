# Icypeas exclude capabilities (verified)

Live-checked via Treg `icypeas.people.search.count` (free) on 2026-10-19.
Source of truth for agents: also `treg catalog get icypeas.people.search`.

## Billing reminder

`icypeas.people.search` is **per returned row** (~$0.00038). Anything droppable
in-query must be excluded **before** paid search — not after.

## Supported in-query excludes

| Field | Shape | Notes |
|-------|-------|-------|
| `currentJobTitle` | `{include, exclude}` | Primary title gate |
| `keyword` | `{include, exclude}` | ICP noise words |
| `currentCompanyWebsite` | `{include, exclude}` | **Domains** — bare host (`acme.com`) |
| `currentCompanyName` | `{include, exclude}` | Known company names |
| `currentCompanyUrn` | `{include, exclude}` | Company LinkedIn URN |
| `currentCompanyId` | `{include, exclude}` | Company id |

Person filters that also support include/exclude per catalog: `firstname`, `lastname`,
`pastJobTitle`, `school`, `languages`, `skills`, `location`, `profileLocation`, `workLocation`.

## Not supported in Icypeas query

| Attempt | Result |
|---------|--------|
| `profileUrl: {exclude: […]}` | `forbidden keys` / `invalid_keys_in_query_error` |
| `currentCompanyUrl: {exclude: […]}` | same |

**Person LinkedIn URLs cannot be suppressed inside Icypeas.** Skip them after rows
return and **before** Blitz (free). You may still have paid Icypeas for that row if
the domain was not already excluded.

## Correct pipeline order

1. Load domains / titles / keywords / LinkedIns / emails from PlusVibe + Supabase
2. Inject **domains + titles + keywords** into Icypeas query
3. Free `.count` with that query → TAM after excludes
4. Paid `.search` with the same query
5. Skip known person LinkedIns / emails (free)
6. Blitz remaining only

## Wrong order (banned)

Pay Icypeas → filter domains in Python → Blitz

## Other providers (only if user approves a course change)

Leadsforge documents `excludeDomains` and `excludeLinkedInURLs` on people search.
That is a **different path** from the locked Icypeas → Blitz Cheap Scrape pipeline —
do not switch mid-run without asking.
