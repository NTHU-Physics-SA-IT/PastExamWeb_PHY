#!/usr/bin/env bash

set -euo pipefail
umask 077

control=/usr/local/sbin/pastexam-production-deployment-control
original="${SSH_ORIGINAL_COMMAND:-}"

deny() {
  echo "Production activation command denied." >&2
  exit 2
}

[[ "$original" != *$'\n'* && "$original" != *$'\r'* ]] || deny
read -r -a arguments <<<"$original"
[ "${#arguments[@]}" -gt 0 ] || deny

sha='^[0-9a-f]{40}$'
request_id='^[a-z][a-z0-9-]{7,79}$'
positive_integer='^[1-9][0-9]*$'

case "${arguments[0]}:${#arguments[@]}" in
  status:1)
    ;;
  observe:4|preflight:4|rollback-preflight:4)
    [[ "${arguments[1]}" =~ $sha ]] || deny
    [[ "${arguments[2]}" =~ $positive_integer ]] || deny
    [[ "${arguments[3]}" =~ $positive_integer ]] || deny
    ;;
  start:7|rollback-start:7)
    [[ "${arguments[1]}" =~ $sha ]] || deny
    [[ "${arguments[2]}" =~ $request_id ]] || deny
    for index in 3 4 5 6; do
      [[ "${arguments[$index]}" =~ $positive_integer ]] || deny
    done
    ;;
  request-status:2|receipt:2|resume:2|reconcile-activation:2)
    [[ "${arguments[1]}" =~ $request_id ]] || deny
    ;;
  *)
    deny
    ;;
esac

exec sudo -n "$control" "${arguments[@]}"
