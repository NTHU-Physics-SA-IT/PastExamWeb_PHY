#!/usr/bin/env bash

set -euo pipefail

: "${BACKUP_FILE:?Set BACKUP_FILE to a custom-format pg_dump}"
: "${DATABASE_CONTAINER:?Set DATABASE_CONTAINER}"
: "${DATABASE_ADMIN_USER:?Set DATABASE_ADMIN_USER}"
: "${RESTORE_DATABASE_NAME:?Set a new RESTORE_DATABASE_NAME}"
: "${RESTORE_DATABASE_OWNER:?Set RESTORE_DATABASE_OWNER}"
: "${MIGRATION_IMAGE:?Set MIGRATION_IMAGE}"
: "${MIGRATION_NETWORK:?Set MIGRATION_NETWORK}"
: "${MIGRATION_ENV_FILE:?Set MIGRATION_ENV_FILE}"

case "$RESTORE_DATABASE_NAME" in
  pastexam_restore_*) ;;
  *)
    echo "RESTORE_DATABASE_NAME must start with pastexam_restore_." >&2
    exit 2
    ;;
esac

case "$RESTORE_DATABASE_NAME:$RESTORE_DATABASE_OWNER:$DATABASE_ADMIN_USER" in
  *[!A-Za-z0-9_.:-]*)
    echo "Database and role names contain unsupported characters." >&2
    exit 2
    ;;
esac

if [ ! -s "$BACKUP_FILE" ]; then
  echo "Backup file is missing or empty: $BACKUP_FILE" >&2
  exit 2
fi
if [ ! -f "$MIGRATION_ENV_FILE" ]; then
  echo "Migration environment file is missing." >&2
  exit 2
fi
if ! docker exec -i "$DATABASE_CONTAINER" pg_restore --list \
  <"$BACKUP_FILE" >/dev/null
then
  echo "Backup is not a readable custom-format PostgreSQL archive." >&2
  exit 2
fi

database_exists="$(
  docker exec "$DATABASE_CONTAINER" sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      -U "$1" -d postgres -Atc \
      "SELECT 1 FROM pg_database WHERE datname = '\''$2'\''"
  ' sh "$DATABASE_ADMIN_USER" "$RESTORE_DATABASE_NAME"
)"
if [ -n "$database_exists" ]; then
  echo "Restore target already exists; overwrite is not supported." >&2
  exit 2
fi

owner_exists="$(
  docker exec "$DATABASE_CONTAINER" sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      -U "$1" -d postgres -Atc \
      "SELECT 1 FROM pg_roles WHERE rolname = '\''$2'\''"
  ' sh "$DATABASE_ADMIN_USER" "$RESTORE_DATABASE_OWNER"
)"
if [ "$owner_exists" != "1" ]; then
  echo "Restore owner does not exist." >&2
  exit 2
fi

docker exec "$DATABASE_CONTAINER" sh -eu -c '
  PGPASSWORD="$POSTGRES_PASSWORD" createdb \
    -U "$1" -O "$2" "$3"
' sh \
  "$DATABASE_ADMIN_USER" \
  "$RESTORE_DATABASE_OWNER" \
  "$RESTORE_DATABASE_NAME"

if ! docker exec -i "$DATABASE_CONTAINER" sh -eu -c '
  PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    --role "$2" \
    --username "$1" \
    --dbname "$3"
' sh \
  "$DATABASE_ADMIN_USER" \
  "$RESTORE_DATABASE_OWNER" \
  "$RESTORE_DATABASE_NAME" <"$BACKUP_FILE"
then
  echo "Restore failed; the new target database was preserved for diagnosis." >&2
  exit 2
fi

docker run --rm \
  --network "$MIGRATION_NETWORK" \
  --env-file "$MIGRATION_ENV_FILE" \
  -e "DB_NAME=$RESTORE_DATABASE_NAME" \
  "$MIGRATION_IMAGE" \
  python migrate.py preflight

echo "Restore and read-only migration preflight completed."
echo "No service was switched and no migration was applied."
