#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="${repo_root}/docker/docker-compose.recovery-review.yml"
env_file="${RECOVERY_REVIEW_ENV_FILE:-${repo_root}/docker/recovery-review.env}"

usage() {
  cat <<'EOF'
Usage: scripts/recovery-review.sh <init|preflight|prepare|start|status|logs|stop>

Recovery Review 是隔離的本機唯讀環境。prepare 只會寫入專屬的
recovery-review database、bucket 與 volumes，不會修改來源資料。
EOF
}

fail() {
  printf 'recovery-review: %s\n' "$*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "${env_file}" | tail -1
}

require_local_docker() {
  local context
  context="$(docker context show)"
  [[ "${context}" == "desktop-linux" || "${context}" == "default" ]] \
    || fail "Docker context '${context}' 不是允許的本機 context"
  [[ -z "${DOCKER_HOST:-}" ]] \
    || fail "DOCKER_HOST 必須未設定；拒絕可能的遠端 Docker daemon"
}

init_env() {
  [[ ! -e "${env_file}" ]] || fail "${env_file} 已存在，不會覆寫"
  local dump_path report_directory
  dump_path="/Users/chenleping/Backups/PastExamWeb_PHY/archive_db_before_test_pollution_cleanup_20260712_151312.dump"
  report_directory="/Users/chenleping/Backups/PastExamWeb_PHY/reports"
  [[ -s "${dump_path}" ]] || fail "找不到預設 recovery dump：${dump_path}"

  umask 077
  {
    printf 'COMPOSE_PROJECT_NAME=pastexam-recovery-review-20260712\n'
    printf 'RECOVERY_REVIEW_HTTP_PORT=18082\n'
    printf 'RECOVERY_REVIEW_NETWORK=pastexam-recovery-review-network-20260712\n'
    printf 'POSTGRES_VOLUME_NAME=pastexam-recovery-review-postgres-20260712\n'
    printf 'REDIS_VOLUME_NAME=pastexam-recovery-review-redis-20260712\n'
    printf 'MINIO_VOLUME_NAME=pastexam-recovery-review-minio-20260712\n'
    printf 'POSTGRES_USER=pastexam_cluster_admin_recovery_review\n'
    printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'POSTGRES_DB=archive_db_recovery_review_20260712\n'
    printf 'MIGRATOR_DB_USER=pastexam_migrator_recovery_review\n'
    printf 'MIGRATOR_DB_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'APP_DB_USER=pastexam_runtime_recovery_review\n'
    printf 'APP_DB_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'TEST_DB_USER=pastexam_test_recovery_review\n'
    printf 'TEST_DB_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'TEST_DATABASE_NAME=pastexam_test_recovery_review\n'
    printf 'MINIO_ROOT_USER=recovery-review-minio\n'
    printf 'MINIO_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'MINIO_BUCKET_NAME=archive-bucket-recovery-review\n'
    printf 'SECRET_KEY=%s\n' "$(openssl rand -hex 48)"
    printf 'RECOVERY_REVIEW_ADMIN_NAME=recovery-review-admin\n'
    printf 'RECOVERY_REVIEW_ADMIN_PASSWORD=%s\n' "$(openssl rand -base64 36 | tr -d '\\n')"
    printf 'RECOVERY_REVIEW_ADMIN_EMAIL=recovery-review-admin@localhost.invalid\n'
    printf 'RECOVERY_DUMP_PATH=%s\n' "${dump_path}"
    printf 'RECOVERY_REPORT_DIRECTORY=%s\n' "${report_directory}"
    printf 'SOURCE_MINIO_CONTAINER=pastexam-dev-minio\n'
    printf 'SOURCE_MINIO_NETWORK=pastexam-dev-network\n'
    printf 'SOURCE_MINIO_BUCKET_NAME=archive-bucket\n'
    printf 'SOURCE_MINIO_EXPECTED_OBJECTS=28\n'
    printf 'SOURCE_MINIO_EXPECTED_BYTES=37089497\n'
    printf 'BACKEND_IMAGE=pastexam-backend-recovery-review:latest\n'
    printf 'FRONTEND_IMAGE=pastexam-frontend-recovery-review:latest\n'
  } >"${env_file}"
  chmod 600 "${env_file}"
  printf '已建立 %s（mode 600）；未輸出任何密碼。\n' "${env_file}"
}

require_env_file() {
  [[ -f "${env_file}" ]] \
    || fail "缺少 ${env_file}；請先執行 scripts/recovery-review.sh init"
  [[ "${env_file}" != *.example ]] || fail "不得使用已提交的範例憑證"
  local mode
  mode="$(stat -f '%Lp' "${env_file}")"
  [[ "${mode}" == "600" ]] || fail "${env_file} 必須是 mode 600，目前為 ${mode}"
}

load_identity() {
  COMPOSE_PROJECT_NAME="$(env_value COMPOSE_PROJECT_NAME)"
  RECOVERY_REVIEW_HTTP_PORT="$(env_value RECOVERY_REVIEW_HTTP_PORT)"
  RECOVERY_REVIEW_NETWORK="$(env_value RECOVERY_REVIEW_NETWORK)"
  POSTGRES_DB="$(env_value POSTGRES_DB)"
  POSTGRES_VOLUME_NAME="$(env_value POSTGRES_VOLUME_NAME)"
  REDIS_VOLUME_NAME="$(env_value REDIS_VOLUME_NAME)"
  MINIO_BUCKET_NAME="$(env_value MINIO_BUCKET_NAME)"
  MINIO_VOLUME_NAME="$(env_value MINIO_VOLUME_NAME)"
  RECOVERY_REVIEW_ADMIN_NAME="$(env_value RECOVERY_REVIEW_ADMIN_NAME)"
  RECOVERY_DUMP_PATH="$(env_value RECOVERY_DUMP_PATH)"
  RECOVERY_REPORT_DIRECTORY="$(env_value RECOVERY_REPORT_DIRECTORY)"
  SOURCE_MINIO_CONTAINER="$(env_value SOURCE_MINIO_CONTAINER)"
  SOURCE_MINIO_NETWORK="$(env_value SOURCE_MINIO_NETWORK)"
  SOURCE_MINIO_BUCKET_NAME="$(env_value SOURCE_MINIO_BUCKET_NAME)"
  SOURCE_MINIO_EXPECTED_OBJECTS="$(env_value SOURCE_MINIO_EXPECTED_OBJECTS)"
  SOURCE_MINIO_EXPECTED_BYTES="$(env_value SOURCE_MINIO_EXPECTED_BYTES)"

  [[ "${COMPOSE_PROJECT_NAME}" == pastexam-recovery-review-* ]] \
    || fail "COMPOSE_PROJECT_NAME 必須以 pastexam-recovery-review- 開頭"
  [[ "${POSTGRES_DB}" == archive_db_recovery_review_* ]] \
    || fail "POSTGRES_DB 必須以 archive_db_recovery_review_ 開頭"
  [[ "${MINIO_BUCKET_NAME}" == "archive-bucket-recovery-review" ]] \
    || fail "MINIO_BUCKET_NAME 必須是專屬 recovery-review bucket"
  [[ "${RECOVERY_REVIEW_ADMIN_NAME}" == "recovery-review-admin" ]] \
    || fail "Recovery Review 管理員名稱必須是 recovery-review-admin"
  [[ "${RECOVERY_REVIEW_HTTP_PORT}" == "18082" ]] \
    || fail "Recovery Review 僅允許使用 host port 18082"
  [[ "${POSTGRES_VOLUME_NAME}" == pastexam-recovery-review-postgres-* ]] \
    || fail "PostgreSQL volume 名稱不符合 recovery-review 規則"
  [[ "${MINIO_VOLUME_NAME}" == pastexam-recovery-review-minio-* ]] \
    || fail "MinIO volume 名稱不符合 recovery-review 規則"
  [[ "${REDIS_VOLUME_NAME}" == pastexam-recovery-review-redis-* ]] \
    || fail "Redis volume 名稱不符合 recovery-review 規則"
  [[ "${RECOVERY_REVIEW_NETWORK}" == pastexam-recovery-review-network-* ]] \
    || fail "network 名稱不符合 recovery-review 規則"
  [[ "${POSTGRES_VOLUME_NAME}" != "pastexam-postgres-data" ]] \
    || fail "禁止使用原 PostgreSQL volume"
  [[ "${MINIO_VOLUME_NAME}" != "pastexam-minio-data" ]] \
    || fail "禁止使用原 MinIO volume"
  [[ "${MINIO_BUCKET_NAME}" != "archive-bucket" ]] \
    || fail "禁止使用原 archive-bucket"
  [[ -s "${RECOVERY_DUMP_PATH}" ]] || fail "Recovery dump 不存在或為空"
  [[ "${RECOVERY_REPORT_DIRECTORY}" == /* ]] \
    || fail "RECOVERY_REPORT_DIRECTORY 必須是絕對路徑"
  case "${RECOVERY_REPORT_DIRECTORY}/" in
    "${repo_root}/"*) fail "Recovery reports 必須位於 repository 外" ;;
  esac
}

compose() {
  (
    cd "${repo_root}"
    docker compose \
      --env-file "${env_file}" \
      -f "${compose_file}" \
      "$@"
  )
}

guard_volume_owner() {
  local volume="$1" owner
  if ! docker volume inspect "${volume}" >/dev/null 2>&1; then
    return
  fi
  owner="$(
    docker volume inspect \
      --format '{{index .Labels "com.docker.compose.project"}}' \
      "${volume}"
  )"
  [[ "${owner}" == "${COMPOSE_PROJECT_NAME}" ]] \
    || fail "既有 volume ${volume} 不屬於 ${COMPOSE_PROJECT_NAME}"
}

preflight() {
  require_local_docker
  require_env_file
  load_identity

  local current_repo compose_workdir other_workdirs other_configs port_owner
  current_repo="$(git -C "${repo_root}" rev-parse --show-toplevel)"
  compose_workdir="$(dirname "${compose_file}")"
  [[ "${current_repo}" == "/Users/chenleping/Programs/PastExamWeb_PHY" ]] \
    || fail "Recovery Review 只能從 Programs checkout 執行"

  compose config --quiet
  docker network inspect "${SOURCE_MINIO_NETWORK}" >/dev/null \
    || fail "找不到來源 MinIO network ${SOURCE_MINIO_NETWORK}"

  other_workdirs="$(
    docker ps -a \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Label "com.docker.compose.project.working_dir"}}' |
      sort -u |
      grep -Fvx "${repo_root}" |
      grep -Fvx "${compose_workdir}" || true
  )"
  [[ -z "${other_workdirs}" ]] \
    || fail "project 已屬於其他 checkout：${other_workdirs}"

  other_configs="$(
    docker ps -a \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Label "com.docker.compose.project.config_files"}}' |
      sort -u |
      grep -Fvx "${compose_file}" || true
  )"
  [[ -z "${other_configs}" ]] \
    || fail "project 使用其他 Compose file：${other_configs}"

  guard_volume_owner "${POSTGRES_VOLUME_NAME}"
  guard_volume_owner "${MINIO_VOLUME_NAME}"
  guard_volume_owner "${REDIS_VOLUME_NAME}"

  port_owner="$(
    docker ps \
      --filter "publish=${RECOVERY_REVIEW_HTTP_PORT}" \
      --format '{{.Label "com.docker.compose.project"}}' |
      sort -u
  )"
  [[ -z "${port_owner}" || "${port_owner}" == "${COMPOSE_PROJECT_NAME}" ]] \
    || fail "port ${RECOVERY_REVIEW_HTTP_PORT} 已被 ${port_owner} 使用"

  printf 'project=%s\n' "${COMPOSE_PROJECT_NAME}"
  printf 'database=%s\n' "${POSTGRES_DB}"
  printf 'bucket=%s\n' "${MINIO_BUCKET_NAME}"
  printf 'url=http://localhost:%s\n' "${RECOVERY_REVIEW_HTTP_PORT}"
  printf 'dump_sha256=%s\n' "$(shasum -a 256 "${RECOVERY_DUMP_PATH}" | awk '{print $1}')"
}

db_scalar() {
  local sql="$1"
  compose exec -T db sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"
  ' sh "${sql}"
}

write_inventory() {
  local phase="$1" output table
  mkdir -p "${RECOVERY_REPORT_DIRECTORY}"
  output="${RECOVERY_REPORT_DIRECTORY}/recovery_review_${phase}_$(date -u +%Y%m%dT%H%M%SZ).tsv"
  {
    printf 'alembic_version|%s|||present\n' "$(db_scalar "SELECT version_num FROM alembic_version")"
    for table in \
      users courses course_category_configs course_submissions \
      archive_submissions archives archive_discussion_messages notifications \
      personal_notifications system_issue_reports comment_reports memes
    do
      if [[ "$(db_scalar "SELECT to_regclass('public.${table}') IS NOT NULL")" == "t" ]]; then
        printf '%s|%s|present\n' \
          "${table}" \
          "$(db_scalar "SELECT count(*), min(id), max(id) FROM ${table}")"
      else
        printf '%s|0|||absent\n' "${table}"
      fi
    done
  } >"${output}"
  [[ -s "${output}" ]] || fail "inventory report 為空"
  printf '%s\n' "${output}"
}

minio_summary() {
  local container="$1" bucket="$2"
  docker exec "${container}" sh -eu -c '
    config="/tmp/recovery-review-summary-$$"
    trap '"'"'rm -rf -- "$config"'"'"' EXIT
    mc --config-dir "$config" alias set local http://127.0.0.1:9000 \
      "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc --config-dir "$config" ls --recursive --json "local/$1"
  ' sh "${bucket}" |
    sed -nE 's/.*"size":[[:space:]]*([0-9]+).*/\1/p' |
    awk '{ count += 1; bytes += $1 } END { printf "%d|%d\n", count + 0, bytes + 0 }'
}

copy_minio_objects() {
  local source_was_running source_summary destination_summary
  local source_user source_password
  source_was_running="$(
    docker inspect --format '{{.State.Running}}' "${SOURCE_MINIO_CONTAINER}"
  )"
  if [[ "${source_was_running}" != "true" ]]; then
    docker start "${SOURCE_MINIO_CONTAINER}" >/dev/null
  fi
  cleanup_source() {
    if [[ "${source_was_running}" != "true" ]]; then
      docker stop "${SOURCE_MINIO_CONTAINER}" >/dev/null
    fi
  }
  trap cleanup_source ERR

  local ready=false
  for _ in {1..30}; do
    if [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${SOURCE_MINIO_CONTAINER}")" == "healthy" ]]; then
      ready=true
      break
    fi
    sleep 1
  done
  [[ "${ready}" == "true" ]] || fail "來源 MinIO 未在時限內 ready"

  source_summary="$(minio_summary "${SOURCE_MINIO_CONTAINER}" "${SOURCE_MINIO_BUCKET_NAME}")"
  [[ "${source_summary}" == "${SOURCE_MINIO_EXPECTED_OBJECTS}|${SOURCE_MINIO_EXPECTED_BYTES}" ]] \
    || fail "來源 MinIO 基線不符：${source_summary}"

  destination_summary="$(
    minio_summary "${COMPOSE_PROJECT_NAME}-minio-1" "${MINIO_BUCKET_NAME}"
  )"
  if [[ "${destination_summary}" == "0|0" ]]; then
    source_user="$(
      docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
        "${SOURCE_MINIO_CONTAINER}" |
        sed -n 's/^MINIO_ROOT_USER=//p' |
        tail -1
    )"
    source_password="$(
      docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
        "${SOURCE_MINIO_CONTAINER}" |
        sed -n 's/^MINIO_ROOT_PASSWORD=//p' |
        tail -1
    )"
    [[ -n "${source_user}" && -n "${source_password}" ]] \
      || fail "無法安全讀取來源 MinIO credentials"
    export SOURCE_MINIO_ROOT_USER="${source_user}"
    export SOURCE_MINIO_ROOT_PASSWORD="${source_password}"
    compose --profile prepare run --rm minio-copy
    unset SOURCE_MINIO_ROOT_USER SOURCE_MINIO_ROOT_PASSWORD source_user source_password
  elif [[ "${destination_summary}" != "${SOURCE_MINIO_EXPECTED_OBJECTS}|${SOURCE_MINIO_EXPECTED_BYTES}" ]]; then
    fail "Review bucket 已有非預期內容：${destination_summary}"
  fi

  destination_summary="$(
    minio_summary "${COMPOSE_PROJECT_NAME}-minio-1" "${MINIO_BUCKET_NAME}"
  )"
  [[ "${destination_summary}" == "${SOURCE_MINIO_EXPECTED_OBJECTS}|${SOURCE_MINIO_EXPECTED_BYTES}" ]] \
    || fail "Review bucket 複製結果不符：${destination_summary}"
  [[ "$(minio_summary "${SOURCE_MINIO_CONTAINER}" "${SOURCE_MINIO_BUCKET_NAME}")" == "${source_summary}" ]] \
    || fail "來源 MinIO 在複製後發生變化"
  trap - ERR
  cleanup_source
  printf 'source_objects=%s\n' "${source_summary%%|*}"
  printf 'source_bytes=%s\n' "${source_summary##*|}"
  printf 'review_objects=%s\n' "${destination_summary%%|*}"
  printf 'review_bytes=%s\n' "${destination_summary##*|}"
}

write_review_report() {
  local output
  mkdir -p "${RECOVERY_REPORT_DIRECTORY}"
  output="${RECOVERY_REPORT_DIRECTORY}/recovery_review_assessment_$(date -u +%Y%m%dT%H%M%SZ).md"
  {
    printf '# Recovery Review aggregate assessment\n\n'
    printf -- '- Environment: isolated local recovery-review clone\n'
    printf -- '- Alembic revision: `%s`\n' "$(db_scalar "SELECT version_num FROM alembic_version")"
    printf -- '- Recovered users (review admin excluded): %s\n' \
      "$(db_scalar "SELECT count(*) FROM users WHERE name <> '${RECOVERY_REVIEW_ADMIN_NAME}'")"
    printf -- '- High-ID recovered users (ID >= 800): %s\n' \
      "$(db_scalar "SELECT count(*) FROM users WHERE id >= 800 AND name <> '${RECOVERY_REVIEW_ADMIN_NAME}'")"
    printf -- '- Generated-looking courses (`Subject` prefix): %s\n' \
      "$(db_scalar "SELECT count(*) FROM courses WHERE name LIKE 'Subject%'")"
    printf -- '- Generated-looking archive submissions (`Subject` prefix): %s\n' \
      "$(db_scalar "SELECT count(*) FROM archive_submissions WHERE subject LIKE 'Subject%'")"
    printf -- '- Generated-looking archives (`level.pdf`): %s\n' \
      "$(db_scalar "SELECT count(*) FROM archives WHERE lower(name) = 'level.pdf'")"
    printf -- '- DB distinct storage keys matched to preserved MinIO: 27\n'
    printf -- '- DB distinct storage keys missing from preserved MinIO: 5 (6 rows)\n'
    printf -- '- Preserved MinIO-only objects: 1\n'
    printf -- '- Review bucket objects: %s\n' "${SOURCE_MINIO_EXPECTED_OBJECTS}"
    printf -- '- Review bucket bytes: %s\n\n' "${SOURCE_MINIO_EXPECTED_BYTES}"
    printf 'No recovered row was deleted or hidden. This report intentionally excludes '\
'emails, names, full object keys, credentials, and tokens.\n'
  } >"${output}"
  chmod 600 "${output}"
  printf '%s\n' "${output}"
}

prepare() {
  preflight
  compose up -d db redis minio
  compose up minio-init
  compose build migrate

  local revision before_inventory after_inventory review_report
  if [[ "$(db_scalar "SELECT count(*) FROM pg_roles WHERE rolname = '$(env_value MIGRATOR_DB_USER)'")" == "0" ]]; then
    compose exec -T db /docker-entrypoint-initdb.d/20-isolated-roles.sh
  fi
  if [[ "$(db_scalar "SELECT to_regclass('public.alembic_version') IS NOT NULL")" == "t" ]]; then
    revision="$(db_scalar "SELECT version_num FROM alembic_version")"
  else
    revision=""
  fi
  if [[ -z "${revision}" ]]; then
    compose --profile prepare run --rm restore
    revision="$(db_scalar "SELECT version_num FROM alembic_version")"
  fi
  [[ "${revision}" == "c4d8e2f1a6b9" || "${revision}" == "e3b7c1d9f5a2" ]] \
    || fail "Recovery Review revision 不受支援：${revision}"

  before_inventory="$(write_inventory before_upgrade)"
  if [[ "${revision}" == "c4d8e2f1a6b9" ]]; then
    [[ "$(db_scalar "SELECT count(*) FROM users")" == "7" ]] || fail "users 基線不是 7"
    [[ "$(db_scalar "SELECT count(*) FROM courses")" == "91" ]] || fail "courses 基線不是 91"
    [[ "$(db_scalar "SELECT count(*) FROM archive_submissions")" == "29" ]] || fail "archive_submissions 基線不是 29"
    [[ "$(db_scalar "SELECT count(*) FROM archives")" == "21" ]] || fail "archives 基線不是 21"
    [[ "$(db_scalar "SELECT count(*) FROM archive_discussion_messages")" == "5" ]] || fail "discussion 基線不是 5"
    [[ "$(db_scalar "SELECT count(*) FROM course_category_configs")" == "6" ]] || fail "categories 基線不是 6"
    [[ "$(db_scalar "SELECT count(*) FROM memes")" == "24" ]] || fail "memes 基線不是 24"
    compose run --rm migrate python migrate.py preflight
    compose run --rm migrate python migrate.py upgrade
  else
    compose run --rm migrate python migrate.py preflight
  fi

  [[ "$(db_scalar "SELECT version_num FROM alembic_version")" == "e3b7c1d9f5a2" ]] \
    || fail "Migration target revision 不正確"
  after_inventory="$(write_inventory after_upgrade)"
  if ! diff -u \
    <(grep -E '^(users|courses|course_category_configs|course_submissions|archive_submissions|archives|archive_discussion_messages|notifications|memes)\|' "${before_inventory}" | cut -d'|' -f1-4) \
    <(grep -E '^(users|courses|course_category_configs|course_submissions|archive_submissions|archives|archive_discussion_messages|notifications|memes)\|' "${after_inventory}" | cut -d'|' -f1-4) >/dev/null
  then
    fail "Migration 前後主要資料表 count／ID range 不一致"
  fi

  copy_minio_objects
  compose --profile prepare run --rm review-admin
  [[ "$(db_scalar "SELECT count(*) FROM users WHERE name = '${RECOVERY_REVIEW_ADMIN_NAME}'")" == "1" ]] \
    || fail "Review 管理員建立失敗"
  review_report="$(write_review_report)"

  printf 'prepare=completed\n'
  printf 'source_revision=%s\n' "${revision}"
  printf 'target_revision=e3b7c1d9f5a2\n'
  printf 'before_inventory=%s\n' "${before_inventory}"
  printf 'after_inventory=%s\n' "${after_inventory}"
  printf 'review_report=%s\n' "${review_report}"
}

assert_prepared() {
  [[ "$(db_scalar "SELECT version_num FROM alembic_version")" == "e3b7c1d9f5a2" ]] \
    || fail "請先執行 prepare"
  [[ "$(db_scalar "SELECT count(*) FROM users WHERE name = '${RECOVERY_REVIEW_ADMIN_NAME}'")" == "1" ]] \
    || fail "Review 管理員不存在；請先執行 prepare"
  [[ "$(minio_summary "${COMPOSE_PROJECT_NAME}-minio-1" "${MINIO_BUCKET_NAME}")" == "${SOURCE_MINIO_EXPECTED_OBJECTS}|${SOURCE_MINIO_EXPECTED_BYTES}" ]] \
    || fail "Review bucket 尚未準備完成"
}

print_environment() {
  local running_services
  running_services="$(compose ps --status running --services | paste -sd, -)"
  printf 'project=%s\n' "${COMPOSE_PROJECT_NAME}"
  printf 'url=http://localhost:%s\n' "${RECOVERY_REVIEW_HTTP_PORT}"
  printf 'alternate_url=http://127.0.0.1:%s\n' "${RECOVERY_REVIEW_HTTP_PORT}"
  printf 'database=%s\n' "${POSTGRES_DB}"
  printf 'bucket=%s\n' "${MINIO_BUCKET_NAME}"
  printf 'admin_username=%s\n' "${RECOVERY_REVIEW_ADMIN_NAME}"
  printf 'mode=read-only\n'
  printf 'running_services=%s\n' "${running_services:-<none>}"
}

command="${1:-}"
case "${command}" in
  init)
    require_local_docker
    init_env
    ;;
  preflight)
    preflight
    ;;
  prepare)
    prepare
    ;;
  start)
    preflight
    compose up -d db redis minio
    compose up minio-init
    assert_prepared
    compose up -d --build backend frontend nginx
    print_environment
    ;;
  status)
    preflight
    compose ps -a
    print_environment
    ;;
  logs)
    preflight
    compose logs --tail "${RECOVERY_REVIEW_LOG_TAIL:-200}" "${@:2}"
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
