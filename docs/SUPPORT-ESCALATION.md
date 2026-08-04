# Support and escalation contract

Contact values are environment/customer configuration. Do not commit personal
phone numbers, credentials, or private incident links. Fill the route keys in
the deployment notification system before cutover.

| Priority | Example trigger | First route key | Acknowledge | Customer update |
|---|---|---|---:|---:|
| P1 | tenant isolation, secret exposure, duplicate side effect, unsafe auto approval, total outage | `platform.p1` + `customer.incident.owner` | 15 minutes | every 30 minutes |
| P2 | queue degradation, connector outage, material drift, failed backup | `platform.p2` + `customer.workflow.owner` | 1 hour | every 4 hours |
| P3 | single review task, cosmetic issue, documentation question | `platform.support` | 1 business day | at resolution |

## Escalation record

- Platform on-call route: `[secret-manager/notification route key]`
- Customer sponsor route: `[customer incident owner route key]`
- Customer workflow owner: `[workflow owner route key]`
- Security/privacy route: `[security route key]`
- Provider escalation references: `[connector-specific route keys]`

Every incident records severity, detection time, impact, owner, customer
notification status, timeline, root cause, corrective action, and postmortem
reference. A P1 cannot be accepted as closed until the workflow owner confirms
service, queue, ledger, audit, and export behavior.
