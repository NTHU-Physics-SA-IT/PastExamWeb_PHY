#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
temporary_directory="$(mktemp -d)"

cleanup() {
  rm -rf -- "$temporary_directory"
}
trap cleanup EXIT HUP INT TERM

production_json="$temporary_directory/production.json"
local_json="$temporary_directory/local.json"
acceptance_json="$temporary_directory/acceptance.json"

PRODUCTION_BACKEND_ENV_FILE="$repository_root/backend/.env.production.runtime.example" \
PRODUCTION_MIGRATOR_ENV_FILE="$repository_root/backend/.env.production.migrator.example" \
docker compose \
  --env-file "$repository_root/docker/production.compose.env.example" \
  --file "$repository_root/docker/docker-compose.yml" \
  config --format json >"$production_json"

docker compose \
  --env-file "$repository_root/docker/.env.example" \
  --file "$repository_root/docker/docker-compose.local.yml" \
  --profile bootstrap \
  config --format json >"$local_json"

docker compose \
  --env-file "$repository_root/docker/acceptance.env.example" \
  --file "$repository_root/docker/docker-compose.acceptance.yml" \
  config --format json >"$acceptance_json"

python3 - \
  "$production_json" \
  "$local_json" \
  "$acceptance_json" <<'PY'
import json
import sys
from pathlib import Path


production, local, acceptance = (
    json.loads(Path(path).read_text(encoding="utf-8"))
    for path in sys.argv[1:]
)

for compose in (production, local, acceptance):
    migrate = compose["services"]["migrate"]
    assert migrate["restart"] == "no"
    assert migrate["command"] == ["python", "migrate.py", "upgrade"]
    assert "container_name" not in migrate
    assert "seed" not in " ".join(migrate["command"]).lower()

assert (
    production["services"]["backend"]["depends_on"]["migrate"]["condition"]
    == "service_completed_successfully"
)
assert (
    production["services"]["backend"]["environment"]["DB_USER"]
    != production["services"]["migrate"]["environment"]["DB_USER"]
)
assert local["services"]["bootstrap"]["profiles"] == ["bootstrap"]
assert (
    acceptance["services"]["backend"]["depends_on"]["migrate"]["condition"]
    == "service_completed_successfully"
)
PY

echo "Compose migration safety validation passed."
