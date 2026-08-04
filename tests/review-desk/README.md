# V-01 review desk verification

V-01 is the operator review desk for the compliance wedge. It turns open verification exceptions into a workspace-scoped queue with deterministic priority, a bounded SLA, source provenance, assignment, escalation, capped bulk actions, and append-only task events.

Run the static contract check without starting Docker:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-review-desk.ps1 -StaticOnly
```

Run the real gate against Docker/PostgreSQL and the built Next.js surface:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-review-desk.ps1
```

The gate uses its own Compose project and ports, runs sequentially, and preserves the named PostgreSQL volume. It does not print `.env` values or use direct database clients.
