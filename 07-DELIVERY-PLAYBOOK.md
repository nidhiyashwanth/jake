# Delivery playbook

How to run an engagement so that it (a) succeeds, (b) makes the next one faster, and (c) produces evidence.

---

## 1. The discovery interview (90 minutes, the most valuable meeting you will have)

Run it with the **person who does the work**, not their manager. Record it with consent. Take structured notes directly into the discovery module.

### Opening
"I'm going to ask you to walk me through this as if I'm your replacement on your first day. I want the boring detail, and especially the parts where you have to think."

### Section A — Shape (15 min)
1. What starts this? Show me where it arrives.
2. How many of these come in a day? Is that steady, or does it spike?
3. Walk me through one, start to finish, clicking through as you go.
4. How long does that take you? And the worst one this week?
5. What do you have open on your screen while you do it?

### Section B — Judgement (25 min) ← the money section
6. What do you check first? Why that?
7. When do you *not* trust what's on the document?
8. Tell me about the last one you had to think about.
9. What would a new hire get wrong in their first month? (Ask this twice, differently.)
10. What do you know that isn't written down anywhere?
11. Who do you ask when you're stuck, and what do you ask them?

### Section C — Exceptions (25 min) ← the moat section
12. What percentage go through cleanly?
13. Give me the five most common ways it goes sideways.
14. Now the weird ones. The ones that happen twice a year.
15. What do you do when [each one]? Where does it go?
16. Which customers/vendors are special, and how?
17. What's the last mistake that got through, and what did it cost?

### Section D — Baseline (15 min)
18. How many people touch this? What fraction of their time?
19. What's the fully loaded cost of one of those people? (Ask the sponsor, not the operator.)
20. How long from arrival to done? Is anyone waiting on it?
21. How often does it have to be redone?
22. What's the backlog right now?

### Section E — Politics (10 min)
23. Whose number gets better if this works?
24. Who will be nervous about this?
25. Has anything like this been tried before? What happened?
26. If this worked perfectly, what would you do with the time?

**Q26 matters more than it looks.** "We'd redeploy them to collections" is a project. "We'd lay them off" is a project that dies in week four when the operators quietly sabotage the pilot. Know which one you're in before you sign.

**Output within 24h:** workflow graph, exception list with frequencies, signed baseline, opportunity score with visible inputs.

---

## 2. The baseline, and why it must be signed

The baseline is the foundation of every claim you will ever make about this engagement. Get it wrong and your ROI is fiction; get it signed and your ROI is evidence.

```
Workflow: Vendor COI verification
Baseline version: 1  |  Period observed: 2026-06-01 → 2026-07-31
Signed: [Sponsor name, title, date]

volume_per_month              1,850 documents
minutes_per_instance (p50)    6.5
minutes_per_instance (p90)    22.0
headcount_touching            3.5 FTE-equivalent
loaded_cost_per_hour          $38
error_rate                    2.8%  (source: internal QA sample, n=200)
cost_per_error                $410  (source: sponsor estimate — flagged as estimate)
cycle_time (recv→verified)    3.4 days
rework_rate                   6%
current_annual_cost           $91,200 labour + $25,500 error cost = $116,700

Method notes: minutes measured by observed sample n=40 over 2 weeks.
Disputed inputs: cost_per_error is a sponsor estimate, not measured. Flagged.
```

Rules:
- Measure, don't ask, wherever you can. Sit with the operator and time 40 instances.
- Record p50 **and** p90. The p90 is where the pain and the automation value live.
- Mark every estimated input as estimated. A baseline with three honest "estimated" flags is more credible than one with none.
- **The sponsor signs it.** Not approves in a meeting — signs a document.
- Re-baseline annually or after any material process change, as a new version. Never edit version 1.

---

## 3. Build cadence (6–8 weeks)

| Week | Focus | Demo shows | Exit criteria |
|---|---|---|---|
| 1 | Ingestion + extraction on their real historicals | "Here are 100 of your documents, parsed" | Field-level accuracy measured on a 50-case golden set |
| 2 | Rules + validation + master data | "Here's what fails your policy and why" | Rules reproduce the operator's judgement on 30 known cases |
| 3 | Confidence + routing + threshold simulator | "At 0.88, 68% goes straight through" | Sponsor picks the threshold |
| 4 | Review desk with their fields and reason codes | Operator uses it live on the call | Operator completes 10 items unassisted |
| 5 | **Pilot with real operators on live volume** (shadow mode) | Side-by-side: system output vs what the operator did | ≥3 operators using it daily |
| 6 | Actions/integrations + notifications | End-to-end on a live item | One real item processed end to end |
| 7 | Ledger, dashboards, audit pack, hardening | Sponsor sees their first value report | Ledger reconciles to baseline |
| 8 | Cutover, training, runbook, handover | Their team runs a day without you | Signed acceptance |

**Non-negotiables:**
- **Weekly demo on real data.** Never a mock. Never a slide. If there's nothing to show, show the failures.
- **Shadow mode before live mode.** Week 5 runs the system alongside the humans and compares. This is how you discover the exceptions nobody mentioned in discovery, and it's the cheapest insurance you can buy.
- **The operator is a stakeholder, not a resource.** They can kill this. Name them in the kickoff, put their reason codes in the system, and credit them when the numbers land.

---

## 4. The exception ritual (how the moat gets built)

Every Friday of the build, and every month thereafter:

1. Export the week's corrections grouped by reason code.
2. Top 3 reason codes by volume → decide for each: **new rule** (deterministic — best), **prompt/schema change** (second best), or **stays human** (fine — say so explicitly and put it in the ledger as a known review driver).
3. Any correction that represents a new class → add to the golden set.
4. Any correction that would have been an expensive mistake if auto-approved → add to the *false-auto* watch set and re-tune the threshold.
5. Update `reason_code_taxonomy` and tell the customer what changed.

After 12 weeks you have a documented exception taxonomy for that workflow at that customer. After three customers in the same vertical, you have one for the *industry*, and build #4 starts at 70% instead of 0%.

---

## 5. SOW skeleton (Production Build)

```
1. Objective
   Put [workflow] into production such that ≥[X]% of monthly volume is processed
   without human touch at a measured error rate ≤[Y]%, measured against
   Baseline v1 dated [date].

2. In scope
   - Sources: [email inbox X, folder Y]
   - Document types: [list — this is the scope boundary, be specific]
   - Systems written to: [list, or "none — output is a reviewed record + export"]
   - Users: up to [N] review-desk operators
   - Environments: production + sandbox

3. Out of scope
   - Any document type not listed in 2
   - Changes to customer systems, data cleanup, ERP configuration
   - Additional workflows
   - Historical backlog processing (available as a separate fixed fee)

4. Acceptance criteria
   Over a continuous 10-business-day acceptance window on live volume:
   - straight-through rate ≥ [X]%
   - measured error rate on auto-processed items ≤ [Y]% (sampled audit, n≥100)
   - all P1 defects closed
   - [N] operators trained and independently processing

5. Customer obligations   ← the clause that saves your project
   - Named sponsor and named workflow owner with [N] hrs/week
   - Historical sample of [N] documents within 5 business days of kickoff
   - Credentials/access within 10 business days
   - Sign-off on baseline before Week 2
   Delays in customer obligations extend the timeline day-for-day.

6. Fee and schedule
   $[fee] fixed. 40% kickoff / 30% week 4 / 30% acceptance.
   Proof Sprint fee credited: $[amount].

7. Change control
   Scope changes priced in writing before work begins. No exceptions,
   including "small" ones.

8. Data, IP and rights   ← see 09-RISKS-COMPLIANCE
   - Customer owns their data and the workflow configuration.
   - Provider owns the platform, and retains a licence to use
     de-identified, aggregated statistics and derived exception patterns
     to improve the platform. Customer documents are not used to train
     third-party models.

9. Post-launch
   30 days hypercare included. Thereafter Run & Improve at $[X]/month.
```

**The acceptance criteria clause is where fixed-fee projects live or die.** Never accept "works well" as a criterion. Never accept an acceptance window shorter than 10 business days. Always define error rate as *measured by sampled audit*, and define who samples.

---

## 6. Handover and the honest failure mode

Handover pack: runbook, architecture note, threshold rationale, reason-code taxonomy, escalation paths, incident history, monthly value report template, and a recorded walkthrough for each role.

**And the thing most agencies never say out loud:** tell the customer, in writing, what will degrade if nobody maintains it. Vendors change templates. Regulations change. Models get deprecated. A workflow with no owner loses ~5–15 points of straight-through rate a year. This is not a scare tactic; it's the honest technical reality, and stating it plainly is exactly how you sell Run & Improve without it feeling like a shakedown.

---

## 7. Delivery quality gates (your internal checklist)

Before you call a build done:
- [ ] Baseline signed and referenced by every value_event
- [ ] Golden set ≥100 cases, ≥20 of them exceptions, ≥3 injection canaries
- [ ] Eval gate wired into publish and actually blocking
- [ ] Sampled audit running at ≥2% of auto-processed volume
- [ ] Every review reason code mapped to either a rule, a prompt fix, or an accepted human-review driver
- [ ] Value ledger reconciles: (auto + reviewed + halted) = total ingested, no orphans
- [ ] Audit pack exports cleanly
- [ ] Runbook tested by someone who didn't build it
- [ ] At least one deliberate failure injected and recovered (kill a worker mid-run)
- [ ] Customer can log in, change a threshold, and see the simulated effect without calling you
