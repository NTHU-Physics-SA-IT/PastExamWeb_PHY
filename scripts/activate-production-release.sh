#!/usr/bin/env bash

set -euo pipefail
umask 077

current_stage="startup"
contract_directory=""
failure_contract_helper=""
record_activation_exit() {
  local status="$?"
  trap - EXIT HUP INT TERM
  set +e
  if [ -n "$contract_directory" ]; then
    rm -rf -- "$contract_directory"
  fi
  if [ "$status" -ne 0 ] && [ -n "${ACTIVATION_FAILURE_EVIDENCE_PATH:-}" ] && \
    [ -n "$failure_contract_helper" ]
  then
    env -i \
      PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}" \
      python3 \
      "$failure_contract_helper" \
      write-engine-failure-evidence \
      --output "$ACTIVATION_FAILURE_EVIDENCE_PATH" \
      --request-id "${ACTIVATION_REQUEST_ID:-}" \
      --target-sha "${ACTIVATION_TARGET_SHA:-}" \
      --stage "$current_stage" \
      --exit-code "$status" \
      >/dev/null 2>&1
  fi
  exit "$status"
}
trap record_activation_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

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
: "${HEALTH_CHECK_ATTEMPTS:=10}"
: "${HEALTH_CHECK_INITIAL_DELAY_SECONDS:=2}"
: "${HEALTH_CHECK_MAX_DELAY_SECONDS:=10}"
: "${OBSERVATION_SNAPSHOTS:=3}"
: "${OBSERVATION_INTERVAL_SECONDS:=300}"
: "${ACTIVATION_CONTRACT_HELPER:=/usr/local/libexec/pastexam-production-activation-contract.py}"
: "${POSTGRES_BACKUP_HELPER:=/usr/local/libexec/pastexam-postgres-logical-backup}"
: "${MINIO_PREFLIGHT_HELPER:=/usr/local/libexec/pastexam-minio-storage-preflight}"
: "${MINIO_MANIFEST_HELPER:=/usr/local/libexec/pastexam-minio-readonly-manifest}"
: "${NGINX_IMAGE_OVERRIDE:=/usr/local/libexec/pastexam-nginx-image-override.yml}"
: "${ACTIVATION_EVIDENCE_PATH:=}"
: "${ACTIVATION_FAILURE_EVIDENCE_PATH:=}"
: "${ACTIVATION_PREFLIGHT_ONLY:=false}"

activation_started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -n "$ACTIVATION_EVIDENCE_PATH" ] && [[ "$ACTIVATION_EVIDENCE_PATH" != /* ]]; then
  echo "ACTIVATION_EVIDENCE_PATH must be absolute." >&2
  exit 2
fi
if [ -n "$ACTIVATION_FAILURE_EVIDENCE_PATH" ] && \
  [[ "$ACTIVATION_FAILURE_EVIDENCE_PATH" != /* ]]
then
  echo "ACTIVATION_FAILURE_EVIDENCE_PATH must be absolute." >&2
  exit 2
fi
if [ "$ACTIVATION_PREFLIGHT_ONLY" != "true" ] && [ "$ACTIVATION_PREFLIGHT_ONLY" != "false" ]; then
  echo "ACTIVATION_PREFLIGHT_ONLY must be true or false." >&2
  exit 2
fi

if [ "$ACTIVATION_CONFIRMATION" != "activate-reviewed-production-release" ]; then
  echo "Production activation confirmation is invalid." >&2
  exit 2
fi

for retry_value in \
  "$HEALTH_CHECK_ATTEMPTS" \
  "$HEALTH_CHECK_INITIAL_DELAY_SECONDS" \
  "$HEALTH_CHECK_MAX_DELAY_SECONDS" \
  "$OBSERVATION_SNAPSHOTS" \
  "$OBSERVATION_INTERVAL_SECONDS"
do
  if [[ ! "$retry_value" =~ ^[0-9]+$ ]]; then
    echo "Health retry settings must be non-negative integers." >&2
    exit 2
  fi
done
if [ "$HEALTH_CHECK_ATTEMPTS" -lt 1 ]; then
  echo "HEALTH_CHECK_ATTEMPTS must be at least 1." >&2
  exit 2
fi
if [ "$OBSERVATION_SNAPSHOTS" -lt 1 ]; then
  echo "OBSERVATION_SNAPSHOTS must be at least 1." >&2
  exit 2
fi

required_compose_flags=(
  --no-env-resolution
  --no-interpolate
  --no-path-resolution
  --format
)
if ! compose_config_help="$(docker compose config --help 2>/dev/null)"; then
  echo "Docker Compose configuration capabilities are unavailable." >&2
  exit 2
fi
for required_compose_flag in "${required_compose_flags[@]}"; do
  if ! awk -v required="$required_compose_flag" '
    {
      for (field = 1; field <= NF; field += 1) {
        if ($field == required) {
          found = 1
        }
      }
    }
    END { exit(found ? 0 : 1) }
  ' <<<"$compose_config_help"
  then
    echo "Docker Compose configuration capability is missing: $required_compose_flag" >&2
    exit 2
  fi
done
unset compose_config_help required_compose_flag

verify_root_helper() {
  local helper mode owner_uid
  helper="$1"
  if [ ! -f "$helper" ] || [ ! -x "$helper" ]; then
    echo "A required root-installed activation helper is unavailable." >&2
    exit 2
  fi
  case "$helper/" in
    "$RELEASE_DIRECTORY/"*)
      echo "Candidate release code cannot be privileged activation authority." >&2
      exit 2
      ;;
  esac
  owner_uid="$(stat -c '%u' "$helper")"
  mode="$(stat -c '%a' "$helper")"
  if [ "$owner_uid" != "0" ] || (( (8#$mode & 8#022) != 0 )); then
    echo "Activation helpers must be root-owned and not group/world writable." >&2
    exit 2
  fi
}

verify_root_readonly_file() {
  local path mode owner_uid
  path="$1"
  [ -f "$path" ] || {
    echo "A required root-installed activation contract is unavailable." >&2
    exit 2
  }
  owner_uid="$(stat -c '%u' "$path")"
  mode="$(stat -c '%a' "$path")"
  if [ "$owner_uid" != "0" ] || (( (8#$mode & 8#022) != 0 )); then
    echo "Activation contracts must be root-owned and not group/world writable." >&2
    exit 2
  fi
}

current_stage="helper-authority"
verify_root_helper "$ACTIVATION_CONTRACT_HELPER"
failure_contract_helper="$ACTIVATION_CONTRACT_HELPER"
for helper in \
  "$POSTGRES_BACKUP_HELPER" \
  "$MINIO_PREFLIGHT_HELPER" \
  "$MINIO_MANIFEST_HELPER"
do
  verify_root_helper "$helper"
done
verify_root_readonly_file "$NGINX_IMAGE_OVERRIDE"

current_stage="external-config"
for config_file in \
  "$PRODUCTION_COMPOSE_ENV_FILE" \
  "$PRODUCTION_BACKEND_ENV_FILE" \
  "$PRODUCTION_MIGRATOR_ENV_FILE" \
  "$PRODUCTION_EDGE_COMPOSE_FILE"
do
  if [ ! -f "$config_file" ] || [ -L "$config_file" ]; then
    echo "External production configuration must be a regular non-symlink file." >&2
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

candidate_compose_env="$RELEASE_DIRECTORY/compose.prod.env"
if [ ! -f "$candidate_compose_env" ]; then
  echo "Immutable candidate Compose environment is missing." >&2
  exit 2
fi

verify_external_file() {
  local external_file mode owner_uid
  external_file="$1"
  if [ ! -f "$external_file" ]; then
    echo "Required external TLS file is missing." >&2
    exit 2
  fi
  mode="$(stat -c '%a' "$external_file")"
  if [ "$mode" != "600" ]; then
    echo "External TLS files must have mode 0600." >&2
    exit 2
  fi
  owner_uid="$(stat -c '%u' "$external_file")"
  if [ "$owner_uid" != "0" ]; then
    echo "External TLS files must be root-owned." >&2
    exit 2
  fi
}

current_stage="candidate-contract"
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

contract_helper="$ACTIVATION_CONTRACT_HELPER"
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
  --project-directory "$RELEASE_DIRECTORY"
  --env-file "$PRODUCTION_COMPOSE_ENV_FILE"
  --env-file "$candidate_compose_env"
  --file "$compose_file"
  --file "$PRODUCTION_EDGE_COMPOSE_FILE"
  --file "$NGINX_IMAGE_OVERRIDE"
)
compose_structure=(
  docker compose
  --project-directory "$RELEASE_DIRECTORY"
  --file "$compose_file"
  --file "$PRODUCTION_EDGE_COMPOSE_FILE"
  --file "$NGINX_IMAGE_OVERRIDE"
)

export PRODUCTION_BACKEND_ENV_FILE
export PRODUCTION_MIGRATOR_ENV_FILE

contract_directory="$(mktemp -d)"
cleanup_contract() {
  rm -rf -- "$contract_directory"
  contract_directory=""
}
current_stage="compose-structure"
structural_compose="$contract_directory/compose-structure.json"
current_nginx_ports="$contract_directory/current-nginx-ports.json"
if ! "${compose_structure[@]}" config \
  --no-env-resolution \
  --no-interpolate \
  --no-path-resolution \
  --format json 2>/dev/null | \
  python3 "$contract_helper" write-validated-structure \
    --output "$structural_compose" \
    --compose-env "$PRODUCTION_COMPOSE_ENV_FILE"
then
  echo "Production Compose structural configuration is invalid." >&2
  exit 2
fi

current_stage="image-contract"
python3 "$contract_helper" verify-images \
  --compose-json "$structural_compose" \
  --manifest "$RELEASE_MANIFEST" \
  --candidate-env "$candidate_compose_env"

runtime_image_values="$(
  python3 "$contract_helper" runtime-image-values \
    --manifest "$RELEASE_MANIFEST"
)"
mapfile -t runtime_image_contract <<<"$runtime_image_values"
if [ "${#runtime_image_contract[@]}" -ne 3 ]; then
  echo "Rendered runtime image contract is incomplete." >&2
  exit 2
fi
declare -A expected_runtime_images
for runtime_image_binding in "${runtime_image_contract[@]}"; do
  container_name="${runtime_image_binding%%=*}"
  expected_image="${runtime_image_binding#*=}"
  if [ -z "$container_name" ] || [ -z "$expected_image" ] || \
    [ "$container_name" = "$runtime_image_binding" ] || \
    [ -n "${expected_runtime_images[$container_name]:-}" ]
  then
    echo "Rendered runtime image contract is malformed." >&2
    exit 2
  fi
  expected_runtime_images["$container_name"]="$expected_image"
done

current_stage="production-values"
production_values="$(
  python3 "$contract_helper" compose-values \
    --compose-json "$structural_compose" \
    --compose-env "$PRODUCTION_COMPOSE_ENV_FILE" \
    --backend-env "$PRODUCTION_BACKEND_ENV_FILE" \
    --migrator-env "$PRODUCTION_MIGRATOR_ENV_FILE"
)"
mapfile -t production_contract <<<"$production_values"
if [ "${#production_contract[@]}" -ne 7 ]; then
  echo "Rendered production backup contract is incomplete." >&2
  exit 2
fi
DATABASE_CONTAINER="${production_contract[0]}"
DATABASE_NAME="${production_contract[1]}"
DATABASE_USER="${production_contract[2]}"
MINIO_CONTAINER="${production_contract[3]}"
MINIO_BUCKET_NAME="${production_contract[4]}"
NGINX_CONTAINER="${production_contract[5]}"
REDIS_CONTAINER="${production_contract[6]}"

current_stage="runtime-compose-config"
if ! "${compose[@]}" config --quiet >/dev/null 2>&1; then
  echo "Production Compose runtime configuration is invalid." >&2
  exit 2
fi

current_stage="ingress-contract"
mount_values="$(
  python3 "$contract_helper" mount-values \
    --compose-json "$structural_compose" \
    --compose-env "$PRODUCTION_COMPOSE_ENV_FILE" \
    --release-directory "$RELEASE_DIRECTORY"
)"
mapfile -t nginx_mount_contract <<<"$mount_values"
if [ "${#nginx_mount_contract[@]}" -ne 4 ]; then
  echo "Rendered production nginx mount contract is incomplete." >&2
  exit 2
fi
verify_external_file "${nginx_mount_contract[2]}"
verify_external_file "${nginx_mount_contract[3]}"

docker inspect --format '{{json .NetworkSettings.Ports}}' \
  "$NGINX_CONTAINER" >"$current_nginx_ports"
python3 "$contract_helper" verify-ingress \
  --compose-json "$structural_compose" \
  --current-ports-json "$current_nginx_ports" \
  --release-directory "$RELEASE_DIRECTORY" \
  --compose-env "$PRODUCTION_COMPOSE_ENV_FILE"

current_stage="persistent-services"
for persistent_container in \
  "$DATABASE_CONTAINER" "$REDIS_CONTAINER" "$MINIO_CONTAINER"
do
  persistent_state="$(
    docker inspect --format \
      '{{.State.Status}}:{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
      "$persistent_container"
  )"
  case "$persistent_state" in
    running:healthy|running:none) ;;
    *)
      echo "A required persistent service is not already running and healthy." >&2
      exit 2
      ;;
  esac
done

current_stage="postgres-readiness"
if ! docker exec "$DATABASE_CONTAINER" \
  pg_isready -U "$DATABASE_USER" -d "$DATABASE_NAME" >/dev/null; then
  echo "PostgreSQL is not accepting connections for activation preflight." >&2
  exit 2
fi
current_stage="redis-readiness"
if [ "$(docker exec "$REDIS_CONTAINER" redis-cli ping)" != "PONG" ]; then
  echo "Redis did not pass the activation preflight PING." >&2
  exit 2
fi
current_stage="minio-preflight"
env -i \
  PATH="$PATH" \
  MINIO_CONTAINER="$MINIO_CONTAINER" \
  MINIO_BUCKET_NAME="$MINIO_BUCKET_NAME" \
  "$MINIO_PREFLIGHT_HELPER"

current_stage="class-zero-before"
migration_report_before="$contract_directory/migration-before.json"
  "${compose[@]}" run --rm --no-deps migrate python migrate.py require-head --json \
  >"$migration_report_before"
database_revision_before="$(
  python3 "$contract_helper" verify-class-zero --report "$migration_report_before"
)"

if [ "$ACTIVATION_PREFLIGHT_ONLY" = "true" ]; then
  printf '{"database_revision":"%s","outcome":"eligible","schema_version":1,"target_sha":"%s"}\n' \
    "$database_revision_before" "$release_sha"
  cleanup_contract
  trap - EXIT HUP INT TERM
  exit 0
fi

current_stage="postgres-backup"
postgres_backup_output="$(env -i \
  PATH="$PATH" \
  BACKUP_DIRECTORY="$PRODUCTION_BACKUP_DIRECTORY" \
  DATABASE_CONTAINER="$DATABASE_CONTAINER" \
  DATABASE_NAME="$DATABASE_NAME" \
  DATABASE_USER="$DATABASE_USER" \
  APPLICATION_RELEASE_SHA="$release_sha" \
  "$POSTGRES_BACKUP_HELPER")"
printf '%s\n' "$postgres_backup_output"
current_stage="minio-manifest"
minio_manifest_output="$(env -i \
  PATH="$PATH" \
  BACKUP_DIRECTORY="$PRODUCTION_BACKUP_DIRECTORY" \
  MINIO_CONTAINER="$MINIO_CONTAINER" \
  MINIO_BUCKET_NAME="$MINIO_BUCKET_NAME" \
  "$MINIO_MANIFEST_HELPER")"
printf '%s\n' "$minio_manifest_output"

current_stage="class-zero-after"
migration_report_after="$contract_directory/migration-after.json"
  "${compose[@]}" run --rm --no-deps migrate python migrate.py require-head --json \
  >"$migration_report_after"
database_revision_after="$(
  python3 "$contract_helper" verify-class-zero --report "$migration_report_after"
)"
if [ "$database_revision_before" != "$database_revision_after" ]; then
  echo "Database revision changed during the Class 0 activation preflight." >&2
  exit 2
fi

current_stage="application-cutover"
"${compose[@]}" up -d --no-deps backend frontend nginx

wait_for_health() {
  local label url attempt delay
  label="$1"
  url="$2"
  attempt=1
  delay="$HEALTH_CHECK_INITIAL_DELAY_SECONDS"
  while true; do
    if curl --fail --silent --show-error \
      --connect-timeout 5 --max-time 10 "$url" >/dev/null
    then
      echo "$label health check succeeded."
      return 0
    fi
    if [ "$attempt" -ge "$HEALTH_CHECK_ATTEMPTS" ]; then
      echo "$label health check failed after $attempt attempts." >&2
      return 1
    fi
    echo "$label health check attempt $attempt failed; retrying in ${delay}s." >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
    if [ "$delay" -gt "$HEALTH_CHECK_MAX_DELAY_SECONDS" ]; then
      delay="$HEALTH_CHECK_MAX_DELAY_SECONDS"
    fi
  done
}

current_stage="internal-health"
wait_for_health "Internal" "$INTERNAL_HEALTH_URL"
current_stage="external-health"
wait_for_health "External" "$EXTERNAL_HEALTH_URL"

current_stage="bounded-observation"
container_names=(
  pastexam-nginx
  pastexam-backend
  pastexam-frontend
  pastexam-postgres
  pastexam-redis
  pastexam-minio
)
declare -A initial_restart_counts
for container_name in "${container_names[@]}"; do
  restart_count="$(docker inspect --format '{{.RestartCount}}' "$container_name")"
  [[ "$restart_count" =~ ^[0-9]+$ ]] || {
    echo "Container restart evidence is malformed." >&2
    exit 2
  }
  initial_restart_counts["$container_name"]="$restart_count"
done

critical_error_count=0
for ((snapshot = 1; snapshot <= OBSERVATION_SNAPSHOTS; snapshot += 1)); do
  if [ "$snapshot" -gt 1 ]; then
    sleep "$OBSERVATION_INTERVAL_SECONDS"
  fi
  wait_for_health "Observation internal" "$INTERNAL_HEALTH_URL"
  wait_for_health "Observation external" "$EXTERNAL_HEALTH_URL"
  test "$(docker exec pastexam-redis redis-cli ping)" = "PONG"
  env -i \
    PATH="$PATH" \
    MINIO_CONTAINER="$MINIO_CONTAINER" \
    MINIO_BUCKET_NAME="$MINIO_BUCKET_NAME" \
    "$MINIO_PREFLIGHT_HELPER"
  for container_name in "${container_names[@]}"; do
    restart_count="$(docker inspect --format '{{.RestartCount}}' "$container_name")"
    if [ "$restart_count" != "${initial_restart_counts[$container_name]}" ]; then
      echo "Container restart count changed during bounded observation." >&2
      exit 2
    fi
  done
  for container_name in pastexam-nginx pastexam-backend pastexam-frontend; do
    running_image="$(docker inspect --format '{{.Config.Image}}' "$container_name")"
    if [ "$running_image" != "${expected_runtime_images[$container_name]}" ]; then
      echo "Container image authority changed during bounded observation." >&2
      exit 2
    fi
    if ! observed_critical_count="$(
      docker logs --since "$activation_started_at" "$container_name" 2>&1 | \
        python3 "$contract_helper" count-critical-log-lines
    )"
    then
      echo "Critical-error observation could not process container logs." >&2
      exit 2
    fi
    if [[ ! "$observed_critical_count" =~ ^[0-9]+$ ]]; then
      echo "Critical-error observation evidence is malformed." >&2
      exit 2
    fi
    critical_error_count=$((critical_error_count + observed_critical_count))
  done
  if [ "$critical_error_count" -ne 0 ]; then
    echo "Critical runtime errors were observed during bounded observation." >&2
    exit 2
  fi
done

current_stage="activation-marker"
activated_marker="$RELEASE_DIRECTORY/.activated"
temporary_marker="$activated_marker.partial"
printf '%s\n' "$RELEASE_MANIFEST_SHA256" >"$temporary_marker"
mv "$temporary_marker" "$activated_marker"

if [ -n "$ACTIVATION_EVIDENCE_PATH" ]; then
  current_stage="engine-evidence"
  postgres_metadata="$(printf '%s\n' "$postgres_backup_output" | sed -n 's/^Metadata: //p')"
  postgres_checksum="$(printf '%s\n' "$postgres_backup_output" | sed -n 's/^Checksum: //p')"
  minio_manifest="$(printf '%s\n' "$minio_manifest_output" | sed -n 's/^Read-only MinIO manifest: //p')"
  python3 "$contract_helper" write-engine-evidence \
    --output "$ACTIVATION_EVIDENCE_PATH" \
    --target-sha "$release_sha" \
    --database-revision-before "$database_revision_before" \
    --database-revision-after "$database_revision_after" \
    --postgres-metadata "$postgres_metadata" \
    --postgres-checksum "$postgres_checksum" \
    --minio-manifest "$minio_manifest" \
    --observation-snapshots "$OBSERVATION_SNAPSHOTS" \
    --critical-error-count "$critical_error_count" \
    --started-at "$activation_started_at"
fi

cleanup_contract
trap - EXIT HUP INT TERM

echo "Production release activation completed."
