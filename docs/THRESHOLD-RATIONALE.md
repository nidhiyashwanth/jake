# Threshold rationale

The confidence policy is a control-plane decision, not a model self-report.
The active policy must be versioned to a workspace and immutable workflow
version. The owner changes it through the Confidence lab and records the reason.

## Release-candidate policy

- Candidate auto threshold: `0.88`.
- Review band: `0.60` through `<0.88`.
- Halt band: `<0.60`, missing evidence, unknown document type, or an explicit
  policy rule failure.
- Minimum sampled audit rate: `2%` of auto-routed cases; the customer may set a
  higher rate.
- Any sampled false-auto opens an alert and records the prior threshold for
  rollback. A threshold rollback is a new immutable policy version.

## Why these values are provisional

The number `0.88` is a release-candidate starting point, not a promise of
accuracy. It should be selected against the golden-set route curve and the
customer's cost of a missed requirement. The acceptance window must measure
straight-through rate and auto-processed error rate separately. A higher rate
is not a win if it moves expensive exceptions into auto approval.

## Review questions

Before live mode, the workflow owner answers:

1. Which requirement failures must always halt regardless of confidence?
2. What is the value-at-risk of an incorrect auto route?
3. Which senders, document types, or new templates need a lower threshold?
4. What sampled-audit result triggers rollback and customer notification?
5. Who can change the policy, and who reviews the immutable audit event?

The model may supply bounded extraction signals. It does not own top-level
orchestration, authorization, threshold selection, or ledger writes.
