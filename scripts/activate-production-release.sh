#!/usr/bin/env bash

set -euo pipefail

PRODUCTION_DEPLOY_ENABLED="${PRODUCTION_DEPLOY_ENABLED:-false}"
if [ "$PRODUCTION_DEPLOY_ENABLED" != "true" ]; then
  echo "Production activation is disabled." >&2
  exit 2
fi

: "${ACTIVATION_CONFIRMATION:?Set ACTIVATION_CONFIRMATION}"
: "${RELEASE_DIRECTORY:?Set RELEASE_DIRECTORY}"
: "${RELEASE_MANIFEST:?Set RELEASE_MANIFEST}"
: "${RELEASE_MANIFEST_SHA256:?Set RELEASE_MANIFEST_SHA256}"
: "${PRODUCTION_COMPOSE_ENV_FILE:=/etc/pastexam/compose.prod.env}"
: "${PRODUCTION_BACKEND_ENV_FILE:=/opt/pastexam-config/backend.env}"
: "${PRODUCTION_MIGRATOR_ENV_FILE:=/opt/pastexam-config/migrator.env}"
: "${PRODUCTION_BACKUP_DIRECTORY:=/opt/pastexam-backups}"
: "${PRODUCTION_LOCK_FILE:=/var/lock/pastexam-production-activation.lock}"
: "${INTERNAL_HEALTH_URL:=http://127.0.0.1:8080/api/health}"
: "${EXTERNAL_HEALTH_URL:?Set EXTERNAL_HEALTH_URL}"

if [ "$ACTIVATION_CONFIRMATION" != "activate-reviewed-production-release" ]; then
  echo "Production activation confirmation is invalid." >&2
  exit 2
fi

for config_file in \
  "$PRODUCTION_COMPOSE_ENV_FILE" \
  "$PRODUCTION_BACKEND_ENV_FILE" \
  "$PRODUCTION_MIGRATOR_ENV_FILE"
do
  if [ ! -f "$config_file" ]; then
    echo "Required external configuration file is missing." >&2
    exit 2
  fi
  mode="$(stat -c '%a' "$config_file")"
  if [ "$mode" != "600" ]; then
    echo "External production configuration must have mode 0600." >&2
    exit 2
  fi
done

case "$RELEASE_MANIFEST" in
  "$RELEASE_DIRECTORY"/*) ;;
  *)
    echo "Release manifest must be inside the immutable release directory." >&2
    exit 2
    ;;
esac

actual_manifest_sha="$(sha256sum "$RELEASE_MANIFEST" | awk '{print $1}')"
if [ "$actual_manifest_sha" != "$RELEASE_MANIFEST_SHA256" ]; then
  echo "Release manifest checksum mismatch." >&2
  exit 2
fi

exec 9>"$PRODUCTION_LOCK_FILE"
if ! flock -n 9; then
  echo "Another production activation holds the deployment lock." >&2
  exit 2
fi

compose_file="$RELEASE_DIRECTORY/docker/docker-compose.prod.yml"
compose=(
  docker compose
  --env-file "$PRODUCTION_COMPOSE_ENV_FILE"
  --file "$compose_file"
)

export PRODUCTION_BACKEND_ENV_FILE
export PRODUCTION_MIGRATOR_ENV_FILE
export BACKUP_DIRECTORY="$PRODUCTION_BACKUP_DIRECTORY"

"${compose[@]}" config --quiet

# The host-specific config supplies DATABASE_CONTAINER, DATABASE_NAME,
# DATABASE_USER, MINIO_CONTAINER, and MINIO_BUCKET_NAME without printing them.
"$RELEASE_DIRECTORY/scripts/postgres-logical-backup.sh"
"$RELEASE_DIRECTORY/scripts/minio-readonly-manifest.sh"

"${compose[@]}" run --rm migrate python migrate.py preflight
"${compose[@]}" run --rm migrate
"${compose[@]}" run --rm migrate python migrate.py preflight

"${compose[@]}" up -d backend frontend nginx

curl --fail --silent --show-error "$INTERNAL_HEALTH_URL" >/dev/null
curl --fail --silent --show-error "$EXTERNAL_HEALTH_URL" >/dev/null

activated_marker="$RELEASE_DIRECTORY/.activated"
temporary_marker="$activated_marker.partial"
printf '%s\n' "$RELEASE_MANIFEST_SHA256" >"$temporary_marker"
mv "$temporary_marker" "$activated_marker"

echo "Production release activation completed."
