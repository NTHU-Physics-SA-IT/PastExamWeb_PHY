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

if ! version_json="$(
  docker exec "$MINIO_CONTAINER" sh -eu -c '
    umask 077
    config_directory=
    cleanup() {
      if [ -n "$config_directory" ]; then
        rm -rf -- "$config_directory"
      fi
    }
    trap cleanup EXIT
    trap "exit 129" HUP
    trap "exit 130" INT
    trap "exit 143" TERM
    config_directory="/tmp/pastexam-minio-preflight.$$"
    if ! mkdir -m 700 -- "$config_directory"; then
      echo "MinIO storage preflight could not create isolated operator state." >&2
      exit 2
    fi

    if ! mc --config-dir "$config_directory" alias set \
      preflight http://127.0.0.1:9000 \
      "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
    then
      echo "MinIO storage preflight could not establish operator authority." >&2
      exit 2
    fi
    if ! mc --config-dir "$config_directory" \
      stat --json "preflight/$1" >/dev/null 2>&1
    then
      echo "MinIO storage preflight could not verify the required bucket." >&2
      exit 2
    fi
    if ! mc --config-dir "$config_directory" \
      version info --json "preflight/$1" 2>/dev/null
    then
      echo "MinIO storage preflight could not inspect bucket versioning." >&2
      exit 2
    fi
  ' sh "$MINIO_BUCKET_NAME"
)"
then
  echo "MinIO storage preflight could not verify required storage state." >&2
  exit 2
fi

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
