#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

: "${MINIO_CONTAINER:?Set MINIO_CONTAINER}"
: "${MINIO_BUCKET_NAME:?Set MINIO_BUCKET_NAME}"
: "${BACKUP_DIRECTORY:?Set an absolute BACKUP_DIRECTORY outside the repository}"

case "$BACKUP_DIRECTORY" in
  /*) ;;
  *)
    echo "BACKUP_DIRECTORY must be absolute." >&2
    exit 2
    ;;
esac
case "$BACKUP_DIRECTORY/" in
  "$repository_root/"*)
    echo "BACKUP_DIRECTORY must be outside the repository." >&2
    exit 2
    ;;
esac
case "$MINIO_BUCKET_NAME" in
  *[!A-Za-z0-9._-]*)
    echo "MINIO_BUCKET_NAME contains unsupported characters." >&2
    exit 2
    ;;
esac

mkdir -p "$BACKUP_DIRECTORY"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
manifest="$BACKUP_DIRECTORY/minio_${MINIO_BUCKET_NAME}_${timestamp}.jsonl"
metadata="$BACKUP_DIRECTORY/minio_${MINIO_BUCKET_NAME}_${timestamp}.metadata"
temporary_manifest="$manifest.partial"

if [ -e "$manifest" ] || [ -e "$temporary_manifest" ]; then
  echo "Refusing to overwrite an existing MinIO manifest." >&2
  exit 2
fi

cleanup_partial() {
  if [ -f "$temporary_manifest" ]; then
    rm -f -- "$temporary_manifest"
  fi
}
trap cleanup_partial EXIT HUP INT TERM

docker exec "$MINIO_CONTAINER" sh -eu -c '
  config_directory="/tmp/pastexam-minio-audit-$1"
  cleanup() {
    rm -rf -- "$config_directory"
  }
  trap cleanup EXIT HUP INT TERM
  mc --config-dir "$config_directory" alias set \
    audit http://127.0.0.1:9000 \
    "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  mc --config-dir "$config_directory" \
    ls --recursive --json "audit/$2"
' sh "$timestamp" "$MINIO_BUCKET_NAME" >"$temporary_manifest"

if grep -q '"status":"error"' "$temporary_manifest"; then
  echo "MinIO listing returned an error; manifest was not published." >&2
  exit 2
fi
mv "$temporary_manifest" "$manifest"
trap - EXIT HUP INT TERM

object_count="$(wc -l <"$manifest" | tr -d ' ')"
total_bytes="$(
  sed -nE \
    's/.*"size":[[:space:]]*([0-9]+).*/\1/p' \
    "$manifest" |
    awk '{ total += $1 } END { print total + 0 }'
)"
checksum="$(shasum -a 256 "$manifest" | awk '{print $1}')"
{
  printf 'manifest_version=1\n'
  printf 'utc_timestamp=%s\n' "$timestamp"
  printf 'bucket=%s\n' "$MINIO_BUCKET_NAME"
  printf 'object_count=%s\n' "$object_count"
  printf 'total_bytes=%s\n' "$total_bytes"
  printf 'sha256=%s\n' "$checksum"
} >"$metadata"

echo "Read-only MinIO manifest: $manifest"
echo "Objects: $object_count; bytes: $total_bytes; sha256: $checksum"
