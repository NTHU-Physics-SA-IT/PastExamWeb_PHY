#!/usr/bin/env bash

# Canonical source for the root-owned host command installed as
# /usr/local/sbin/pastexam-prepare-candidate. The candidate SSH principal may
# invoke only its fixed preflight, prepare, and run-scoped cleanup interface.
set -euo pipefail
umask 077

minimum_available_bytes=$((10 * 1024 * 1024 * 1024))
minimum_available_percent=20
minimum_available_inodes=100000
minimum_inode_percent=10
maximum_archive_bytes=$((256 * 1024 * 1024))

if [ "${PASTEXAM_CANDIDATE_TEST_MODE:-}" = "1" ] && [ "$(id -u)" -ne 0 ]; then
  releases_root="${PASTEXAM_CANDIDATE_TEST_RELEASES_ROOT:?Set test releases root}"
  production_compose_env="${PASTEXAM_CANDIDATE_TEST_COMPOSE_ENV:?Set test Compose env}"
  preparation_lock="$releases_root/.candidate-preparation.lock"
else
  releases_root=/opt/pastexam-releases
  production_compose_env=/etc/pastexam/compose.prod.env
  preparation_lock=/run/lock/pastexam-candidate-preparation.lock
fi

frontend_repository=ghcr.io/nthu-physics-sa-it/pastexam
backend_repository=ghcr.io/nthu-physics-sa-it/pastexam
nginx_image=nginx:1.29.2@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903
nginx_digest=sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903
manifest_name=release-manifest.env
receipt_name=candidate-receipt.json
receipt_checksum_name=candidate-receipt.sha256

die() {
  printf '%s\n' "$1" >&2
  exit 1
}

require_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || die "Release SHA must be a full lowercase commit SHA."
}

require_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]] || die "$2 must be a positive decimal integer."
}

require_digest() {
  [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Image digest is malformed."
}

require_checksum() {
  [[ "$1" =~ ^[0-9a-f]{64}$ ]] || die "Candidate checksum is malformed."
}

if command -v sha256sum >/dev/null 2>&1; then
  checksum_command=(env LC_ALL=C LANG=C sha256sum)
  checksum_check_command=(env LC_ALL=C LANG=C sha256sum --check --quiet)
else
  die "sha256sum is required."
fi

source_authorities=(
  scripts/production-deployment-control.py
  scripts/pastexam-activate-ssh-wrapper.sh
  scripts/activate-production-release.sh
  scripts/production-activation-contract.py
  scripts/postgres-logical-backup.sh
  scripts/minio-storage-preflight.sh
  scripts/minio-readonly-manifest.sh
  docker/docker-compose.nginx-immutable.yml
)

capacity_preflight() {
  [ -d "$releases_root" ] || die "Candidate release root is unavailable."
  local disk_metrics inode_metrics
  disk_metrics="$(LC_ALL=C df -Pk -- "$releases_root" | awk 'NR == 2 {print $2, $4, $5}')"
  inode_metrics="$(LC_ALL=C df -Pi -- "$releases_root" | awk 'NR == 2 {print $2, $4, $5}')"
  local total_blocks available_blocks disk_used extra
  local total_inodes available_inodes inode_used
  read -r total_blocks available_blocks disk_used extra <<<"$disk_metrics"
  [ -z "${extra:-}" ] || die "Filesystem capacity metrics are malformed."
  read -r total_inodes available_inodes inode_used extra <<<"$inode_metrics"
  [ -z "${extra:-}" ] || die "Filesystem inode metrics are malformed."
  [[ "$total_blocks" =~ ^[1-9][0-9]*$ ]] || die "Filesystem capacity metrics are unavailable."
  [[ "$available_blocks" =~ ^[0-9]+$ ]] || die "Filesystem capacity metrics are unavailable."
  [[ "$disk_used" =~ ^[0-9]+%$ ]] || die "Filesystem capacity metrics are unavailable."
  [[ "$total_inodes" =~ ^[1-9][0-9]*$ ]] || die "Filesystem inode metrics are unavailable."
  [[ "$available_inodes" =~ ^[0-9]+$ ]] || die "Filesystem inode metrics are unavailable."
  [[ "$inode_used" =~ ^[0-9]+%$ ]] || die "Filesystem inode metrics are unavailable."
  [ "$available_blocks" -le "$total_blocks" ] || \
    die "Filesystem capacity metrics are malformed."
  [ "$available_inodes" -le "$total_inodes" ] || \
    die "Filesystem inode metrics are malformed."
  local available_bytes disk_available_percent inode_available_percent
  available_bytes=$((available_blocks * 1024))
  disk_available_percent=$((100 - ${disk_used%\%}))
  inode_available_percent=$((100 - ${inode_used%\%}))
  [ "$disk_available_percent" -ge 0 ] && [ "$disk_available_percent" -le 100 ] || \
    die "Filesystem capacity metrics are malformed."
  [ "$inode_available_percent" -ge 0 ] && [ "$inode_available_percent" -le 100 ] || \
    die "Filesystem inode metrics are malformed."
  [ "$available_bytes" -ge "$minimum_available_bytes" ] && \
    [ "$disk_available_percent" -ge "$minimum_available_percent" ] || \
    die "Candidate disk capacity is below the fail-closed threshold."
  [ "$available_inodes" -ge "$minimum_available_inodes" ] && \
    [ "$inode_available_percent" -ge "$minimum_inode_percent" ] || \
    die "Candidate inode capacity is below the fail-closed threshold."
  printf '{"available_bytes":%s,"available_inodes":%s,"disk_available_percent":%s,"inode_available_percent":%s,"outcome":"capacity-verified","schema_version":1}\n' \
    "$available_bytes" "$available_inodes" "$disk_available_percent" \
    "$inode_available_percent"
}

manifest_value() {
  sed -n "s/^${2}=//p" "$1" | tail -n 1
}

verify_framework_source_authorities() {
  local candidate_root="$1" candidate_owner relative source_path
  local source_owner source_mode
  candidate_owner="$(stat -c '%u' "$candidate_root")"
  for relative in "${source_authorities[@]}"; do
    source_path="$candidate_root/$relative"
    [ -f "$source_path" ] && [ ! -L "$source_path" ] || \
      die "Activation framework source authority is not a regular file."
    source_owner="$(stat -c '%u' "$source_path")"
    [ "$source_owner" = "$candidate_owner" ] || \
      die "Activation framework source authority has an unexpected owner."
    source_mode="$(stat -c '%a' "$source_path")"
    (( (8#$source_mode & 8#022) == 0 )) || \
      die "Activation framework source authority is writable by an unsafe role."
  done
}

verify_candidate() {
  local candidate_root="$1"
  local release_sha="$2"
  local frontend_digest="$3"
  local backend_digest="$4"
  local source_archive_checksum="$5"
  local release_files_checksum="$6"
  local manifest="$candidate_root/$manifest_name"
  local receipt="$candidate_root/$receipt_name"
  local candidate_compose_env="$candidate_root/compose.prod.env"
  local frontend_image="$frontend_repository:frontend-$release_sha@$frontend_digest"
  local backend_image="$backend_repository:backend-$release_sha@$backend_digest"

  test -d "$candidate_root"
  test -f "$manifest"
  test -f "$receipt"
  test -f "$candidate_root/$receipt_checksum_name"
  test -f "$candidate_root/.release-source-sha"
  test -f "$candidate_root/.release-files.sha256"
  test "$(cat "$candidate_root/.release-source-sha")" = "$release_sha"
  test "$("${checksum_command[@]}" "$candidate_root/.release-files.sha256" | cut -d ' ' -f 1)" = "$release_files_checksum"
  (cd "$candidate_root" && "${checksum_check_command[@]}" .release-files.sha256)
  (cd "$candidate_root" && "${checksum_check_command[@]}" "$receipt_checksum_name")
  verify_framework_source_authorities "$candidate_root"

  test "$(manifest_value "$manifest" release_sha)" = "$release_sha"
  test "$(manifest_value "$manifest" source_archive_sha256)" = "$source_archive_checksum"
  test "$(manifest_value "$manifest" release_files_sha256)" = "$release_files_checksum"
  test "$(manifest_value "$manifest" frontend_image_digest)" = "$frontend_digest"
  test "$(manifest_value "$manifest" backend_image_digest)" = "$backend_digest"
  test "$(manifest_value "$manifest" nginx_image)" = "$nginx_image"
  test "$(manifest_value "$manifest" nginx_image_digest)" = "$nginx_digest"
  local manifest_checksum
  manifest_checksum="$("${checksum_command[@]}" "$manifest" | cut -d ' ' -f 1)"

  python3 - "$receipt" "$release_sha" "$frontend_digest" "$backend_digest" "$nginx_digest" \
    "$source_archive_checksum" "$release_files_checksum" "$manifest_checksum" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
sha, frontend, backend, nginx, package, files, manifest = sys.argv[2:]
expected = {
    "schema_version": 1,
    "kind": "production-candidate-preparation",
    "source_sha": sha,
    "image_digests": {"frontend": frontend, "backend": backend, "nginx": nginx},
    "package_sha256": package,
    "release_files_sha256": files,
    "release_manifest_sha256": manifest,
    "release_id": sha,
    "release_path": f"releases/{sha}",
    "outcome": "verified",
}
for key, value in expected.items():
    if data.get(key) != value:
        raise SystemExit(f"Candidate receipt field {key} does not match.")
for key in ("workflow_run_id", "workflow_run_attempt", "source_ci_run_id", "source_ci_run_attempt"):
    if not isinstance(data.get(key), int) or data[key] < 1:
        raise SystemExit(f"Candidate receipt field {key} is invalid.")
if not isinstance(data.get("prepared_at"), str) or not re.fullmatch(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", data["prepared_at"]
):
    raise SystemExit("Candidate receipt timestamp is invalid.")
PY

  local configured_images
  configured_images="$(docker compose --project-directory "$candidate_root" \
    --env-file "$production_compose_env" \
    --env-file "$candidate_compose_env" \
    --file "$candidate_root/docker/docker-compose.prod.yml" config --images)"
  printf '%s\n' "$configured_images" | grep -Fxq "$frontend_image"
  printf '%s\n' "$configured_images" | grep -Fxq "$backend_image"
  printf '%s\n' "$configured_images" | grep -Fxq "$nginx_image"
}

prepare_candidate() {
  [ "$#" -eq 9 ] || die "Prepare requires exactly nine fixed arguments."
  local release_sha="$1" run_id="$2" run_attempt="$3"
  local source_ci_run_id="$4" source_ci_run_attempt="$5"
  local frontend_digest="$6" backend_digest="$7"
  local source_archive_checksum="$8" release_files_checksum="$9"
  require_sha "$release_sha"
  require_integer "$run_id" "Run ID"
  require_integer "$run_attempt" "Run attempt"
  require_integer "$source_ci_run_id" "Source CI run ID"
  require_integer "$source_ci_run_attempt" "Source CI run attempt"
  require_digest "$frontend_digest"
  require_digest "$backend_digest"
  require_checksum "$source_archive_checksum"
  require_checksum "$release_files_checksum"
  command -v flock >/dev/null 2>&1 || die "flock is required."
  exec 9>"$preparation_lock"
  flock -n 9 || die "Another candidate preparation is active."
  capacity_preflight >/dev/null

  local archive="/tmp/pastexam-$release_sha-$run_id.tar.gz"
  local release_root="$releases_root/$release_sha"
  local staging_root="$releases_root/$release_sha.staging-$run_id"
  local frontend_image="$frontend_repository:frontend-$release_sha@$frontend_digest"
  local backend_image="$backend_repository:backend-$release_sha@$backend_digest"
  PREPARE_CLEANUP_ARCHIVE="$archive"
  PREPARE_CLEANUP_STAGING_ROOT="$staging_root"

  cleanup_run_artifacts() {
    rm -f -- "$PREPARE_CLEANUP_ARCHIVE"
    if [ -e "$PREPARE_CLEANUP_STAGING_ROOT" ]; then
      rm -rf -- "$PREPARE_CLEANUP_STAGING_ROOT"
    fi
    unset PREPARE_CLEANUP_ARCHIVE PREPARE_CLEANUP_STAGING_ROOT
  }
  trap cleanup_run_artifacts EXIT
  trap 'exit 130' HUP INT TERM

  test -f "$archive"
  test "$("${checksum_command[@]}" "$archive" | cut -d ' ' -f 1)" = "$source_archive_checksum"
  if [ -e "$release_root" ]; then
    verify_candidate "$release_root" "$release_sha" "$frontend_digest" \
      "$backend_digest" "$source_archive_checksum" "$release_files_checksum"
    cat "$release_root/$receipt_name"
    cleanup_run_artifacts
    trap - EXIT HUP INT TERM
    return
  fi
  [ ! -e "$staging_root" ] || die "Run-specific staging path already exists."
  [ -f "$production_compose_env" ] || die "Production Compose authority is unavailable."
  python3 - "$archive" <<'PY'
import pathlib
import sys
import tarfile

with tarfile.open(sys.argv[1], mode="r:gz") as archive:
    for member in archive.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.issym()
            or member.islnk()
            or not (member.isfile() or member.isdir())
        ):
            raise SystemExit("Candidate archive member is unsafe.")
PY
  install -d -m 700 "$staging_root"
  tar -xzf "$archive" -C "$staging_root"
  test "$(cat "$staging_root/.release-source-sha")" = "$release_sha"
  test "$("${checksum_command[@]}" "$staging_root/.release-files.sha256" | cut -d ' ' -f 1)" = "$release_files_checksum"
  (cd "$staging_root" && "${checksum_check_command[@]}" .release-files.sha256)
  verify_framework_source_authorities "$staging_root"

  printf '# Immutable images for release %s\nFRONTEND_IMAGE=%s\nBACKEND_IMAGE=%s\n' \
    "$release_sha" "$frontend_image" "$backend_image" >"$staging_root/compose.prod.env"
  chmod 600 "$staging_root/compose.prod.env"
  docker compose --project-directory "$staging_root" \
    --env-file "$production_compose_env" \
    --env-file "$staging_root/compose.prod.env" \
    --file "$staging_root/docker/docker-compose.prod.yml" config --quiet

  local created_at manifest manifest_checksum
  created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  manifest="$staging_root/$manifest_name"
  cat >"$manifest" <<EOF
release_sha=$release_sha
workflow_run_id=$run_id
workflow_run_attempt=$run_attempt
source_ci_run_id=$source_ci_run_id
source_ci_run_attempt=$source_ci_run_attempt
frontend_image=$frontend_image
frontend_image_digest=$frontend_digest
backend_image=$backend_image
backend_image_digest=$backend_digest
nginx_image=$nginx_image
nginx_image_digest=$nginx_digest
created_at=$created_at
source_archive_sha256=$source_archive_checksum
release_files_sha256=$release_files_checksum
EOF
  chmod 600 "$manifest"
  manifest_checksum="$("${checksum_command[@]}" "$manifest" | cut -d ' ' -f 1)"

  python3 - "$staging_root/$receipt_name" "$release_sha" "$run_id" \
    "$run_attempt" "$source_ci_run_id" "$source_ci_run_attempt" \
    "$created_at" "$frontend_digest" "$backend_digest" "$nginx_digest" \
    "$source_archive_checksum" "$release_files_checksum" "$manifest_checksum" <<'PY'
import json
import pathlib
import sys

(path, sha, run_id, run_attempt, source_run, source_attempt, prepared_at,
 frontend, backend, nginx, package, files, manifest) = sys.argv[1:]
receipt = {
    "schema_version": 1,
    "kind": "production-candidate-preparation",
    "source_sha": sha,
    "workflow_run_id": int(run_id),
    "workflow_run_attempt": int(run_attempt),
    "source_ci_run_id": int(source_run),
    "source_ci_run_attempt": int(source_attempt),
    "prepared_at": prepared_at,
    "image_digests": {"frontend": frontend, "backend": backend, "nginx": nginx},
    "package_sha256": package,
    "release_files_sha256": files,
    "release_manifest_sha256": manifest,
    "release_id": sha,
    "release_path": f"releases/{sha}",
    "outcome": "verified",
}
pathlib.Path(path).write_text(
    json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
  chmod 600 "$staging_root/$receipt_name"
  (cd "$staging_root" && "${checksum_command[@]}" "$receipt_name" >"$receipt_checksum_name")
  chmod 600 "$staging_root/$receipt_checksum_name"

  verify_candidate "$staging_root" "$release_sha" "$frontend_digest" \
    "$backend_digest" "$source_archive_checksum" "$release_files_checksum"
  [ ! -e "$release_root" ] || die "Candidate appeared while staging."
  mv "$staging_root" "$release_root"
  verify_candidate "$release_root" "$release_sha" "$frontend_digest" \
    "$backend_digest" "$source_archive_checksum" "$release_files_checksum"
  cat "$release_root/$receipt_name"
  cleanup_run_artifacts
  trap - EXIT HUP INT TERM
}

upload_candidate() {
  [ "$#" -eq 3 ] || die "Upload requires release SHA, run ID, and checksum."
  require_sha "$1"
  require_integer "$2" "Run ID"
  require_checksum "$3"
  capacity_preflight >/dev/null
  local archive="/tmp/pastexam-$1-$2.tar.gz"
  local partial="$archive.partial"
  [ ! -e "$archive" ] && [ ! -e "$partial" ] || \
    die "Run-specific upload path already exists."
  trap 'rm -f -- "$partial"' EXIT HUP INT TERM
  (set -o noclobber; head -c "$((maximum_archive_bytes + 1))" >"$partial") || \
    die "Run-specific upload path could not be created safely."
  [ "$(wc -c <"$partial")" -le "$maximum_archive_bytes" ] || \
    die "Candidate archive exceeds the fixed upload limit."
  test "$("${checksum_command[@]}" "$partial" | cut -d ' ' -f 1)" = "$3" || \
    die "Uploaded candidate checksum does not match."
  mv "$partial" "$archive"
  trap - EXIT HUP INT TERM
  printf '{"outcome":"upload-verified","schema_version":1}\n'
}

cleanup_candidate() {
  [ "$#" -eq 2 ] || die "Cleanup requires release SHA and run ID."
  require_sha "$1"
  require_integer "$2" "Run ID"
  rm -f -- "/tmp/pastexam-$1-$2.tar.gz"
  rm -f -- "/tmp/pastexam-$1-$2.tar.gz.partial"
  if [ -e "$releases_root/$1.staging-$2" ]; then
    rm -rf -- "$releases_root/$1.staging-$2"
  fi
}

case "${1:-}" in
  preflight)
    [ "$#" -eq 1 ] || die "Preflight accepts no arguments."
    capacity_preflight
    ;;
  prepare)
    shift
    prepare_candidate "$@"
    ;;
  upload)
    shift
    upload_candidate "$@"
    ;;
  cleanup)
    shift
    cleanup_candidate "$@"
    ;;
  *)
    die "Usage: pastexam-prepare-candidate <preflight|upload|prepare|cleanup>"
    ;;
esac
