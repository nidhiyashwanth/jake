# Compliance API

FastAPI API for the compliance platform. It requires a PostgreSQL
`DATABASE_URL`; SQLite is intentionally rejected at configuration time. Local
credentials live in the ignored repository-root `.env`; `.env.example` is only
a placeholder template. The Compose path prepares a separate non-superuser
application role, runs Alembic through the owner role, and starts Uvicorn and
the worker with the application role:

```powershell
docker compose --env-file .env --file docker-compose.yml up -d --build
```

For a local Python process, install the package with the test extras and load
the application-role `DATABASE_URL` plus the owner `DATABASE_ADMIN_URL` before
running migrations or integration tests:

```powershell
python -m pip install -e ".[test]"
$env:DATABASE_URL = (Get-Content .env | Where-Object { $_ -like 'DATABASE_URL=*' }) -replace '^DATABASE_URL=', ''
$env:DATABASE_ADMIN_URL = (Get-Content .env | Where-Object { $_ -like 'DATABASE_ADMIN_URL=*' }) -replace '^DATABASE_ADMIN_URL=', ''
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```
