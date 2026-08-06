# C-01 connector, MCP, and vault verification

C-01 exposes a real modular-monolith integration boundary without pretending that external customer credentials or providers exist locally. The sandbox adapters exercise the same connector interface used by the first-party kinds; production adapters remain deployment-scoped.

Static contract check:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-connectors.ps1 -StaticOnly
```

Full real Compose/PostgreSQL, sandbox, and browser gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-connectors.ps1
```

The verifier never prints `.env` or synthetic credential values. It uses a separate Compose project and preserves the named PostgreSQL volume under the 32 GB storage guard.
