#!/usr/bin/env python3
"""Validate immutable release and production activation contracts."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REQUEST_ID = re.compile(r"^[a-z][a-z0-9-]{7,79}$")
IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}$")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
SAFE_CONTAINER = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_BUCKET = re.compile(r"^[A-Za-z0-9._-]+$")
ACTIVATION_FAILURE_STAGES = frozenset(
    {
        "startup",
        "helper-authority",
        "external-config",
        "candidate-contract",
        "mutation-lock",
        "compose-structure",
        "image-contract",
        "production-values",
        "runtime-compose-config",
        "ingress-contract",
        "persistent-services",
        "postgres-readiness",
        "redis-readiness",
        "minio-preflight",
        "class-zero-before",
        "postgres-backup",
        "minio-manifest",
        "class-zero-after",
        "application-cutover",
        "internal-health",
        "external-health",
        "bounded-observation",
        "activation-marker",
        "engine-evidence",
    }
)
LISTEN_PORT = re.compile(
    r"\blisten\s+(?:\[[^\]]+\]:|[A-Za-z0-9_.-]+:)?"
    r"(?P<port>[0-9]{1,5})(?=[\s;])"
)
NGINX_CONFIG_TARGET = "/etc/nginx/nginx.conf"
NGINX_LISTENER_TARGET = "/etc/nginx/pastexam-listeners.conf"
TLS_CERTIFICATE_TARGET = "/etc/nginx/certs/origin.pem"
TLS_KEY_TARGET = "/etc/nginx/certs/origin-key.pem"
NGINX_MOUNT_TARGETS = frozenset(
    {
        NGINX_CONFIG_TARGET,
        NGINX_LISTENER_TARGET,
        TLS_CERTIFICATE_TARGET,
        TLS_KEY_TARGET,
    }
)
RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
APP_NETWORK = "app_network"
TRUSTED_PROXY_NETWORK = "trusted_proxy_network"
TRUSTED_PROXY_NETWORK_NAME = "pastexam-trusted-proxy-network"
TRUSTED_BACKEND_ALIAS = "backend-trusted"
EXPECTED_SERVICES = frozenset(
    {"frontend", "backend", "migrate", "db", "minio", "redis", "nginx"}
)
ENVIRONMENT_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$"
)
FRONTEND_IMAGE_EXPRESSION = (
    "${FRONTEND_IMAGE:-ghcr.io/nthu-physics-sa-it/pastexam:frontend}"
)
BACKEND_IMAGE_EXPRESSION = (
    "${BACKEND_IMAGE:-ghcr.io/nthu-physics-sa-it/pastexam:backend}"
)
BACKEND_ENV_FILE_EXPRESSION = (
    "${PRODUCTION_BACKEND_ENV_FILE:-/opt/pastexam-config/backend.env}"
)
MIGRATOR_ENV_FILE_EXPRESSION = (
    "${PRODUCTION_MIGRATOR_ENV_FILE:-/opt/pastexam-config/migrator.env}"
)
PROXY_IP_EXPRESSION = (
    "${PRODUCTION_NGINX_PROXY_IP:?Set PRODUCTION_NGINX_PROXY_IP}"
)
TLS_CERTIFICATE_EXPRESSION = (
    "${PRODUCTION_TLS_CERT_FILE:?Set PRODUCTION_TLS_CERT_FILE}"
)
TLS_KEY_EXPRESSION = "${PRODUCTION_TLS_KEY_FILE:?Set PRODUCTION_TLS_KEY_FILE}"
DATABASE_ENVIRONMENT_EXPRESSIONS = {
    "POSTGRES_USER": "${POSTGRES_USER}",
    "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD}",
    "POSTGRES_DB": "${POSTGRES_DB}",
}
MINIO_ENVIRONMENT_EXPRESSIONS = frozenset(
    {
        "MINIO_ROOT_USER=${MINIO_ROOT_USER}",
        "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}",
    }
)
BACKEND_ENVIRONMENT_EXPRESSIONS = {"FORWARDED_ALLOW_IPS": PROXY_IP_EXPRESSION}
FORBIDDEN_PRODUCTION_KEYS = frozenset({"DEFAULT_ADMIN_PASSWORD"})
BACKEND_REQUIRED_KEYS = frozenset(
    {
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET_NAME",
    }
)
MIGRATOR_REQUIRED_KEYS = frozenset(
    {"DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"}
)
SERVICE_KEYS = {
    "frontend": frozenset({"image", "container_name", "restart", "networks"}),
    "backend": frozenset(
        {
            "image",
            "container_name",
            "restart",
            "depends_on",
            "env_file",
            "environment",
            "networks",
        }
    ),
    "migrate": frozenset(
        {"image", "restart", "command", "depends_on", "env_file", "networks"}
    ),
    "db": frozenset(
        {
            "image",
            "container_name",
            "restart",
            "environment",
            "healthcheck",
            "volumes",
            "networks",
        }
    ),
    "minio": frozenset(
        {
            "image",
            "container_name",
            "restart",
            "command",
            "environment",
            "healthcheck",
            "volumes",
            "networks",
        }
    ),
    "redis": frozenset(
        {"image", "container_name", "restart", "volumes", "networks"}
    ),
    "nginx": frozenset(
        {
            "image",
            "container_name",
            "restart",
            "expose",
            "volumes",
            "depends_on",
            "networks",
            "ports",
        }
    ),
}
NAMED_VOLUME_AUTHORITY = {
    "pg_data": {"name": "pastexam-postgres-data"},
    "minio_data": {"name": "pastexam-minio-data"},
    "redis_data": {"name": "pastexam-redis-data"},
}
CRITICAL_LOG_PATTERN = re.compile(
    rb"(^|[^a-z])(panic|fatal|segmentation fault|traceback|unhandled exception|\[emerg\]|\[crit\])([^a-z]|$)",
    re.IGNORECASE,
)
CRITICAL_LOG_NONTERMINAL_PATTERN = re.compile(
    rb"(^|[^a-z])(panic|fatal|segmentation fault|traceback|unhandled exception|\[emerg\]|\[crit\])([^a-z])",
    re.IGNORECASE,
)
CRITICAL_LOG_CHUNK_SIZE = 64 * 1024
CRITICAL_LOG_TAIL_SIZE = 64


class ContractError(ValueError):
    """A production activation input is incomplete or inconsistent."""


def _unquote_metadata_value(raw_value: str, key: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if not value or any(character in value for character in "\r\n"):
        raise ContractError(f"Production metadata key {key} is empty or malformed.")
    return value


def _assignment_has_value(raw_value: str) -> bool:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return bool(value[1:-1])
    return bool(value)


def _read_environment_metadata(
    path: Path,
    *,
    required_keys: frozenset[str],
    selected_value_keys: frozenset[str] = frozenset(),
    forbidden_keys: frozenset[str] = FORBIDDEN_PRODUCTION_KEYS,
) -> tuple[frozenset[str], dict[str, str]]:
    keys: set[str] = set()
    selected_values: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8") as environment_file:
            for line_number, line in enumerate(environment_file, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = ENVIRONMENT_ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
                if match is None:
                    raise ContractError(
                        f"Production environment assignment is malformed at line {line_number}."
                    )
                key = match.group("key")
                if key in keys:
                    raise ContractError(
                        f"Production environment key {key} is duplicated."
                    )
                keys.add(key)
                raw_value = match.group("value")
                if key in required_keys and not _assignment_has_value(raw_value):
                    raise ContractError(f"Production environment key {key} is empty.")
                if key in selected_value_keys:
                    selected_values[key] = _unquote_metadata_value(raw_value, key)
    except OSError as error:
        raise ContractError(
            f"Cannot read production environment metadata: {path.name}"
        ) from error

    forbidden = sorted(keys & forbidden_keys)
    if forbidden:
        raise ContractError(
            "Production environment contains forbidden key names: "
            + ", ".join(forbidden)
        )
    missing = sorted(required_keys - keys)
    if missing:
        raise ContractError(
            "Production environment is missing required key names: "
            + ", ".join(missing)
        )
    return frozenset(keys), selected_values


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"Cannot read validated JSON input: {path.name}") from error


def _load_json_stream() -> Any:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise ContractError("Structural Compose input is not valid JSON.") from error


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(output: Path, payload: Any) -> None:
    if not output.is_absolute():
        raise ContractError("Validated metadata output path must be absolute.")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.partial-", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            else:
                os.chmod(temporary, 0o600)
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        _fsync_directory(output.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _count_critical_log_lines() -> None:
    count = 0
    tail = b""
    line_matched = False
    while chunk := sys.stdin.buffer.read(CRITICAL_LOG_CHUNK_SIZE):
        offset = 0
        while True:
            newline = chunk.find(b"\n", offset)
            if newline < 0:
                segment = chunk[offset:]
                if not line_matched:
                    candidate = tail + segment
                    line_matched = bool(
                        CRITICAL_LOG_NONTERMINAL_PATTERN.search(candidate)
                    )
                    tail = candidate[-CRITICAL_LOG_TAIL_SIZE:]
                break
            segment = chunk[offset:newline]
            if not line_matched:
                line_matched = bool(CRITICAL_LOG_PATTERN.search(tail + segment))
            if line_matched:
                count += 1
            tail = b""
            line_matched = False
            offset = newline + 1
    if tail or line_matched:
        if not line_matched:
            line_matched = bool(CRITICAL_LOG_PATTERN.search(tail))
        if line_matched:
            count += 1
    print(count)


def _service(compose: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        service = compose["services"][name]
    except (KeyError, TypeError) as error:
        raise ContractError(f"Rendered Compose is missing service {name!r}.") from error
    if not isinstance(service, dict):
        raise ContractError(f"Rendered Compose service {name!r} is invalid.")
    return service


def _required_string(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError(f"Rendered Compose is missing {label}.")
    return value


def _verify_backend_storage_credentials(keys: frozenset[str]) -> None:
    forbidden = sorted(keys & {"MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"})
    if forbidden:
        raise ContractError(
            "Backend environment retains the legacy MinIO root-named contract."
        )


def _verify_proxy_trust(compose: dict[str, Any], proxy_ip: str) -> None:
    backend = _service(compose, "backend")
    nginx = _service(compose, "nginx")
    backend_environment = backend.get("environment")
    backend_networks = backend.get("networks")
    nginx_networks = nginx.get("networks")
    if (
        not isinstance(backend_environment, dict)
        or not isinstance(backend_networks, dict)
        or not isinstance(nginx_networks, dict)
    ):
        raise ContractError("Rendered client-IP proxy trust contract is incomplete.")

    networks = compose.get("networks")
    if not isinstance(networks, dict) or set(networks) != {
        APP_NETWORK,
        TRUSTED_PROXY_NETWORK,
    }:
        raise ContractError("Rendered client-IP proxy trust networks are incomplete.")
    app_network = networks.get(APP_NETWORK)
    trusted_network = networks.get(TRUSTED_PROXY_NETWORK)
    if not isinstance(app_network, dict) or not isinstance(trusted_network, dict):
        raise ContractError("Rendered client-IP proxy trust networks are incomplete.")
    if app_network != {"name": "pastexam-network", "driver": "bridge"}:
        raise ContractError("Rendered shared application network must not define IPAM.")
    if (
        trusted_network.get("name") != TRUSTED_PROXY_NETWORK_NAME
        or trusted_network.get("driver") != "bridge"
    ):
        raise ContractError(
            "Rendered client-IP proxy trust network identity is unsafe."
        )

    ipam = trusted_network.get("ipam")
    configurations = ipam.get("config") if isinstance(ipam, dict) else None
    if not isinstance(configurations, list) or len(configurations) != 1:
        raise ContractError("Rendered client-IP proxy trust IPAM is incomplete.")
    configuration = configurations[0]
    if not isinstance(configuration, dict):
        raise ContractError("Rendered client-IP proxy trust IPAM is incomplete.")

    try:
        trusted_subnet = ipaddress.ip_network(
            _required_string(configuration, "subnet", "trusted proxy subnet"),
            strict=True,
        )
        dynamic_range = ipaddress.ip_network(
            _required_string(configuration, "ip_range", "trusted proxy dynamic range"),
            strict=True,
        )
        gateway = ipaddress.ip_address(
            _required_string(configuration, "gateway", "trusted proxy gateway")
        )
    except ValueError as error:
        raise ContractError(
            "Rendered client-IP proxy trust IPAM is invalid."
        ) from error
    if (
        trusted_subnet.version != 4
        or not any(trusted_subnet.subnet_of(network) for network in RFC1918_NETWORKS)
        or dynamic_range.version != 4
        or not dynamic_range.subnet_of(trusted_subnet)
        or gateway.version != 4
        or gateway not in trusted_subnet
        or gateway in (trusted_subnet.network_address, trusted_subnet.broadcast_address)
        or gateway in dynamic_range
    ):
        raise ContractError("Rendered client-IP proxy trust IPAM is unsafe.")

    backend_trusted_attachment = backend_networks.get(TRUSTED_PROXY_NETWORK)
    nginx_trusted_attachment = nginx_networks.get(TRUSTED_PROXY_NETWORK)
    if not isinstance(backend_trusted_attachment, dict) or not isinstance(
        nginx_trusted_attachment, dict
    ):
        raise ContractError("Rendered trusted proxy peers are not both attached.")
    aliases = backend_trusted_attachment.get("aliases")
    if not isinstance(aliases, list) or aliases != [TRUSTED_BACKEND_ALIAS]:
        raise ContractError("Rendered trusted backend alias is not network-scoped.")
    app_attachment = backend_networks.get(APP_NETWORK)
    app_aliases = (
        app_attachment.get("aliases", []) if isinstance(app_attachment, dict) else None
    )
    if (
        not isinstance(app_aliases, list)
        or TRUSTED_BACKEND_ALIAS in app_aliases
        or APP_NETWORK not in nginx_networks
    ):
        raise ContractError(
            "Rendered trusted backend alias leaks to the shared network."
        )

    services = compose.get("services")
    if not isinstance(services, dict):
        raise ContractError("Rendered client-IP proxy trust services are incomplete.")
    for service_name, service in services.items():
        if service_name in ("backend", "nginx"):
            continue
        service_networks = (
            service.get("networks", {}) if isinstance(service, dict) else None
        )
        if (
            not isinstance(service_networks, dict)
            or TRUSTED_PROXY_NETWORK in service_networks
        ):
            raise ContractError(
                "Rendered trusted proxy network has an unrelated service."
            )

    expected_network_names = {
        "frontend": {APP_NETWORK},
        "backend": {APP_NETWORK, TRUSTED_PROXY_NETWORK},
        "migrate": {APP_NETWORK},
        "db": {APP_NETWORK},
        "minio": {APP_NETWORK},
        "redis": {APP_NETWORK},
        "nginx": {APP_NETWORK, TRUSTED_PROXY_NETWORK},
    }
    for service_name, expected_names in expected_network_names.items():
        service_networks = services[service_name].get("networks")
        if not isinstance(service_networks, dict) or set(service_networks) != expected_names:
            raise ContractError(
                f"Rendered Compose service {service_name!r} network authority is not exact."
            )
    if backend_networks.get(APP_NETWORK) != {"aliases": ["backend"]}:
        raise ContractError("Rendered backend application-network aliases are unsafe.")
    if backend_trusted_attachment != {"aliases": [TRUSTED_BACKEND_ALIAS]}:
        raise ContractError("Rendered backend trusted-network aliases are unsafe.")
    if nginx_networks.get(APP_NETWORK) not in (None, {}):
        raise ContractError("Rendered nginx application-network attachment is unsafe.")
    if set(nginx_trusted_attachment) != {"ipv4_address"}:
        raise ContractError("Rendered nginx trusted-network attachment is unsafe.")
    expected_app_attachments = {
        "frontend": {"aliases": ["frontend"]},
        "migrate": None,
        "db": None,
        "minio": {"aliases": ["minio"]},
        "redis": None,
    }
    for service_name, expected_attachment in expected_app_attachments.items():
        attachment = services[service_name]["networks"].get(APP_NETWORK)
        if expected_attachment is None:
            if attachment not in (None, {}):
                raise ContractError(
                    f"Rendered Compose service {service_name!r} network attachment is unsafe."
                )
        elif attachment != expected_attachment:
            raise ContractError(
                f"Rendered Compose service {service_name!r} network attachment is unsafe."
            )

    trusted_peer_expression = _required_string(
        backend_environment,
        "FORWARDED_ALLOW_IPS",
        "Uvicorn trusted proxy address",
    )
    nginx_address_expression = _required_string(
        nginx_trusted_attachment,
        "ipv4_address",
        "stable nginx trusted-proxy address",
    )
    if (
        trusted_peer_expression != PROXY_IP_EXPRESSION
        or nginx_address_expression != PROXY_IP_EXPRESSION
    ):
        raise ContractError(
            "Structural Compose proxy trust does not use the reviewed metadata key."
        )

    try:
        trusted_address = ipaddress.ip_address(proxy_ip)
        assigned_address = ipaddress.ip_address(proxy_ip)
    except ValueError as error:
        raise ContractError(
            "Rendered client-IP proxy trust must use one exact IP address."
        ) from error
    if trusted_address.version != 4 or not any(
        trusted_address in network for network in RFC1918_NETWORKS
    ):
        raise ContractError(
            "Rendered Uvicorn proxy trust must use one private IPv4 address."
        )
    if trusted_address != assigned_address:
        raise ContractError(
            "Rendered Uvicorn proxy trust does not match nginx's assigned address."
        )
    if (
        assigned_address not in trusted_subnet
        or assigned_address in dynamic_range
        or assigned_address
        in (trusted_subnet.network_address, gateway, trusted_subnet.broadcast_address)
    ):
        raise ContractError(
            "Rendered nginx trusted proxy address is not safely reserved by IPAM."
        )


def _verify_no_privilege_expansion(compose: dict[str, Any]) -> None:
    if set(compose) != {"name", "services", "networks", "volumes"} or compose.get(
        "name"
    ) != "pastexam":
        raise ContractError("Structural Compose top-level authority is not exact.")
    services = compose.get("services")
    if not isinstance(services, dict) or set(services) != EXPECTED_SERVICES:
        raise ContractError(
            "Rendered Compose service set is not the reviewed production set."
        )
    forbidden_keys = {
        "privileged",
        "network_mode",
        "pid",
        "ipc",
        "userns_mode",
        "user",
        "devices",
        "cap_add",
        "group_add",
        "cgroup_parent",
        "device_cgroup_rules",
        "volumes_from",
        "configs",
        "secrets",
        "sysctls",
        "runtime",
        "build",
    }
    for name, service in services.items():
        if not isinstance(service, dict):
            raise ContractError("Rendered Compose service contract is malformed.")
        if set(service) != SERVICE_KEYS[name]:
            raise ContractError(
                f"Rendered Compose service {name!r} expands host privilege or structure."
            )
    exact_service_values = {
        "frontend": {"container_name": "pastexam-frontend", "restart": "always"},
        "backend": {
            "container_name": "pastexam-backend",
            "restart": "always",
            "depends_on": {
                "migrate": {
                    "condition": "service_completed_successfully",
                    "required": True,
                },
                "minio": {"condition": "service_started", "required": True},
                "redis": {"condition": "service_started", "required": True},
            },
        },
        "migrate": {
            "restart": "no",
            "depends_on": {
                "db": {"condition": "service_healthy", "required": True}
            },
        },
        "db": {
            "image": "postgres:15.14-alpine3.22",
            "container_name": "pastexam-postgres",
            "restart": "always",
            "healthcheck": {
                "test": [
                    "CMD-SHELL",
                    "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}",
                ],
                "interval": "5s",
                "timeout": "5s",
                "retries": 5,
            },
        },
        "minio": {
            "image": "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z",
            "container_name": "pastexam-minio",
            "restart": "always",
            "healthcheck": {
                "test": ["CMD", "mc", "ready", "local"],
                "interval": "5s",
                "timeout": "5s",
                "retries": 5,
            },
        },
        "redis": {
            "image": "redis:7.4.5-alpine3.21",
            "container_name": "pastexam-redis",
            "restart": "always",
        },
        "nginx": {
            "container_name": "pastexam-nginx",
            "restart": "always",
            "expose": ["8080", "8443"],
            "depends_on": {
                "backend": {"condition": "service_started", "required": True},
                "frontend": {"condition": "service_started", "required": True},
                "minio": {"condition": "service_started", "required": True},
            },
        },
    }
    for service_name, expected_values in exact_service_values.items():
        if any(
            services[service_name].get(key) != value
            for key, value in expected_values.items()
        ):
            raise ContractError(
                f"Rendered Compose service {service_name!r} authority is not exact."
            )
        present = [
            key
            for key in forbidden_keys
            if service.get(key) not in (None, False, [], {})
        ]
        if present:
            raise ContractError(
                f"Rendered Compose service {name!r} expands host privilege."
            )
        if service.get("entrypoint") not in (None, [], ""):
            raise ContractError(
                f"Rendered Compose service {name!r} overrides its entrypoint."
            )
        security_options = service.get("security_opt", [])
        if not isinstance(security_options, list) or any(
            not isinstance(option, str) or option != "no-new-privileges:true"
            for option in security_options
        ):
            raise ContractError(
                f"Rendered Compose service {name!r} has unsafe security options."
            )
        volumes = service.get("volumes", [])
        if not isinstance(volumes, list):
            raise ContractError(
                f"Rendered Compose service {name!r} has malformed mounts."
            )
        if name == "nginx" and (
            len(volumes) != len(NGINX_MOUNT_TARGETS)
            or {volume.get("target") for volume in volumes if isinstance(volume, dict)}
            != NGINX_MOUNT_TARGETS
            or any(
                not isinstance(volume, dict)
                or volume.get("type") != "bind"
                or volume.get("read_only") is not True
                for volume in volumes
            )
        ):
            raise ContractError(
                "Rendered nginx mounts are not the exact reviewed read-only set."
            )
        if name != "nginx" and any(
            isinstance(volume, dict) and volume.get("type") == "bind"
            for volume in volumes
        ):
            raise ContractError(
                f"Rendered Compose service {name!r} has an unreviewed host bind mount."
            )
        if name != "nginx" and any(
            not isinstance(volume, dict)
            or volume.get("type") != "volume"
            or not isinstance(volume.get("source"), str)
            or not volume.get("source")
            for volume in volumes
        ):
            raise ContractError(
                f"Rendered Compose service {name!r} has an unsafe volume contract."
            )
        if name not in {"migrate", "minio"} and service.get("command") not in (
            None,
            [],
            "",
        ):
            raise ContractError(
                f"Rendered Compose service {name!r} overrides its command."
            )
    for top_level in ("configs", "secrets"):
        if compose.get(top_level) not in (None, {}):
            raise ContractError(
                f"Rendered Compose has unreviewed top-level {top_level}."
            )
    if compose.get("volumes") != NAMED_VOLUME_AUTHORITY:
        raise ContractError("Rendered Compose named-volume authority is not exact.")
    expected_service_volumes = {
        "db": ("pg_data", "/var/lib/postgresql/data"),
        "minio": ("minio_data", "/data"),
        "redis": ("redis_data", "/data"),
    }
    for service_name, (source, target) in expected_service_volumes.items():
        service_volumes = services[service_name].get("volumes")
        if not isinstance(service_volumes, list) or len(service_volumes) != 1:
            raise ContractError(
                f"Rendered Compose service {service_name!r} volume authority is not exact."
            )
        volume = service_volumes[0]
        if (
            not isinstance(volume, dict)
            or set(volume) - {"source", "target", "type", "volume"}
            or volume.get("source") != source
            or volume.get("target") != target
            or volume.get("type") != "volume"
            or volume.get("volume") not in (None, {})
        ):
            raise ContractError(
                f"Rendered Compose service {service_name!r} volume authority is not exact."
            )
    for service_name in ("frontend", "backend", "migrate"):
        if services[service_name].get("volumes") not in (None, []):
            raise ContractError(
                f"Rendered Compose service {service_name!r} has an unreviewed volume."
            )
    migrate_command = services["migrate"].get("command")
    if migrate_command != ["python", "migrate.py", "upgrade"]:
        raise ContractError(
            "Rendered migration command is not the reviewed fixed command."
        )
    minio_command = services["minio"].get("command")
    if minio_command not in (
        ["server", "/data", "--console-address", ":9001"],
        "server /data --console-address :9001",
        'server /data --console-address ":9001"',
    ):
        raise ContractError("Rendered MinIO command is not the reviewed fixed command.")


def _verify_env_file_reference(
    service: dict[str, Any], expression: str, label: str
) -> None:
    env_files = service.get("env_file")
    if env_files != [{"path": expression, "required": True}]:
        raise ContractError(
            f"Structural Compose {label} env-file binding is not the reviewed path."
        )


def _verify_structural_expressions(compose: dict[str, Any]) -> None:
    backend = _service(compose, "backend")
    migrate = _service(compose, "migrate")
    database = _service(compose, "db")
    minio = _service(compose, "minio")
    _verify_env_file_reference(
        backend, BACKEND_ENV_FILE_EXPRESSION, "backend"
    )
    _verify_env_file_reference(
        migrate, MIGRATOR_ENV_FILE_EXPRESSION, "migrator"
    )
    if backend.get("environment") != BACKEND_ENVIRONMENT_EXPRESSIONS:
        raise ContractError(
            "Structural Compose proxy trust backend environment is not key-name-only."
        )
    if database.get("environment") != DATABASE_ENVIRONMENT_EXPRESSIONS:
        raise ContractError(
            "Structural Compose database environment is not key-name-only."
        )
    minio_environment = minio.get("environment")
    if (
        not isinstance(minio_environment, list)
        or frozenset(minio_environment) != MINIO_ENVIRONMENT_EXPRESSIONS
        or len(minio_environment) != len(MINIO_ENVIRONMENT_EXPRESSIONS)
    ):
        raise ContractError(
            "Structural Compose MinIO environment is not key-name-only."
        )
    for service_name in ("frontend", "db", "minio", "redis", "nginx"):
        if _service(compose, service_name).get("env_file") not in (None, []):
            raise ContractError(
                f"Structural Compose {service_name} has an unreviewed env-file binding."
            )
    for service_name in ("frontend", "migrate", "redis", "nginx"):
        if _service(compose, service_name).get("environment") not in (None, {}):
            raise ContractError(
                f"Structural Compose {service_name} has an unreviewed environment."
            )


def _write_validated_structure(output: Path, compose_environment_path: Path) -> None:
    compose = _load_json_stream()
    if not isinstance(compose, dict):
        raise ContractError("Structural Compose root must be an object.")
    _, compose_values = _read_environment_metadata(
        compose_environment_path,
        required_keys=frozenset({"PRODUCTION_NGINX_PROXY_IP"}),
        selected_value_keys=frozenset({"PRODUCTION_NGINX_PROXY_IP"}),
    )
    _verify_no_privilege_expansion(compose)
    _verify_structural_expressions(compose)
    _verify_proxy_trust(compose, compose_values["PRODUCTION_NGINX_PROXY_IP"])
    _write_json_atomic(output, compose)


def _compose_values(
    compose_path: Path,
    compose_environment_path: Path,
    backend_environment_path: Path,
    migrator_environment_path: Path,
) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Structural Compose root must be an object.")

    compose_required = frozenset(
        {
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "MINIO_ROOT_USER",
            "MINIO_ROOT_PASSWORD",
            "PRODUCTION_NGINX_PROXY_IP",
            "PRODUCTION_TLS_CERT_FILE",
            "PRODUCTION_TLS_KEY_FILE",
        }
    )
    _, compose_values = _read_environment_metadata(
        compose_environment_path,
        required_keys=compose_required,
        selected_value_keys=frozenset(
            {
                "POSTGRES_USER",
                "POSTGRES_DB",
                "PRODUCTION_NGINX_PROXY_IP",
                "PRODUCTION_TLS_CERT_FILE",
                "PRODUCTION_TLS_KEY_FILE",
            }
        ),
    )
    backend_keys, backend_values = _read_environment_metadata(
        backend_environment_path,
        required_keys=BACKEND_REQUIRED_KEYS,
        selected_value_keys=frozenset({"MINIO_BUCKET_NAME"}),
    )
    _read_environment_metadata(
        migrator_environment_path,
        required_keys=MIGRATOR_REQUIRED_KEYS,
    )

    _verify_no_privilege_expansion(compose)
    _verify_structural_expressions(compose)
    _verify_proxy_trust(compose, compose_values["PRODUCTION_NGINX_PROXY_IP"])

    database = _service(compose, "db")
    minio = _service(compose, "minio")
    redis = _service(compose, "redis")
    nginx = _service(compose, "nginx")
    _verify_backend_storage_credentials(backend_keys)

    values_and_patterns = (
        (
            _required_string(database, "container_name", "database container identity"),
            SAFE_CONTAINER,
        ),
        (
            compose_values["POSTGRES_DB"],
            SAFE_IDENTIFIER,
        ),
        (
            compose_values["POSTGRES_USER"],
            SAFE_IDENTIFIER,
        ),
        (
            _required_string(minio, "container_name", "MinIO container identity"),
            SAFE_CONTAINER,
        ),
        (
            backend_values["MINIO_BUCKET_NAME"],
            SAFE_BUCKET,
        ),
        (
            _required_string(nginx, "container_name", "nginx container identity"),
            SAFE_CONTAINER,
        ),
        (
            _required_string(redis, "container_name", "Redis container identity"),
            SAFE_CONTAINER,
        ),
    )
    for value, pattern in values_and_patterns:
        if pattern.fullmatch(value) is None:
            raise ContractError("Production metadata contains an unsafe contract value.")
        print(value)


def _bind_mount_source(service: dict[str, Any], target: str, label: str) -> str:
    volumes = service.get("volumes")
    if not isinstance(volumes, list):
        raise ContractError(f"Rendered nginx is missing the required {label} mount.")
    matches = [
        volume
        for volume in volumes
        if isinstance(volume, dict) and volume.get("target") == target
    ]
    if len(matches) != 1:
        raise ContractError(
            f"Rendered nginx must have exactly one required {label} mount."
        )
    mount = matches[0]
    source = mount.get("source")
    expected_keys = {"type", "source", "target", "read_only"}
    if source not in {TLS_CERTIFICATE_EXPRESSION, TLS_KEY_EXPRESSION}:
        expected_keys.add("bind")
    if (
        set(mount) != expected_keys
        or mount.get("type") != "bind"
        or mount.get("read_only") is not True
        or not isinstance(source, str)
        or not source
        or any(character in source for character in "\r\n")
        or (
            "bind" in expected_keys
            and mount.get("bind") != {"create_host_path": True}
        )
    ):
        raise ContractError(f"Rendered nginx {label} mount is not a read-only bind.")
    return source


def _nginx_mount_sources(compose: dict[str, Any]) -> tuple[str, str, str, str]:
    nginx = _service(compose, "nginx")
    return (
        _bind_mount_source(nginx, NGINX_CONFIG_TARGET, "configuration"),
        _bind_mount_source(nginx, NGINX_LISTENER_TARGET, "listener configuration"),
        _bind_mount_source(nginx, TLS_CERTIFICATE_TARGET, "TLS certificate"),
        _bind_mount_source(nginx, TLS_KEY_TARGET, "TLS private key"),
    )


def _resolved_nginx_mount_sources(
    compose: dict[str, Any],
    release_directory: Path,
    compose_values: dict[str, str],
) -> tuple[Path, Path, Path, Path]:
    sources = _nginx_mount_sources(compose)
    expected = (
        "../proxy/nginx.conf",
        "../proxy/nginx.production-listeners.conf",
        TLS_CERTIFICATE_EXPRESSION,
        TLS_KEY_EXPRESSION,
    )
    if sources != expected:
        raise ContractError(
            "Structural Compose nginx mounts do not use the reviewed metadata bindings."
        )
    return (
        release_directory / "proxy" / "nginx.conf",
        release_directory / "proxy" / "nginx.production-listeners.conf",
        Path(compose_values["PRODUCTION_TLS_CERT_FILE"]),
        Path(compose_values["PRODUCTION_TLS_KEY_FILE"]),
    )


def _mount_values(
    compose_path: Path, compose_environment_path: Path, release_directory: Path
) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Structural Compose root must be an object.")
    _, compose_values = _read_environment_metadata(
        compose_environment_path,
        required_keys=frozenset(
            {"PRODUCTION_TLS_CERT_FILE", "PRODUCTION_TLS_KEY_FILE"}
        ),
        selected_value_keys=frozenset(
            {"PRODUCTION_TLS_CERT_FILE", "PRODUCTION_TLS_KEY_FILE"}
        ),
    )
    for source in _resolved_nginx_mount_sources(
        compose, release_directory, compose_values
    ):
        if not source.is_absolute():
            raise ContractError("Production nginx mount metadata is not absolute.")
        print(source)


def _manifest_release_sha(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ContractError("Cannot read the release manifest.") from error
    values = [
        line.removeprefix("release_sha=")
        for line in lines
        if line.startswith("release_sha=")
    ]
    if len(values) != 1 or FULL_SHA.fullmatch(values[0]) is None:
        raise ContractError("Release manifest has no unique valid release SHA.")
    return values[0]


def _manifest_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ContractError("Cannot read the release manifest.") from error
    prefix = f"{key}="
    values = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
    if len(values) != 1 or not values[0]:
        raise ContractError(f"Release manifest has no unique {key} value.")
    return values[0]


def _optional_manifest_value(path: Path, key: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ContractError("Cannot read the release manifest.") from error
    prefix = f"{key}="
    values = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
    if len(values) > 1 or any(not value for value in values):
        raise ContractError(f"Release manifest has an ambiguous {key} value.")
    return values[0] if values else None


def _verify_images(
    compose_path: Path, manifest: Path, candidate_environment_path: Path
) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Structural Compose root must be an object.")
    expected_frontend = _manifest_value(manifest, "frontend_image")
    expected_backend = _manifest_value(manifest, "backend_image")
    expected_nginx = _optional_manifest_value(manifest, "nginx_image") or (
        "nginx:1.29.2@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903"
    )
    structural = {
        "frontend": FRONTEND_IMAGE_EXPRESSION,
        "backend": BACKEND_IMAGE_EXPRESSION,
        "migrate": BACKEND_IMAGE_EXPRESSION,
        "nginx": expected_nginx,
    }
    mismatches = [
        name
        for name, expected_image in structural.items()
        if _required_string(_service(compose, name), "image", f"{name} image")
        != expected_image
    ]
    if mismatches:
        raise ContractError(
            "Structural Compose images disagree with the reviewed image authority: "
            + ", ".join(mismatches)
        )
    candidate_keys, candidate_values = _read_environment_metadata(
        candidate_environment_path,
        required_keys=frozenset({"FRONTEND_IMAGE", "BACKEND_IMAGE"}),
        selected_value_keys=frozenset({"FRONTEND_IMAGE", "BACKEND_IMAGE"}),
        forbidden_keys=frozenset(),
    )
    if candidate_keys != frozenset({"FRONTEND_IMAGE", "BACKEND_IMAGE"}):
        raise ContractError("Immutable candidate image environment has unexpected keys.")
    if (
        candidate_values["FRONTEND_IMAGE"] != expected_frontend
        or candidate_values["BACKEND_IMAGE"] != expected_backend
    ):
        raise ContractError(
            "Immutable candidate images disagree with the release manifest."
        )


def _runtime_image_values(manifest: Path) -> None:
    images = (
        (
            _optional_manifest_value(manifest, "nginx_image")
            or "nginx:1.29.2@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903",
            "pastexam-nginx",
            "nginx_image",
        ),
        (
            _manifest_value(manifest, "backend_image"),
            "pastexam-backend",
            "backend_image",
        ),
        (
            _manifest_value(manifest, "frontend_image"),
            "pastexam-frontend",
            "frontend_image",
        ),
    )
    for image, container, manifest_key in images:
        if IMAGE_PATTERN.fullmatch(image) is None:
            raise ContractError(f"{manifest_key} runtime image is not digest-pinned.")
        print(f"{container}={image}")


def _verify_class_zero(report_path: Path) -> None:
    report = _load_json(report_path)
    if not isinstance(report, dict):
        raise ContractError("Migration report root must be an object.")
    heads = report.get("repository_heads")
    current = report.get("current_revision")
    errors = report.get("errors")
    if (
        report.get("database_connected") is not True
        or report.get("current_revision_known") is not True
        or report.get("multiple_heads") is not False
        or not isinstance(heads, list)
        or len(heads) != 1
        or not isinstance(current, str)
        or current != heads[0]
        or report.get("schema_matches_head") is not True
        or report.get("upgrade_allowed") is not True
        or not isinstance(errors, list)
        or errors
    ):
        raise ContractError(
            "Production migration delta is non-zero or database head authority is incomplete."
        )
    if SAFE_IDENTIFIER.fullmatch(current) is None:
        raise ContractError("Production database revision is malformed.")
    print(current)


def _write_engine_evidence(
    output: Path,
    target_sha: str,
    database_revision_before: str,
    database_revision_after: str,
    postgres_metadata: Path,
    postgres_checksum: Path,
    minio_manifest: Path,
    observation_snapshots: int,
    critical_error_count: int,
    started_at: str,
) -> None:
    if not output.is_absolute() or FULL_SHA.fullmatch(target_sha) is None:
        raise ContractError("Engine evidence target is malformed.")
    if (
        SAFE_IDENTIFIER.fullmatch(database_revision_before) is None
        or database_revision_before != database_revision_after
    ):
        raise ContractError("Engine evidence database revision disagrees.")
    if observation_snapshots < 1:
        raise ContractError("Engine observation evidence is malformed.")
    if critical_error_count != 0:
        raise ContractError("Engine critical-error evidence is not clean.")
    for path, label in (
        (postgres_metadata, "PostgreSQL backup metadata"),
        (postgres_checksum, "PostgreSQL backup checksum"),
        (minio_manifest, "MinIO manifest"),
    ):
        if not path.is_absolute() or not path.is_file():
            raise ContractError(f"{label} evidence is unavailable.")
    payload = {
        "schema_version": 1,
        "target_sha": target_sha,
        "started_at": started_at,
        "completed_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "database_revision_before": database_revision_before,
        "database_revision_after": database_revision_after,
        "postgres_backup_metadata": str(postgres_metadata),
        "postgres_backup_checksum": str(postgres_checksum),
        "minio_manifest": str(minio_manifest),
        "observation_snapshots": observation_snapshots,
        "critical_error_count": critical_error_count,
        "health_outcome": "green",
        "restart_stability": "stable",
    }
    _write_json_atomic(output, payload)


def _write_engine_failure_evidence(
    output: Path,
    request_id: str,
    target_sha: str,
    stage: str,
    exit_code: int,
) -> None:
    if not output.is_absolute():
        raise ContractError("Engine failure evidence output path must be absolute.")
    if REQUEST_ID.fullmatch(request_id) is None:
        raise ContractError("Engine failure evidence request ID is malformed.")
    if FULL_SHA.fullmatch(target_sha) is None:
        raise ContractError("Engine failure evidence target SHA is malformed.")
    if stage not in ACTIVATION_FAILURE_STAGES:
        raise ContractError("Engine failure evidence stage is unsupported.")
    if isinstance(exit_code, bool) or not 1 <= exit_code <= 255:
        raise ContractError("Engine failure evidence exit code is malformed.")
    payload = {
        "schema_version": 1,
        "request_id": request_id,
        "target_sha": target_sha,
        "stage": stage,
        "exit_code": exit_code,
        "observed_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    _write_json_atomic(output, payload)


def _verify_release(
    manifest: Path, source_sha_path: Path, release_directory: Path
) -> None:
    release_sha = _manifest_release_sha(manifest)
    try:
        source_lines = source_sha_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ContractError("Cannot read immutable source SHA metadata.") from error
    if source_lines != [release_sha]:
        raise ContractError("Immutable release SHA metadata disagrees.")
    if release_directory.name != release_sha:
        raise ContractError(
            "Release directory identity disagrees with release metadata."
        )
    print(release_sha)


def _port(value: Any, label: str) -> int:
    text = str(value)
    if not text.isdecimal():
        raise ContractError(f"{label} must be one numeric port.")
    port = int(text)
    if not 1 <= port <= 65535:
        raise ContractError(f"{label} is outside the valid port range.")
    return port


def _scope(host_ip: Any) -> str:
    value = "" if host_ip is None else str(host_ip)
    return "*" if value == "" else value


def _scope_covers(target_scope: str, current_scope: str) -> bool:
    if target_scope == "*" or target_scope == current_scope:
        return True
    try:
        current_ip = ipaddress.ip_address(current_scope)
    except ValueError:
        return False
    return (target_scope == "0.0.0.0" and current_ip.version == 4) or (
        target_scope == "::" and current_ip.version == 6
    )


def _target_bindings(compose: dict[str, Any]) -> set[tuple[str, int, int, str]]:
    ports = _service(compose, "nginx").get("ports")
    if not isinstance(ports, list) or not ports:
        raise ContractError("Target nginx has no explicit published ingress bindings.")
    bindings: set[tuple[str, int, int, str]] = set()
    for entry in ports:
        if not isinstance(entry, dict):
            raise ContractError("Rendered nginx ports must use normalized mappings.")
        protocol = str(entry.get("protocol", "tcp"))
        if protocol not in ("tcp", "udp"):
            raise ContractError("Rendered nginx port protocol is unsupported.")
        if entry.get("published") is None:
            raise ContractError("Every target nginx port must be explicitly published.")
        bindings.add(
            (
                _scope(entry.get("host_ip")),
                _port(entry["published"], "Published nginx port"),
                _port(entry.get("target"), "Container nginx port"),
                protocol,
            )
        )
    expected_ports = {
        (80, 8080, "tcp"),
        (8080, 8080, "tcp"),
        (443, 8443, "tcp"),
    }
    if (
        {(published, target, protocol) for _, published, target, protocol in bindings}
        != expected_ports
        or any(scope not in {"*", "0.0.0.0"} for scope, _, _, _ in bindings)
    ):
        raise ContractError("Target nginx ingress port/listener authority is not exact.")
    return bindings


def _current_bindings(ports: Any) -> set[tuple[str, int, int, str]]:
    if not isinstance(ports, dict):
        raise ContractError("Current nginx published-port inspection is invalid.")
    bindings: set[tuple[str, int, int, str]] = set()
    for container_key, published_entries in ports.items():
        match = re.fullmatch(
            r"(?P<port>[0-9]{1,5})/(?P<protocol>tcp|udp)", container_key
        )
        if match is None:
            raise ContractError("Current nginx contains an unsupported port binding.")
        if published_entries is None:
            continue
        if not isinstance(published_entries, list):
            raise ContractError("Current nginx published-port inspection is invalid.")
        for entry in published_entries:
            if not isinstance(entry, dict):
                raise ContractError(
                    "Current nginx published-port inspection is invalid."
                )
            bindings.add(
                (
                    _scope(entry.get("HostIp")),
                    _port(entry.get("HostPort"), "Current published nginx port"),
                    _port(match.group("port"), "Current container nginx port"),
                    match.group("protocol"),
                )
            )
    if not bindings:
        raise ContractError("Current nginx has no published production ingress.")
    return bindings


def _binding_is_preserved(
    current: tuple[str, int, int, str],
    targets: set[tuple[str, int, int, str]],
) -> bool:
    current_scope, published, target, protocol = current
    return any(
        target_published == published
        and target_container == target
        and target_protocol == protocol
        and _scope_covers(target_scope, current_scope)
        for target_scope, target_published, target_container, target_protocol in targets
    )


def _read_nginx_source(path: Path, label: str) -> str:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractError(f"Cannot read the immutable nginx {label}.") from error
    return re.sub(r"#.*", "", source)


def _same_path(actual: Path, expected: Path) -> bool:
    return actual.resolve(strict=False) == expected.resolve(strict=False)


def _verify_ingress(
    compose_path: Path,
    current_ports_path: Path,
    release_directory: Path,
    compose_environment_path: Path,
) -> None:
    compose = _load_json(compose_path)
    current_ports = _load_json(current_ports_path)
    if not isinstance(compose, dict):
        raise ContractError("Structural Compose root must be an object.")
    targets = _target_bindings(compose)
    current = _current_bindings(current_ports)
    _, compose_values = _read_environment_metadata(
        compose_environment_path,
        required_keys=frozenset(
            {"PRODUCTION_TLS_CERT_FILE", "PRODUCTION_TLS_KEY_FILE"}
        ),
        selected_value_keys=frozenset(
            {"PRODUCTION_TLS_CERT_FILE", "PRODUCTION_TLS_KEY_FILE"}
        ),
    )
    nginx_config, listener_config, _, _ = _resolved_nginx_mount_sources(
        compose, release_directory, compose_values
    )

    expected_nginx_config = release_directory / "proxy" / "nginx.conf"
    expected_listener_config = (
        release_directory / "proxy" / "nginx.production-listeners.conf"
    )
    if not _same_path(nginx_config, expected_nginx_config) or not _same_path(
        listener_config, expected_listener_config
    ):
        raise ContractError(
            "Rendered Compose would mount an unreviewed nginx configuration."
        )

    nginx_source = _read_nginx_source(nginx_config, "configuration")
    if (
        re.search(
            r"\binclude\s+/etc/nginx/pastexam-listeners\.conf\s*;",
            nginx_source,
        )
        is None
    ):
        raise ContractError(
            "Immutable nginx configuration does not load the mounted listener contract."
        )

    listener_source = _read_nginx_source(listener_config, "listener configuration")
    listeners = {
        _port(match.group("port"), "nginx listener")
        for match in LISTEN_PORT.finditer(listener_source)
    }
    if not listeners:
        raise ContractError("Immutable nginx configuration has no listener.")
    unmatched_targets = sorted({binding[2] for binding in targets} - listeners)
    if unmatched_targets:
        raise ContractError(
            "Target Compose ports disagree with immutable nginx listeners."
        )

    required_tls_directives = (
        r"\blisten\s+8443\s+ssl\s*;",
        r"\bssl_certificate\s+/etc/nginx/certs/origin\.pem\s*;",
        r"\bssl_certificate_key\s+/etc/nginx/certs/origin-key\.pem\s*;",
    )
    if any(
        re.search(directive, listener_source) is None
        for directive in required_tls_directives
    ):
        raise ContractError(
            "Immutable nginx production TLS configuration is incomplete."
        )

    missing = [
        binding for binding in current if not _binding_is_preserved(binding, targets)
    ]
    if missing:
        raise ContractError(
            "Target nginx ingress would drop a current production binding; activation is blocked."
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    values = subparsers.add_parser("compose-values")
    values.add_argument("--compose-json", type=Path, required=True)
    values.add_argument("--compose-env", type=Path, required=True)
    values.add_argument("--backend-env", type=Path, required=True)
    values.add_argument("--migrator-env", type=Path, required=True)

    structure = subparsers.add_parser("write-validated-structure")
    structure.add_argument("--output", type=Path, required=True)
    structure.add_argument("--compose-env", type=Path, required=True)

    mounts = subparsers.add_parser("mount-values")
    mounts.add_argument("--compose-json", type=Path, required=True)
    mounts.add_argument("--compose-env", type=Path, required=True)
    mounts.add_argument("--release-directory", type=Path, required=True)

    release = subparsers.add_parser("verify-release")
    release.add_argument("--manifest", type=Path, required=True)
    release.add_argument("--source-sha", type=Path, required=True)
    release.add_argument("--release-directory", type=Path, required=True)

    images = subparsers.add_parser("verify-images")
    images.add_argument("--compose-json", type=Path, required=True)
    images.add_argument("--manifest", type=Path, required=True)
    images.add_argument("--candidate-env", type=Path, required=True)

    runtime_images = subparsers.add_parser("runtime-image-values")
    runtime_images.add_argument("--manifest", type=Path, required=True)

    ingress = subparsers.add_parser("verify-ingress")
    ingress.add_argument("--compose-json", type=Path, required=True)
    ingress.add_argument("--current-ports-json", type=Path, required=True)
    ingress.add_argument("--release-directory", type=Path, required=True)
    ingress.add_argument("--compose-env", type=Path, required=True)
    class_zero = subparsers.add_parser("verify-class-zero")
    class_zero.add_argument("--report", type=Path, required=True)
    evidence = subparsers.add_parser("write-engine-evidence")
    evidence.add_argument("--output", type=Path, required=True)
    evidence.add_argument("--target-sha", required=True)
    evidence.add_argument("--database-revision-before", required=True)
    evidence.add_argument("--database-revision-after", required=True)
    evidence.add_argument("--postgres-metadata", type=Path, required=True)
    evidence.add_argument("--postgres-checksum", type=Path, required=True)
    evidence.add_argument("--minio-manifest", type=Path, required=True)
    evidence.add_argument("--observation-snapshots", type=int, required=True)
    evidence.add_argument("--critical-error-count", type=int, required=True)
    evidence.add_argument("--started-at", required=True)
    failure = subparsers.add_parser("write-engine-failure-evidence")
    failure.add_argument("--output", type=Path, required=True)
    failure.add_argument("--request-id", required=True)
    failure.add_argument("--target-sha", required=True)
    failure.add_argument("--stage", required=True)
    failure.add_argument("--exit-code", type=int, required=True)
    subparsers.add_parser("count-critical-log-lines")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")
    args = _parser().parse_args()
    try:
        if args.command == "compose-values":
            _compose_values(
                args.compose_json,
                args.compose_env,
                args.backend_env,
                args.migrator_env,
            )
        elif args.command == "write-validated-structure":
            _write_validated_structure(args.output, args.compose_env)
        elif args.command == "mount-values":
            _mount_values(
                args.compose_json, args.compose_env, args.release_directory
            )
        elif args.command == "verify-release":
            _verify_release(args.manifest, args.source_sha, args.release_directory)
        elif args.command == "verify-images":
            _verify_images(args.compose_json, args.manifest, args.candidate_env)
        elif args.command == "runtime-image-values":
            _runtime_image_values(args.manifest)
        elif args.command == "verify-ingress":
            _verify_ingress(
                args.compose_json,
                args.current_ports_json,
                args.release_directory,
                args.compose_env,
            )
        elif args.command == "verify-class-zero":
            _verify_class_zero(args.report)
        elif args.command == "count-critical-log-lines":
            _count_critical_log_lines()
        elif args.command == "write-engine-failure-evidence":
            _write_engine_failure_evidence(
                args.output,
                args.request_id,
                args.target_sha,
                args.stage,
                args.exit_code,
            )
        else:
            _write_engine_evidence(
                args.output,
                args.target_sha,
                args.database_revision_before,
                args.database_revision_after,
                args.postgres_metadata,
                args.postgres_checksum,
                args.minio_manifest,
                args.observation_snapshots,
                args.critical_error_count,
                args.started_at,
            )
    except ContractError as error:
        print(f"Production activation contract failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
