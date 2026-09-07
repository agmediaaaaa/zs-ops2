# MARS RESPONSE MATRIX
## Skilled-trade & precision manufacturing staffing — workspace `6a8d53c5977bb5537e41fcf2`

Use with `08-inbox-management/SOP.md`. Classification and hygiene live there. This file is **what to send**.

---

## 1. CLIENT SNAPSHOT (DO NOT IMPROVISE PAST THIS)

| Item | Spec |
|---|---|
| Brand on signature | Mars Staffing LLC |
| Founder | Matt Arias |
| Calendar | https://calendly.com/matt-mars-staffing/15min |
| Timezone on times | **PST** unless the lead specified otherwise |
| Who they sell to | Plant / ops / hiring managers at US manufacturing facilities (core footprint: California / Inland Empire / Greater LA, plus US shops) needing CNC, Swiss turn, tool & die, certified welders, maintenance, quality, shop-floor leads |
| What Step 1 already promised | Candidate-led sourcing. *No long recruiting agreements up front. Review screened profiles first, then decide if an interview makes sense. Share JD / specs → 2–3 screened write-ups in 4–5 days.* |
| Pain already named | Overtime burnout, machine downtime, delivery delays, job-board turnover |
| What you never promise | A named candidate you have not pulled, that you replace HR, exclusive contracts, ITAR/union terms you do not own |

### Campaigns currently configured (context only)

| Campaign | Role in inbox |
|---|---|
| Generic | Resume-preview / backup-on-file / floor inventory. Categories 2, 4, 5. |
| Enterprise & Defense (200+ FTE or defense/aerospace) | Tight-tolerance / quality-bar language. Categories 4 and 8. |
| Stable & Mid-Market (11–200 FTE, 0–10% growth) | Stale seats, overtime fatigue, retention reframe. Categories 5, 6. |
| High-Growth Scalers (12-mo growth >10%) | Order ramp vs recruiting lag. Category 9 if volume. |

### Allowed dictionary

craft talent · screened profiles · write-ups · workstations · overtime · tolerances · setup · controls (Haas / Mazak / Doosan) · backup on file · floor · shift · wage

### Banned dictionary

acquisitions · valuations · EBITDA · multiples · sell-side · PE fund · “mandate”

---

## 2. CLASS → CATEGORY ROUTER

| If the inbound is… | Category | Rule |
|---|---|---|
| Open to a call / “we can’t find machinists” | 1 | 1 |
| Sends a JD / specs immediately | 2 | 1 + delivery commitment |
| Fees / markup / exclusivity / terms | 3 | 2 |
| “Do you have candidates in [city / control]?” | 4 | 2 |
| Fully staffed / no openings | 5 | 2 |
| “We have in-house HR / recruiting” | 6 | 2 |
| Talk to [Plant Manager / Ops] | 7 | 1-route |
| Union / ITAR / defense compliance / DOD flow-down | 8 | 3 |
| Volume ramp / custom bill rate / temp-to-perm tiers | 9 | 3 |
| Already have a staffing firm | 10 | 2 |
| “Just send resumes” with no specs | 11 | 2 |
| Stop / unsubscribe / hostile | SOP Part 7 | — |

---

## 3. SEND-READY CATEGORIES

Fill `{{first_name}}`, `{{sender_first_name}}`, `{{custom_talent_type}}`. Replace example clock times with real future **PST** slots.

After send: follow SOP Part 5. Category 2 also starts the **3–4 business-day** write-up clock.

---

### Category 1 — Direct interest / open to a call

- **Rule:** 1  
- **Label:** `INTERESTED` → `MEETING_BOOKED` once locked  
- **Sequence:** Pause  
- **Example inbound:** “Yes, we are having a tough time finding machinists. Let’s do a quick call.”

```text
Hi {{first_name}},

Glad to connect.

Do either of these windows work for a brief 10-minute call to discuss what your floor needs?
- Tomorrow (Tuesday) at 1:30 PM PST
- Wednesday at 10:00 AM PST

Or feel free to grab a time that fits your floor schedule directly here:
https://calendly.com/matt-mars-staffing/15min

Best,
{{sender_first_name}}
```

**Do not:** ask current agency spend, open-role count, or bill-rate before giving times.

---

### Category 2 — Prospect sends a job description immediately

- **Rule:** 1 + delivery commitment  
- **Label:** `JD_RECEIVED` + `INTERESTED`  
- **Sequence:** Pause  
- **Clock:** 2–3 screened write-ups in **3–4 business days** (tighter than the 4–5 day cold-email outer bound — hit the inner bound).  
- **Also:** 5–10 min calibration call so the pull matches shift / wage / machine.  
- **Example inbound:** “Here is the JD for our CNC Lathe setup operator. Let’s see what you have.”

```text
Hi {{first_name}},

Received, thank you. Reviewing the specifications now.

We are pulling 2–3 screened profiles from our pipeline who have verified experience on these setups and hold tight tolerance without a long ramp. I will have those candidate write-ups in your inbox within 3–4 business days.

To make sure we only send candidates that match your exact shift, wage, and machine requirements, would you have 5–10 minutes tomorrow afternoon for a quick calibration call?

You can lock in a quick time here:
https://calendly.com/matt-mars-staffing/15min

Best,
{{sender_first_name}}
```

**Operator follow-through (same session):** log JD filename, role, due date, and whether calibration is booked. Missing the due date is a broken Step-1 promise.

**Do not:** attach generic resumes in the first reply. Do not wait for the calibration call to **start** the pull — wait for it to **filter** the pull.

---

### Category 3 — “What are your fees / markup / terms?”

- **Rule:** 2  
- **Incentive:** $0 to review profiles; no exclusivity; rate card for **their trade** on a 10-min call.  
- **Label:** `INTERESTED`  
- **Example inbound:** “What is your fee percentage or markup? We do not sign exclusive staffing contracts.”

```text
Hi {{first_name}},

We work on a straightforward performance model: zero upfront retainer, no exclusivity required, and no cost to review screened candidate summaries. You only pay if you interview and decide to bring someone onto your floor.

Our standard fee is a competitive flat percentage upon hire, backed by a 60-day replacement guarantee.

If you have an active seat or want to see the exact rate card for {{custom_talent_type}}, happy to jump on a quick 10-minute call to share the details and see what profiles we have available in your area.

Do you have a few minutes this Wednesday or Thursday?

Best,
{{sender_first_name}}
```

**Do not:** quote a made-up percentage in Unibox. Exact rate card = call. Volume / custom tiers = Category 9.

If `{{custom_talent_type}}` is empty, use the role they named in the email (“CNC setup,” “TIG welder”) or “that seat.”

---

### Category 4 — “Do you have candidates in [city / machine control]?”

- **Rule:** 2  
- **Incentive:** Confirm footprint, then **2 tailored write-ups** after a 10-min floor-needs pass — not a résumé dump.  
- **Label:** `INTERESTED`  
- **Example inbound:** “Do you have 5-axis Haas CNC machinists in Ontario, CA right now?”

```text
Hi {{first_name}},

Yes, Southern California precision machining is right in our core footprint. We maintain active files on trade-tested CNC operators and setup machinists across the Inland Empire and Greater LA who have proven backgrounds on Haas, Mazak, and Doosan controls.

Rather than sending general resumes, I can pull 2 relevant candidate write-ups that match your exact machine setup and tolerance requirements.

Would you have 10 minutes tomorrow or Wednesday to review what your floor needs so I only send exact matches?

You can also pick a quick time here:
https://calendly.com/matt-mars-staffing/15min

Best,
{{sender_first_name}}
```

**Geo honesty:** SoCal / Inland Empire / Greater LA can be confirmed as core. For a city **outside** that footprint, do not fake local inventory. Say you will check the file for that ZIP and still book 10 minutes. If you already know it is outside coverage → Rule 3 rather than a yes.

---

### Category 5 — “We are fully staffed / no openings”

- **Rule:** 2  
- **Incentive:** Preventative backup profile on file at $0 so a two-week notice does not kill machine time.  
- **Label:** `TIMING_DELAY` if they only want a check-back; `INTERESTED` if they name a role for a backup summary  
- **Example inbound:** “Thanks, but our shop is fully staffed at the moment. All shifts are covered.”

```text
Hi {{first_name}},

Glad to hear the floor is in good shape—that is rare in manufacturing right now.

Most plant managers we work with simply keep 1–2 screened profiles on file with us as preventative backup so that when an unexpected two-week notice hits, they don't lose machine capacity scrambling to hire from scratch.

If you'd like to have a vetted backup profile on deck for your hardest-to-fill trade, reply with the role and I'll send one summary for your records—no strings attached.

Otherwise, happy to check back with you in a couple of months.

Best,
{{sender_first_name}}
```

If they name a role: send **one** anonymized summary (not three) and pause. If they take the check-back: pause, resume +60 days, no more pitch this week.

---

### Category 6 — “We have in-house HR / recruiting”

- **Rule:** 2  
- **Incentive:** You do not replace HR. You supply **passive, employed craftspeople** who do not apply on boards when a specialized seat sits open past 30 days.  
- **Label:** `INTERESTED`  
- **Example inbound:** “All recruiting is handled internally by our HR department.”

```text
Hi {{first_name}},

Completely understand. We don't replace internal HR—we act as an external specialist pipeline specifically for trade-tested shop floor talent that doesn't apply to job boards.

Most internal teams lean on us when a specialized machine seat sits open past 30 days and overtime starts wearing on the crew.

If you'd be open to seeing a couple of anonymized candidate profiles for your hardest-to-fill trade to keep in your back pocket, worth a quick 10-minute chat?

Best,
{{sender_first_name}}
```

---

### Category 7 — Referral / routing to operations / plant manager

- **Rule:** 1-route  
- **Label:** `REFERRAL`  
- **Sequence:** Stop pitching the sender. Open/create Dave (or named person) immediately.  
- **Example inbound:** “I don’t handle this directly. Talk to our Plant Manager, Dave (dave@company.com).”

```text
Hi {{first_name}},

Appreciate the direction. I will reach out to Dave directly and reference our note.

Best,
{{sender_first_name}}
```

**Then the same hour**, first-touch Dave:

```text
Hi Dave,

{{original_first_name}} suggested I contact you directly.

We source trade-tested {{custom_talent_type}} for shops that are tired of job-board churn and overtime covering open seats. No long agreement up front — you review screened profiles first.

If a floor seat is currently hard to fill, I can send 2–3 write-ups after a 10-minute calibration. Grab a time here if useful:
https://calendly.com/matt-mars-staffing/15min

Best,
{{sender_first_name}}
Mars Staffing LLC
```

Do not forward the original cold chain unedited.

---

### Category 8 — Complex specs / union rules / ITAR & defense compliance

- **Rule:** 3  
- **Label:** `CEO_HANDOFF`  
- **CC:** Matt Arias  
- **Example inbound:** “We are an ITAR-registered defense contractor with union floor rules (IAMAW) and DOD flow-down requirements. Can your contract accommodate this?”

```text
Hi {{first_name}},

Thank you for raising that. Precision defense and regulated production environments are an area we handle carefully, including US citizenship verification and compliance flow-downs.

I've looped in Matt Arias, Founder and Managing Director of Mars Staffing, who manages our enterprise client agreements and defense facility compliance.

Matt can walk you through our specific vetting protocols and contract terms for union/regulated facilities.

In the meantime, feel free to grab a brief 10–15 minute window on Matt's calendar so we can address your floor requirements directly:
https://calendly.com/matt-mars-staffing/15min

Best regards,
{{sender_first_name}}
Mars Staffing LLC
```

Internal: Slack Matt with facility type, union named, ITAR/DOD flags, and whether they also sent a JD. Do not invent contract language.

---

### Category 9 — Volume expansion / custom bill rate

- **Rule:** 3  
- **Label:** `CEO_HANDOFF`  
- **CC:** Matt Arias  
- **Example inbound:** “We are launching a second shift next month and need 12 CNC operators and 2 shift supervisors. What kind of tiered volume pricing or temp-to-perm rate can you offer?”

```text
Hi {{first_name}},

That is a significant expansion, and we can definitely structure custom tiered volume rates for a 12+ headcount ramp.

I've CC'd Matt Arias, our Founder and Managing Director, who structures our volume enterprise partnerships and oversees talent allocation.

Matt will review the volume tiering and follow up with a tailored commercial structure.

To review the timeline and launch requirements without delay, feel free to lock in 15 minutes with Matt directly here:
https://calendly.com/matt-mars-staffing/15min

Best regards,
{{sender_first_name}}
Mars Staffing LLC
```

Threshold: **~8+ heads or any custom/temp-to-perm structure** → this category. One-off fee question stays Category 3.

---

### Category 10 — Already have a staffing firm / MSP

- **Rule:** 2  
- **Incentive:** No exclusivity; backup craft pipeline when the incumbent cannot fill a specialized seat.  
- **Label:** `INTERESTED`  
- **Example inbound:** “We’re already on a contract with another agency.”

```text
Hi {{first_name}},

No issue — we don't need exclusivity.

Shops usually keep us as a specialist bench for the seats their current firm struggles to fill (tight-tolerance CNC, Swiss, tool & die) so overtime doesn't become the default.

If you want a couple of anonymized write-ups for the hardest trade on the floor, 10 minutes is enough to aim them. Wednesday or Thursday?

Best,
{{sender_first_name}}
```

---

### Category 11 — “Just send resumes” with no JD / no specs

- **Rule:** 2  
- **Incentive:** 2–3 write-ups **after** a 5–10 min calibration (or a pasted spec). Sending blind resumes burns the list and the promise.  
- **Label:** `INTERESTED`  
- **Example inbound:** “Just shoot over some CNC resumes.”

```text
Hi {{first_name}},

Happy to. I don't want to dump generic CNC resumes that miss your control, tolerance, or shift.

Reply with the machine, shift, and target wage — or grab 5–10 minutes here — and I will send 2–3 screened write-ups within 3–4 business days:
https://calendly.com/matt-mars-staffing/15min

Best,
{{sender_first_name}}
```

If they paste specs in the next mail → switch to Category 2 (clock starts then).

---

## 4. MARS PRE-SEND ADD-ON

In addition to SOP Part 8:

- [ ] No M&A / valuation / multiple language  
- [ ] Times are PST (or their stated zone)  
- [ ] Signature is Mars Staffing LLC, not GWS  
- [ ] If Category 2: due date is written in the lead note  
- [ ] If you claimed local inventory, geography is actually core footprint  
- [ ] If Rule 3: Matt is actually on CC  
