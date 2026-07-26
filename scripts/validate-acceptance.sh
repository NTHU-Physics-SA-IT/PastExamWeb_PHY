#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repository_root/docker/docker-compose.acceptance.yml"
env_file="${ACCEPTANCE_ENV_FILE:-$repository_root/docker/acceptance.env.example}"

if [ ! -f "$env_file" ]; then
  echo "Acceptance environment file not found: $env_file" >&2
  exit 1
fi

project_name="${ACCEPTANCE_PROJECT_NAME:-}"
if [ -z "$project_name" ]; then
  project_name="pastexam-acceptance-$(
    date -u +%Y%m%d%H%M%S
  )-$$-$RANDOM"
fi

case "$project_name" in
  pastexam-acceptance-*) ;;
  *)
    echo "Refusing non-acceptance Compose project: $project_name" >&2
    exit 1
    ;;
esac

export COMPOSE_PROJECT_NAME="$project_name"

compose=(
  docker compose
  --project-name "$project_name"
  --env-file "$env_file"
  --file "$compose_file"
)

case "${ACCEPTANCE_BUILD:-true}" in
  true) build_enabled=1 ;;
  false) build_enabled=0 ;;
  *)
    echo "ACCEPTANCE_BUILD must be true or false." >&2
    exit 1
    ;;
esac

postgres_user="$(
  sed -n 's/^POSTGRES_USER=//p' "$env_file" |
    tail -n 1
)"
empty_database="$(
  sed -n 's/^POSTGRES_DB=//p' "$env_file" |
    tail -n 1
)"
upgrade_database="$(
  sed -n 's/^ACCEPTANCE_UPGRADE_DB=//p' "$env_file" |
    tail -n 1
)"
test_database="$(
  sed -n 's/^ACCEPTANCE_TEST_DB=//p' "$env_file" |
    tail -n 1
)"
http_port="$(
  sed -n 's/^ACCEPTANCE_HTTP_PORT=//p' "$env_file" |
    tail -n 1
)"

for required_value in \
  "$postgres_user" \
  "$empty_database" \
  "$upgrade_database" \
  "$test_database" \
  "$http_port"
do
  if [ -z "$required_value" ]; then
    echo "Acceptance environment is missing a required value." >&2
    exit 1
  fi
done

"${compose[@]}" config --quiet

keep_acceptance="${KEEP_ACCEPTANCE:-0}"
case "$keep_acceptance" in
  0 | 1) ;;
  *)
    echo "KEEP_ACCEPTANCE must be 0 or 1." >&2
    exit 1
    ;;
esac

if [ -n "$(
  docker ps -aq \
    --filter "label=com.docker.compose.project=$project_name"
)" ]; then
  echo "Refusing to reuse acceptance containers for $project_name." >&2
  exit 1
fi

if docker network inspect "${project_name}_default" >/dev/null 2>&1; then
  echo "Refusing to reuse acceptance network for $project_name." >&2
  exit 1
fi

for volume_name in \
  "${project_name}_postgres_data" \
  "${project_name}_redis_data" \
  "${project_name}_minio_data"
do
  if docker volume inspect "$volume_name" >/dev/null 2>&1; then
    echo "Refusing to reuse acceptance volume: $volume_name" >&2
    exit 1
  fi
done

cleanup_acceptance() {
  exit_status=$?
  trap - EXIT HUP INT TERM

  if [ "$keep_acceptance" = "1" ]; then
    echo "Keeping acceptance resources for diagnostics: $project_name"
  elif ! "${compose[@]}" down --volumes --remove-orphans; then
    echo "Failed to clean acceptance resources: $project_name" >&2
    if [ "$exit_status" -eq 0 ]; then
      exit_status=1
    fi
  fi

  exit "$exit_status"
}

trap cleanup_acceptance EXIT
trap 'exit 130' HUP INT TERM

compose_up() {
  if [ "$build_enabled" = "1" ]; then
    "${compose[@]}" up -d --build --wait "$@"
  else
    "${compose[@]}" up -d --wait "$@"
  fi
}

compose_up db redis minio

echo "Validating empty database migration to head..."
alembic_table_exists="$(
  "${compose[@]}" exec -T db sh -eu -c '
    psql \
      -U "$POSTGRES_USER" \
      -d "$POSTGRES_DB" \
      -Atc "
        SELECT to_regclass('\''public.alembic_version'\'') IS NOT NULL;
      "
  '
)"

if [ "$alembic_table_exists" != "f" ]; then
  echo "Empty acceptance database already contains alembic_version." >&2
  exit 1
fi

"${compose[@]}" run --rm migrate
"${compose[@]}" run --rm migrate alembic current
"${compose[@]}" run --rm migrate

echo "Validating migration path from 3a7e9c1d5b42 to head..."
"${compose[@]}" exec -T db sh -eu -c '
  database_name="$1"
  if ! psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '\''$database_name'\''" |
    grep -Fxq 1
  then
    createdb -U "$POSTGRES_USER" "$database_name"
  fi
' sh "$upgrade_database"
"${compose[@]}" run --rm \
  -e "DB_NAME=$upgrade_database" \
  migrate alembic upgrade 3a7e9c1d5b42
"${compose[@]}" run --rm \
  -e "DB_NAME=$upgrade_database" \
  migrate alembic current
"${compose[@]}" run --rm \
  -e "DB_NAME=$upgrade_database" \
  migrate alembic upgrade head
"${compose[@]}" run --rm \
  -e "DB_NAME=$upgrade_database" \
  migrate alembic current
"${compose[@]}" run --rm \
  -e "DB_NAME=$upgrade_database" \
  migrate alembic upgrade head

echo "Running backend tests against a third isolated database..."
"${compose[@]}" exec -T db sh -eu -c '
  database_name="$1"
  if ! psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '\''$database_name'\''" |
    grep -Fxq 1
  then
    createdb -U "$POSTGRES_USER" "$database_name"
  fi
' sh "$test_database"
"${compose[@]}" run --rm \
  -e "DB_NAME=$test_database" \
  migrate alembic upgrade head
"${compose[@]}" run --rm \
  -e "DB_NAME=$test_database" \
  -e "ALLOW_DATABASE_BOOTSTRAP=true" \
  migrate python -m app.scripts.seed_db \
  --confirm-database-name "$test_database"
"${compose[@]}" --profile tests run --rm backend-tests

compose_up backend frontend nginx

curl --fail --silent --show-error \
  "http://127.0.0.1:$http_port/api/health"
curl --fail --silent --show-error \
  "http://127.0.0.1:$http_port/" >/dev/null

"${compose[@]}" exec -T redis redis-cli ping |
  grep -Fxq PONG
"${compose[@]}" exec -T minio mc ready local

"${compose[@]}" ps
echo "Acceptance validation completed for $project_name."
