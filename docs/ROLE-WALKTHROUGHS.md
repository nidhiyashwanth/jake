# Role walkthroughs

The walkthrough is performed on a synthetic or customer-approved staging
workspace. Each role proves only the capabilities it is meant to have. The
handover owner repeats the tour without the builder present.

## Owner / administrator

1. Sign in through the configured identity boundary.
2. Confirm the active workspace and mode.
3. Review Compliance policy, Confidence lab, Evaluation control, Connections,
   Value ledger, and Governance.
4. Inspect the signed baseline, active workflow and threshold hashes, audit
   events, redacted audit pack, retention dry-run, and incident lifecycle.
5. Confirm the owner can manage policy and support routes without seeing raw
   secret values.

## Builder

1. Open Discovery studio and review the signed baseline and opportunity score.
2. Open Workflows, validate a draft, run the evaluation gate, and inspect the
   immutable version ledger.
3. Open Execution runtime and inspect a pinned run, trace, degraded signal, or
   safe dry-run replay.
4. Confirm a failed evaluation cannot publish and an immutable version cannot be
   edited in place.

## Operator / reviewer

1. Open Field handoff and Review desk.
2. Select the highest-SLA exception, read provenance, correct only the observed
   field, and supply a reason code.
3. Re-run verification and confirm the status history and ledger event.
4. Test the keyboard path, escalation path, and guarded bulk action cap.
5. Confirm the operator cannot manage governance or credentials outside the
   role matrix.

## Auditor / viewer

1. Open Governance and Value ledger in read-only mode.
2. Trace a dashboard value to the immutable event, execution/review record,
   source hash, baseline hash, and audit event.
3. Download the redacted audit pack and confirm access logging.
4. Confirm the role cannot upload documents, change thresholds, call tools, or
   mutate incidents/policies.

## Handover evidence

- [ ] Named non-builder completes the tour and records questions.
- [ ] At least three operators complete the independent operator path.
- [ ] All blocked actions return a role-scoped denial without loading data.
- [ ] The role-tour browser smoke has no console errors, missing auth headers,
      or horizontal overflow.
