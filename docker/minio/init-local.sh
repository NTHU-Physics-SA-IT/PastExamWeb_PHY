#!/bin/sh

set -eu

: "${MINIO_ROOT_USER:?Set MINIO_ROOT_USER}"
: "${MINIO_ROOT_PASSWORD:?Set MINIO_ROOT_PASSWORD}"
: "${MINIO_BUCKET_NAME:?Set MINIO_BUCKET_NAME}"
: "${MINIO_APPLICATION_PARENT_USER:?Set MINIO_APPLICATION_PARENT_USER}"
: "${MINIO_ACCESS_KEY:?Set MINIO_ACCESS_KEY}"
: "${MINIO_SECRET_KEY:?Set MINIO_SECRET_KEY}"

policy_name="pastexam-application"
policy_file="/tmp/pastexam-application-policy.json"
trap 'rm -f "$policy_file"' EXIT HUP INT TERM

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" \
  "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing "local/$MINIO_BUCKET_NAME" >/dev/null
mc version enable "local/$MINIO_BUCKET_NAME" >/dev/null

while IFS= read -r policy_line || [ -n "$policy_line" ]; do
  printf '%s\n' "${policy_line//<bucket>/$MINIO_BUCKET_NAME}"
done </policies/application-policy.template.json >"$policy_file"
mc admin policy create local "$policy_name" "$policy_file" >/dev/null

if parent_info="$(
  mc admin user info local "$MINIO_APPLICATION_PARENT_USER" --json 2>/dev/null
)"; then
  case "$parent_info" in
    *'"userStatus":"enabled"'*) ;;
    *)
      printf '%s\n' 'minio-init: application parent exists but is not enabled' >&2
      exit 1
      ;;
  esac
else
  if [ -z "${MINIO_APPLICATION_PARENT_PASSWORD:-}" ]; then
    printf '%s\n' 'minio-init: parent bootstrap password is required for a new parent' >&2
    exit 1
  fi
  if ! mc admin user add local "$MINIO_APPLICATION_PARENT_USER" \
    "$MINIO_APPLICATION_PARENT_PASSWORD" >/dev/null 2>&1; then
    printf '%s\n' 'minio-init: failed to create application parent' >&2
    exit 1
  fi
fi

mc admin policy attach local "$policy_name" \
  --user "$MINIO_APPLICATION_PARENT_USER" >/dev/null
parent_info="$(
  mc admin user info local "$MINIO_APPLICATION_PARENT_USER" --json
)"
case "$parent_info" in
  *'"userStatus":"enabled"'*) ;;
  *)
    printf '%s\n' 'minio-init: application parent status verification failed' >&2
    exit 1
    ;;
esac
case "$parent_info" in
  *'"policyName":"pastexam-application"'*) ;;
  *)
    printf '%s\n' 'minio-init: application parent policy verification failed' >&2
    exit 1
    ;;
esac

if mc admin accesskey info local/ "$MINIO_ACCESS_KEY" >/dev/null 2>&1; then
  child_list="$(
    mc admin accesskey list local/ "$MINIO_APPLICATION_PARENT_USER" --json
  )"
  child_needle="\"accessKey\":\"$MINIO_ACCESS_KEY\""
  case "$child_list" in
    *"$child_needle"*) ;;
    *)
      printf '%s\n' 'minio-init: configured child belongs to another parent' >&2
      exit 1
      ;;
  esac
else
  if ! mc admin accesskey create local/ "$MINIO_APPLICATION_PARENT_USER" \
    --access-key "$MINIO_ACCESS_KEY" \
    --secret-key "$MINIO_SECRET_KEY" >/dev/null 2>&1; then
    printf '%s\n' 'minio-init: failed to create backend child access key' >&2
    exit 1
  fi
fi

mc admin accesskey info local/ "$MINIO_ACCESS_KEY" >/dev/null
child_list="$(
  mc admin accesskey list local/ "$MINIO_APPLICATION_PARENT_USER" --json
)"
child_needle="\"accessKey\":\"$MINIO_ACCESS_KEY\""
case "$child_list" in
  *"$child_needle"*) ;;
  *)
    printf '%s\n' 'minio-init: backend child access key verification failed' >&2
    exit 1
    ;;
esac
