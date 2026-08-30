#!/usr/bin/env bash

set -euo pipefail

: "${MINIO_CONTAINER:?Set MINIO_CONTAINER}"
: "${MINIO_BUCKET_NAME:?Set MINIO_BUCKET_NAME}"
: "${PYTHON_BIN:=python3}"

if [[ ! "$MINIO_CONTAINER" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "MinIO storage preflight received an unsafe container identity." >&2
  exit 2
fi
if [[ ! "$MINIO_BUCKET_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "MinIO storage preflight received an unsafe bucket identity." >&2
  exit 2
fi

if ! docker exec "$MINIO_CONTAINER" \
  mc stat --json "local/$MINIO_BUCKET_NAME" >/dev/null
then
  echo "MinIO storage preflight could not verify the required bucket." >&2
  exit 2
fi

version_json="$(
  docker exec "$MINIO_CONTAINER" \
    mc version info --json "local/$MINIO_BUCKET_NAME"
)"

if ! "$PYTHON_BIN" -c '
import json
import sys

payload = json.load(sys.stdin)
versioning = payload.get("versioning")
status = versioning.get("status") if isinstance(versioning, dict) else None
if status != "Enabled":
    raise SystemExit(2)
' <<<"$version_json"
then
  echo "MinIO storage preflight requires bucket versioning to be enabled." >&2
  exit 2
fi

echo "MinIO storage preflight passed."
