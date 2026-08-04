# Governance and privacy contract

G-01 is the canonical contract for governance behavior. Product code, verifiers,
runbooks, and later deployment work should link here instead of restating these
rules.

## Evidence boundaries

- Governance artifacts are workspace-scoped metadata records with a source
  reference, hash, MIME type, classification, PII status, and retention state.
- PII classification records field paths and the versioned classifier only. It
  never stores the detected email, phone number, token, or other raw value.
- Audit and export payloads redact PII, bearer material, secrets, private-key
  material, and raw prompt bodies. Hashes and policy markers may remain as proof.
- Field-level governance access is role-gated: owners and admins manage all
  governance controls; auditors can read and export; other delivery roles do
  not receive governance data.

## Retention and deletion

- Retention policies are workspace-scoped and support dry-run evidence before a
  deletion run.
- A legal hold wins over a due policy. Held sources are reported as skipped.
- Eligible compliance-document source bytes may be deleted, but derived
  verification metadata and hashes remain for auditability. Verification of a
  source-deleted document returns an explicit source-deleted response.

## Models, incidents, and audit packs

- Model registrations default to `no_training`. Customer training requires an
  explicit `customer_opt_in` policy and reference.
- Model changes, incidents, incident timelines, exports, and governance reads
  are recorded through the existing workspace-scoped audit/access paths.
- A dated audit pack includes published workflow/version hashes, model registry
  and change history, oversight thresholds, connector/data-flow summaries,
  value rollups, incidents, retention state, and redacted audit/access logs.
- PostgreSQL mutation triggers protect append-only audit, access, credential,
  model-history, retention-run, and audit-pack evidence. Application checks are
  not the sole immutability boundary.

## Verification

Run the focused gate from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-governance.ps1 -StaticOnly
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-governance.ps1 -KeepRunning
```

The real gate must exercise Compose/PostgreSQL, the authenticated Governance
surface, role/request scoping, classification/redaction, legal-hold retention,
incident lifecycle, audit-pack download, access logging, and direct database
mutation rejection.
