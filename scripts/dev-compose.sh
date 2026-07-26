#!/bin/sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
compose_dir="$repo_root/docker"
compose_file="$compose_dir/docker-compose.dev.yml"
project_name="pastexam-dev"
failed=0

check_container() {
  container_name="$1"
  service="$2"
  working_dir="$3"
  config_files="$4"

  if [ "$working_dir" != "$compose_dir" ]; then
    printf >&2 '%s\n' \
      "Refusing to mix Compose checkouts: $container_name uses $working_dir; expected $compose_dir"
    failed=1
  fi
  if [ "$config_files" != "$compose_file" ]; then
    printf >&2 '%s\n' \
      "Refusing to mix Compose configs: $container_name uses $config_files; expected $compose_file"
    failed=1
  fi

  case "$service" in
    frontend)
      expected_bind="$repo_root/frontend:/app"
      ;;
    backend)
      expected_bind="$repo_root/backend:/app"
      ;;
    nginx)
      expected_bind="$repo_root/proxy/nginx.conf:/etc/nginx/nginx.conf"
      ;;
    *)
      expected_bind=""
      ;;
  esac

  if [ -n "$expected_bind" ]; then
    actual_binds="$(
      docker inspect -f \
        '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}:{{.Destination}}{{"\n"}}{{end}}{{end}}' \
        "$container_name"
    )"
    if ! printf '%s\n' "$actual_binds" | grep -Fqx "$expected_bind"; then
      printf >&2 '%s\n' \
        "Refusing to use unexpected bind mount for $container_name; expected $expected_bind"
      failed=1
    fi
  fi
}

containers="$(
  docker ps -a \
    --filter "label=com.docker.compose.project=$project_name" \
    --format '{{.Names}}'
)"

for container_name in $containers; do
  service="$(
    docker inspect -f \
      '{{index .Config.Labels "com.docker.compose.service"}}' \
      "$container_name"
  )"
  running="$(
    docker inspect -f '{{.State.Running}}' "$container_name"
  )"
  case "$service" in
    frontend|backend|db|pgadmin|minio|redis|nginx)
      ;;
    *)
      if [ "$running" != "true" ]; then
        continue
      fi
      ;;
  esac
  working_dir="$(
    docker inspect -f \
      '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
      "$container_name"
  )"
  config_files="$(
    docker inspect -f \
      '{{index .Config.Labels "com.docker.compose.project.config_files"}}' \
      "$container_name"
  )"
  check_container "$container_name" "$service" "$working_dir" "$config_files"
done

if [ "$failed" -ne 0 ]; then
  printf >&2 '%s\n' \
    "Run this script from the canonical checkout after safely recreating only the mismatched application containers."
  exit 2
fi

if [ "${1:-}" = "preflight" ]; then
  printf '%s\n' "Development Compose preflight passed for $repo_root"
  exit 0
fi

exec docker compose -f "$compose_file" "$@"
