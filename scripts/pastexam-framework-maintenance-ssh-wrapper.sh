#!/usr/bin/env bash

set -euo pipefail
umask 077

helper=/usr/local/libexec/pastexam-production-framework-maintenance
original="${SSH_ORIGINAL_COMMAND:-}"

deny() {
  echo "Production framework maintenance command denied." >&2
  exit 2
}

[[ "$original" != *$'\n'* && "$original" != *$'\r'* ]] || deny
read -r -a arguments <<<"$original"
[ "${#arguments[@]}" -eq 2 ] || deny
[ "${arguments[0]}" = install ] || deny
[[ "${arguments[1]}" =~ ^[0-9a-f]{40}$ ]] || deny

exec sudo -n "$helper" "${arguments[1]}"
