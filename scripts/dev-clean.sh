#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="${repo_root}/docker/docker-compose.clean-dev.yml"
env_file="${CLEAN_DEV_ENV_FILE:-${repo_root}/docker/clean-dev.env}"

usage() {
  cat <<'EOF'
Usage: scripts/dev-clean.sh <preflight|start|bootstrap|status|logs|stop>

The clean-development stack is isolated from the normal local stack. Copy
docker/clean-dev.env.example to docker/clean-dev.env and replace every example
credential before starting it.
EOF
}

fail() {
  printf 'dev-clean: %s\n' "$*" >&2
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
  [[ -f "${env_file}" ]] || fail "missing ${env_file}; create it from docker/clean-dev.env.example"
  [[ "${env_file}" != *.example ]] || fail "do not run with the committed example credentials"
}

load_identity() {
  COMPOSE_PROJECT_NAME="$(
    sed -n 's/^COMPOSE_PROJECT_NAME=//p' "${env_file}" | tail -1
  )"
  POSTGRES_DB="$(sed -n 's/^POSTGRES_DB=//p' "${env_file}" | tail -1)"
  MINIO_BUCKET_NAME="$(
    sed -n 's/^MINIO_BUCKET_NAME=//p' "${env_file}" | tail -1
  )"
  CLEAN_DEV_HTTP_PORT="$(
    sed -n 's/^CLEAN_DEV_HTTP_PORT=//p' "${env_file}" | tail -1
  )"
  DEFAULT_ADMIN_NAME="$(
    sed -n 's/^DEFAULT_ADMIN_NAME=//p' "${env_file}" | tail -1
  )"
  CLEAN_DEV_HTTP_PORT="${CLEAN_DEV_HTTP_PORT:-18081}"

  [[ "${COMPOSE_PROJECT_NAME}" == pastexam-dev-clean-* ]] \
    || fail "COMPOSE_PROJECT_NAME must start with pastexam-dev-clean-"
  [[ "${POSTGRES_DB}" == archive_db_dev_* ]] \
    || fail "POSTGRES_DB must start with archive_db_dev_"
  [[ "${MINIO_BUCKET_NAME}" == *-dev-clean* ]] \
    || fail "MINIO_BUCKET_NAME must be an isolated dev-clean bucket"
  [[ "${POSTGRES_DB}" != "archive_db" ]] || fail "normal archive_db is forbidden"
  [[ "${MINIO_BUCKET_NAME}" != "archive-bucket" ]] || fail "normal archive-bucket is forbidden"
  [[ "${CLEAN_DEV_HTTP_PORT}" =~ ^[0-9]+$ ]] \
    || fail "CLEAN_DEV_HTTP_PORT must be numeric"
  [[ -n "${DEFAULT_ADMIN_NAME}" ]] || fail "DEFAULT_ADMIN_NAME must be set"
}

compose() {
  docker compose --env-file "${env_file}" -f "${compose_file}" "$@"
}

print_manual_environment() {
  local running_services
  running_services="$(compose ps --status running --services | paste -sd, -)"
  printf 'project=%s\n' "${COMPOSE_PROJECT_NAME}"
  printf 'url=http://127.0.0.1:%s\n' "${CLEAN_DEV_HTTP_PORT}"
  printf 'alternate_url=http://localhost:%s\n' "${CLEAN_DEV_HTTP_PORT}"
  printf 'database=%s\n' "${POSTGRES_DB}"
  printf 'bucket=%s\n' "${MINIO_BUCKET_NAME}"
  printf 'admin_username=%s\n' "${DEFAULT_ADMIN_NAME}"
  printf 'running_services=%s\n' "${running_services:-<none>}"
}

preflight() {
  require_local_docker
  require_env_file
  load_identity
  "${repo_root}/scripts/validate-compose-safety.sh"
  compose config --quiet

  local compose_dir other_workdirs other_config_files
  compose_dir="$(dirname "${compose_file}")"
  other_workdirs="$(
    docker ps -a \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Label "com.docker.compose.project.working_dir"}}' |
      sort -u |
      grep -Fvx "${compose_dir}" || true
  )"
  [[ -z "${other_workdirs}" ]] \
    || fail "project ${COMPOSE_PROJECT_NAME} already belongs to another checkout: ${other_workdirs}"

  other_config_files="$(
    docker ps -a \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Label "com.docker.compose.project.config_files"}}' |
      sort -u |
      grep -Fvx "${compose_file}" || true
  )"
  [[ -z "${other_config_files}" ]] \
    || fail "project ${COMPOSE_PROJECT_NAME} uses another compose file: ${other_config_files}"

  printf 'project=%s\n' "${COMPOSE_PROJECT_NAME}"
  printf 'database=%s\n' "${POSTGRES_DB}"
  printf 'bucket=%s\n' "${MINIO_BUCKET_NAME}"
  printf 'compose=%s\n' "${compose_file}"
}

command="${1:-}"
case "${command}" in
  preflight)
    preflight
    ;;
  start)
    preflight
    compose up -d db redis minio
    compose up --build migrate
    compose up minio-init
    compose up -d --build backend frontend nginx
    print_manual_environment
    ;;
  bootstrap)
    preflight
    compose --profile bootstrap run --rm bootstrap
    ;;
  status)
    preflight
    compose ps -a
    print_manual_environment
    ;;
  logs)
    preflight
    compose logs --tail "${CLEAN_DEV_LOG_TAIL:-200}" "${@:2}"
    ;;
  stop)
    preflight
    compose stop
    ;;
  *)
    usage
    exit 2
    ;;
esac
