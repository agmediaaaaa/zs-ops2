# Company Brain — target operating model

Corrected map after Nov 2026 review. Notion = slim. Airtable = leads + weekly reporting. GrokBot = onboarding + execution.

## Current state (audit)

| Area | Today | Gap |
| --- | --- | --- |
| Client Airtable bases (e.g. GWS, Codicen) | `Positive lead dealflow` + optional `Campaign Targeting` | No weekly snapshots, no reporting overview |
| Client Airtable automations | PlusVibe webhooks → create lead / Slack positive; booked webhook often undeployed | No reporting automation |
| ZS OS (`appfAlYx7U0ZU3H0j`) | Clients, Campaigns, Tasks, Success fees, Volume calculator | Account registry only — not per-client weekly reporting |
| Notion | Scripts, ideas, campaign narrative often parked here | Should only keep **best campaigns** + SOPs |
| Onboarding | Manual checklists in Client Onboarding / Client Setup | Must be GrokBot-driven |

## Target Airtable per-client base

Keep existing:

- **Positive lead dealflow** — lead status, replies, booked, paid

Add:

### Weekly performance snapshots

One record per ISO week. Suggested fields:

- Week start (date)
- Emails sent
- Replies
- Positive replies
- Meetings booked
- Meetings held (optional)
- Reply rate (formula)
- Positive rate (formula)
- Source notes (PlusVibe pull / manual)

### Reporting overview

Client-facing weekly view (interface or dedicated table fed by snapshots):

- This week vs last week
- Lead funnel counts by status
- Meetings booked this week
- Link / embed surface clients can open weekly

### Reporting automation

Per-client automation that:

1. Runs on a weekly schedule (or is triggered by GrokBot after PlusVibe stats pull)
2. Creates / updates the snapshot row
3. Refreshes reporting overview fields used by the client view

## Notion (slim)

Allowed:

- Best campaigns (GrokBot curated)
- SOPs (Client Onboarding, Client Setup, Inbox, scrape playbooks live in GitHub)

Not the home for:

- Positioning / ICP / offers as the default knowledge pile
- All campaign intelligence
- Reporting numbers

## GrokBot onboarding sequence (must automate)

Trigger: onboarding starts (signed / ready to onboard).

1. Generate JotForm contract
2. Send payment link
3. Create private Slack `#client-[company]`
4. Invite client + Aarav + Swapnil (or current owners)
5. Post welcome message with Wistia + Tally (`https://tally.so/r/3x97B9`)
6. Create PlusVibe workspace named for client
7. Duplicate Airtable template base → rename to client
8. Configure PlusVibe webhooks → Airtable (positive leads + booked status)
9. Track handoff gates: contract signed, payment received, Slack active, Tally submitted, calendar sync

Source SOPs to encode (do not leave as human-only forever):

- Notion Client Onboarding
- Notion Client Setup (workspace / CRM / webhook sections)

## Explicit non-goals

- Rebuilding full ICP / offer / positioning libraries in Notion
- Using Notion as the weekly client reporting sheet
- Manual Airtable base creation + webhook copy-paste as the steady-state process

## Demo base (built)

**[ZS Demo — Client Reporting](https://airtable.com/appxmkWs0HNIoPy5n)** in workspace `ZS OPS`

| Piece | Link |
| --- | --- |
| Base | https://airtable.com/appxmkWs0HNIoPy5n |
| Weekly overview (KPIs + charts) | https://airtable.com/appxmkWs0HNIoPy5n/pagfHEP7zsYuAq4mq |
| Dealflow board | https://airtable.com/appxmkWs0HNIoPy5n/pagmzjjmzmUAx3bcH |
| Weekly snapshots grid | https://airtable.com/appxmkWs0HNIoPy5n/pagIehKsYymP4QmkM |
| Slack automation (draft → `#zs-chat`) | https://airtable.com/appxmkWs0HNIoPy5n/wflNNZjJzxdJc2CmL |

Includes: Positive lead dealflow + Weekly performance snapshots, 12 seeded leads, 8 weekly rows, published Client Reporting interface, Slack alert on new lead (turn **on** in UI).

Onboarding APIs (JotForm / Slack Connect / Payoneer) deferred until files arrive.
