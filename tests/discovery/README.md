# D-01 discovery verification

`contract.json` and `scripts/verify-discovery.ps1` define the black-box D-01
contract. The verifier starts the real Docker Compose stack with PostgreSQL,
creates two workspaces through the HTTP development-login and membership
routes, and exercises discovery, human draft review, signed-baseline, scoring,
RBAC, and audit behavior through HTTP only.

The run deliberately uses two synthetic tracked fixtures:

- `fixtures/discovery.sop.txt`
- `fixtures/discovery.transcript.txt`

They contain no customer data or credentials. Ingestion must return a human-
editable draft graph, exception list, and baseline questions while explicitly
remaining unpublished. The verifier then edits a draft, answers a question,
adds a human exception, signs version 1, attempts a forbidden mutation, creates
and signs a superseding version 2, and recomputes a visible formula-versioned
opportunity score.

Static contract and PowerShell syntax checks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-discovery.ps1 -StaticOnly
```

The full gate requires the ignored repository `.env` and Docker Desktop:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-discovery.ps1
```

The verifier uses the isolated Compose project `ai-ops-platform-d01`, checks the
32 GB Docker storage guard before startup and after cleanup, and stops only that
project without removing the named PostgreSQL volume. Use `-KeepRunning` only
for manual inspection; stop the exact project afterward:

```powershell
docker compose --project-name ai-ops-platform-d01 --env-file .env --file docker-compose.yml down --remove-orphans
```

The current T-01 checkpoint has no D-01 API routes yet, so a full run is
expected to stop at the first missing runtime contract until D-01 product code
and migrations are integrated. That is a contract failure, not a passing
placeholder.
