# Operations runbook

This runbook is the operational handover surface for the vendor-compliance
wedge. It assumes the deployment, migration, secret, and recovery contract in
`docs/DEPLOYMENT.md`; it never contains credentials.

## Start-of-day checks

1. Confirm the API health endpoint, worker heartbeat, queue age, and failed or
   dead-letter counts.
2. Confirm the active workflow version, threshold policy version, connector
   allow-list, and last successful backup timestamp.
3. Review open review tasks by SLA and any false-auto or drift alerts.
4. Process only the document types in the signed SOW. Halt unknown types.

## Operator path

1. Open the Field handoff or Review desk queue.
2. Start with the vendor, exact requirement, source provenance, and reason code.
3. Correct only what the source proves; record a reason-coded correction.
4. Re-run verification and confirm the new point-in-time status.
5. Do not approve coverage, negotiate terms, or send a chase without the
   customer-owned connector and explicit approval boundary.

## Weekly control ritual

- Export corrections by reason code.
- Select the top three drivers and classify each as a deterministic rule,
  prompt/schema change, or accepted human-review driver.
- Add new expensive exceptions to the golden set and false-auto watch set.
- Review threshold simulation, sampled-audit rate, ledger reconciliation, and
  drift alerts with the workflow owner.
- Demo representative documents and failures to the customer; never substitute
  slides for the live evidence.

## Deliberate worker failure and recovery

During a sandbox drill, stop one worker after claim and before completion.
Confirm the lease becomes recoverable, no external receipt is duplicated, the
outbox is dispatched once, the run is visible in the inspector, and the
operator receives a degraded-mode signal. Record the run ID, timestamps, and
recovery result in the acceptance evidence bundle.

## Incident response

1. Classify P1/P2/P3 using `docs/SUPPORT-ESCALATION.md`.
2. Halt automatic routing if there is a false-auto, policy, tenant-isolation,
   secret, or duplicate-side-effect risk.
3. Open a governance incident with severity, impact, customer-notification
   state, timeline, root cause, and owner.
4. Preserve relevant evidence under legal hold when required. Do not copy raw
   PII or prompt bodies into chat or an incident export.
5. Perform an application rollback to the last compatible image digest when
   required; restore service using that digest and use a forward repair
   migration for schema defects. Verify the queue, ledger, audit trail, and
   connector receipts before resuming.

## Backup, export, and deletion

Run the checked-in backup and restore scripts with the production secret manager
and versioned encrypted object storage. Export value/audit data from the UI or
API with the access log intact. For deletion, run a retention dry-run first,
respect legal holds, delete eligible source bytes, and verify that derived
metadata and hashes remain as defined by `docs/GOVERNANCE.md`.

## Clock-out

Record the active release SHA, migration head, workflow/threshold hashes, open
incidents, unresolved exceptions, backup evidence, and next action. Never leave
an unowned P1, an unreviewed false-auto, or a secret in a log.
