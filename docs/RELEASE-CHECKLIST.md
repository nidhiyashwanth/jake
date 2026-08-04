# Release checklist

Use this checklist for a release candidate. A checked item must link to real
evidence; an unchecked item is a hold, not a verbal waiver.

## Candidate identity

- [ ] Exact Git SHA and image digests recorded.
- [ ] Migration head and workflow/threshold hashes recorded.
- [ ] X-01 clean-checkout CI run is green.
- [ ] `.env` and deployment secrets come from the correct secret manager.
- [ ] Storage, retention, and provider budgets are within their configured caps.

## Product acceptance

- [ ] Signed baseline is present and referenced by value events.
- [ ] Shadow-mode comparison and weekly demos are recorded.
- [ ] Golden set has at least 100 cases, 20 exceptions, and 3 injection canaries.
- [ ] Evaluation gate blocks the intentionally failing candidate.
- [ ] Sampled audit is at least 2%; false-auto rollback was rehearsed.
- [ ] Ten-business-day acceptance counts meet the explicit SOW thresholds.
- [ ] Value ledger reconciles with zero orphan events.
- [ ] Redacted audit pack is generated and its access is logged.
- [ ] A non-builder completed the role walkthrough and worker-failure drill.

## Known limitations to disclose

- OCR/image-only interpretation and document types outside the signed v1 list
  are held for human handling; they are not silently verified.
- External provider delivery, OIDC/JWT, KMS, object storage, PITR, and customer
  notification routes require deployment configuration and real sandbox access.
- Local development identity is never a production authentication path.
- Model-assisted extraction remains bounded by deterministic workflow control,
  policy rules, confidence routing, sampled audit, and human review.
- Straight-through rate can degrade when vendor templates, regulations, sender
  patterns, provider APIs, or model versions change; maintain the golden set,
  taxonomy, thresholds, and drift review.

## Data export and deletion

- [ ] Customer can export the value ledger and redacted audit pack.
- [ ] Export access events are visible to an auditor.
- [ ] Retention dry-run, legal-hold behavior, source deletion, and derived
      metadata retention were demonstrated.
- [ ] Customer-owned source copies and provider retention terms are documented.

## Promotion, rollback, and support

- [ ] Promote the same image digests that passed CI; do not rebuild between
      staging and production.
- [ ] Confirm database head compatibility before application rollback.
- [ ] Use a forward repair migration for schema problems; never downgrade a
      production database as an application rollback.
- [ ] Run the restore drill and record RPO/RTO evidence.
- [ ] Fill the route keys in `docs/SUPPORT-ESCALATION.md`.
- [ ] Record the hypercare owner, customer workflow owner, security route, and
      next maintenance review.
