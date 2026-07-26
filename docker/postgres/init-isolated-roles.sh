#!/usr/bin/env bash

set -euo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${MIGRATOR_DB_USER:?MIGRATOR_DB_USER is required}"
: "${MIGRATOR_DB_PASSWORD:?MIGRATOR_DB_PASSWORD is required}"
: "${APP_DB_USER:?APP_DB_USER is required}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${TEST_DB_USER:?TEST_DB_USER is required}"
: "${TEST_DB_PASSWORD:?TEST_DB_PASSWORD is required}"
: "${TEST_DATABASE_NAME:?TEST_DATABASE_NAME is required}"

case "$TEST_DB_USER" in
  pastexam_test_*) ;;
  *)
    echo "TEST_DB_USER must start with pastexam_test_." >&2
    exit 1
    ;;
esac

case "$TEST_DATABASE_NAME" in
  pastexam_test_*) ;;
  *)
    echo "TEST_DATABASE_NAME must start with pastexam_test_." >&2
    exit 1
    ;;
esac

psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname postgres \
  --set=main_database="$POSTGRES_DB" \
  --set=migrator_user="$MIGRATOR_DB_USER" \
  --set=migrator_password="$MIGRATOR_DB_PASSWORD" \
  --set=runtime_user="$APP_DB_USER" \
  --set=runtime_password="$APP_DB_PASSWORD" \
  --set=test_user="$TEST_DB_USER" \
  --set=test_password="$TEST_DB_PASSWORD" \
  --set=test_database="$TEST_DATABASE_NAME" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'migrator_user',
  :'migrator_password'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = :'migrator_user'
)
\gexec

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'runtime_user',
  :'runtime_password'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = :'runtime_user'
)
\gexec

SELECT format(
  'ALTER DATABASE %I OWNER TO %I',
  :'main_database',
  :'migrator_user'
)
\gexec

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'test_user',
  :'test_password'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = :'test_user'
)
\gexec

SELECT format(
  'CREATE DATABASE %I OWNER %I',
  :'test_database',
  :'test_user'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_database WHERE datname = :'test_database'
)
\gexec
SQL

psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname postgres \
  --set=database_name="$POSTGRES_DB" \
  --set=cluster_admin="$POSTGRES_USER" \
  --set=migrator_user="$MIGRATOR_DB_USER" \
  --set=runtime_user="$APP_DB_USER" \
  --set=test_user="$TEST_DB_USER" <<'SQL'
REVOKE CONNECT ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name"
  TO :"cluster_admin", :"migrator_user", :"runtime_user";
REVOKE CONNECT ON DATABASE :"database_name" FROM :"test_user";
SQL

psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=migrator_user="$MIGRATOR_DB_USER" \
  --set=runtime_user="$APP_DB_USER" <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"runtime_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
  TO :"runtime_user";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public
  TO :"runtime_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_user" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"runtime_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_user" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"runtime_user";
SQL

psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname postgres \
  --set=test_database="$TEST_DATABASE_NAME" \
  --set=cluster_admin="$POSTGRES_USER" \
  --set=migrator_user="$MIGRATOR_DB_USER" \
  --set=test_user="$TEST_DB_USER" <<'SQL'
REVOKE CONNECT ON DATABASE :"test_database" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"test_database"
  TO :"cluster_admin", :"migrator_user", :"test_user";
SQL
