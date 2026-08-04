# Incident history handover

Incident history is part of the release proof. Record resolved incidents and
deliberate failure drills; do not erase an entry because service recovered.
Raw PII, credentials, prompt bodies, and private provider payloads do not belong
in this document.

## Release-candidate history

| ID | Type | Severity | Detection | Recovery | Customer notification | Status |
|---|---|---|---|---|---|---|
| `synthetic-worker-drill-v1` | deliberate worker failure | test | acceptance gate | lease recovery, no duplicate receipt, audit evidence | not applicable | recovered |

This row is synthetic release-candidate evidence. It is not a customer incident.
Production incidents must use the governance incident API and add their
customer-notification, root-cause, timeline, corrective-action, and postmortem
references before handover.

## Incident record template

- Incident ID and release SHA: `[values]`
- Detected at / resolved at: `[timestamps]`
- Severity and affected workspace: `[values]`
- Trigger, scope, and customer impact: `[redacted summary]`
- Containment and rollback/repair action: `[values]`
- Queue, ledger, audit, connector, and export checks: `[evidence links]`
- Customer notification status and timestamps: `[values]`
- Root cause and corrective action: `[values]`
- Postmortem or follow-up owner: `[reference and role]`
