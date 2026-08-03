# Compliance API

FastAPI API for the F01 vendor compliance verification slice. It requires a
PostgreSQL `DATABASE_URL`; SQLite is intentionally rejected at configuration
time. The Compose path runs Alembic before starting Uvicorn:

```powershell
docker compose up -d --build postgres backend
```

For a local Python process, install the package with the test extras and set a
PostgreSQL URL before running:

```powershell
python -m pip install -e ".[test]"
$env:DATABASE_URL = "postgresql+psycopg://mvp:mvp@localhost:5432/mvp"
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```
