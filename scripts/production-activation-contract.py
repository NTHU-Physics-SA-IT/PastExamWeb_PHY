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
IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}$")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
SAFE_CONTAINER = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_BUCKET = re.compile(r"^[A-Za-z0-9._-]+$")
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


class ContractError(ValueError):
    """A production activation input is incomplete or inconsistent."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"Cannot read validated JSON input: {path.name}") from error


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


def _verify_backend_storage_credentials(environment: dict[str, Any]) -> None:
    for key in ("MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"):
        _required_string(environment, key, f"backend {key}")
    forbidden = [
        key for key in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD") if key in environment
    ]
    if forbidden:
        raise ContractError(
            "Rendered backend environment retains the legacy MinIO root-named contract."
        )


def _verify_proxy_trust(compose: dict[str, Any]) -> None:
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
    if not isinstance(networks, dict):
        raise ContractError("Rendered client-IP proxy trust networks are incomplete.")
    app_network = networks.get(APP_NETWORK)
    trusted_network = networks.get(TRUSTED_PROXY_NETWORK)
    if not isinstance(app_network, dict) or not isinstance(trusted_network, dict):
        raise ContractError("Rendered client-IP proxy trust networks are incomplete.")
    if app_network.get("ipam") not in (None, {}):
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

    trusted_peer = _required_string(
        backend_environment,
        "FORWARDED_ALLOW_IPS",
        "Uvicorn trusted proxy address",
    )
    nginx_address = _required_string(
        nginx_trusted_attachment,
        "ipv4_address",
        "stable nginx trusted-proxy address",
    )

    try:
        trusted_address = ipaddress.ip_address(trusted_peer)
        assigned_address = ipaddress.ip_address(nginx_address)
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
    volumes = compose.get("volumes", {})
    if not isinstance(volumes, dict) or any(
        not isinstance(definition, dict)
        or definition.get("driver_opts") not in (None, {})
        for definition in volumes.values()
    ):
        raise ContractError(
            "Rendered Compose volume definitions can escape Docker storage."
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
    ):
        raise ContractError("Rendered MinIO command is not the reviewed fixed command.")


def _compose_values(compose_path: Path) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Rendered Compose root must be an object.")

    _verify_no_privilege_expansion(compose)
    _verify_proxy_trust(compose)

    database = _service(compose, "db")
    minio = _service(compose, "minio")
    redis = _service(compose, "redis")
    backend = _service(compose, "backend")
    nginx = _service(compose, "nginx")
    database_environment = database.get("environment")
    backend_environment = backend.get("environment")
    if not isinstance(database_environment, dict) or not isinstance(
        backend_environment, dict
    ):
        raise ContractError("Rendered Compose environments are incomplete.")
    _verify_backend_storage_credentials(backend_environment)

    values_and_patterns = (
        (
            _required_string(database, "container_name", "database container identity"),
            SAFE_CONTAINER,
        ),
        (
            _required_string(database_environment, "POSTGRES_DB", "database name"),
            SAFE_IDENTIFIER,
        ),
        (
            _required_string(database_environment, "POSTGRES_USER", "database role"),
            SAFE_IDENTIFIER,
        ),
        (
            _required_string(minio, "container_name", "MinIO container identity"),
            SAFE_CONTAINER,
        ),
        (
            _required_string(backend_environment, "MINIO_BUCKET_NAME", "MinIO bucket"),
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
            raise ContractError("Rendered Compose contains an unsafe contract value.")
        print(value)


def _bind_mount_source(service: dict[str, Any], target: str, label: str) -> Path:
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
    if (
        mount.get("type") != "bind"
        or mount.get("read_only") is not True
        or not isinstance(source, str)
        or not source
        or any(character in source for character in "\r\n")
    ):
        raise ContractError(f"Rendered nginx {label} mount is not a read-only bind.")
    path = Path(source)
    if not path.is_absolute():
        raise ContractError(f"Rendered nginx {label} source is not absolute.")
    return path


def _nginx_mount_sources(compose: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    nginx = _service(compose, "nginx")
    return (
        _bind_mount_source(nginx, NGINX_CONFIG_TARGET, "configuration"),
        _bind_mount_source(nginx, NGINX_LISTENER_TARGET, "listener configuration"),
        _bind_mount_source(nginx, TLS_CERTIFICATE_TARGET, "TLS certificate"),
        _bind_mount_source(nginx, TLS_KEY_TARGET, "TLS private key"),
    )


def _mount_values(compose_path: Path) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Rendered Compose root must be an object.")
    for source in _nginx_mount_sources(compose):
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


def _verify_images(compose_path: Path, manifest: Path) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Rendered Compose root must be an object.")
    expected_frontend = _manifest_value(manifest, "frontend_image")
    expected_backend = _manifest_value(manifest, "backend_image")
    expected_nginx = _optional_manifest_value(manifest, "nginx_image") or (
        "nginx:1.29.2@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903"
    )
    expected = {
        "frontend": expected_frontend,
        "backend": expected_backend,
        "migrate": expected_backend,
        "nginx": expected_nginx,
    }
    mismatches = [
        name
        for name, expected_image in expected.items()
        if _required_string(_service(compose, name), "image", f"{name} image")
        != expected_image
    ]
    if mismatches:
        raise ContractError(
            "Rendered Compose images disagree with the immutable release manifest: "
            + ", ".join(mismatches)
        )


def _runtime_image_values(compose_path: Path) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Rendered Compose root must be an object.")
    for service, container in (
        ("nginx", "pastexam-nginx"),
        ("backend", "pastexam-backend"),
        ("frontend", "pastexam-frontend"),
    ):
        image = _required_string(
            _service(compose, service), "image", f"{service} image"
        )
        if IMAGE_PATTERN.fullmatch(image) is None:
            raise ContractError(f"{service} runtime image is not digest-pinned.")
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
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.partial-", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


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
    compose_path: Path, current_ports_path: Path, release_directory: Path
) -> None:
    compose = _load_json(compose_path)
    current_ports = _load_json(current_ports_path)
    if not isinstance(compose, dict):
        raise ContractError("Rendered Compose root must be an object.")
    targets = _target_bindings(compose)
    current = _current_bindings(current_ports)
    nginx_config, listener_config, _, _ = _nginx_mount_sources(compose)

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

    mounts = subparsers.add_parser("mount-values")
    mounts.add_argument("--compose-json", type=Path, required=True)

    release = subparsers.add_parser("verify-release")
    release.add_argument("--manifest", type=Path, required=True)
    release.add_argument("--source-sha", type=Path, required=True)
    release.add_argument("--release-directory", type=Path, required=True)

    images = subparsers.add_parser("verify-images")
    images.add_argument("--compose-json", type=Path, required=True)
    images.add_argument("--manifest", type=Path, required=True)

    runtime_images = subparsers.add_parser("runtime-image-values")
    runtime_images.add_argument("--compose-json", type=Path, required=True)

    ingress = subparsers.add_parser("verify-ingress")
    ingress.add_argument("--compose-json", type=Path, required=True)
    ingress.add_argument("--current-ports-json", type=Path, required=True)
    ingress.add_argument("--release-directory", type=Path, required=True)
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
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")
    args = _parser().parse_args()
    try:
        if args.command == "compose-values":
            _compose_values(args.compose_json)
        elif args.command == "mount-values":
            _mount_values(args.compose_json)
        elif args.command == "verify-release":
            _verify_release(args.manifest, args.source_sha, args.release_directory)
        elif args.command == "verify-images":
            _verify_images(args.compose_json, args.manifest)
        elif args.command == "runtime-image-values":
            _runtime_image_values(args.compose_json)
        elif args.command == "verify-ingress":
            _verify_ingress(
                args.compose_json, args.current_ports_json, args.release_directory
            )
        elif args.command == "verify-class-zero":
            _verify_class_zero(args.report)
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
