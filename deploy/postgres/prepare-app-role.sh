#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_APP_USER:?POSTGRES_APP_USER is required}"
: "${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD is required}"

export PGPASSWORD="$POSTGRES_PASSWORD"

psql \
  --host=postgres \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --set=app_user="$POSTGRES_APP_USER" \
  --set=app_password="$POSTGRES_APP_PASSWORD" \
  --set=app_database="$POSTGRES_DB" \
  --set=owner="$POSTGRES_USER" \
  --set=ON_ERROR_STOP=1 <<'SQL'
SELECT format(
  'DO $do$
   BEGIN
     IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %L) THEN
       CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L;
     ELSE
       ALTER ROLE %I WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L;
     END IF;
   END $do$;',
  :'app_user', :'app_user', :'app_password', :'app_user', :'app_password'
)
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'app_database', :'app_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user')
\gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public TO %I', :'app_user')
\gexec
SELECT format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I', :'app_user')
\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER ON TABLES TO %I', :'owner', :'app_user')
\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'owner', :'app_user')
\gexec
SQL
