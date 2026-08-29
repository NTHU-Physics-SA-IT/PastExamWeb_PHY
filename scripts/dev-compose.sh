#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="${repo_root}/docker/docker-compose.dev.yml"
runtime_root="${PASTEXAM_DEV_RUNTIME_ROOT:-${repo_root}}"
default_env_file="${runtime_root}/docker/.env"
legacy_env_file="${runtime_root}/docker/compose.dev.env"
env_file="${PASTEXAM_DEV_COMPOSE_ENV_FILE:-${default_env_file}}"
canonical_database="archive_db"
canonical_postgres_volume="pastexam-postgres-data"
EXPECTED_DATABASE=""
EXPECTED_POSTGRES_VOLUME=""
SCOPED_IDENTITY="false"

usage() {
  cat <<'EOF'
Usage: scripts/dev-compose.sh <preflight [identity options]|config|start|stop|status|logs|schema-status [identity options] [--expected-ledger REVISION]|backend-pause|backend-resume>

The development stack reads secrets and resource identities from the ignored
docker/.env file. It never bootstraps, destroys volumes, or targets
a remote Docker daemon.

Scoped persistent-local verification requires both --expected-database and
--expected-postgres-volume. The options are read-only identity assertions and
never rewrite the running database, volume, or Compose project.
EOF
}

fail() {
  printf 'dev-compose: %s\n' "$*" >&2
  exit 1
}

validate_database() {
  [[ "$1" =~ ^[a-z][a-z0-9_]{0,62}$ ]] \
    || fail "$2 must be a safe lowercase PostgreSQL database name"
}

validate_volume() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] \
    || fail "$2 must be a safe Docker volume name"
}

parse_identity_options() {
  local action="$1"
  shift
  EXPECTED_DATABASE=""
  EXPECTED_POSTGRES_VOLUME=""
  SCOPED_IDENTITY="false"
  SCHEMA_EXPECTED_LEDGER=""

  while [[ "$#" -gt 0 ]]; do
    [[ "$#" -ge 2 ]] || fail "$1 requires a non-empty value"
    case "$1" in
      --expected-ledger)
        [[ "${action}" == "schema-status" ]] \
          || fail "${action} does not accept --expected-ledger"
        [[ -z "${SCHEMA_EXPECTED_LEDGER}" ]] \
          || fail "--expected-ledger was provided twice"
        [[ "$2" =~ ^[0-9a-f]{12}$ ]] \
          || fail "--expected-ledger must be a 12-character lowercase hexadecimal revision"
        SCHEMA_EXPECTED_LEDGER="$2"
        ;;
      --expected-database)
        [[ -z "${EXPECTED_DATABASE}" ]] \
          || fail "--expected-database was provided twice"
        validate_database "$2" "--expected-database"
        EXPECTED_DATABASE="$2"
        ;;
      --expected-postgres-volume)
        [[ -z "${EXPECTED_POSTGRES_VOLUME}" ]] \
          || fail "--expected-postgres-volume was provided twice"
        validate_volume "$2" "--expected-postgres-volume"
        EXPECTED_POSTGRES_VOLUME="$2"
        ;;
      *)
        fail "unknown ${action} option: $1"
        ;;
    esac
    shift 2
  done

  if [[ -n "${EXPECTED_DATABASE}" || -n "${EXPECTED_POSTGRES_VOLUME}" ]]; then
    [[ -n "${EXPECTED_DATABASE}" && -n "${EXPECTED_POSTGRES_VOLUME}" ]] \
      || fail "scoped identity requires --expected-database and --expected-postgres-volume together"
    SCOPED_IDENTITY="true"
  else
    EXPECTED_DATABASE="${canonical_database}"
    EXPECTED_POSTGRES_VOLUME="${canonical_postgres_volume}"
  fi
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

load_base_identity() {
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
  validate_database "${POSTGRES_DB}" "POSTGRES_DB"
  [[ "${MINIO_BUCKET_NAME}" == "archive-bucket" ]] \
    || fail "MINIO_BUCKET_NAME must be archive-bucket"
  [[ "${DEV_HTTP_PORT}" == "8080" ]] || fail "development must use port 8080"
  [[ -n "${POSTGRES_VOLUME_NAME}" ]] || fail "POSTGRES_VOLUME_NAME must be set"
  [[ -n "${MINIO_VOLUME_NAME}" ]] || fail "MINIO_VOLUME_NAME must be set"
  [[ -n "${REDIS_VOLUME_NAME}" ]] || fail "REDIS_VOLUME_NAME must be set"
  [[ -n "${TARGET_NETWORK_NAME}" ]] || fail "TARGET_NETWORK_NAME must be set"
}

load_identity() {
  load_base_identity
  [[ "${POSTGRES_DB}" == "${canonical_database}" ]] \
    || fail "POSTGRES_DB must be ${canonical_database} unless scoped identity is explicit"
  [[ "${POSTGRES_VOLUME_NAME}" == "${canonical_postgres_volume}" ]] \
    || fail "POSTGRES_VOLUME_NAME must be ${canonical_postgres_volume} unless scoped identity is explicit"
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

require_runtime_root() {
  [[ "${runtime_root}" == /* ]] \
    || fail "PASTEXAM_DEV_RUNTIME_ROOT must be an absolute path"
  local resolved_runtime_root subject_common runtime_common worktree_path found
  resolved_runtime_root="$(cd "${runtime_root}" && pwd -P)" \
    || fail "PASTEXAM_DEV_RUNTIME_ROOT does not exist"
  [[ "${resolved_runtime_root}" == "${runtime_root}" ]] \
    || fail "PASTEXAM_DEV_RUNTIME_ROOT must be canonical"
  subject_common="$(git -C "${repo_root}" rev-parse --path-format=absolute --git-common-dir)" \
    || fail "cannot resolve tooling repository identity"
  runtime_common="$(git -C "${runtime_root}" rev-parse --path-format=absolute --git-common-dir)" \
    || fail "runtime root is not a Git worktree"
  [[ "$(normalize_checkout_path "${runtime_common}")" == \
      "$(normalize_checkout_path "${subject_common}")" ]] \
    || fail "runtime root belongs to another repository"
  found="false"
  while IFS= read -r worktree_path; do
    if [[ "$(normalize_checkout_path "${worktree_path}")" == \
        "$(normalize_checkout_path "${runtime_root}")" ]]; then
      found="true"
      break
    fi
  done < <(
    git -C "${repo_root}" worktree list --porcelain \
      | sed -n 's/^worktree //p'
  )
  [[ "${found}" == "true" ]] || fail "runtime root is not a registered worktree"
  if [[ "$(normalize_checkout_path "${runtime_root}")" != \
      "$(normalize_checkout_path "${repo_root}")" ]]; then
    [[ -f "${runtime_root}/backend/.env" ]] \
      || fail "runtime root backend environment is unavailable"
  fi
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

postgres_database_state() {
  docker inspect \
    --format '{{range .Config.Env}}{{println .}}{{end}}' \
    pastexam-dev-postgres \
    | sed -n 's/^POSTGRES_DB=//p'
}

postgres_volume_state() {
  docker inspect \
    --format \
    '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{printf "%s|%s|%s\n" .Type .Name .Destination}}{{end}}{{end}}' \
    pastexam-dev-postgres
}

require_postgres_identity() {
  local expected_database="$1"
  local expected_volume="$2"
  local actual_database actual_mount expected_mount
  actual_database="$(postgres_database_state)" \
    || fail "cannot inspect pastexam-dev-postgres database identity"
  [[ "${actual_database}" == "${expected_database}" ]] \
    || fail "pastexam-dev-postgres database identity does not match the explicit expectation"
  actual_mount="$(postgres_volume_state)" \
    || fail "cannot inspect pastexam-dev-postgres data mount"
  expected_mount="volume|${expected_volume}|/var/lib/postgresql/data"
  [[ "${actual_mount}" == "${expected_mount}" ]] \
    || fail "pastexam-dev-postgres volume identity does not match the explicit expectation"
  ACTUAL_DATABASE="${actual_database}"
  ACTUAL_POSTGRES_VOLUME="${expected_volume}"
}

audit_python() {
  local executable="${PASTEXAM_DEV_AUDIT_PYTHON:-${runtime_root}/backend/.venv/bin/python}"
  [[ -x "${executable}" ]] \
    || fail "missing backend audit environment; run 'uv sync --locked' in backend"
  printf '%s\n' "${executable}"
}

schema_status() {
  parse_identity_options "schema-status" "$@"
  if [[ "${SCOPED_IDENTITY}" == "true" ]]; then
    scoped_preflight
  else
    default_preflight
  fi
  require_container_state "pastexam-dev-postgres" "db" "running" "healthy"
  require_postgres_identity "${EXPECTED_DATABASE}" "${EXPECTED_POSTGRES_VOLUME}"
  local executable
  executable="$(audit_python)"
  local repository_sha
  repository_sha="$(git -C "${repo_root}" rev-parse HEAD)" \
    || fail "cannot resolve tooling repository HEAD for the sealed audit"
  [[ "${repository_sha}" =~ ^[0-9a-f]{40}$ ]] \
    || fail "tooling repository HEAD is invalid for the sealed audit"
  local audit_args=(
    "${repo_root}/backend/audit.py" run
    --audit archive-submission-self-delete-eligibility
    --mode persistent-local
    --repository-revision "${repository_sha}"
    --expected-database "${EXPECTED_DATABASE}"
    --output text
  )
  if [[ -n "${SCHEMA_EXPECTED_LEDGER}" ]]; then
    audit_args+=(--expected-ledger "${SCHEMA_EXPECTED_LEDGER}")
  fi
  (
    cd "${runtime_root}/backend"
    if [[ "$(normalize_checkout_path "${runtime_root}")" != \
        "$(normalize_checkout_path "${repo_root}")" ]]; then
      "${executable}" -m dotenv \
        --file "${runtime_root}/backend/.env" \
        run -- "${executable}" "${audit_args[@]}"
    else
      "${executable}" "${audit_args[@]}"
    fi
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

print_identity() {
  printf 'project=%s\n' "${COMPOSE_PROJECT_NAME}"
  printf 'url=http://localhost:%s\n' "${DEV_HTTP_PORT}"
  printf 'declared_database=%s\n' "${POSTGRES_DB}"
  printf 'expected_database=%s\n' "${EXPECTED_DATABASE}"
  printf 'actual_database=%s\n' "${ACTUAL_DATABASE}"
  printf 'bucket=%s\n' "${MINIO_BUCKET_NAME}"
  printf 'declared_postgres_volume=%s\n' "${POSTGRES_VOLUME_NAME}"
  printf 'expected_postgres_volume=%s\n' "${EXPECTED_POSTGRES_VOLUME}"
  printf 'actual_postgres_volume=%s\n' "${ACTUAL_POSTGRES_VOLUME}"
  printf 'minio_volume=%s\n' "${MINIO_VOLUME_NAME}"
  printf 'redis_volume=%s\n' "${REDIS_VOLUME_NAME}"
  printf 'network=%s\n' "${TARGET_NETWORK_NAME}"
}

default_preflight() {
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

  EXPECTED_DATABASE="${canonical_database}"
  EXPECTED_POSTGRES_VOLUME="${canonical_postgres_volume}"
  ACTUAL_DATABASE="not-running"
  ACTUAL_POSTGRES_VOLUME="not-running"
  if docker inspect pastexam-dev-postgres >/dev/null 2>&1; then
    require_postgres_identity "${EXPECTED_DATABASE}" "${EXPECTED_POSTGRES_VOLUME}"
  fi
  print_identity
}

scoped_preflight() {
  require_local_docker
  require_env_file
  load_base_identity
  require_runtime_root
  POSTGRES_DB="${EXPECTED_DATABASE}" \
    POSTGRES_VOLUME_NAME="${EXPECTED_POSTGRES_VOLUME}" \
    DEVELOPMENT_BACKEND_ENV_FILE="${runtime_root}/backend/.env" \
    DEVELOPMENT_FRONTEND_ENV_FILE="${runtime_root}/frontend/.env" \
    compose config --quiet
  require_container_state "pastexam-dev-postgres" "db" "running" "healthy"
  require_postgres_identity "${EXPECTED_DATABASE}" "${EXPECTED_POSTGRES_VOLUME}"
  print_identity
}

preflight() {
  parse_identity_options "preflight" "$@"
  if [[ "${SCOPED_IDENTITY}" == "true" ]]; then
    scoped_preflight
  else
    default_preflight
  fi
}

case "${1:-}" in
  preflight)
    preflight "${@:2}"
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
