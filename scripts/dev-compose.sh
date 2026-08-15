#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="${repo_root}/docker/docker-compose.dev.yml"
default_env_file="${repo_root}/docker/.env"
legacy_env_file="${repo_root}/docker/compose.dev.env"
env_file="${PASTEXAM_DEV_COMPOSE_ENV_FILE:-${default_env_file}}"

usage() {
  cat <<'EOF'
Usage: scripts/dev-compose.sh <preflight|config|start|stop|status|logs|schema-status [--expected-ledger REVISION]|backend-pause|backend-resume>

The development stack reads secrets and resource identities from the ignored
docker/.env file. It never bootstraps, destroys volumes, or targets
a remote Docker daemon.
EOF
}

fail() {
  printf 'dev-compose: %s\n' "$*" >&2
  exit 1
}

require_local_docker() {
  local context
  context="$(docker context show)"
  [[ "${context}" == "desktop-linux" || "${context}" == "default" ]] \
    || fail "Docker context '${context}' is not an approved local context"
  [[ -z "${DOCKER_HOST:-}" ]] \
    || fail "DOCKER_HOST must be unset; refusing a possibly remote daemon"
}

require_env_file() {
  if [[ ! -f "${env_file}" ]]; then
    if [[ "${env_file}" == "${default_env_file}" && -f "${legacy_env_file}" ]]; then
      fail "docker/compose.dev.env is retired; move it to docker/.env"
    fi
    fail "missing ${env_file}; run: cp docker/.env.example docker/.env"
  fi
  [[ "${env_file}" != *.example ]] || fail "do not run with committed example credentials"
  case "$(basename "${env_file}")" in
    .env.production | compose.prod.env)
      fail "refusing to use the production Compose environment"
      ;;
  esac
}

env_value() {
  sed -n "s/^$1=//p" "${env_file}" | tail -1
}

load_identity() {
  COMPOSE_PROJECT_NAME="$(env_value COMPOSE_PROJECT_NAME)"
  POSTGRES_DB="$(env_value POSTGRES_DB)"
  MINIO_BUCKET_NAME="$(env_value MINIO_BUCKET_NAME)"
  DEV_HTTP_PORT="$(env_value DEV_HTTP_PORT)"
  POSTGRES_VOLUME_NAME="$(env_value POSTGRES_VOLUME_NAME)"
  MINIO_VOLUME_NAME="$(env_value MINIO_VOLUME_NAME)"
  REDIS_VOLUME_NAME="$(env_value REDIS_VOLUME_NAME)"
  TARGET_NETWORK_NAME="$(env_value TARGET_NETWORK_NAME)"

  [[ "${COMPOSE_PROJECT_NAME}" == "pastexam-dev" ]] \
    || fail "COMPOSE_PROJECT_NAME must be pastexam-dev"
  [[ "${POSTGRES_DB}" == "archive_db" ]] || fail "POSTGRES_DB must be archive_db"
  [[ "${MINIO_BUCKET_NAME}" == "archive-bucket" ]] \
    || fail "MINIO_BUCKET_NAME must be archive-bucket"
  [[ "${DEV_HTTP_PORT}" == "8080" ]] || fail "development must use port 8080"
  [[ -n "${POSTGRES_VOLUME_NAME}" ]] || fail "POSTGRES_VOLUME_NAME must be set"
  [[ -n "${MINIO_VOLUME_NAME}" ]] || fail "MINIO_VOLUME_NAME must be set"
  [[ -n "${REDIS_VOLUME_NAME}" ]] || fail "REDIS_VOLUME_NAME must be set"
  [[ -n "${TARGET_NETWORK_NAME}" ]] || fail "TARGET_NETWORK_NAME must be set"
}

compose() {
  docker compose \
    --project-name "${COMPOSE_PROJECT_NAME}" \
    --env-file "${env_file}" \
    -f "${compose_file}" \
    "$@"
}

normalize_checkout_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    path="$(cygpath -am "${path}")"
  fi
  path="${path//\\//}"
  printf '%s\n' "${path%/}"
}

container_state() {
  local container_name="$1"
  docker inspect \
    --format \
    '{{.Name}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
    "${container_name}"
}

require_container_state() {
  local container_name="$1"
  local service="$2"
  local state="$3"
  local health="$4"
  local actual expected
  actual="$(container_state "${container_name}")" \
    || fail "cannot inspect ${container_name}"
  expected="/${container_name}|${COMPOSE_PROJECT_NAME}|${service}|${state}|${health}"
  [[ "${actual}" == "${expected}" ]] \
    || fail "${container_name} identity/state is incompatible: ${actual}"
}

audit_python() {
  local executable="${PASTEXAM_DEV_AUDIT_PYTHON:-${repo_root}/backend/.venv/bin/python}"
  [[ -x "${executable}" ]] \
    || fail "missing backend audit environment; run 'uv sync --locked' in backend"
  printf '%s\n' "${executable}"
}

schema_status() {
  local expected_ledger=""
  if [[ "$#" -eq 0 ]]; then
    :
  elif [[ "$#" -eq 2 \
    && "$1" == "--expected-ledger" \
    && "$2" =~ ^[0-9a-f]{12}$ ]]; then
    expected_ledger="$2"
  else
    fail "schema-status accepts only --expected-ledger with a 12-character lowercase hexadecimal revision"
  fi

  preflight
  require_container_state "pastexam-dev-postgres" "db" "running" "healthy"
  local executable
  executable="$(audit_python)"
  local audit_args=(
    audit.py run
    --audit archive-submission-self-delete-eligibility
    --mode persistent-local
    --output text
  )
  if [[ -n "${expected_ledger}" ]]; then
    audit_args+=(--expected-ledger "${expected_ledger}")
  fi
  (
    cd "${repo_root}/backend"
    "${executable}" "${audit_args[@]}"
  )
}

backend_pause() {
  preflight
  require_container_state "pastexam-dev-backend" "backend" "running" "healthy"
  compose stop backend
}

backend_resume() {
  schema_status
  local stopped
  stopped="$(container_state "pastexam-dev-backend")" \
    || fail "cannot inspect pastexam-dev-backend before resume"
  if [[ "${stopped}" != \
      "/pastexam-dev-backend|${COMPOSE_PROJECT_NAME}|backend|exited|" \
    && "${stopped}" != \
      "/pastexam-dev-backend|${COMPOSE_PROJECT_NAME}|backend|exited|unhealthy" ]]; then
    fail "pastexam-dev-backend identity/state is incompatible: ${stopped}"
  fi
  compose start backend

  local attempt actual
  for attempt in {1..30}; do
    actual="$(container_state "pastexam-dev-backend")" \
      || fail "cannot inspect pastexam-dev-backend after resume"
    if [[ "${actual}" == \
      "/pastexam-dev-backend|${COMPOSE_PROJECT_NAME}|backend|running|healthy" ]]; then
      printf 'backend=running/healthy\n'
      return
    fi
    sleep 2
  done
  fail "backend did not become healthy after guarded resume"
}

preflight() {
  require_local_docker
  require_env_file
  load_identity
  compose config --quiet

  local compose_dir project_workdirs other_workdirs project_workdir
  compose_dir="$(normalize_checkout_path "$(dirname "${compose_file}")")"
  project_workdirs="$(
    docker ps -a \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Label "com.docker.compose.project.working_dir"}}'
  )" || fail "cannot inspect the local Docker project"
  other_workdirs=""
  while IFS= read -r project_workdir; do
    [[ -z "${project_workdir}" ]] && continue
    if [[ "$(normalize_checkout_path "${project_workdir}")" != "${compose_dir}" ]]; then
      other_workdirs+="${project_workdir}"$'\n'
    fi
  done < <(printf '%s\n' "${project_workdirs}" | sort -u)
  other_workdirs="${other_workdirs%$'\n'}"
  [[ -z "${other_workdirs}" ]] \
    || fail "project ${COMPOSE_PROJECT_NAME} belongs to another checkout: ${other_workdirs}"

  printf 'project=%s\n' "${COMPOSE_PROJECT_NAME}"
  printf 'url=http://localhost:%s\n' "${DEV_HTTP_PORT}"
  printf 'database=%s\n' "${POSTGRES_DB}"
  printf 'bucket=%s\n' "${MINIO_BUCKET_NAME}"
  printf 'postgres_volume=%s\n' "${POSTGRES_VOLUME_NAME}"
  printf 'minio_volume=%s\n' "${MINIO_VOLUME_NAME}"
  printf 'redis_volume=%s\n' "${REDIS_VOLUME_NAME}"
  printf 'network=%s\n' "${TARGET_NETWORK_NAME}"
}

case "${1:-}" in
  preflight)
    preflight
    ;;
  config)
    preflight
    compose config --services
    ;;
  start)
    preflight
    compose up -d
    ;;
  stop)
    preflight
    compose stop
    ;;
  status)
    preflight
    compose ps -a
    ;;
  logs)
    preflight
    compose logs --tail "${DEV_LOG_TAIL:-200}" "${@:2}"
    ;;
  schema-status)
    schema_status "${@:2}"
    ;;
  backend-pause)
    backend_pause
    ;;
  backend-resume)
    backend_resume
    ;;
  *)
    usage
    exit 2
    ;;
esac
