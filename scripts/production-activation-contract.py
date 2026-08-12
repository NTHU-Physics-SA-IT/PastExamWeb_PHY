#!/usr/bin/env python3
"""Validate immutable release and production activation contracts."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys
from typing import Any


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
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


def _compose_values(compose_path: Path) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Rendered Compose root must be an object.")

    database = _service(compose, "db")
    minio = _service(compose, "minio")
    backend = _service(compose, "backend")
    nginx = _service(compose, "nginx")
    database_environment = database.get("environment")
    backend_environment = backend.get("environment")
    if not isinstance(database_environment, dict) or not isinstance(
        backend_environment, dict
    ):
        raise ContractError("Rendered Compose environments are incomplete.")

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


def _verify_images(compose_path: Path, manifest: Path) -> None:
    compose = _load_json(compose_path)
    if not isinstance(compose, dict):
        raise ContractError("Rendered Compose root must be an object.")
    expected_frontend = _manifest_value(manifest, "frontend_image")
    expected_backend = _manifest_value(manifest, "backend_image")
    expected = {
        "frontend": expected_frontend,
        "backend": expected_backend,
        "migrate": expected_backend,
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

    ingress = subparsers.add_parser("verify-ingress")
    ingress.add_argument("--compose-json", type=Path, required=True)
    ingress.add_argument("--current-ports-json", type=Path, required=True)
    ingress.add_argument("--release-directory", type=Path, required=True)
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
        else:
            _verify_ingress(
                args.compose_json, args.current_ports_json, args.release_directory
            )
    except ContractError as error:
        print(f"Production activation contract failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
