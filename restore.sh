#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$repository_root/scripts/postgres-logical-restore.sh" "$@"
