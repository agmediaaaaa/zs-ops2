# Codicen Wave 1 — GTM brief

**Internal. Do not send this document to prospects.**

Third-grade rule: if a 9-year-old cannot say what we are offering in one sentence, rewrite it.

Spam / templating SOPs: [SOP.md](../05-copy-messaging-framework-agent-5/SOP.md), [SOP-spam-guard.md](../05-copy-messaging-framework-agent-5/SOP-spam-guard.md), [SOP-plusvibe-templating.md](../05-copy-messaging-framework-agent-5/SOP-plusvibe-templating.md).

Related earlier offer notes: [Codicen — Front-End Offers](https://docs.google.com/document/d/1XT3EWMVvf-k7rsPlNqANC_sozXwyQpCz0xiZIb3h68Y) — **Wave 1 offer below overrides the old “send three dates” front door.**

---

## 0) Premise (what this is trying to give them)

### Who Codicen is

**Codicen LLC** (codicen.com) helps **California contractors with an active CSLB license**.

In plain words:

1. Build a **12-month deadline calendar** for that business (license, bond, coverage on file, then city / trade items once they share more).
2. **Text + email** the office **60 / 30 / 7 days** before each date.
3. They **do not** file renewals, pay bonds, sell coverage, give legal advice, or work for the state.

### Why the old script failed

Saying “want me to send you three dates?” is weak.

Those dates already sit on a **public file**. Many offices already have a letter, a bond person, or a sticky note. Handing them a copy of data they already own does not feel like a favor.

### What we offer instead (Wave 1 front door)

**Promise the thing they do not have:** a **full-year map of dates for their shop**, plus how reminders would land before each one.

**Deliver after yes (proof slice):** send **three** public dates (license / bond / coverage on file) so they see we are real.

**Then the call:** walk the rest of the year + how 60/30/7 reminders work so the office sees each date before it lands — permits, pay, and bids stay clear.

### One-line premise

We mail shops whose next public date is inside **120 days**, name that countdown in plain words, offer a **12-month calendar for their company**, prove it with three dates after they say yes, then call to show the rest and the reminder flow.

### Sales path

| Step | What happens |
|------|----------------|
| List build | Active CA CSLB + trade + title + **next public date ≤ 120 days** |
| Cold Email 1 | Countdown + offer **12-month calendar**. Easy yes. No call ask. |
| After yes | Send **3** dates (proof). Soft: “this is the front of the year map.” |
| Email 3 / same thread | Confirm phone for ~10–12 min to walk **the rest** + reminder setup |
| Phone | Walk dates + how texts/emails would fire. No hard price dump required. |
| Teams demo | 30 min Haroon / Idris (8am–5pm PDT) |
| After agreement | Full calendar build. Second call. Live 60/30/7. |

Pricing only on a call:

> We tailor every calendar to the business, so pricing depends on how complex yours is: how many licenses, entities, cities and crews you have.

---

## 1) Targeting (who we mail)

### Must be true

- California only
- Active CSLB contractor (CLEAR / renewable)
- Trade in the list below
- Title: **Office Manager first**, then Owner / CEO / qualifier (RMO)
- **Hot window (Wave 1 list filter):** nearest of license / bond / coverage-on-file expiration is **≤ 120 days** out (and still in the future — do not cold-mail already-lapsed as “you are lapsed”)

The ~23k “special / near-term” band is the **priority pool**. Firmographic size/title still apply on top.

### Size bands

| Band | Headcount | Who we email | Why |
|------|-----------|--------------|-----|
| **ICP 1 (Wave 1 control)** | 10–50 | Office Manager → Owner / RMO | Crew + office, no compliance team |
| ICP 2 | 5–9 | Owner / RMO | Owner still runs the office |
| ICP 3 | 50–100 | Office / Ops Manager | More dates, still no department |
| Kill-test only | 1–4 | Owner | Cap volume |

### Trade bands (plain words in copy)

| Code | Say in email |
|------|----------------|
| B | general building |
| C-10 | electrical |
| C-36 | plumbing |
| C-20 | HVAC |
| C-39 | roofing |
| C-33 | painting |
| C-8 | concrete |

Dedup on CSLB number.

### How countdown personalization works

From CSLB public fields, compute for each company:

| Var | Meaning |
|-----|---------|
| `next_item` | Which of the three is soonest: `license` / `bond` / `coverage on file` |
| `next_date` | That date (MM/DD/YYYY) |
| `days_left` | Whole days until `next_date` (1–120 for Wave 1) |

**Copy rule:** state the countdown as a **fact from the public file**, not a threat.

Safe: “Public file shows {{company_name}}’s next {{next_item}} date about {{days_left}} days out.”

Banned in cold copy: at risk, lapsed, under audit, urgent, “coming due,” “expires soon,” “act now,” that *they* are in trouble.

### Do not mail

- Outside California / not a contractor / 100+
- Already expired *and* framed as “you are lapsed” (ops may handle separately; not this sequence)
- People who only want someone to **file / fix** a suspension
- Current clients / known leads (suppress)

---

## 2) Persona (who we talk to)

### Primary — Office Manager (ICP 1)

**Job:** keep the office moving while the qualifier is on a job.

**Internal monologue:**

1. “I’ll deal with the mail when it shows up.”
2. “The boss is on a job; this can wait.”
3. “We already have a system… I think.”
4. “If something’s wrong, someone would tell us.”
5. “I don’t want another tool. I just don’t want a surprise.”
6. “Don’t make me look stupid in front of the boss.”

| | Their words |
|--|-------------|
| **Pain** | Dates live in mail / someone else’s head |
| **Fear** | Job or permit stops; boss blames the office |
| **Gain** | See the year of dates before each one lands |

### Secondary — Owner / CEO / RMO

| | Their words |
|--|-------------|
| **Pain** | Paperwork they do not watch day to day |
| **Fear** | Paper kills a job, a payment, or a bid |
| **Gain** | Stay clear to work and collect without babysitting |

---

## 3) Offers (what we put in their hands)

### Core truth

They will not care about “I can forward you three public dates.”

They will care about:

> a full year of dates for **my** shop, and someone who pings the office before each one

### Locked Wave 1 offer (promise → proof → call)

| Stage | What we say | What we actually send / do |
|-------|-------------|----------------------------|
| **Email 1 promise** | 12-month deadline calendar for {{company_name}} | Nothing yet — earn yes |
| **After yes (proof)** | “Front of that map” | License + bond + coverage-on-file dates |
| **Call** | Rest of the year + how 60/30/7 reminders work | Phone 10–12 min → Teams demo |

City / EPA / DIR dates still need them to share more — promise on the call as “we add these once you name cities,” not as Email 1 deliverable.

### Offer cards (same calendar, different want)

| Offer | Want in their words | Who | Wave |
|-------|---------------------|-----|------|
| **A — Permits** | Keep pulling permits through the next date and the ones after | OM | Wave 1 control |
| **B — Pay / collect** | Stay clear so finished work stays collectible | Owner | ICP 2 / Owner lines |
| **C — Bids / tenders** | Stay clear to bid and take the next job | Owner / OM on public-works-heavy trades | Test after A |
| **E — Office while boss is out** | Office sees every date while qualifier is on site | OM | Wave 2 |
| **D — City / EPA / DIR** | Keep specialty work | Named cities | Not cold Email 1 |

### Why this is better than “send dates”

| Old | New |
|-----|-----|
| Asset = copy of public file | Asset = **year map + reminder system** |
| Feels like spam with their own data | Feels like a service for the next 12 months |
| Yes → dump → awkward call | Yes → proof slice → call to unlock the rest |

---

## 4) Angles (how we say it)

One idea per email. Soft countdown. No scare.

| # | Angle | One sentence |
|---|-------|--------------|
| 1 | **Countdown + year map** | Your next public date is ~X days out; want the full 12-month map for the shop? |
| 2 | **Permits** | So the next permit pull is not the moment you learn a date was hiding |
| 3 | **Pay / collect** | So pay on finished work is not blocked by a date the letter did not spell out |
| 4 | **Bids / tenders** | So you stay clear to bid when the next job shows up |
| 5 | **Office vs field** | So the office holds the year while the qualifier is on a job |
| 6 | **Letter hole** | The renewal letter is one piece; the year map covers the rest |

Wave 1 control: **Offer A + Angle 1** (countdown + year map).  
Swap outcome line for B / C / E without changing the asset.

---

## 5) Custom snippets

### Email 1 — required personalization

Use **all** of:

- `{{company_name}}`, `{{city}}`, `{{trade_plain}}`
- `{{next_item}}`, `{{days_left}}` (from ≤120d filter)

Optional: `{{principal_first}}` for Offer E.

**Never in Email 1:** license number, full 12-date dump, “comp,” Teams, price, at-risk language, call ask.

### Email 2 — proof slice only

```
License: {{license_exp}}
Bond: {{bond_exp}}
Coverage on file: {{coverage_exp}}
```

One line: “This is the front of the 12-month map. The rest is easier on a short call.”

### PlusVibe vars (additions)

| Var | Source |
|-----|--------|
| `next_item` | soonest of license / bond / coverage |
| `next_date` | that date |
| `days_left` | integer 1–120 |
| `license_exp`, `bond_exp`, `coverage_exp` | Email 2 |
| `surety_short` | optional Email 2 |
| `phone` | Email 3 |
| `cslb_number` | **ops only** — never Email 1 |

---

## 6) Script system

**their next date → why a year map beats a letter → offer calendar → easy yes**  
→ proof 3 dates → call for rest + reminders

Locked CTAs:

| Email | CTA |
|-------|-----|
| 1 | “Want the 12-month calendar for {{company_name}}?” / “Reply yes and I’ll start it.” |
| 2 | Deliver 3 dates. Soft bridge to call — or wait for Email 3. |
| 3 | Confirm `{{phone}}` for ~10–12 min to walk the rest + reminder flow. |

Style: no Hi/Hey/Hello, no em dashes in bodies, spam-scan every send.

---

## 7) Script previews (ready to read)

Filled example company for reading: **Harbor Peak Electric**, San Jose, electrical, next item = bond, **67 days** out. Office Manager = Maria.

---

### Email 1 — A1 (control): countdown + year map + permits

**Subject:** `Harbor Peak Electric next 12 months`

**How it reads (filled):**

```
Maria

Public file shows Harbor Peak Electric's next bond date about 67 days out (electrical, San Jose).

Most offices only watch the renewal letter. That letter is one piece. A 12-month calendar for the shop covers license, bond, and coverage on file, plus the dates that follow.

Want the 12-month calendar for Harbor Peak Electric?
```

**PlusVibe:**

```
{{first_name}}

Public file shows {{company_name}}'s next {{next_item}} date about {{days_left}} days out ({{trade_plain}}, {{city}}).

Most offices only watch the renewal letter. That letter is one piece. A 12-month calendar for the shop covers license, bond, and coverage on file, plus the dates that follow.

Want the 12-month calendar for {{company_name}}?
```

---

### Email 1 — A2: countdown + permits outcome

**Filled:**

```
Maria

Harbor Peak Electric's next bond date on the public file is about 67 days out.

Before the next permit pull in San Jose, it helps to see the full year of license, bond, and coverage-on-file dates in one place, not only the letter.

Want me to build that 12-month calendar for Harbor Peak Electric?
```

**PlusVibe:**

```
{{first_name}}

{{company_name}}'s next {{next_item}} date on the public file is about {{days_left}} days out.

Before the next permit pull in {{city}}, it helps to see the full year of license, bond, and coverage-on-file dates in one place, not only the letter.

Want me to build that 12-month calendar for {{company_name}}?
```

---

### Email 1 — B1: pay / collect (Owner)

**Filled:**

```
James

Public file shows Harbor Peak Electric's next bond date about 67 days out.

A date like that can sit outside the renewal letter and still affect whether finished work stays clear to collect on.

Want the 12-month calendar for Harbor Peak Electric so those dates sit in front of the office?
```

**PlusVibe:**

```
{{first_name}}

Public file shows {{company_name}}'s next {{next_item}} date about {{days_left}} days out.

A date like that can sit outside the renewal letter and still affect whether finished work stays clear to collect on.

Want the 12-month calendar for {{company_name}} so those dates sit in front of the office?
```

---

### Email 1 — C1: bids / tenders

**Filled:**

```
James

Harbor Peak Electric's next bond date is about 67 days out on the public file.

When the next bid or job packet shows up, shops usually want license, bond, and coverage on file already mapped for the year, not chased the week of.

Want the 12-month calendar for Harbor Peak Electric?
```

**PlusVibe:**

```
{{first_name}}

{{company_name}}'s next {{next_item}} date is about {{days_left}} days out on the public file.

When the next bid or job packet shows up, shops usually want license, bond, and coverage on file already mapped for the year, not chased the week of.

Want the 12-month calendar for {{company_name}}?
```

---

### Email 1 — E1: office vs field

**Filled:**

```
Maria

When the qualifier is on a job, Harbor Peak Electric's office still has to watch dates. Next bond date on the public file is about 67 days out.

Want a 12-month calendar the office can hold, with reminders before each date?
```

**PlusVibe:**

```
{{first_name}}

When the qualifier is on a job, {{company_name}}'s office still has to watch dates. Next {{next_item}} date on the public file is about {{days_left}} days out.

Want a 12-month calendar the office can hold, with reminders before each date?
```

---

### Email 2 — proof slice (after yes)

**Filled:**

```
Maria

Starting the 12-month calendar for Harbor Peak Electric. Here is the front of that map from the public file:

License: 03/14/2027
Bond: 01/06/2027
Coverage on file: 08/22/2026

The rest of the year (and how reminders would hit 60, 30, and 7 days out) is clearer on a short call.
```

**PlusVibe:**

```
{{first_name}}

Starting the 12-month calendar for {{company_name}}. Here is the front of that map from the public file:

License: {{license_exp}}
Bond: {{bond_exp}}
Coverage on file: {{coverage_exp}}

The rest of the year (and how reminders would hit 60, 30, and 7 days out) is clearer on a short call.
```

---

### Email 3 — call for the rest + reminders

**Filled:**

```
Maria

Those three dates are only the front of Harbor Peak Electric's year.

On a short phone walkthrough (about 10 to 12 min) I can show the rest of the map and how texts and emails would land before each date so the office sees them in time for permits and pay.

Can I try you at (408) 555-0142, or is there a better number?
```

**PlusVibe:**

```
{{first_name}}

Those three dates are only the front of {{company_name}}'s year.

On a short phone walkthrough (about 10 to 12 min) I can show the rest of the map and how texts and emails would land before each date so the office sees them in time for permits and pay.

Can I try you at {{phone}}, or is there a better number?
```

---

## 8) Objection one-liners

| They say | We say |
|----------|--------|
| “We already have those dates.” | Good. Most shops do for one or two items. The calendar is the full year plus reminders before each date, not a copy of the letter. |
| “We already have someone for this.” | What’s due in the next 90 days, and which of those arrive by mail? Happy to show how the year map sits next to that. |
| “Just email me the details.” | Happy to. The year map is easier to see live. Worth 15 minutes? |
| “Not right now.” | Understood. With about {{days_left}} days to the next {{next_item}} date, can we check back before that window gets tight? |
| Price by email | We tailor every calendar to the business, so pricing depends on how complex yours is: how many licenses, entities, cities and crews you have. |

Do **not** say they will “never miss” a deadline, payment, or bid (Codicen never-say + spam). Say the office **sees dates before they land**.

---

## 9) Inbox / booking handoff

| Item | Value |
|------|--------|
| First live touch | **Phone** 10–12 min (rest of map + reminders) |
| Demo after phone | **Microsoft Teams**, 30 min |
| Hours | 8:00 AM – 5:00 PM PDT |
| CC | Haroon — haroon.elgabalawy@codicen.com — 626-634-9044 |
| | Idris — idris.elgabalawy@codicen.com — 626-390-1958 |

### Never say

- Prices / client names / results  
- Guarantee they will never miss a deadline, penalty, license, payment, or bid  
- That we file, renew, or pay anything  
- Legal / tax / insurance advice; CSLB affiliation  
- That **their** license/bond/coverage is lapsed, at risk, or under audit  
- Uncited law changes; reminder go-live dates  
- Email 1 call ask or full date dump  

---

## 10) Wave plan

### Wave 1

- List: CA, ICP 1, 10–50, mixed trades, **days_left ≤ 120** on soonest public date  
- Offer: **12-month calendar** (promise) → 3-date proof → phone for rest + reminders  
- Angle: countdown + permits (A1)  
- Metric: completed phone calls  

### Wave 2

- Same conversion; swap B (collect) / C (bids) / E (office)  

### List ops

- Compute `next_item` / `days_left` from CSLB before upload  
- Suppress days_left ≤ 0 from this “about X days out” sequence  
- PlusVibe send-suppress + client suppress  

---

## 11) Checklist before send

- [ ] Lead has `days_left` 1–120 and `next_item` set  
- [ ] Email 1 promises **calendar**, not “three dates you already have”  
- [ ] Countdown is factual, not scare  
- [ ] No license #, no “comp,” no call ask in Email 1  
- [ ] Email 2 = three dates as **front of the map**  
- [ ] Email 3 = phone for **rest + reminders**  
- [ ] Spam-guard scan  
- [ ] Never-say checked  

---

## Premise again

**Old:** “Can I send you dates?” → weak, they already have them.  
**New:** “Your next public date is ~X days out. Want a 12-month calendar for the shop?” → yes → send three as proof → call to show the rest and the reminder system.
