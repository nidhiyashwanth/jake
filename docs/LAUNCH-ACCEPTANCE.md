# Launch acceptance contract

This is the canonical release-candidate contract for `LAUNCH-01`. It converts
the delivery playbook into evidence that a customer can inspect without relying
on a founder's memory or a successful demo.

The checked-in acceptance fixture is synthetic. It proves that the release gate
can evaluate the required shape; it is not customer acceptance and it contains
no customer documents, credentials, or contact details. A real engagement must
replace the fixture with customer-owned evidence and a signed baseline before
live mode.

## Release boundary

The first live workflow is vendor and subcontractor compliance-document
verification with proof. The v1 document boundary is ACORD 25, ACORD 855,
W-9, state contractor licence, business licence, workers-comp exemption,
OSHA 10/30, MSA/subcontract agreement, and conditional/unconditional
lien-waiver documents. A document outside this list is halted or routed to a
human; it is never silently treated as compliant.

## Acceptance thresholds

| Control | Release candidate requirement | Evidence owner |
|---|---:|---|
| Signed baseline | Versioned, hashed, sponsor-signed, referenced by value events | Sponsor/workflow owner |
| Shadow mode | At least 5 observed days before live-mode acceptance | Workflow owner |
| Golden set | At least 100 cases, at least 20 exceptions, at least 3 injection canaries | Builder/evaluator |
| Straight-through rate | At least 80% of the acceptance window | Product owner |
| Auto-processed error rate | At most 2%, measured on at least 100 auto cases | Auditor |
| Sampled audit | At least 2% of auto-processed volume, with false-auto rollback available | Auditor |
| P1 defects | Zero open P1 defects at acceptance | Platform owner |
| Operator independence | Three trained operators complete the role tour without builder intervention | Customer workflow owner |
| Ledger | Auto + reviewed + halted equals ingested; zero orphan events | Sponsor/auditor |
| Handover | Runbook tested by a non-builder and rollback rehearsal recorded | Customer workflow owner |

The target values are explicit in
`tests/launch/acceptance-manifest.json`. The verifier recomputes rates from
counts; it does not trust a supplied pass/fail flag.

## Required sequence

1. Run the discovery interview and record the observed workflow, exception
   taxonomy, baseline inputs, and customer obligations.
2. Obtain a signed baseline before the first production-like evaluation.
3. Run shadow mode beside the existing operator path. Hold a weekly demo on
   representative documents and show failures as well as passes.
4. Run the golden set, injection canaries, threshold simulation, sampled-audit
   policy, and deliberate worker-failure recovery.
5. Run the 10-business-day live-mode acceptance simulation. Close P1 defects,
   reconcile the value ledger, generate the redacted audit pack, and record
   operator independence.
6. Handover the runbook, threshold rationale, taxonomy, support routes, export
   and deletion instructions, incident history, value-report template, known
   limitations, and rollback plan.
7. Promote the exact release SHA and image digests only after the X-01 CI gate
   and this release-candidate gate pass.

## Executable evidence

Run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-launch.ps1 -StaticOnly
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-launch.ps1
```

The full gate starts a dedicated `ai-ops-platform-x01` Compose project through
the passing X-01 verifier, runs the browser role tour against the live stack,
recomputes the synthetic acceptance manifest, writes a redacted report under
`artifacts/launch/`, and removes only that named project and its temporary
volume. It never prints `.env` values and never touches a user's base Compose
project.

## Ship / hold rules

Ship only when every required evidence item is present and the verifier passes.
Hold when a baseline is unsigned, a document is out of scope, a canary is
missing, a sampled audit cannot trigger rollback, a ledger does not reconcile,
an operator needs the builder to complete the tour, or any P1 defect remains.
Known limitations are disclosed in `docs/RELEASE-CHECKLIST.md`; they are not
converted into silent acceptance exceptions.
