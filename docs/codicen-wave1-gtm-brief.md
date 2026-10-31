# Codicen Wave 1 — GTM brief

**Internal. Do not send this document to prospects.**

Third-grade rule: if a 9-year-old cannot say what we are offering in one sentence, rewrite it.

Spam / templating: [SOP.md](../05-copy-messaging-framework-agent-5/SOP.md), [SOP-spam-guard.md](../05-copy-messaging-framework-agent-5/SOP-spam-guard.md), [SOP-plusvibe-templating.md](../05-copy-messaging-framework-agent-5/SOP-plusvibe-templating.md).

---

## 0) Premise

**Codicen** builds a deadline calendar for California CSLB contractors and texts/emails the office 60 / 30 / 7 days before each date. They track and remind. They do not file, pay, advise, or work for the state.

**Cold email is not “here are three public dates.”** That data already sits on a file. Weak.

**Cold email is:** pick a segment → name a **want they feel** → promise an asset they do **not** already have on a sticky note → after yes, prove it with a small public-file slice → call to unlock the full year + reminder system.

### Conversion skeleton (every offer)

| Step | Job |
|------|-----|
| Email 1 | Segment hook + **named offer** + easy yes. No call ask. |
| Email 2 | Proof slice (real for *their* company). Soft bridge. |
| Email 3 | Confirm phone. Walk rest of year + 60/30/7. |
| Teams | Demo after phone (Haroon / Idris, 8am–5pm PDT). |

---

## 1) Targeting + how we segment

### Always true

- California, active CSLB, trade in band, Office Manager → Owner
- ICP 1 control: 10–50 employees
- Dedup on CSLB number
- Suppress clients / prior sends

### Segment axes (cut the list before writing copy)

| Axis | Cuts | Why it changes the offer |
|------|------|---------------------------|
| **Hot item** | Soonest of license / bond / coverage ≤ 120 days | What we name in the first line |
| **Timing band** | 1–30 / 31–60 / 61–120 days | Urgency of “prep pack” vs “year map” |
| **Title** | Office Manager vs Owner | Permits/office desk vs collect/bid |
| **Trade** | B, C-10, C-36, C-20, C-39, C-33, C-8 | Plain-word relevance; WC-heavy trades lean coverage |
| **Entity** | LLC vs Corp/sole | LLC shops often juggle more than one bond story |
| **Class count** | Single vs multi-class | Multi-class → “one map for every class” |

### Trade plain words

| Code | `trade_plain` |
|------|----------------|
| B | general building |
| C-10 | electrical |
| C-36 | plumbing |
| C-20 | HVAC |
| C-39 | roofing |
| C-33 | painting |
| C-8 | concrete |

### Do not mail

Outside CA, non-contractors, 100+, “file my suspension for me,” scare framing of already-lapsed as “you are lapsed.”

### Vars every segment can use

| Var | Meaning |
|-----|---------|
| `next_item` | license / bond / coverage on file |
| `days_left` | 1–120 |
| `next_date` | that date |
| `license_exp`, `bond_exp`, `coverage_exp` | Email 2 proof |
| `surety_short` | optional when bond is hot |
| `principal_first` | office-vs-field |
| `class_count` | multi-class offers |
| `business_type` | LLC pack |
| `phone` | Email 3 |

---

## 2) Persona (short)

**Office Manager:** mail + permits + “don’t look bad.” Fears a stopped job. Wants dates the office can hold.

**Owner:** keep working and collecting. Fears paper blocking pay or a bid. Wants clarity without babysitting.

Language: permits, letter, bond person, jobs, crews. Not “compliance platform.”

---

## 3) Offer portfolio (create your own cuts)

Rule for every offer: **promise something they do not already have printed on the CSLB letter.**

Proof after yes can still use the three public dates — but Email 1 sells a **job-to-be-done**, not a data dump.

### Portfolio map

| ID | Offer name | Segment | Promise (Email 1) | Proof (Email 2) | Call unlock |
|----|------------|---------|-------------------|-----------------|-------------|
| **O1** | 12-month shop calendar | Any ≤120d, OM | Full-year deadline calendar for the company | 3 public dates as “front of map” | Rest of year + reminders |
| **O2** | Letter-vs-file gap card | OM who trusts the letter | Side-by-side: what the letter covers vs what else sits on *their* public file | Their 3 dates labeled letter vs file | How reminders cover the “file” side |
| **O3** | Next-date prep pack | Hot item = bond *or* coverage *or* license; ≤60d stronger | Prep pack for the **specific** next item + the other two lined up | Next item date + other two | Who owns each + reminder timing |
| **O4** | Who-owns-what desk sheet | OM, 10–50 | One sheet: which date → which party (CSLB / surety / carrier) for *their* shop | Filled sheet from public file | Add city/trade rows on call |
| **O5** | Reminder dry-run | Any ≤120d | Sample 60/30/7 messages timed to *their* next date | Dry-run copy + the 3 dates | Turn dry-run into live calendar |
| **O6** | 90-day permit-clear view | OM; permits language; ≤120d | Ordered view of public dates inside the next ~90 days for permit pulls | Those dates in order | Full 12 months beyond the 90 |
| **O7** | Collect-clear year map | Owner / RMO | Year map so finished work stays clear to collect on | 3 dates | Reminder system + demo |
| **O8** | Bid-ready date map | Owner; bid-heavy trades (B, C-10, etc.) | Map of public dates so the shop stays clear to bid | 3 dates | Full year + how office gets pinged |
| **O9** | Office desk pack | OM + known qualifier name | Calendar the **office** holds while qualifier is on a job | 3 dates | Reminders to office contacts |
| **O10** | LLC entity pack | `business_type` = LLC | Entity-aware year map (license + bond + coverage, not “one letter”) | 3 dates | Entity/city add-ons on call |
| **O11** | Multi-class map | `class_count` ≥ 2 | One calendar across every class on the license | 3 dates (+ class list plain) | Per-class extras on call |
| **O12** | Coverage-weighted trade pack | C-20 / C-39 / C-8 (and similar) | Year map with coverage-on-file called out as a first-class date | 3 dates | Trade extras (EPA etc.) only after they share more |

**Parked (not Email 1 cold):** city / EPA / DIR lists until they name cities (Offer D).

### How to pick Wave 1 tests (do not run all 12 at once)

| Test | Offer | List cut | Why |
|------|-------|----------|-----|
| Control | **O1** | ICP1 OM, ≤120d, mixed trades | Clear product promise |
| Challenger A | **O2** | Same, exclude if prior “we already get the letter” is unknown — still strong default challenger | Attacks the real objection |
| Challenger B | **O5** | ≤90d | Product preview feels tangible |
| Challenger C | **O3** | `next_item` = bond, ≤60d | Sharp personalization |
| Owner lane | **O7** | Title = Owner, ≤120d | Different want |
| Trade lane | **O12** | C-20 + C-39 + C-8, ≤120d | Trade-true |

Metric: **completed phone calls**, not raw yeses.

---

## 4) Angles (pair with an offer)

One idea per email.

| Angle | Pairs well with |
|-------|-----------------|
| Countdown fact (public file, ~X days) | O1, O3, O5, O6 |
| Letter is incomplete | O2, O1 |
| Permits | O1, O6, O9 |
| Collect / pay clear | O7 |
| Bid / tender clear | O8 |
| Office vs field | O9 |
| Entity complexity | O10 |
| Many classes, one map | O11 |
| Coverage is not “extra paperwork” for this trade | O12 |
| Reminder preview beats another spreadsheet | O5 |

---

## 5) Snippet rules

**Email 1:** company, city, trade, and (when in segment) `next_item` + `days_left`. One offer. No license #. No “comp.” No call ask. No scare.

**Email 2:** proof only — three dates and/or the named artifact (gap labels, dry-run lines, who-owns-what).

**Email 3:** phone confirm for rest + reminders.

---

## 6) Script previews (filled + PlusVibe)

Shared example: **Harbor Peak Electric**, San Jose, electrical, Office Manager **Maria**, Owner **James**, next **bond** in **67** days (O3 bond pack uses 45 days).

All bodies spam-scanned: no Hi/Hey, no banned tokens, no em dashes in sendable copy.

---

### O1 — 12-month shop calendar (control)

**Filled:**

```
Maria

Public file shows Harbor Peak Electric's next bond date about 67 days out (electrical, San Jose).

Most offices only watch the renewal letter. A 12-month calendar for the shop covers license, bond, and coverage on file, plus the dates that follow.

Want the 12-month calendar for Harbor Peak Electric?
```

**PlusVibe:**

```
{{first_name}}

Public file shows {{company_name}}'s next {{next_item}} date about {{days_left}} days out ({{trade_plain}}, {{city}}).

Most offices only watch the renewal letter. A 12-month calendar for the shop covers license, bond, and coverage on file, plus the dates that follow.

Want the 12-month calendar for {{company_name}}?
```

**Email 2 proof:**

```
{{first_name}}

Starting the 12-month calendar for {{company_name}}. Front of that map:

License: {{license_exp}}
Bond: {{bond_exp}}
Coverage on file: {{coverage_exp}}

The rest of the year and the reminder timing are clearer on a short call.
```

---

### O2 — Letter-vs-file gap card

**Filled:**

```
Maria

Harbor Peak Electric's renewal letter mostly tracks the license. The public file also carries a bond date about 67 days out, plus coverage on file.

Want a one-page gap card for Harbor Peak Electric that labels letter vs file for those items?
```

**PlusVibe:**

```
{{first_name}}

{{company_name}}'s renewal letter mostly tracks the license. The public file also carries a {{next_item}} date about {{days_left}} days out, plus the other two public items.

Want a one-page gap card for {{company_name}} that labels letter vs file for those items?
```

**Email 2 proof:**

```
{{first_name}}

Gap card draft for {{company_name}}:

Letter side: license {{license_exp}}
File side: bond {{bond_exp}} | coverage on file {{coverage_exp}}

Happy to walk how reminders cover the file side on a short call.
```

---

### O3 — Next-date prep pack (bond-hot example)

Segment: `next_item` = bond, `days_left` ≤ 60 (filled at 45).

**Filled:**

```
Maria

Harbor Peak Electric's next bond date on the public file is about 45 days out.

Want a bond prep pack for the office: that date, the surety on record, and the license plus coverage-on-file dates lined up next to it?
```

**PlusVibe:**

```
{{first_name}}

{{company_name}}'s next {{next_item}} date on the public file is about {{days_left}} days out.

Want a {{next_item}} prep pack for the office: that date, who sits on record for it, and the other two public dates lined up next to it?
```

**Email 2 proof:**

```
{{first_name}}

Bond prep pack for {{company_name}}:

Bond: {{bond_exp}}{% if surety_short != blank %} ({{surety_short}}){% endif %}
License: {{license_exp}}
Coverage on file: {{coverage_exp}}

On a short call we can set who in the office owns each and when reminders should land.
```

*(Swap “bond” language automatically via `next_item` for license-hot or coverage-hot packs.)*

---

### O4 — Who-owns-what desk sheet

**Filled:**

```
Maria

In most electrical shops in San Jose, license dates point one place, bond dates another, coverage on file another. Harbor Peak Electric's next public date is the bond, about 67 days out.

Want a who-owns-what desk sheet filled for Harbor Peak Electric?
```

**PlusVibe:**

```
{{first_name}}

In most {{trade_plain}} shops in {{city}}, license dates point one place, bond dates another, coverage on file another. {{company_name}}'s next public date is the {{next_item}}, about {{days_left}} days out.

Want a who-owns-what desk sheet filled for {{company_name}}?
```

**Email 2 proof:**

```
{{first_name}}

Desk sheet draft for {{company_name}}:

License → CSLB record → {{license_exp}}
Bond → surety on file → {{bond_exp}}
Coverage on file → carrier on record → {{coverage_exp}}

We can add city and trade rows on a short call once you name them.
```

---

### O5 — Reminder dry-run

**Filled:**

```
Maria

Harbor Peak Electric's next bond date is about 67 days out on the public file.

Want a dry-run of the 60, 30, and 7 day reminder texts timed to that date for your office?
```

**PlusVibe:**

```
{{first_name}}

{{company_name}}'s next {{next_item}} date is about {{days_left}} days out on the public file.

Want a dry-run of the 60, 30, and 7 day reminder texts timed to that date for your office?
```

**Email 2 proof** (swap “bond” lines when `next_item` differs):

```
{{first_name}}

Dry-run for {{company_name}} (next {{next_item}} {{next_date}}):

About 60 days out: Bond date for {{company_name}} is on the calendar. Flag the office.
About 30 days out: 30 days to the bond date on file. Confirm who is handling it.
About 7 days out: One week to the bond date on file. Last office check.

Public dates next to that:
License {{license_exp}} | Bond {{bond_exp}} | Coverage on file {{coverage_exp}}

A short call turns this dry-run into a live calendar.
```

---

### O6 — 90-day permit-clear view

**Filled:**

```
Maria

For permit pulls at Harbor Peak Electric over the next stretch, it helps to see every public date inside about 90 days in one ordered list. Your next one is the bond, about 67 days out.

Want that 90-day permit-clear view for Harbor Peak Electric?
```

**PlusVibe:**

```
{{first_name}}

For permit pulls at {{company_name}} over the next stretch, it helps to see every public date inside about 90 days in one ordered list. Your next one is the {{next_item}}, about {{days_left}} days out.

Want that 90-day permit-clear view for {{company_name}}?
```

**Email 2:** ordered dates that fall inside 90 days (subset of the three), then: “Full 12 months on a short call.”

---

### O7 — Collect-clear year map (Owner)

**Filled:**

```
James

Public file shows Harbor Peak Electric's next bond date about 67 days out.

Want a 12-month collect-clear map for Harbor Peak Electric so license, bond, and coverage on file sit in front of the office before finished work hits paperwork checks?
```

**PlusVibe:**

```
{{first_name}}

Public file shows {{company_name}}'s next {{next_item}} date about {{days_left}} days out.

Want a 12-month collect-clear map for {{company_name}} so license, bond, and coverage on file sit in front of the office before finished work hits paperwork checks?
```

---

### O8 — Bid-ready date map (Owner)

**Filled:**

```
James

When Harbor Peak Electric puts a bid together, the packet usually assumes license, bond, and coverage on file are already mapped. Next public date is the bond, about 67 days out.

Want a bid-ready date map for the next 12 months?
```

**PlusVibe:**

```
{{first_name}}

When {{company_name}} puts a bid together, the packet usually assumes license, bond, and coverage on file are already mapped. Next public date is the {{next_item}}, about {{days_left}} days out.

Want a bid-ready date map for the next 12 months?
```

---

### O9 — Office desk pack

**Filled:**

```
Maria

When the qualifier is on a job, Harbor Peak Electric's office still has to watch dates. Next bond date on the public file is about 67 days out.

Want an office desk pack: 12-month calendar the office holds, with reminders before each date?
```

**PlusVibe:**

```
{{first_name}}

When {% if principal_first != blank %}{{principal_first}} is{% else %}the qualifier is{% endif %} on a job, {{company_name}}'s office still has to watch dates. Next {{next_item}} date on the public file is about {{days_left}} days out.

Want an office desk pack: 12-month calendar the office holds, with reminders before each date?
```

---

### O10 — LLC entity pack

Segment: LLC only.

**Filled:**

```
Maria

For an LLC like Harbor Peak Electric, the renewal letter is still only one piece. Bond and coverage on file sit beside the license on the public record. Next date up is the bond, about 67 days out.

Want an LLC entity pack: a 12-month map built for how your entity actually shows up on file?
```

**PlusVibe:**

```
{{first_name}}

For an LLC like {{company_name}}, the renewal letter is still only one piece. Bond and coverage on file sit beside the license on the public record. Next date up is the {{next_item}}, about {{days_left}} days out.

Want an LLC entity pack: a 12-month map built for how your entity actually shows up on file?
```

---

### O11 — Multi-class map

Segment: `class_count` ≥ 2.

**Filled:**

```
Maria

Harbor Peak Electric carries more than one class on the license. Dates still hide across letter, bond, and coverage on file. Next public date is the bond, about 67 days out.

Want one 12-month map across every class, not a separate sticky note per trade?
```

**PlusVibe:**

```
{{first_name}}

{{company_name}} carries more than one class on the license. Dates still hide across letter, bond, and coverage on file. Next public date is the {{next_item}}, about {{days_left}} days out.

Want one 12-month map across every class, not a separate sticky note per trade?
```

---

### O12 — Coverage-weighted trade pack (roofing example)

Segment: C-39 / C-20 / C-8; prefer when coverage is hot or always name it.

**Filled (roofer, coverage hot, 52 days):**

```
Maria

For a roofing shop like Lakeview Roofing in Fresno, coverage on file is not side paperwork. Public file shows that date about 52 days out.

Want a 12-month trade pack that treats coverage on file, license, and bond as first-class dates for the office?
```

**PlusVibe:**

```
{{first_name}}

For a {{trade_plain}} shop like {{company_name}} in {{city}}, coverage on file is not side paperwork. Public file shows the next {{next_item}} date about {{days_left}} days out.

Want a 12-month trade pack that treats coverage on file, license, and bond as first-class dates for the office?
```

---

### Email 3 — shared closer (all offers)

```
{{first_name}}

That proof note was only the front of {{company_name}}'s year.

On a short phone walkthrough (about 10 to 12 min) I can show the rest of the map and how texts and emails would land before each date so the office sees them in time for permits, pay, and bids.

Can I try you at {{phone}}, or is there a better number?
```

---

## 7) Objections (short)

| They say | We say |
|----------|--------|
| “We already have those dates.” | Good for one or two items. These offers are the year map, the gap card, the desk sheet, or the reminder dry-run — not a copy of the letter. |
| “CSLB already mails us.” | That is why the gap card / file side exists. Want that one-pager? |
| “Just email me details.” | Happy to. Worth 15 minutes to see the full map live? |
| “Not right now.” | Understood. With about {{days_left}} days to the next {{next_item}} date, can we check back before that window gets tight? |
| Price | We tailor every calendar to the business, so pricing depends on how complex yours is: how many licenses, entities, cities and crews you have. |

Never promise they will “never miss” a deadline, payment, or bid.

---

## 8) Inbox / never-say

- Phone first (10–12 min) → Teams 30 min demo  
- CC Haroon (haroon.elgabalawy@codicen.com, 626-634-9044) and Idris (idris.elgabalawy@codicen.com, 626-390-1958)  
- Hours: 8am–5pm PDT  
- Never: prices, client results, file/renew/pay, legal advice, CSLB endorsement, “your license is at risk/lapsed,” fake urgency, Email 1 call ask  

---

## 9) Wave plan

1. **Wave 1a:** O1 vs O2 vs O5 on ICP1 OM ≤120d (even split).  
2. **Wave 1b:** Winner vs O3 on bond-hot ≤60d.  
3. **Wave 2:** O7 Owner lane + O12 trade lane.  
4. **Wave 3:** O9 / O10 / O11 on matching firmographic cuts.  
5. City/EPA/DIR only after they name cities.

---

## 10) Checklist

- [ ] Segment cut matches the offer ID  
- [ ] Email 1 sells a **named asset**, not “your own dates back to you”  
- [ ] Countdown factual if used  
- [ ] Spam-guard + never-say  
- [ ] Email 2 = proof of *that* offer  
- [ ] Email 3 = phone for rest + reminders  

---

## Premise again

**Do not** offer a photocopy of the public file.  
**Do** segment the list, pick a job-to-be-done (gap card, prep pack, dry-run, permit-clear view, collect-clear map, bid map, desk pack, LLC pack, multi-class map, trade pack, or full-year calendar), prove it small, then call to install the reminder system.
