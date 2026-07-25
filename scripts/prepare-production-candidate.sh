#!/usr/bin/env bash

set -euo pipefail
umask 077

release_sha="${RELEASE_SHA:?Set RELEASE_SHA}"
run_id="${RUN_ID:?Set RUN_ID}"
frontend_digest="${FRONTEND_IMAGE_DIGEST:?Set FRONTEND_IMAGE_DIGEST}"
backend_digest="${BACKEND_IMAGE_DIGEST:?Set BACKEND_IMAGE_DIGEST}"
source_archive_checksum="${SOURCE_ARCHIVE_SHA256:?Set SOURCE_ARCHIVE_SHA256}"
release_files_checksum="${RELEASE_FILES_SHA256:?Set RELEASE_FILES_SHA256}"
archive="${ARCHIVE_PATH:?Set ARCHIVE_PATH}"

releases_root="${RELEASES_ROOT:-/opt/pastexam-releases}"
production_config_root="${PRODUCTION_CONFIG_ROOT:-/opt/PastExamWeb_PHY}"
frontend_repository="${FRONTEND_IMAGE_REPOSITORY:-ghcr.io/nthu-physics-sa-it/pastexam}"
backend_repository="${BACKEND_IMAGE_REPOSITORY:-ghcr.io/nthu-physics-sa-it/pastexam}"

if command -v sha256sum >/dev/null 2>&1; then
  checksum_command=(env LC_ALL=C LANG=C sha256sum)
  checksum_check_command=(env LC_ALL=C LANG=C sha256sum --check --quiet)
elif command -v shasum >/dev/null 2>&1; then
  checksum_command=(env LC_ALL=C LANG=C shasum -a 256)
  checksum_check_command=(env LC_ALL=C LANG=C shasum -a 256 --check --status)
else
  echo "A SHA-256 checksum utility is required." >&2
  exit 1
fi

if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "RELEASE_SHA must be a full lowercase Git commit SHA." >&2
  exit 1
fi

if [[ ! "$run_id" =~ ^[0-9]+$ ]]; then
  echo "RUN_ID must contain only decimal digits." >&2
  exit 1
fi

for digest in "$frontend_digest" "$backend_digest"; do
  if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Image digests must be immutable sha256 references." >&2
    exit 1
  fi
done

for checksum in "$source_archive_checksum" "$release_files_checksum"; do
  if [[ ! "$checksum" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Candidate checksums must be lowercase SHA-256 values." >&2
    exit 1
  fi
done

release_root="$releases_root/$release_sha"
staging_root="$release_root.staging-$run_id"
manifest_name="release-manifest.env"

frontend_image="$frontend_repository:frontend-$release_sha@$frontend_digest"
backend_image="$backend_repository:backend-$release_sha@$backend_digest"

cleanup_run_artifacts() {
  rm -f -- "$archive"
  if [ -e "$staging_root" ]; then
    rm -rf -- "$staging_root"
  fi
}

trap cleanup_run_artifacts EXIT
trap 'exit 130' HUP INT TERM

manifest_value() {
  local manifest="$1"
  local key="$2"

  sed -n "s/^${key}=//p" "$manifest" | tail -n 1
}

verify_candidate() {
  local candidate_root="$1"
  local manifest="$candidate_root/$manifest_name"

  test -d "$candidate_root"
  test -f "$manifest"
  test -f "$candidate_root/.release-source-sha"
  test -f "$candidate_root/.release-files.sha256"
  test "$(cat "$candidate_root/.release-source-sha")" = "$release_sha"
  test "$("${checksum_command[@]}" "$candidate_root/.release-files.sha256" |
    cut -d ' ' -f 1)" = \
    "$release_files_checksum"

  (
    cd "$candidate_root"
    "${checksum_check_command[@]}" .release-files.sha256
  )

  test "$(manifest_value "$manifest" release_sha)" = "$release_sha"
  test -n "$(manifest_value "$manifest" workflow_run_id)"
  test -n "$(manifest_value "$manifest" created_at)"
  test "$(manifest_value "$manifest" source_archive_sha256)" = \
    "$source_archive_checksum"
  test "$(manifest_value "$manifest" release_files_sha256)" = \
    "$release_files_checksum"
  test "$(manifest_value "$manifest" frontend_image)" = "$frontend_image"
  test "$(manifest_value "$manifest" frontend_image_digest)" = \
    "$frontend_digest"
  test "$(manifest_value "$manifest" backend_image)" = "$backend_image"
  test "$(manifest_value "$manifest" backend_image_digest)" = \
    "$backend_digest"

  configured_images="$(
    docker compose \
      --env-file "$candidate_root/.env" \
      --file "$candidate_root/docker/docker-compose.yml" \
      config --images
  )"

  printf '%s\n' "$configured_images" | grep -Fxq "$frontend_image"
  printf '%s\n' "$configured_images" | grep -Fxq "$backend_image"
}

test -f "$archive"
test "$("${checksum_command[@]}" "$archive" | cut -d ' ' -f 1)" = \
  "$source_archive_checksum"

if [ -e "$release_root" ]; then
  verify_candidate "$release_root"
  echo "Existing candidate matches immutable release inputs: $release_root"
  exit 0
fi

if [ -e "$staging_root" ]; then
  echo "Run-specific staging path already exists: $staging_root" >&2
  exit 1
fi

root_env="$production_config_root/.env"
backend_env="$production_config_root/backend/.env"

if [ ! -f "$root_env" ] || [ ! -f "$backend_env" ]; then
  echo "Required production configuration files are unavailable." >&2
  exit 1
fi

install -d -m 700 "$releases_root"
install -d -m 700 "$staging_root"
tar -xzf "$archive" -C "$staging_root"

test "$(cat "$staging_root/.release-source-sha")" = "$release_sha"
test "$("${checksum_command[@]}" "$staging_root/.release-files.sha256" |
  cut -d ' ' -f 1)" = \
  "$release_files_checksum"

(
  cd "$staging_root"
  "${checksum_check_command[@]}" .release-files.sha256
)

install -m 600 "$root_env" "$staging_root/.env"
install -m 600 "$backend_env" "$staging_root/backend/.env"

{
  printf '\n'
  printf '# Immutable images for release %s\n' "$release_sha"
  printf 'FRONTEND_IMAGE=%s\n' "$frontend_image"
  printf 'BACKEND_IMAGE=%s\n' "$backend_image"
} >>"$staging_root/.env"

docker compose \
  --env-file "$staging_root/.env" \
  --file "$staging_root/docker/docker-compose.yml" \
  config --quiet

configured_images="$(
  docker compose \
    --env-file "$staging_root/.env" \
    --file "$staging_root/docker/docker-compose.yml" \
    config --images
)"

printf '%s\n' "$configured_images" | grep -Fxq "$frontend_image"
printf '%s\n' "$configured_images" | grep -Fxq "$backend_image"

created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat >"$staging_root/$manifest_name" <<EOF
release_sha=$release_sha
workflow_run_id=$run_id
frontend_image=$frontend_image
frontend_image_digest=$frontend_digest
backend_image=$backend_image
backend_image_digest=$backend_digest
created_at=$created_at
source_archive_sha256=$source_archive_checksum
release_files_sha256=$release_files_checksum
EOF
chmod 600 "$staging_root/$manifest_name"

verify_candidate "$staging_root"

if [ -e "$release_root" ]; then
  echo "Candidate appeared while staging; refusing to overwrite it." >&2
  exit 1
fi

mv "$staging_root" "$release_root"
verify_candidate "$release_root"

echo "Candidate prepared without switching production: $release_root"
