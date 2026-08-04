# Statement of work and acceptance template

Replace bracketed fields before sending. This template is a customer contract
starting point, not legal advice. Customer counsel owns the final language.

## 1. Objective

Put `[workflow]` into production so that at least `[X]%` of in-scope monthly
volume is processed without human touch at a measured auto-processed error rate
of at most `[Y]%`, measured against signed baseline version `[N]` dated `[date]`.

## 2. In scope

- Sources: `[customer-owned inbox/folder/API]`
- Document types: `[explicit v1 list]`
- Systems written to: `[list, or reviewed record plus export]`
- Users and seats: `[count and roles]`
- Environments: production plus synthetic sandbox
- Retention, export, and deletion policy: `[customer policy reference]`

Anything not listed is halted or routed to a human and is subject to written
change control.

## 3. Acceptance criteria

During a continuous 10-business-day acceptance window on representative volume:

- straight-through rate is at least `[X]%`;
- auto-processed error rate is at most `[Y]%`, measured by an auditor's sample
  of at least 100 auto-processed cases;
- at least 2% of auto-processed volume is sampled for audit;
- the signed baseline, golden set, injection canaries, value ledger, and redacted
  audit pack are present and reconciled;
- all P1 defects are closed;
- `[N]` named operators complete the role walkthrough independently;
- a deliberate worker failure is recovered without losing or duplicating a
  durable side effect; and
- the workflow owner signs the handover and rollback rehearsal.

The platform verifier computes the rates from case counts. A dashboard label or
model confidence value is not acceptance evidence.

## 4. Customer obligations

- Name a sponsor and workflow owner with `[hours]/week` available.
- Provide `[N]` representative historical documents within `[days]` business
  days, with rights to use them in the evaluation.
- Approve the baseline before evaluation.
- Provide sandbox/production connector access through the secret manager.
- Provide named support and escalation routes before cutover.

Customer delays extend the acceptance window day for day; scope changes are
priced and approved in writing before implementation.

## 5. Data, IP, and model boundary

The customer owns its documents and workflow configuration. The platform keeps
the application and deployment code. Customer documents are not used to train
third-party models; model registrations default to `no_training`. Export,
retention, legal hold, and deletion follow `docs/GOVERNANCE.md`.

## 6. Post-launch

`[30]` days of hypercare are included. After hypercare, the customer chooses a
named owner and a Run & Improve service. The customer acknowledges that vendor
templates, regulations, provider APIs, and model behavior can reduce
straight-through rate unless the taxonomy, golden set, and thresholds are
maintained.
