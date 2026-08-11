#!/usr/bin/env bash

set -euo pipefail
umask 077

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
: "${PRODUCTION_EDGE_COMPOSE_FILE:=/etc/pastexam/docker-compose.edge.yml}"
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
  "$PRODUCTION_MIGRATOR_ENV_FILE" \
  "$PRODUCTION_EDGE_COMPOSE_FILE"
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
  owner_uid="$(stat -c '%u' "$config_file")"
  if [ "$owner_uid" != "0" ]; then
    echo "External production configuration must be root-owned." >&2
    exit 2
  fi
done

if [ "$RELEASE_MANIFEST" != "$RELEASE_DIRECTORY/release-manifest.env" ]; then
  echo "Release manifest must use the canonical immutable release path." >&2
  exit 2
fi

if [[ ! "$RELEASE_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Release manifest checksum must be a SHA-256 value." >&2
  exit 2
fi

actual_manifest_sha="$(sha256sum "$RELEASE_MANIFEST" | awk '{print $1}')"
if [ "$actual_manifest_sha" != "$RELEASE_MANIFEST_SHA256" ]; then
  echo "Release manifest checksum mismatch." >&2
  exit 2
fi

contract_helper="$RELEASE_DIRECTORY/scripts/production-activation-contract.py"
release_sha="$(
  python3 "$contract_helper" verify-release \
    --manifest "$RELEASE_MANIFEST" \
    --source-sha "$RELEASE_DIRECTORY/.release-source-sha" \
    --release-directory "$RELEASE_DIRECTORY"
)"

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
  --file "$PRODUCTION_EDGE_COMPOSE_FILE"
)

export PRODUCTION_BACKEND_ENV_FILE
export PRODUCTION_MIGRATOR_ENV_FILE
"${compose[@]}" config --quiet

contract_directory="$(mktemp -d)"
cleanup_contract() {
  rm -rf -- "$contract_directory"
}
trap cleanup_contract EXIT HUP INT TERM
rendered_compose="$contract_directory/compose.json"
current_nginx_ports="$contract_directory/current-nginx-ports.json"
"${compose[@]}" config --format json >"$rendered_compose"

production_values="$(
  python3 "$contract_helper" compose-values \
    --compose-json "$rendered_compose"
)"
mapfile -t production_contract <<<"$production_values"
if [ "${#production_contract[@]}" -ne 6 ]; then
  echo "Rendered production backup contract is incomplete." >&2
  exit 2
fi
DATABASE_CONTAINER="${production_contract[0]}"
DATABASE_NAME="${production_contract[1]}"
DATABASE_USER="${production_contract[2]}"
MINIO_CONTAINER="${production_contract[3]}"
MINIO_BUCKET_NAME="${production_contract[4]}"
NGINX_CONTAINER="${production_contract[5]}"

docker inspect --format '{{json .NetworkSettings.Ports}}' \
  "$NGINX_CONTAINER" >"$current_nginx_ports"
python3 "$contract_helper" verify-ingress \
  --compose-json "$rendered_compose" \
  --current-ports-json "$current_nginx_ports" \
  --nginx-config "$RELEASE_DIRECTORY/proxy/nginx.conf"

cleanup_contract
trap - EXIT HUP INT TERM

env -i \
  PATH="$PATH" \
  BACKUP_DIRECTORY="$PRODUCTION_BACKUP_DIRECTORY" \
  DATABASE_CONTAINER="$DATABASE_CONTAINER" \
  DATABASE_NAME="$DATABASE_NAME" \
  DATABASE_USER="$DATABASE_USER" \
  APPLICATION_RELEASE_SHA="$release_sha" \
  "$RELEASE_DIRECTORY/scripts/postgres-logical-backup.sh"
env -i \
  PATH="$PATH" \
  BACKUP_DIRECTORY="$PRODUCTION_BACKUP_DIRECTORY" \
  MINIO_CONTAINER="$MINIO_CONTAINER" \
  MINIO_BUCKET_NAME="$MINIO_BUCKET_NAME" \
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
