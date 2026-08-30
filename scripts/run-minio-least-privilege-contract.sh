#!/usr/bin/env bash

set -euo pipefail

# Git Bash on Windows must not rewrite container-internal /tmp paths.
export MSYS_NO_PATHCONV=1

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [ -x "$repository_root/backend/.venv/bin/python" ]; then
  python="$repository_root/backend/.venv/bin/python"
else
  python="$repository_root/backend/.venv/Scripts/python.exe"
fi
lab_directory="$(mktemp -d)"
container="pastexam-sec04-minio-$RANDOM-$$"
root_user="sec04-root-$RANDOM"
root_secret="sec04-root-secret-$RANDOM-$$"
parent_user="sec04-parent-$RANDOM"
parent_secret="sec04-parent-secret-$RANDOM-$$"
app_key="sec04-child-$RANDOM"
app_secret="sec04-child-secret-$RANDOM-$$"
bucket="sec04-target-$RANDOM"
unrelated_bucket="sec04-unrelated-$RANDOM"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf -- "$lab_directory"
}
trap cleanup EXIT HUP INT TERM

sed "s/<bucket>/$bucket/g" \
  "$repository_root/docker/minio/application-policy.template.json" \
  >"$lab_directory/application-policy.json"
sed "s/<bucket>/$bucket/g" \
  "$repository_root/docker/minio/rollback-list-bucket-policy.template.json" \
  >"$lab_directory/rollback-policy.json"

docker run -d --rm \
  --name "$container" \
  -p 127.0.0.1::9000 \
  -e MINIO_ROOT_USER="$root_user" \
  -e MINIO_ROOT_PASSWORD="$root_secret" \
  quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z \
  server /data >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$container" mc alias set local http://127.0.0.1:9000 \
    "$root_user" "$root_secret" >/dev/null 2>&1 && \
    docker exec "$container" mc ready local >/dev/null 2>&1
  then
    break
  fi
  sleep 1
done
docker exec "$container" mc ready local >/dev/null

docker exec "$container" mc mb "local/$bucket" >/dev/null
docker exec "$container" mc mb "local/$unrelated_bucket" >/dev/null
docker exec "$container" mc version enable "local/$bucket" >/dev/null
printf 'unrelated' | docker exec -i "$container" \
  mc pipe "local/$unrelated_bucket/existing-object" >/dev/null
env MINIO_CONTAINER="$container" MINIO_BUCKET_NAME="$bucket" \
  PYTHON_BIN="$python" \
  "$repository_root/scripts/minio-storage-preflight.sh" >/dev/null
docker exec -i "$container" sh -c 'cat >/tmp/application-policy.json' \
  <"$lab_directory/application-policy.json"
docker exec "$container" mc admin policy create local pastexam-sec04-app \
  /tmp/application-policy.json >/dev/null
docker exec "$container" mc admin user add local "$parent_user" \
  "$parent_secret" >/dev/null
docker exec "$container" mc admin policy attach local pastexam-sec04-app \
  --user "$parent_user" >/dev/null
docker exec "$container" mc admin user svcacct add \
  --access-key "$app_key" \
  --secret-key "$app_secret" \
  local "$parent_user" >/dev/null

port="$(
  docker inspect --format '{{(index (index .NetworkSettings.Ports "9000/tcp") 0).HostPort}}' \
    "$container"
)"

test_file="$repository_root/scripts/tests/test_minio_least_privilege_integration.py"
confcutdir="$repository_root/scripts/tests"
if command -v cygpath >/dev/null 2>&1; then
  test_file="$(cygpath -w "$test_file")"
  confcutdir="$(cygpath -w "$confcutdir")"
fi

env \
  SEC04_MINIO_ENDPOINT="127.0.0.1:$port" \
  SEC04_MINIO_ACCESS_KEY="$app_key" \
  SEC04_MINIO_SECRET_KEY="$app_secret" \
  SEC04_MINIO_BUCKET="$bucket" \
  SEC04_MINIO_UNRELATED_BUCKET="$unrelated_bucket" \
  "$python" -m pytest -q \
  "$test_file" \
  -k 'not temporary_list_bucket' \
  --confcutdir="$confcutdir"

docker exec -i "$container" sh -c 'cat >/tmp/rollback-policy.json' \
  <"$lab_directory/rollback-policy.json"
docker exec "$container" mc admin policy create local pastexam-sec04-rollback \
  /tmp/rollback-policy.json >/dev/null
docker exec "$container" mc admin policy attach local pastexam-sec04-rollback \
  --user "$parent_user" >/dev/null

env \
  SEC04_MINIO_ENDPOINT="127.0.0.1:$port" \
  SEC04_MINIO_ACCESS_KEY="$app_key" \
  SEC04_MINIO_SECRET_KEY="$app_secret" \
  SEC04_MINIO_BUCKET="$bucket" \
  SEC04_MINIO_UNRELATED_BUCKET="$unrelated_bucket" \
  SEC04_ROLLBACK_POLICY_ATTACHED=1 \
  "$python" -m pytest -q \
  "$test_file" \
  -k temporary_list_bucket \
  --confcutdir="$confcutdir"

echo "SEC-04 exact-version MinIO policy contract passed."
