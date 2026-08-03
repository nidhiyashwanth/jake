# Compliance API

FastAPI API for the compliance platform. It requires a PostgreSQL
`DATABASE_URL`; SQLite is intentionally rejected at configuration time. Local
credentials live in the ignored repository-root `.env`; `.env.example` is only
a placeholder template. The Compose path runs Alembic before starting Uvicorn:

```powershell
docker compose up -d --build postgres backend
```

For a local Python process, install the package with the test extras and load
the local `.env` values before running:

```powershell
python -m pip install -e ".[test]"
$env:DATABASE_URL = (Get-Content ..\.env | Where-Object { $_ -like 'DATABASE_URL=*' }) -replace '^DATABASE_URL=', ''
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```
