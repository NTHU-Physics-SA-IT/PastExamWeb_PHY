#!/usr/bin/env bash

set -euo pipefail
umask 077

[ "$#" -eq 2 ] || {
  echo "Usage: $0 <exact-release-directory> <40-character-source-sha>" >&2
  exit 2
}
[ "$(id -u)" -eq 0 ] || {
  echo "Framework installation requires root." >&2
  exit 2
}

source_root="$(readlink -f -- "$1")"
expected_sha="$2"
[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Expected source SHA is malformed." >&2
  exit 2
}
[ "$(basename -- "$source_root")" = "$expected_sha" ]
[ "$(stat -c '%u' "$source_root")" = 0 ]
source_mode="$(stat -c '%a' "$source_root")"
(( (8#$source_mode & 8#022) == 0 )) || {
  echo "Immutable release source must not be group/world writable." >&2
  exit 2
}
[ "$(cat "$source_root/.release-source-sha")" = "$expected_sha" ]
(cd "$source_root" && sha256sum --check --quiet .release-files.sha256)

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
for relative in "${source_authorities[@]}"; do
  source_path="$source_root/$relative"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || {
    echo "Activation framework source authority is not a regular file." >&2
    exit 2
  }
  [ "$(stat -c '%u' "$source_path")" = 0 ] || {
    echo "Activation framework source authority must be root-owned." >&2
    exit 2
  }
  source_mode="$(stat -c '%a' "$source_path")"
  (( (8#$source_mode & 8#022) == 0 )) || {
    echo "Activation framework source authority is writable by an unsafe role." >&2
    exit 2
  }
done

id pastexam-activate >/dev/null 2>&1
passwd_status="$(passwd -S pastexam-activate | awk '{print $2}')"
case "$passwd_status" in L|LK) ;; *) echo "Activation account password is not locked." >&2; exit 2 ;; esac
if id -nG pastexam-activate | tr ' ' '\n' | grep -Fxq docker; then
  echo "Activation account must not belong to the Docker group." >&2
  exit 2
fi

atomic_install() {
  local source="$1" target="$2" mode="$3" directory temporary
  directory="$(dirname -- "$target")"
  install -d -o root -g root -m 0755 "$directory"
  temporary="$directory/.$(basename -- "$target").partial-$$"
  trap 'rm -f -- "$temporary"' RETURN
  install -o root -g root -m "$mode" "$source" "$temporary"
  sync -f "$temporary"
  mv -fT -- "$temporary" "$target"
  sync -f "$directory"
  trap - RETURN
}

atomic_install \
  "$source_root/scripts/production-deployment-control.py" \
  /usr/local/sbin/pastexam-production-deployment-control 0755
atomic_install \
  "$source_root/scripts/pastexam-activate-ssh-wrapper.sh" \
  /usr/local/sbin/pastexam-activate-ssh-wrapper 0755
atomic_install \
  "$source_root/scripts/activate-production-release.sh" \
  /usr/local/libexec/pastexam-activate-production-release 0700
atomic_install \
  "$source_root/scripts/production-activation-contract.py" \
  /usr/local/libexec/pastexam-production-activation-contract.py 0700
atomic_install \
  "$source_root/scripts/postgres-logical-backup.sh" \
  /usr/local/libexec/pastexam-postgres-logical-backup 0700
atomic_install \
  "$source_root/scripts/minio-storage-preflight.sh" \
  /usr/local/libexec/pastexam-minio-storage-preflight 0700
atomic_install \
  "$source_root/scripts/minio-readonly-manifest.sh" \
  /usr/local/libexec/pastexam-minio-readonly-manifest 0700
atomic_install \
  "$source_root/docker/docker-compose.nginx-immutable.yml" \
  /usr/local/libexec/pastexam-nginx-image-override.yml 0600

install -d -o root -g root -m 0700 \
  /var/lib/pastexam-deployments \
  /var/lib/pastexam-deployments/requests \
  /var/lib/pastexam-deployments/receipts
install -d -o root -g root -m 0755 /run/lock
touch /run/lock/pastexam-production-activation.lock
chown root:root /run/lock/pastexam-production-activation.lock
chmod 0600 /run/lock/pastexam-production-activation.lock

control=/usr/local/sbin/pastexam-production-deployment-control
control_digest="$(sha256sum "$control" | cut -d ' ' -f 1)"
sudoers=/etc/sudoers.d/pastexam-production-activation
sudoers_partial="$sudoers.partial-$$"
trap 'rm -f -- "$sudoers_partial"' EXIT HUP INT TERM
printf 'pastexam-activate ALL=(root) NOPASSWD: sha256:%s %s *\n' \
  "$control_digest" "$control" >"$sudoers_partial"
chown root:root "$sudoers_partial"
chmod 0440 "$sudoers_partial"
visudo -cf "$sudoers_partial"
mv -fT -- "$sudoers_partial" "$sudoers"
visudo -c
trap - EXIT HUP INT TERM

echo "Production activation framework installed from $expected_sha; no deployment was started."
