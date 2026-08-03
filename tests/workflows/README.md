# W-01 workflow verification

`contract.json` is the tracked black-box contract exercised by
`scripts/verify-workflows.ps1`. The verifier is intentionally outside the product
implementation: it proves the workflow API and browser surface through the real
Docker Compose/PostgreSQL stack when W-01 runtime code is present.

## Contract coverage

The static contract and synthetic fixtures cover:

- all twelve deterministic node kinds: `trigger`, `fetch`, `parse`, `classify`,
  `extract`, `rule`, `score`, `llm`, `tool`, `approve`, `notify`, and `halt`;
- form-shaped persistence of nodes, edges, thresholds, prompts, and model configs;
- duplicate-key, unknown-node, missing-reference, duplicate-edge, cycle, terminal,
  and schema-constrained `llm` validation;
- two-workspace isolation and builder/viewer authorization;
- content-addressed SHA-256 version hashes and immutable published versions;
- publish denial before evaluation and after a failing server-owned evaluation,
  including repairable failure reasons;
- publish success only after a passing evaluation bound to the exact version hash;
- append-only audit ids and deletion-denial evidence; and
- a live browser form plus read-only graph smoke with no drag/drop mutation path.

The evaluation fixture records suite keys only. The verifier never sends `passed`,
metrics, failure reasons, or a version hash; those values must be computed and
stored by the service.

## Run

Static checks do not require Docker or `.env`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-workflows.ps1 -StaticOnly
```

The full gate requires the ignored repository-root `.env`, Docker Desktop, the
Compose PostgreSQL service, W-01 API routes, and the W-01 frontend UI:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-workflows.ps1
```

The full run uses a separate Compose project (`ai-ops-platform-w01`) and alternate
host ports. It preserves the named PostgreSQL volume and stops only that project
unless `-KeepRunning` is supplied. It invokes the tracked browser smoke through
the available Python/Playwright runtime after the HTTP contract passes.

The current D-01 checkpoint intentionally has no W-01 API or workflow UI yet. On
that checkpoint `-StaticOnly` is the expected passing verifier-local result; the
full command must stop at the first missing W-01 integration route and report the
exact dependency without falling back to mocks, SQLite, direct database access,
`docker exec`, or response-body dumps.
