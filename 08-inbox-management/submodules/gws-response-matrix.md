# GWS RESPONSE MATRIX
## Sell-side M&A advisory — workspace `6a880928da046f3b189bb4e1`

Use with `08-inbox-management/SOP.md`. Classification and hygiene live there. This file is **what to send**.

---

## 1. CLIENT SNAPSHOT (DO NOT IMPROVISE PAST THIS)

| Item | Spec |
|---|---|
| Brand on signature | GWS Advisory Firm |
| Founder | Jonathon Rapacki — `jrapacki@gwsconsulting.co` |
| Calendar | https://calendly.com/jonathon-gws/15min |
| Timezone on times | EST unless the lead specified otherwise |
| Who they sell to | Owners / CEOs of privately held US companies, roughly $5M–$50M+ revenue, industrial / manufacturing / specialty services / B2B |
| What Step 1 already promised | Practical buyer-side valuation read, market-readiness review, mapping acquirer interest. *No assumption they are looking to sell. Not a formal appraisal. Zero commitment. 10–15 min to share peer multiples and buyer rationale.* |
| What you never promise | Named funds in cold email, a formal paid appraisal, that they should sell, FINRA/registration answers you do not own |

### Campaigns currently configured (context only)

| Campaign | Role in inbox |
|---|---|
| C6 — Emerging / Sub-ICP (Generic) | Highest volume. Pattern-interrupt and “not assuming sale” language is already in market. Lean on Category 5 if they push back. |
| C5 — Strategic Value Offer | Valuation / acquirer-map promises. Categories 4 and 6. |
| C4 — Strategic Signals | Inflection (funding, leadership, footprint). Do not over-claim you “saw their transaction.” |
| C3 — Industry and Market Activity | Comp transactions / consolidation. Category 3 and 6. |
| C2 — Growth, Momentum, Value Creation | Growth → acquirer interest. |
| C1 — Owner Exit Planning | Optionality / legacy. Category 5 if they say they are not exiting. |

### Allowed dictionary

targets · mandates · buyer interest · peer multiples · valuation read · optionality · indicative range · strategic operators · platforms · sub-industry

### Banned dictionary

candidates · placements · resumes · markup · bill rate · shop floor · overtime · “we’ll staff that”

---

## 2. CLASS → CATEGORY ROUTER

| If the inbound is… | Category | Rule |
|---|---|---|
| Open to a call / “what does your calendar look like” | 1 | 1 |
| Named a day/time / “send an invite” | 2 | 1 |
| “Who is the buyer?” / name the fund | 3 | 2 |
| “What does this cost?” / fee for the valuation | 4 | 2 |
| “We are not looking to sell” | 5 | 2 |
| “What multiples are buyers paying?” | 6 | 2 |
| “We need an NDA first” | 7 | 2 |
| “Check back in 3–6 months” / busy season | 8 | 2 (pause) |
| Mandate fees, FINRA/SIPC, deal list, registration | 9 | 3 |
| High-value params / “if you have a legitimate buyer…” | 10 | 3 |
| Wrong person / talk to [Name] | 11 | 1-route |
| Already have an investment banker | 12 | 2 |
| “Send me the report by email” | 13 | 2 |
| Stop / unsubscribe / hostile | SOP Part 7 | — |

---

## 3. SEND-READY CATEGORIES

Fill `{{first_name}}`, `{{sender_first_name}}`, `{{company_name}}`, `{{custom_sub_industry}}`, `{{custom_core_specialization}}`, `{{next_quarter_month}}`. Replace the example clock times with real future slots.

After send: follow SOP Part 5 (label, pause/complete, notes).

---

### Category 1 — Direct interest / ready to meet

- **Rule:** 1  
- **Label:** `INTERESTED` → `MEETING_BOOKED` once locked  
- **Sequence:** Pause  
- **Example inbound:** “Sure, I’d be open to a quick call to see what you mean.” / “What does your calendar look like this week?”

```text
Hi {{first_name}},

Glad to connect.

Do either of these windows work for a brief 10–15 minute conversation?
- Tuesday at 11:00 AM EST
- Wednesday at 2:00 PM EST

If another time suits you better, feel free to pick directly here:
https://calendly.com/jonathon-gws/15min

Looking forward,
{{sender_first_name}}
```

**Do not:** ask what they want to cover, ask for financials, restate the full offer.

---

### Category 2 — Prospect proposes a specific time

- **Rule:** 1  
- **Label:** `MEETING_BOOKED`  
- **Sequence:** Pause; complete after invite is out  
- **Operator action before hitting send:** create the calendar event with Google Meet, same day/time/timezone they named, founder + sending identity + prospect.  
- **Example inbound:** “I can do Thursday at 2:00 PM EST. Send an invite.”

```text
Hi {{first_name}},

Thursday at 2:00 PM EST is locked on our end.

I've sent a calendar invite with the Google Meet link over to this email.

Looking forward to speaking then,
{{sender_first_name}}
```

**Do not:** send this copy before the invite exists. Repeat their time exactly.

---

### Category 3 — “Who is the buyer?” / “Name the firm”

- **Rule:** 2  
- **Incentive:** Confidentiality blocks fund names over email; on a call we can share **acquisition criteria** (thesis, size, geography) — not a press-release name.  
- **Label:** `INTERESTED`  
- **Example inbound:** “Who is the buyer you mentioned? What is their name or fund?”

```text
Hi {{first_name}},

We work under confidentiality agreements, so we cannot broadcast specific fund names over cold email.

That said, the groups active in your space right now are well-capitalized strategic operators and private equity-backed platforms looking specifically for established operations in {{custom_sub_industry}}.

Happy to jump on a quick 10-minute call to share their exact acquisition criteria and see if their target parameters align with where {{company_name}} is headed.

Do you have 10 minutes this Wednesday or Thursday afternoon?

Best,
{{sender_first_name}}
```

**Do not:** invent a fund name “just to get the call.” If they insist on a name before any call → Category 10 (founder).

---

### Category 4 — “What does this cost?” / fee for the valuation

- **Rule:** 2  
- **Incentive:** Initial review is $0 / no obligation; the call is to walk **peer multiple ranges**, not to sell a consulting report.  
- **Label:** `INTERESTED`  
- **Example inbound:** “What do you charge for this valuation? We aren’t paying for a consulting report.”

```text
Hi {{first_name}},

There is zero cost or obligation for this initial valuation review.

We provide a practical, buyer-side view of where the market values businesses like {{company_name}} today based on recent transaction data in {{custom_sub_industry}}—not a formal paid appraisal.

If useful, we can walk you through the preliminary multiple ranges and buyer drivers on a quick 10-minute call so you have clear benchmarks for your records.

Would Thursday at 11:00 AM or 3:00 PM EST work for a brief run-through?

Best,
{{sender_first_name}}
```

**Do not:** quote success-fee / retainer / mandate economics. That is Category 9.

---

### Category 5 — “We are NOT looking to sell right now”

- **Rule:** 2  
- **Incentive:** No pressure to sell; value is an **enterprise-value baseline** plus 2–3 drivers that move exit multiples later.  
- **Label:** `INTERESTED` if they engage the chat option; `TIMING_DELAY` if they take “check back next quarter”  
- **Example inbound:** “Thanks, but we have no intention of selling. We’re continuing to grow independently.”

```text
Hi {{first_name}},

Completely understand, and we are not assuming you are looking to sell today.

Most founders we speak with simply find it useful to know what their business would command in the current market, and what 2–3 drivers could increase outside valuation down the road.

If you are open to a brief 10-minute conversation, we can share the high-level multiples we are seeing across {{custom_sub_industry}} so you have that benchmark on hand for future planning.

Worth a quick chat this week, or prefer I check back next quarter?

Best,
{{sender_first_name}}
```

If they reply “check back next quarter” → switch to Category 8. Do not keep selling optionality.

---

### Category 6 — “What multiples are buyers paying in our space?”

- **Rule:** 2  
- **Incentive:** Give a **band**, then the call is where **their** business sits in that band.  
- **Label:** `INTERESTED`  
- **Example inbound:** “What kind of EBITDA multiples are buyers paying right now in our sector?”

```text
Hi {{first_name}},

Across {{custom_sub_industry}}, we are currently seeing transactions settle in the 5x–8x EBITDA range for established operations, with strategic premiums paid for proprietary capabilities like {{custom_core_specialization}}.

The exact spread depends on recurring revenue concentration, margin profile, and customer diversity.

We can put together a high-level indicative range specifically for {{company_name}} and walk through the 2–3 factors that dictate the top of that band on a short 10-minute call.

Open to a brief conversation this Wednesday or Thursday?

Best,
{{sender_first_name}}
```

**Band rule:** 5x–8x is the default public range in this playbook. If the campaign variation already used a different range, **match the variation**, do not contradict it. If `{{custom_core_specialization}}` is empty, delete the “like …” clause.

**Do not:** give a single-point “you’re a 7x” over email.

---

### Category 7 — “We need an NDA signed first”

- **Rule:** 2  
- **Incentive:** Call 1 does not request confidential figures; mutual NDA before any proprietary disclosure.  
- **Label:** `INTERESTED`  
- **Example inbound:** “We don’t share confidential financial details without an executed NDA.”

```text
Hi {{first_name}},

Completely respect that. We routinely sign mutual NDAs before any proprietary data is discussed.

That said, on a brief initial call we don't ask for any confidential figures—our goal is simply to share high-level buyer activity in {{custom_sub_industry}} and see if an M&A valuation read is even relevant for you.

If you'd like our standard mutual NDA ahead of time, let me know and I will send it right over. Otherwise, are you open to a high-level 10-minute chat this week?

Best,
{{sender_first_name}}
```

If they ask for the NDA: send the **standard mutual NDA from GWS files** (do not draft legal yourself). Then keep the booking hook. If no NDA is on file → Rule 3.

---

### Category 8 — Timing delay (“check back in 3–6 months”)

- **Rule:** 2 (pause variant — do **not** keep pushing times)  
- **Label:** `TIMING_DELAY`  
- **Sequence:** Pause. Calendar resume for `{{next_quarter_month}}`.  
- **Example inbound:** “We are in the middle of our busy season. Check back with us early next year.”

```text
Hi {{first_name}},

Understood. I will pause outreach and touch base with you in early {{next_quarter_month}}.

If you'd like me to email over a one-page summary of recent M&A transactions in {{custom_sub_industry}} in the meantime for your records, just let me know.

Wishing you a productive busy season.

Best,
{{sender_first_name}}
```

Set `{{next_quarter_month}}` to the month they named, or the first month of the next quarter if they were vague. Do not send the one-pager unless they ask.

---

### Category 9 — Complex technical / mandate / registration

- **Rule:** 3  
- **Label:** `CEO_HANDOFF`  
- **CC:** Jonathon Rapacki  
- **Example inbound:** “What is your specific mandate fee structure, are you FINRA/SIPC registered, and what deals have you completed in our specific sector under $40M EV?”

```text
Hi {{first_name}},

Thank you for the detailed questions.

I've CC'd Jonathon Rapacki, our Founder and Managing Director at GWS Advisory, who leads our advisory mandates and transaction execution in this sector.

Jonathon will follow up directly with the specific transaction background and regulatory structure you requested.

In the meantime, so we can align schedules without back-and-forth, feel free to grab a convenient 15-minute slot on Jonathon's calendar here:
https://calendly.com/jonathon-gws/15min

Best regards,
{{sender_first_name}}
GWS Advisory Firm
```

Internal: Slack Jonathon with the exact questions, company, campaign, and thread. Do not answer FINRA/fee in your own words.

---

### Category 10 — High-value buyer verification / strict deal parameters

- **Rule:** 3  
- **Label:** `CEO_HANDOFF`  
- **CC:** Jonathon Rapacki  
- **Example inbound:** “We do $18M ARR with 22% EBITDA in precision defense. If you have a legitimate buyer, what are their minimum platform parameters and geographic requirements?”

```text
Hi {{first_name}},

Those parameters fit directly into the core criteria of the buyer groups we are speaking with.

I've looped in Jonathon Rapacki, our CEO & Managing Director, who is actively managing those buyer relationships and can speak directly to their geographic and size criteria.

Jonathon, see {{first_name}}'s profile above regarding {{company_name}}.

{{first_name}}, you can also reserve a time directly on Jonathon's calendar below for a confidential conversation:
https://calendly.com/jonathon-gws/15min

Best,
{{sender_first_name}}
GWS Advisory Firm
```

Only use “fit directly” when size/sector is in-ICP ($5M–$50M+ revenue, relevant industry). If clearly out of ICP, still CC Jonathon — do not freelance a “not a fit” rejection.

---

### Category 11 — Wrong person / referral

- **Rule:** 1-route  
- **Label:** `WRONG_PERSON` or `REFERRAL`  
- **Sequence:** Stop on this lead. Open the referred contact as a new first-touch.  
- **Example inbound:** “I don’t handle this. Talk to our CFO, Priya (priya@company.com).”

```text
Hi {{first_name}},

Appreciate the direction. I will reach out to Priya directly and reference our note.

Best,
{{sender_first_name}}
```

Then email Priya as a **new** thread: short referral opener + same low-friction valuation-read offer + calendar link. Do not forward the original cold sequence.

---

### Category 12 — Already have an advisor / banker

- **Rule:** 2  
- **Incentive:** Second-opinion buyer-side read, no mandate required, $0 for the first conversation.  
- **Label:** `INTERESTED`  
- **Example inbound:** “We already work with an investment bank.”

```text
Hi {{first_name}},

That makes sense — we are not asking you to replace an existing advisor.

What we usually share is a buyer-side view of current multiples and who is actually active in {{custom_sub_industry}}, which some owners use as a second data point alongside their banker.

If useful, we can run that in 10 minutes with no mandate discussion. Thursday 11:00 AM or 3:00 PM EST?

Best,
{{sender_first_name}}
```

---

### Category 13 — “Just send the report / deck by email”

- **Rule:** 2  
- **Incentive:** High-level one-pager or verbal multiples on a call — not a confidential CIM-style file.  
- **Label:** `INTERESTED`  
- **Example inbound:** “Just email me the valuation.”

```text
Hi {{first_name}},

Happy to share a high-level view. We don't send a full write-up cold because the useful part is where {{company_name}} sits inside the {{custom_sub_industry}} range, which takes a few minutes to frame.

I can send a one-page summary of recent transactions in your space after a brief 10-minute call, or walk the ranges live — whichever is easier.

Do you have 10 minutes Wednesday or Thursday afternoon?

Best,
{{sender_first_name}}
```

If they already took Category 8’s optional one-pager: send **only** a non-confidential transaction summary, then stop pushing for that week.

---

## 4. GWS PRE-SEND ADD-ON

In addition to SOP Part 8:

- [ ] No candidate / resume / staffing language  
- [ ] No named fund or buyer  
- [ ] Times are EST (or their stated zone)  
- [ ] Signature is GWS, not Mars  
- [ ] If Rule 3: Jonathon is actually on CC  
