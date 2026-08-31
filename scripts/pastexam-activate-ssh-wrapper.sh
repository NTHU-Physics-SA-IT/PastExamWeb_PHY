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
  preflight:4|rollback-preflight:4)
    [[ "${arguments[1]}" =~ $sha ]]
    [[ "${arguments[2]}" =~ $positive_integer ]]
    [[ "${arguments[3]}" =~ $positive_integer ]]
    ;;
  start:7|rollback-start:7)
    [[ "${arguments[1]}" =~ $sha ]]
    [[ "${arguments[2]}" =~ $request_id ]]
    for index in 3 4 5 6; do
      [[ "${arguments[$index]}" =~ $positive_integer ]]
    done
    ;;
  request-status:2|receipt:2|resume:2)
    [[ "${arguments[1]}" =~ $request_id ]]
    ;;
  *)
    deny
    ;;
esac

exec sudo -n "$control" "${arguments[@]}"
