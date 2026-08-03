# T-01 tenancy verification

`contract.json` is the black-box contract exercised by `scripts/verify-tenancy.ps1`.
The verifier uses the real Docker Compose PostgreSQL service and the HTTP API. It
does not connect to SQLite, seed tables directly, mock an API response, or print
credentials.

## Scope

The run creates two synthetic tenants, two workspaces per tenant, and one
synthetic principal for each canonical role in each tenant:

`owner`, `admin`, `builder`, `operator`, `viewer`, and `auditor`.

It then verifies:

- registration, login, bearer sessions, session revocation, and active workspace context;
- owner/admin workspace and membership management;
- the canonical role matrix at the existing F01 API boundary;
- cross-workspace and cross-tenant read/write denial;
- disabled-membership and revoked-session denial;
- append-only audit/access evidence for login, context changes, denials, membership/session changes, and sensitive F01 operations;
- the existing vendor, document upload, verification, review correction, status-history, and ledger flow under tenancy context;
- deterministic cleanup of the named Compose project and the existing Docker storage guard.

## Contract assumptions

T-01 has not yet published an implementation API contract in the product
documents. The least-surprising HTTP contract is therefore recorded explicitly
in `contract.json` and its `assumptions` array. In particular, the verifier
expects normal authenticated organization/workspace/membership routes rather
than a test-only database seed endpoint. A backend that chooses different route
names or response shapes must either document and align that contract before
running this verifier or update this file in the same reviewed T-01 change.

The requested `reviewer` label is not silently treated as a canonical role. If
the implementation exposes a documented reviewer alias, the coordinator must
record its mapping to one or more canonical capabilities before extending the
matrix.

## Running

Static contract and PowerShell syntax checks, which do not need Docker or `.env`,
run with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-tenancy.ps1 -StaticOnly
```

The full run requires the ignored repository-root `.env` and an available Docker
engine:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-tenancy.ps1
```

The verifier never creates or prints `.env`. It starts a separate Compose
project named `ai-ops-platform-t01`, preserves the named PostgreSQL volume, and
stops/removes only that project on exit unless `-KeepRunning` is supplied.
