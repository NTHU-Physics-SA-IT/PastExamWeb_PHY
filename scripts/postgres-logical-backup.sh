#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

: "${BACKUP_DIRECTORY:?Set an absolute BACKUP_DIRECTORY outside the repository}"
: "${DATABASE_CONTAINER:?Set DATABASE_CONTAINER}"
: "${DATABASE_NAME:?Set DATABASE_NAME}"
: "${DATABASE_USER:?Set DATABASE_USER}"

case "$BACKUP_DIRECTORY" in
  /*) ;;
  *)
    echo "BACKUP_DIRECTORY must be absolute." >&2
    exit 2
    ;;
esac

case "$BACKUP_DIRECTORY/" in
  "$repository_root/"*)
    echo "BACKUP_DIRECTORY must be outside the repository." >&2
    exit 2
    ;;
esac

case "$DATABASE_NAME:$DATABASE_USER" in
  *[!A-Za-z0-9_.:-]*)
    echo "Database and role names contain unsupported characters." >&2
    exit 2
    ;;
esac

if ! docker inspect "$DATABASE_CONTAINER" >/dev/null 2>&1; then
  echo "Database container does not exist: $DATABASE_CONTAINER" >&2
  exit 2
fi

mkdir -p "$BACKUP_DIRECTORY"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
base_name="${DATABASE_NAME}_${timestamp}"
dump_path="$BACKUP_DIRECTORY/$base_name.dump"
metadata_path="$BACKUP_DIRECTORY/$base_name.metadata.json"
checksum_path="$BACKUP_DIRECTORY/$base_name.sha256"
temporary_dump="$dump_path.partial"

if [ -e "$dump_path" ] || [ -e "$temporary_dump" ]; then
  echo "Refusing to overwrite an existing backup artifact." >&2
  exit 2
fi

actual_database="$(
  docker exec "$DATABASE_CONTAINER" sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      -U "$1" -d "$2" -Atc "SELECT current_database()"
  ' sh "$DATABASE_USER" "$DATABASE_NAME"
)"
if [ "$actual_database" != "$DATABASE_NAME" ]; then
  echo "Connected database identity does not match DATABASE_NAME." >&2
  exit 2
fi

alembic_revision="$(
  docker exec "$DATABASE_CONTAINER" sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      -U "$1" -d "$2" -Atc "
        SELECT CASE
          WHEN to_regclass('\''public.alembic_version'\'') IS NULL THEN '\'''\''
          WHEN (SELECT count(*) FROM alembic_version) = 1
            THEN (SELECT version_num FROM alembic_version)
          ELSE '\'''\''
        END
      "
  ' sh "$DATABASE_USER" "$DATABASE_NAME"
)"
if [ -z "$alembic_revision" ]; then
  echo "Backup blocked: database has no single Alembic revision." >&2
  exit 2
fi

postgres_version="$(
  docker exec "$DATABASE_CONTAINER" sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      -U "$1" -d "$2" -Atc "SHOW server_version"
  ' sh "$DATABASE_USER" "$DATABASE_NAME"
)"
application_commit="$(git -C "$repository_root" rev-parse HEAD)"
repository_head="$(
  git -C "$repository_root" rev-parse refs/heads/"$(
    git -C "$repository_root" branch --show-current
  )"
)"

cleanup_partial() {
  if [ -f "$temporary_dump" ]; then
    rm -f -- "$temporary_dump"
  fi
}
trap cleanup_partial EXIT HUP INT TERM

docker exec "$DATABASE_CONTAINER" sh -eu -c '
  PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump \
    --format=custom \
    --no-owner \
    --no-privileges \
    --username "$1" \
    --dbname "$2"
' sh "$DATABASE_USER" "$DATABASE_NAME" >"$temporary_dump"

if [ ! -s "$temporary_dump" ]; then
  echo "pg_dump produced an empty file." >&2
  exit 2
fi
if ! docker exec -i "$DATABASE_CONTAINER" pg_restore --list \
  <"$temporary_dump" >/dev/null
then
  echo "pg_restore could not read the new backup." >&2
  exit 2
fi

mv "$temporary_dump" "$dump_path"
trap - EXIT HUP INT TERM
checksum="$(shasum -a 256 "$dump_path" | awk '{print $1}')"
printf '%s  %s\n' "$checksum" "$(basename "$dump_path")" >"$checksum_path"

cat >"$metadata_path" <<EOF
{
  "manifest_version": 1,
  "utc_timestamp": "$timestamp",
  "application_commit_sha": "$application_commit",
  "alembic_revision": "$alembic_revision",
  "repository_head": "$repository_head",
  "postgresql_version": "$postgres_version",
  "database_name": "$DATABASE_NAME",
  "backup_file": "$(basename "$dump_path")",
  "sha256": "$checksum"
}
EOF

echo "Logical PostgreSQL backup verified: $dump_path"
echo "Metadata: $metadata_path"
echo "Checksum: $checksum_path"
