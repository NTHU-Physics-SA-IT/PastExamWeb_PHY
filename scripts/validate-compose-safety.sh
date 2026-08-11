#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
temporary_directory="$(mktemp -d)"

cleanup() {
  rm -rf -- "$temporary_directory"
}
trap cleanup EXIT HUP INT TERM

production_json="$temporary_directory/production.json"
development_json="$temporary_directory/development.json"

env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  PRODUCTION_BACKEND_ENV_FILE="$repository_root/backend/.env.production.runtime.example" \
  PRODUCTION_MIGRATOR_ENV_FILE="$repository_root/backend/.env.production.migrator.example" \
  docker compose \
  --env-file "$repository_root/docker/.env.production.example" \
  --file "$repository_root/docker/docker-compose.prod.yml" \
  --file "$repository_root/docker/docker-compose.prod-edge.example.yml" \
  config --format json >"$production_json"

env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  DEVELOPMENT_BACKEND_ENV_FILE="../backend/.env.example" \
  DEVELOPMENT_FRONTEND_ENV_FILE="../frontend/.env.example" \
  docker compose \
  --env-file "$repository_root/docker/.env.example" \
  --file "$repository_root/docker/docker-compose.dev.yml" \
  --profile bootstrap \
  config --format json >"$development_json"

python3 - \
  "$production_json" \
  "$development_json" \
  "$repository_root/proxy/nginx.conf" <<'PY'
import json
import re
import sys
from pathlib import Path


production, development = (
    json.loads(Path(path).read_text(encoding="utf-8"))
    for path in sys.argv[1:3]
)
nginx_config = Path(sys.argv[3]).read_text(encoding="utf-8")

for compose in (production, development):
    migrate = compose["services"]["migrate"]
    assert migrate["restart"] == "no"
    assert migrate["command"] == ["python", "migrate.py", "upgrade"]
    assert "container_name" not in migrate
    assert "seed" not in " ".join(migrate["command"]).lower()

assert "bootstrap" not in production["services"]
for service in production["services"].values():
    raw_command = service.get("command") or []
    command = (
        raw_command
        if isinstance(raw_command, str)
        else " ".join(raw_command)
    )
    assert "seed_db" not in command
    assert "bootstrap" not in command.lower()

nginx_listeners = {
    int(port)
    for port in re.findall(r"\blisten\s+(?:[^\s;:]+:)?([0-9]{1,5})(?=[\s;])", nginx_config)
}
production_nginx_ports = production["services"]["nginx"]["ports"]
assert production_nginx_ports
assert {int(binding["target"]) for binding in production_nginx_ports} <= nginx_listeners

assert (
    production["services"]["backend"]["depends_on"]["migrate"]["condition"]
    == "service_completed_successfully"
)
assert (
    production["services"]["backend"]["environment"]["DB_USER"]
    != production["services"]["migrate"]["environment"]["DB_USER"]
)
assert development["services"]["bootstrap"]["profiles"] == ["bootstrap"]
assert (
    development["services"]["backend"]["depends_on"]["migrate"]["condition"]
    == "service_completed_successfully"
)
assert (
    development["services"]["backend"]["environment"]["DB_USER"]
    != development["services"]["migrate"]["environment"]["DB_USER"]
)
development_db_environment = development["services"]["db"]["environment"]
assert development_db_environment["TEST_DB_USER"].startswith("pastexam_test_")
assert development_db_environment["TEST_DATABASE_NAME"].startswith("pastexam_test_")
assert (
    development_db_environment["TEST_DB_USER"]
    != development["services"]["backend"]["environment"]["DB_USER"]
)
PY

echo "Compose migration safety validation passed."
