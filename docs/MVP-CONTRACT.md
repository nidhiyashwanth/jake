# MVP contract: vendor compliance verification

- **Status:** active feature F01; this is the only product scope currently in flight.
- **Source:** `11-WEDGE-COMPLIANCE-DOCS.md`, `05-ARCHITECTURE.md`, and the harness Definition of Done.
- **Applicability:** first local vertical slice; replace or extend only after F01 passes end to end.
- **Expiry:** revisit after the first real operator feedback cycle, not while the path is still unverified.

## The promise

Given a vendor and a COI-shaped document, the system produces a transparent verification result: normalized observed fields, deterministic requirement checks, explicit exception reason codes, a human correction path, a point-in-time compliance status, and an auditable event trail.

The MVP must be usable locally without external model credentials, inbox access, OCR services, or a hosted database. The extraction boundary must be replaceable later; the first implementation may use deterministic text/PDF parsing over representative fixtures.

## In scope

- Create and list vendors.
- Upload a text or PDF document tagged as `COI`.
- Extract the minimum fields: named insured, certificate holder, GL occurrence limit, policy expiry, additional-insured flag, and waiver-of-subrogation flag.
- Apply a seeded requirement set: named insured match, certificate holder match, minimum GL occurrence limit, policy not expired, additional insured present, and waiver of subrogation present.
- Create review tasks for failed or uncertain checks.
- Edit extracted values through a review action and re-run checks.
- Append a new `compliance_status` snapshot after every verification/review decision; never overwrite historical snapshots.
- Show the current vendor status, failed requirements, observed/required values, and ledger/audit events.

## Explicitly out of scope for F01

- Email chasing, broker escalation, mailbox or cloud-drive connectors.
- OCR for image-only documents.
- LLM calls or provider credentials.
- Authentication, multi-tenancy, billing, permissions, and production deployment.
- Full document taxonomy beyond the generic `doc_type` field and the COI path.
- A visual workflow editor, Temporal, Kubernetes, or a custom observability product.

## API contract

The API is versioned under `/api` and returns JSON. Error responses must include a stable `code` and repairable `message`.

| Method | Route | Behavior |
|---|---|---|
| GET | `/api/health` | Returns service readiness and database status. |
| POST | `/api/vendors` | Creates a vendor from `legal_name`. |
| GET | `/api/vendors` | Lists vendors and their latest status. |
| GET | `/api/vendors/{vendor_id}` | Returns vendor details, documents, latest status, and recent events. |
| POST | `/api/vendors/{vendor_id}/documents` | Accepts multipart `file` and `doc_type=COI`; stores and extracts it. |
| POST | `/api/documents/{document_id}/verify` | Runs deterministic checks and creates a status snapshot/review tasks. |
| GET | `/api/vendors/{vendor_id}/status` | Returns the latest status plus failed requirements and evidence. |
| GET | `/api/vendors/{vendor_id}/ledger` | Returns append-only verification/review events. |
| GET | `/api/reviews` | Lists open review tasks. |
| PATCH | `/api/reviews/{review_id}` | Applies a human correction and re-runs the affected verification. |

## Minimum persistence model

Use a modular repository boundary even with SQLite: `vendors`, `compliance_documents`, `compliance_checks`, `review_tasks`, `compliance_status`, and `audit_events`. `compliance_status` is append-only and includes `vendor_id`, `document_id`, `as_of`, `status`, `failing_requirements`, `computed_by_version`, and a JSON evidence payload. Rule evaluation is versioned and deterministic.

## Definition of Done

F01 is complete only when `scripts/verify-mvp.ps1` starts the real local service, exercises the full API path, proves a failing check becomes compliant after a review correction, proves at least two historical status snapshots remain, and confirms the UI or API exposes the audit evidence. A unit test alone cannot pass F01.
