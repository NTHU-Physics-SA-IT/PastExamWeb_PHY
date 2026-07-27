#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="${repo_root}/docker/docker-compose.dev.yml"
default_env_file="${repo_root}/docker/.env"
legacy_env_file="${repo_root}/docker/compose.dev.env"
env_file="${PASTEXAM_DEV_COMPOSE_ENV_FILE:-${default_env_file}}"

usage() {
  cat <<'EOF'
Usage: scripts/dev-compose.sh <preflight|config|start|stop|status|logs>

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

preflight() {
  require_local_docker
  require_env_file
  load_identity
  compose config --quiet

  local compose_dir project_workdirs other_workdirs
  compose_dir="$(dirname "${compose_file}")"
  project_workdirs="$(
    docker ps -a \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Label "com.docker.compose.project.working_dir"}}'
  )" || fail "cannot inspect the local Docker project"
  other_workdirs="$(
    printf '%s\n' "${project_workdirs}" |
      sort -u |
      grep -Fvx "${compose_dir}" || true
  )"
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
  *)
    usage
    exit 2
    ;;
esac
