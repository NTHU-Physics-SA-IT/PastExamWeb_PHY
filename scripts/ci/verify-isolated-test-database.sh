#!/bin/sh

set -eu

fail() {
  printf 'Isolated test database verification failed: %s\n' "$1" >&2
  exit 1
}

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${MIGRATOR_DB_USER:?MIGRATOR_DB_USER is required}"
: "${TEST_DB_USER:?TEST_DB_USER is required}"
: "${TEST_DB_PASSWORD:?TEST_DB_PASSWORD is required}"
: "${TEST_DATABASE_NAME:?TEST_DATABASE_NAME is required}"

pg_isready \
  -h 127.0.0.1 \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  >/dev/null 2>&1 \
  || fail "final PostgreSQL TCP server is not ready"

metadata="$(
  PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 \
    --no-password \
    --username "$POSTGRES_USER" \
    --dbname postgres \
    --set=ON_ERROR_STOP=1 \
    --set=test_database="$TEST_DATABASE_NAME" \
    --set=test_user="$TEST_DB_USER" \
    --set=migrator_user="$MIGRATOR_DB_USER" \
    --tuples-only \
    --no-align \
    --field-separator='|' <<'SQL'
SELECT
  database.datname,
  pg_get_userbyid(database.datdba),
  test_role.rolcanlogin,
  test_role.rolsuper,
  test_role.rolcreatedb,
  test_role.rolcreaterole,
  test_role.rolreplication,
  test_role.rolbypassrls,
  has_database_privilege(test_role.oid, database.oid, 'CONNECT'),
  has_database_privilege(migrator_role.oid, database.oid, 'CONNECT'),
  EXISTS (
    SELECT 1
    FROM aclexplode(
      COALESCE(database.datacl, acldefault('d', database.datdba))
    ) AS database_acl
    WHERE database_acl.grantee = 0
      AND database_acl.privilege_type = 'CONNECT'
  )
FROM pg_database AS database
JOIN pg_roles AS test_role
  ON test_role.rolname = :'test_user'
JOIN pg_roles AS migrator_role
  ON migrator_role.rolname = :'migrator_user'
WHERE database.datname = :'test_database';
SQL
)" || fail "database metadata query failed"

expected_metadata="$TEST_DATABASE_NAME|$TEST_DB_USER|t|f|f|f|f|f|t|t|f"
[ "$metadata" = "$expected_metadata" ] \
  || fail "database owner, role, or CONNECT privileges do not match"

identity="$(
  PGPASSWORD="$TEST_DB_PASSWORD" psql \
    -h 127.0.0.1 \
    --no-password \
    --username "$TEST_DB_USER" \
    --dbname "$TEST_DATABASE_NAME" \
    --set=ON_ERROR_STOP=1 \
    --tuples-only \
    --no-align \
    --field-separator='|' <<'SQL'
SELECT current_database(), current_user;
SQL
)" || fail "expected test role cannot connect"

expected_identity="$TEST_DATABASE_NAME|$TEST_DB_USER"
[ "$identity" = "$expected_identity" ] \
  || fail "connected database identity does not match"

printf 'Isolated test database verification passed\n'
