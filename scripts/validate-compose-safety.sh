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
  "$repository_root/proxy/nginx.conf" \
  "$repository_root/proxy/nginx.production-listeners.conf" \
  "$repository_root/proxy/nginx.development-listeners.conf" <<'PY'
import ipaddress
import json
import re
import sys
from pathlib import Path


production, development = (
    json.loads(Path(path).read_text(encoding="utf-8"))
    for path in sys.argv[1:3]
)
nginx_config = Path(sys.argv[3]).read_text(encoding="utf-8")
production_listener_config = Path(sys.argv[4]).read_text(encoding="utf-8")
development_listener_config = Path(sys.argv[5]).read_text(encoding="utf-8")

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

def listeners(config):
    return {
    int(port)
    for port in re.findall(r"\blisten\s+(?:[^\s;:]+:)?([0-9]{1,5})(?=[\s;])", config)
    }


assert "include /etc/nginx/pastexam-listeners.conf;" in nginx_config
production_listeners = listeners(production_listener_config)
development_listeners = listeners(development_listener_config)
production_nginx_ports = production["services"]["nginx"]["ports"]
assert production_nginx_ports
assert {
    (int(binding["published"]), int(binding["target"]))
    for binding in production_nginx_ports
} == {(80, 8080), (8080, 8080), (443, 8443)}
assert {int(binding["target"]) for binding in production_nginx_ports} <= production_listeners
development_nginx_ports = development["services"]["nginx"]["ports"]
assert {int(binding["target"]) for binding in development_nginx_ports} <= development_listeners

production_mounts = {
    mount["target"]: mount
    for mount in production["services"]["nginx"]["volumes"]
}
for target in (
    "/etc/nginx/nginx.conf",
    "/etc/nginx/pastexam-listeners.conf",
    "/etc/nginx/certs/origin.pem",
    "/etc/nginx/certs/origin-key.pem",
):
    assert production_mounts[target]["type"] == "bind"
    assert production_mounts[target]["read_only"] is True
assert "listen 8443 ssl;" in production_listener_config
assert "ssl_certificate /etc/nginx/certs/origin.pem;" in production_listener_config
assert "ssl_certificate_key /etc/nginx/certs/origin-key.pem;" in production_listener_config

trusted_proxy = production["services"]["backend"]["environment"][
    "FORWARDED_ALLOW_IPS"
]
nginx_proxy_address = production["services"]["nginx"]["networks"][
    "trusted_proxy_network"
]["ipv4_address"]
trusted_proxy_address = ipaddress.ip_address(trusted_proxy)
assert trusted_proxy_address.version == 4
assert any(
    trusted_proxy_address in ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
assert trusted_proxy_address == ipaddress.ip_address(nginx_proxy_address)

assert production["networks"]["app_network"].get("ipam") in (None, {})
trusted_network = production["networks"]["trusted_proxy_network"]
assert trusted_network["name"] == "pastexam-trusted-proxy-network"
assert trusted_network["driver"] == "bridge"
trusted_ipam = trusted_network["ipam"]["config"]
assert len(trusted_ipam) == 1
trusted_subnet = ipaddress.ip_network(trusted_ipam[0]["subnet"])
trusted_dynamic_range = ipaddress.ip_network(trusted_ipam[0]["ip_range"])
trusted_gateway = ipaddress.ip_address(trusted_ipam[0]["gateway"])
assert trusted_subnet == ipaddress.ip_network("172.30.0.0/28")
assert trusted_dynamic_range == ipaddress.ip_network("172.30.0.8/29")
assert trusted_dynamic_range.subnet_of(trusted_subnet)
assert trusted_proxy_address in trusted_subnet
assert trusted_proxy_address not in trusted_dynamic_range
assert trusted_proxy_address not in {
    trusted_subnet.network_address,
    trusted_gateway,
    trusted_subnet.broadcast_address,
}

backend_networks = production["services"]["backend"]["networks"]
nginx_networks = production["services"]["nginx"]["networks"]
assert backend_networks["trusted_proxy_network"]["aliases"] == ["backend-trusted"]
assert "backend-trusted" not in backend_networks["app_network"]["aliases"]
assert "trusted_proxy_network" in nginx_networks
assert "app_network" in nginx_networks
for service, definition in production["services"].items():
    if service not in ("backend", "nginx"):
        assert "trusted_proxy_network" not in definition["networks"]

assert development["services"]["backend"]["networks"]["default"]["aliases"] == [
    "backend-trusted"
]
assert nginx_config.count("proxy_pass http://backend-trusted:8000/") == 4
assert "proxy_pass http://backend:8000/" not in nginx_config

assert (
    production["services"]["backend"]["depends_on"]["migrate"]["condition"]
    == "service_completed_successfully"
)
assert (
    production["services"]["backend"]["environment"]["DB_USER"]
    != production["services"]["migrate"]["environment"]["DB_USER"]
)
production_backend_environment = production["services"]["backend"]["environment"]
assert production_backend_environment["MINIO_ACCESS_KEY"]
assert production_backend_environment["MINIO_SECRET_KEY"]
assert "MINIO_ROOT_USER" not in production_backend_environment
assert "MINIO_ROOT_PASSWORD" not in production_backend_environment
production_minio_environment = production["services"]["minio"]["environment"]
assert production_minio_environment["MINIO_ROOT_USER"]
assert production_minio_environment["MINIO_ROOT_PASSWORD"]
assert development["services"]["bootstrap"]["profiles"] == ["bootstrap"]
assert (
    development["services"]["backend"]["depends_on"]["migrate"]["condition"]
    == "service_completed_successfully"
)
assert (
    development["services"]["backend"]["environment"]["DB_USER"]
    != development["services"]["migrate"]["environment"]["DB_USER"]
)
development_backend_environment = development["services"]["backend"]["environment"]
assert development_backend_environment["MINIO_ACCESS_KEY"]
assert development_backend_environment["MINIO_SECRET_KEY"]
assert "MINIO_ROOT_USER" not in development_backend_environment
assert "MINIO_ROOT_PASSWORD" not in development_backend_environment
development_db_environment = development["services"]["db"]["environment"]
assert development_db_environment["TEST_DB_USER"].startswith("pastexam_test_")
assert development_db_environment["TEST_DATABASE_NAME"].startswith("pastexam_test_")
assert (
    development_db_environment["TEST_DB_USER"]
    != development["services"]["backend"]["environment"]["DB_USER"]
)
PY

for listener_config in \
  "$repository_root/proxy/nginx.development-listeners.conf" \
  "$repository_root/proxy/nginx.production-listeners.conf"; do
  docker run --rm --network none \
    --add-host frontend:127.0.0.1 \
    --add-host backend:127.0.0.1 \
    --add-host backend-trusted:127.0.0.1 \
    --add-host minio:127.0.0.1 \
    --mount \
      "type=bind,source=$repository_root/proxy/nginx.conf,target=/etc/nginx/nginx.conf,readonly" \
    --mount \
      "type=bind,source=$listener_config,target=/etc/nginx/pastexam-listeners.conf,readonly" \
    nginx:1.29.2 sh -eu -c '
      if grep -q "ssl_certificate " /etc/nginx/pastexam-listeners.conf; then
        mkdir -p /etc/nginx/certs
        openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
          -subj /CN=localhost \
          -keyout /etc/nginx/certs/origin-key.pem \
          -out /etc/nginx/certs/origin.pem >/dev/null 2>&1
      fi
      nginx -t
    '
done

echo "Compose migration safety validation passed."
