# Monthly value report template

Use one report per workspace and period. Every number must drill into immutable
value events and reference the signed baseline and workflow version; leave
measured error, dollar value, ROI, or payback null when the required evidence is
unknown instead of filling the gap with an estimate.

## Report identity

- Customer / workspace: `[name]`
- Period: `[start]` to `[end]`
- Baseline version / hash: `[signed baseline reference]`
- Workflow version / immutable hash: `[release reference]`
- Threshold policy version: `[policy reference]`
- Prepared by / reviewed by: `[roles and dates]`

## Reconciled activity

| Measure | Value | Evidence route |
|---|---:|---|
| Ingested | `[count]` | value ledger reconciliation |
| Auto-routed | `[count]` | execution events |
| Reviewed | `[count]` | review events |
| Halted | `[count]` | halt events |
| Orphan events | `[count; target 0]` | ledger integrity check |
| Straight-through rate | `[value]` | auto / ingested |
| Sampled-audit rate | `[value; target >=2%]` | sampled audit policy |
| Measured auto error rate | `[value]` | sampled cases and corrections |

## Value and cost

- Minutes saved and method: `[value/source]`
- Errors prevented and method: `[value/source]`
- Cycle-time change versus baseline: `[value/source]`
- Human-touch cost: `[value/source]`
- Model/infrastructure cost: `[value/source]`
- Rework cost: `[value/source]`
- Net value: `[value or unpriced]`
- ROI / payback: `[value or unpriced]`

## Exceptions and decisions

- Top reason codes: `[three codes and counts]`
- New golden-set cases: `[count and rights reference]`
- False-auto events and threshold action: `[none or linked events]`
- Accepted human-review drivers: `[list]`
- Drift or connector incidents: `[linked incident IDs]`

## Attestation

The sponsor confirms that the report is a reconciliation of the immutable
ledger, not a client-submitted total. Attach the CSV/PDF export and redacted
audit pack, then record the export access event and sponsor signature.
