#!/usr/bin/env bash

# One-time, separately authorized root bootstrap. This script establishes only
# the fixed framework-maintenance SSH lane; it does not install the activation
# framework or perform any application operation.
set -euo pipefail
umask 077

[ "$#" -eq 1 ] || { echo "Usage: $0 <40-character-source-sha>" >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "Bootstrap requires root." >&2; exit 2; }
source_sha="$1"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Source SHA is malformed." >&2; exit 2; }

release_root="/opt/pastexam-releases/$source_sha"
public_key_file=/root/pastexam-framework-maintenance-authorized-key.pub
account=pastexam-framework-maintenance
wrapper=/usr/local/sbin/pastexam-framework-maintenance-ssh-wrapper
helper=/usr/local/libexec/pastexam-production-framework-maintenance

[ "$(readlink -f -- "$release_root")" = "$release_root" ]
[ "$(stat -c '%u:%g' "$release_root")" = 0:0 ]
[ "$(cat "$release_root/.release-source-sha")" = "$source_sha" ]
(cd "$release_root" && sha256sum --check --quiet .release-files.sha256)
for relative in scripts/pastexam-framework-maintenance-ssh-wrapper.sh scripts/production-framework-maintenance.py; do
  path="$release_root/$relative"
  [ -f "$path" ] && [ ! -L "$path" ] && [ "$(stat -c '%u:%g' "$path")" = 0:0 ]
  mode="$(stat -c '%a' "$path")"
  (( (8#$mode & 8#022) == 0 ))
done

[ -f "$public_key_file" ] && [ ! -L "$public_key_file" ]
[ "$(stat -c '%u:%g' "$public_key_file")" = 0:0 ]
[ "$(stat -c '%a' "$public_key_file")" = 600 ]
IFS=' ' read -r key_type key_blob key_extra <"$public_key_file"
[ "$key_type" = ssh-ed25519 ] && [[ "$key_blob" =~ ^[A-Za-z0-9+/]+={0,2}$ ]] && [ -z "${key_extra:-}" ]
[ "$(wc -l <"$public_key_file")" -eq 1 ]
ssh-keygen -l -f "$public_key_file" >/dev/null

install -o root -g root -m 0755 "$release_root/scripts/pastexam-framework-maintenance-ssh-wrapper.sh" "$wrapper"
install -o root -g root -m 0700 "$release_root/scripts/production-framework-maintenance.py" "$helper"

if ! id "$account" >/dev/null 2>&1; then
  useradd --system --user-group --create-home \
    --home-dir /var/lib/pastexam-framework-maintenance \
    --shell "$wrapper" "$account"
fi
passwd -l "$account" >/dev/null
IFS=: read -r _ _ _ _ _ account_home account_shell < <(getent passwd "$account")
[ "$account_home" = /var/lib/pastexam-framework-maintenance ]
[ "$account_shell" = "$wrapper" ]
[ "$(id -nG "$account")" = "$account" ]
if id -nG "$account" | tr ' ' '\n' | grep -Fxq docker; then
  echo "Maintenance account must not belong to the Docker group." >&2
  exit 2
fi

home=/var/lib/pastexam-framework-maintenance
install -d -o "$account" -g "$account" -m 0700 "$home/.ssh"
printf 'restrict,command="%s" %s %s\n' "$wrapper" "$key_type" "$key_blob" >"$home/.ssh/authorized_keys"
chown "$account:$account" "$home/.ssh/authorized_keys"
chmod 0600 "$home/.ssh/authorized_keys"

helper_digest="$(sha256sum "$helper" | cut -d ' ' -f 1)"
sudoers=/etc/sudoers.d/pastexam-production-framework-maintenance
partial="$sudoers.partial-$$"
trap 'rm -f -- "$partial"' EXIT HUP INT TERM
printf '%s ALL=(root) NOPASSWD: sha256:%s %s *\n' "$account" "$helper_digest" "$helper" >"$partial"
chown root:root "$partial"
chmod 0440 "$partial"
visudo -cf "$partial"
mv -fT -- "$partial" "$sudoers"
visudo -c
trap - EXIT HUP INT TERM

echo "Production framework maintenance channel bootstrapped; no framework was installed."
