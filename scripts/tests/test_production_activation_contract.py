from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACTIVATION_SCRIPT = REPOSITORY_ROOT / "scripts" / "activate-production-release.sh"
BACKUP_SCRIPT = REPOSITORY_ROOT / "scripts" / "postgres-logical-backup.sh"
CONTRACT_HELPER = REPOSITORY_ROOT / "scripts" / "production-activation-contract.py"
STORAGE_PREFLIGHT = REPOSITORY_ROOT / "scripts" / "minio-storage-preflight.sh"
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
RELEASE_SHA = "19782580b710924d8ccdb939600be72ecd44d303"
FRONTEND_IMAGE = f"ghcr.io/example/pastexam:frontend-{RELEASE_SHA}@sha256:{'1' * 64}"
BACKEND_IMAGE = f"ghcr.io/example/pastexam:backend-{RELEASE_SHA}@sha256:{'2' * 64}"
NGINX_IMAGE = "nginx:1.29.2@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903"
SECRET_SENTINEL = "THIS_MUST_NEVER_APPEAR_IN_DEPLOYMENT_EVIDENCE_DSMD_2026"
FRONTEND_IMAGE_EXPRESSION = (
    "${FRONTEND_IMAGE:-ghcr.io/nthu-physics-sa-it/pastexam:frontend}"
)
BACKEND_IMAGE_EXPRESSION = (
    "${BACKEND_IMAGE:-ghcr.io/nthu-physics-sa-it/pastexam:backend}"
)
PROXY_IP_EXPRESSION = "${PRODUCTION_NGINX_PROXY_IP:?Set PRODUCTION_NGINX_PROXY_IP}"
COMPOSE_CONFIG_HELP = (
    "Usage: docker compose config [OPTIONS]\n"
    "      --format string\n"
    "      --no-env-resolution\n"
    "      --no-interpolate\n"
    "      --no-path-resolution\n"
    f"unrelated-help-text={SECRET_SENTINEL}\n"
)


def _load_contract():
    spec = importlib.util.spec_from_file_location(
        "production_activation_contract", CONTRACT_HELPER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def contract():
    return _load_contract()


def _bash() -> Path:
    if os.name == "nt":
        path = Path(os.environ["ProgramFiles"]) / "Git" / "bin" / "bash.exe"
        assert path.is_file()
        return path
    return Path("/bin/bash")


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    resolved = path.resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if resolved.is_relative_to(temporary_root):
        relative = resolved.relative_to(temporary_root).as_posix()
        return f"/tmp/{relative}"
    drive = resolved.drive.rstrip(":").lower()
    remainder = resolved.as_posix()[2:]
    return f"/{drive}{remainder}"


def _path_with(directory: Path) -> str:
    if os.name != "nt":
        return f"{directory}{os.pathsep}{os.environ['PATH']}"
    process = subprocess.run(
        [str(_bash()), "-lc", 'printf "%s" "$PATH"'],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return f"{_bash_path(directory)}:{process.stdout}"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)


def _structural_bind(source: str, target: str) -> dict[str, object]:
    binding: dict[str, object] = {
        "type": "bind",
        "source": source,
        "target": target,
        "read_only": True,
    }
    if not source.startswith("${"):
        binding["bind"] = {"create_host_path": True}
    return binding


def _compose_contract(
    release: Path,
    certificate: Path,
    certificate_key: Path,
    *,
    ports: list[tuple[int, int]] | None = None,
    nginx_config: Path | None = None,
    listener_config: Path | None = None,
    include_certificate_mounts: bool = True,
) -> dict:
    nginx_volumes = [
        _structural_bind(
            str(nginx_config) if nginx_config else "../proxy/nginx.conf",
            "/etc/nginx/nginx.conf",
        ),
        _structural_bind(
            str(listener_config)
            if listener_config
            else "../proxy/nginx.production-listeners.conf",
            "/etc/nginx/pastexam-listeners.conf",
        ),
    ]
    if include_certificate_mounts:
        nginx_volumes.extend(
            [
                _structural_bind(
                    "${PRODUCTION_TLS_CERT_FILE:?Set PRODUCTION_TLS_CERT_FILE}",
                    "/etc/nginx/certs/origin.pem",
                ),
                _structural_bind(
                    "${PRODUCTION_TLS_KEY_FILE:?Set PRODUCTION_TLS_KEY_FILE}",
                    "/etc/nginx/certs/origin-key.pem",
                ),
            ]
        )
    return {
        "name": "pastexam",
        "services": {
            "backend": {
                "image": BACKEND_IMAGE_EXPRESSION,
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
                "env_file": [
                    {
                        "path": "${PRODUCTION_BACKEND_ENV_FILE:-/opt/pastexam-config/backend.env}",
                        "required": True,
                    }
                ],
                "environment": {"FORWARDED_ALLOW_IPS": PROXY_IP_EXPRESSION},
                "networks": {
                    "app_network": {"aliases": ["backend"]},
                    "trusted_proxy_network": {"aliases": ["backend-trusted"]},
                },
            },
            "frontend": {
                "image": FRONTEND_IMAGE_EXPRESSION,
                "container_name": "pastexam-frontend",
                "restart": "always",
                "networks": {"app_network": {"aliases": ["frontend"]}},
            },
            "migrate": {
                "image": BACKEND_IMAGE_EXPRESSION,
                "restart": "no",
                "command": ["python", "migrate.py", "upgrade"],
                "depends_on": {
                    "db": {"condition": "service_healthy", "required": True}
                },
                "env_file": [
                    {
                        "path": "${PRODUCTION_MIGRATOR_ENV_FILE:-/opt/pastexam-config/migrator.env}",
                        "required": True,
                    }
                ],
                "networks": {"app_network": {}},
            },
            "db": {
                "image": "postgres:15.14-alpine3.22",
                "container_name": "pastexam-postgres",
                "restart": "always",
                "environment": {
                    "POSTGRES_DB": "${POSTGRES_DB}",
                    "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD}",
                    "POSTGRES_USER": "${POSTGRES_USER}",
                },
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}",
                    ],
                    "interval": "5s",
                    "timeout": "5s",
                    "retries": 5,
                },
                "volumes": [
                    {
                        "type": "volume",
                        "source": "pg_data",
                        "target": "/var/lib/postgresql/data",
                        "volume": {},
                    }
                ],
                "networks": {"app_network": {}},
            },
            "minio": {
                "image": "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z",
                "container_name": "pastexam-minio",
                "restart": "always",
                "command": ["server", "/data", "--console-address", ":9001"],
                "environment": [
                    "MINIO_ROOT_USER=${MINIO_ROOT_USER}",
                    "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}",
                ],
                "healthcheck": {
                    "test": ["CMD", "mc", "ready", "local"],
                    "interval": "5s",
                    "timeout": "5s",
                    "retries": 5,
                },
                "volumes": [
                    {
                        "type": "volume",
                        "source": "minio_data",
                        "target": "/data",
                        "volume": {},
                    }
                ],
                "networks": {"app_network": {"aliases": ["minio"]}},
            },
            "redis": {
                "image": "redis:7.4.5-alpine3.21",
                "container_name": "pastexam-redis",
                "restart": "always",
                "volumes": [
                    {
                        "type": "volume",
                        "source": "redis_data",
                        "target": "/data",
                        "volume": {},
                    }
                ],
                "networks": {"app_network": {}},
            },
            "nginx": {
                "image": NGINX_IMAGE,
                "container_name": "pastexam-nginx",
                "restart": "always",
                "expose": ["8080", "8443"],
                "depends_on": {
                    "backend": {"condition": "service_started", "required": True},
                    "frontend": {"condition": "service_started", "required": True},
                    "minio": {"condition": "service_started", "required": True},
                },
                "networks": {
                    "app_network": {},
                    "trusted_proxy_network": {
                        "ipv4_address": PROXY_IP_EXPRESSION
                    },
                },
                "ports": [
                    {
                        "published": str(published),
                        "protocol": "tcp",
                        "target": target,
                    }
                    for published, target in (
                        ports or [(80, 8080), (8080, 8080), (443, 8443)]
                    )
                ],
                "volumes": nginx_volumes,
            },
        },
        "networks": {
            "app_network": {
                "name": "pastexam-network",
                "driver": "bridge",
            },
            "trusted_proxy_network": {
                "name": "pastexam-trusted-proxy-network",
                "driver": "bridge",
                "ipam": {
                    "driver": "default",
                    "config": [
                        {
                            "subnet": "172.30.0.0/28",
                            "ip_range": "172.30.0.8/29",
                            "gateway": "172.30.0.1",
                        }
                    ],
                },
            },
        },
        "volumes": {
            "pg_data": {"name": "pastexam-postgres-data"},
            "minio_data": {"name": "pastexam-minio-data"},
            "redis_data": {"name": "pastexam-redis-data"},
        },
    }


def _activation_environment(
    tmp_path: Path,
    *,
    compose_contract: dict | None = None,
    current_ports: dict | None = None,
    postgres_exit: int = 0,
    storage_preflight_exit: int = 0,
    compose_quiet_exit: int = 0,
    source_sha: str = RELEASE_SHA,
    edge_mode: str = "600",
    config_owner: str = "0",
    tls_mode: str = "600",
    tls_owner: str = "0",
    migration_revision: str = "9f1c2a7e4b63",
    repository_head: str = "9f1c2a7e4b63",
) -> tuple[dict[str, str], Path, Path]:
    release = tmp_path / RELEASE_SHA
    scripts = release / "scripts"
    host_helpers = tmp_path / "host-helpers"
    proxy = release / "proxy"
    docker_dir = release / "docker"
    scripts.mkdir(parents=True)
    host_helpers.mkdir()
    proxy.mkdir()
    docker_dir.mkdir()

    certificate = tmp_path / "origin.pem"
    certificate_key = tmp_path / "origin-key.pem"
    certificate.write_text("contract-test-certificate\n", encoding="utf-8")
    certificate_key.write_text("contract-test-private-key\n", encoding="utf-8")

    (release / ".release-source-sha").write_text(f"{source_sha}\n", encoding="utf-8")
    manifest = release / "release-manifest.env"
    manifest.write_text(
        f"release_sha={RELEASE_SHA}\n"
        f"frontend_image={FRONTEND_IMAGE}\n"
        f"backend_image={BACKEND_IMAGE}\n"
        f"nginx_image={NGINX_IMAGE}\n"
        "nginx_image_digest=sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903\n",
        encoding="utf-8",
    )
    (release / "compose.prod.env").write_text(
        f"FRONTEND_IMAGE={FRONTEND_IMAGE}\nBACKEND_IMAGE={BACKEND_IMAGE}\n",
        encoding="utf-8",
    )
    (docker_dir / "docker-compose.prod.yml").write_text(
        "services:\n  nginx:\n    image: nginx:contract-test\n",
        encoding="utf-8",
    )
    (proxy / "nginx.conf").write_text(
        "events {}\nhttp { server { include /etc/nginx/pastexam-listeners.conf; } }\n",
        encoding="utf-8",
    )
    (proxy / "nginx.production-listeners.conf").write_text(
        "listen 8080;\n"
        "listen 8443 ssl;\n"
        "ssl_certificate /etc/nginx/certs/origin.pem;\n"
        "ssl_certificate_key /etc/nginx/certs/origin-key.pem;\n",
        encoding="utf-8",
    )
    if CONTRACT_HELPER.exists():
        shutil.copy2(CONTRACT_HELPER, host_helpers / CONTRACT_HELPER.name)
        (host_helpers / CONTRACT_HELPER.name).chmod(0o755)
    nginx_override = host_helpers / "pastexam-nginx-image-override.yml"
    nginx_override.write_text(
        "services:\n  nginx:\n    image: nginx:1.29.2@sha256:" + "0" * 64 + "\n",
        encoding="utf-8",
    )

    backup_log = tmp_path / "backup-contract.log"
    postgres_metadata = tmp_path / "postgres-backup-metadata.json"
    postgres_checksum = tmp_path / "postgres-backup-metadata.sha256"
    minio_manifest = tmp_path / "minio-readonly-manifest.json"
    postgres_metadata.write_text("{}\n", encoding="utf-8")
    postgres_checksum.write_text("0" * 64 + "\n", encoding="utf-8")
    minio_manifest.write_text("{}\n", encoding="utf-8")
    _write_executable(
        host_helpers / "postgres-logical-backup.sh",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"printf 'postgres:%s:%s:%s:%s\\n' \"$BACKUP_DIRECTORY\" "
        f'"$DATABASE_CONTAINER" "$DATABASE_NAME" "$DATABASE_USER" '
        f">>'{_bash_path(backup_log)}'\n"
        f"printf 'Metadata: %s\n' '{_bash_path(postgres_metadata)}'\n"
        f"printf 'Checksum: %s\n' '{_bash_path(postgres_checksum)}'\n"
        f"exit {postgres_exit}\n",
    )
    _write_executable(
        host_helpers / "minio-readonly-manifest.sh",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"printf 'minio:%s:%s:%s\\n' \"$BACKUP_DIRECTORY\" "
        f'"$MINIO_CONTAINER" "$MINIO_BUCKET_NAME" '
        f">>'{_bash_path(backup_log)}'\n"
        f"printf 'Read-only MinIO manifest: %s\n' '{_bash_path(minio_manifest)}'\n",
    )
    _write_executable(
        host_helpers / STORAGE_PREFLIGHT.name,
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"printf 'preflight:%s:%s\n' \"$MINIO_CONTAINER\" "
        f"\"$MINIO_BUCKET_NAME\" >>'{_bash_path(backup_log)}'\n"
        f"exit {storage_preflight_exit}\n",
    )

    resolved_compose = compose_contract or _compose_contract(
        release, certificate, certificate_key
    )
    compose_json = tmp_path / "compose.json"
    compose_json.write_text(
        json.dumps(resolved_compose),
        encoding="utf-8",
    )
    ports_json = tmp_path / "current-ports.json"
    ports_json.write_text(
        json.dumps(
            current_ports
            or {
                "8080/tcp": [
                    {"HostIp": "0.0.0.0", "HostPort": "80"},
                    {"HostIp": "0.0.0.0", "HostPort": "8080"},
                ],
                "8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "443"}],
            }
        ),
        encoding="utf-8",
    )
    migration_report = tmp_path / "migration-report.json"
    migration_report.write_text(
        json.dumps(
            {
                "database_connected": True,
                "current_revision": migration_revision,
                "current_revision_known": True,
                "repository_heads": [repository_head],
                "multiple_heads": False,
                "schema_matches_head": True,
                "upgrade_allowed": True,
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    docker_log = tmp_path / "docker.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'printf \'%s\\n\' "$*" >>"$FAKE_DOCKER_LOG"\n'
        "if [[ \"$1\" == 'compose' && \"$*\" == 'compose config --help' ]]; then\n"
        "  printf '%s' \"$FAKE_COMPOSE_HELP\"\n"
        "  printf '%s' \"$FAKE_COMPOSE_HELP_STDERR\" >&2\n"
        "  exit \"$FAKE_COMPOSE_HELP_EXIT\"\n"
        "elif [[ \"$1\" == 'compose' && \"$*\" == *'config '* && \"$*\" == *'--no-env-resolution'* && \"$*\" == *'--no-interpolate'* && \"$*\" == *'--no-path-resolution'* && \"$*\" == *'--format json'* ]]; then\n"
        '  cat "$FAKE_COMPOSE_JSON"\n'
        "elif [[ \"$1\" == 'compose' && \"$*\" == *'config --quiet'* ]]; then\n"
        "  printf '%s' \"$FAKE_COMPOSE_QUIET_STDERR\" >&2\n"
        "  exit \"$FAKE_COMPOSE_QUIET_EXIT\"\n"
        "elif [[ \"$1\" == 'compose' && \"$*\" == *'require-head --json'* ]]; then\n"
        '  cat "$FAKE_MIGRATION_REPORT"\n'
        "elif [[ \"$1\" == 'exec' && \"$*\" == *'redis-cli ping'* ]]; then\n"
        "  printf '%s\\n' \"$FAKE_REDIS_PING\"\n"
        "elif [[ \"$1\" == 'inspect' && \"$*\" == *'RestartCount'* ]]; then\n"
        "  printf '0\\n'\n"
        "elif [[ \"$1\" == 'inspect' && \"$*\" == *'Config.Image'* ]]; then\n"
        '  case "${@: -1}" in\n'
        "    pastexam-nginx) printf '%s\\n' \"$FAKE_NGINX_IMAGE\" ;;\n"
        "    pastexam-backend) printf '%s\\n' \"$FAKE_BACKEND_IMAGE\" ;;\n"
        "    pastexam-frontend) printf '%s\\n' \"$FAKE_FRONTEND_IMAGE\" ;;\n"
        "  esac\n"
        "elif [[ \"$1\" == 'inspect' && \"$*\" == *'State.Status'* ]]; then\n"
        "  printf '%s\\n' \"$FAKE_PERSISTENT_STATE\"\n"
        "elif [[ \"$1\" == 'logs' ]]; then\n"
        "  printf '%s' \"$FAKE_CRITICAL_LOG\"\n"
        "  printf '%s' \"$FAKE_CRITICAL_LOG_STDERR\" >&2\n"
        "  exit \"$FAKE_CRITICAL_LOG_EXIT\"\n"
        "elif [[ \"$1\" == 'inspect' ]]; then\n"
        '  cat "$FAKE_CURRENT_PORTS_JSON"\n'
        "fi\n",
    )
    _write_executable(fake_bin / "curl", "#!/usr/bin/env bash\nset -eu\nexit 0\n")
    _write_executable(
        fake_bin / "python3",
        "#!/usr/bin/env bash\n"
        f"exec '{_bash_path(Path(sys.executable))}' \"$@\"\n",
    )
    _write_executable(
        fake_bin / "stat",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'if [[ "$*" == *"%u"* ]]; then\n'
        "  printf '0\\n'\n"
        'elif [[ "${@: -1}" == "$FAKE_EDGE_FILE" ]]; then\n'
        "  printf '%s\\n' \"$FAKE_EDGE_MODE\"\n"
        "else\n"
        "  printf '600\\n'\n"
        "fi\n",
    )
    bash_env = tmp_path / "activation-bash-env"
    bash_env.write_text(
        "mktemp() {\n"
        '  mkdir -p "$FAKE_CONTRACT_DIRECTORY"\n'
        '  printf "%s\\n" "$FAKE_CONTRACT_DIRECTORY"\n'
        "}\n"
        "stat() {\n"
        '  if [[ "$*" == *"%u"* ]]; then\n'
        '    if [[ "${@: -1}" == *"origin"* ]]; then\n'
        "      printf '%s\\n' \"$FAKE_TLS_OWNER\"\n"
        "    else\n"
        "      printf '%s\\n' \"$FAKE_CONFIG_OWNER\"\n"
        "    fi\n"
        '  elif [[ "${@: -1}" == "$FAKE_EDGE_FILE" ]]; then\n'
        "    printf '%s\\n' \"$FAKE_EDGE_MODE\"\n"
        '  elif [[ "${@: -1}" == *"origin"* ]]; then\n'
        "    printf '%s\\n' \"$FAKE_TLS_MODE\"\n"
        "  else\n"
        "    printf '600\\n'\n"
        "  fi\n"
        "}\n"
        "docker() {\n"
        '  printf \'%s\\n\' "$*" >>"$FAKE_DOCKER_LOG"\n'
        "  if [[ \"$1\" == 'compose' && \"$*\" == 'compose config --help' ]]; then\n"
        "    printf '%s' \"$FAKE_COMPOSE_HELP\"\n"
        "    printf '%s' \"$FAKE_COMPOSE_HELP_STDERR\" >&2\n"
        "    return \"$FAKE_COMPOSE_HELP_EXIT\"\n"
        "  elif [[ \"$1\" == 'compose' && \"$*\" == *'config '* && \"$*\" == *'--no-env-resolution'* && \"$*\" == *'--no-interpolate'* && \"$*\" == *'--no-path-resolution'* && \"$*\" == *'--format json'* ]]; then\n"
        '    cat "$FAKE_COMPOSE_JSON"\n'
        "  elif [[ \"$1\" == 'compose' && \"$*\" == *'config --quiet'* ]]; then\n"
        "    printf '%s' \"$FAKE_COMPOSE_QUIET_STDERR\" >&2\n"
        "    return \"$FAKE_COMPOSE_QUIET_EXIT\"\n"
        "  elif [[ \"$1\" == 'compose' && \"$*\" == *'require-head --json'* ]]; then\n"
        '    cat "$FAKE_MIGRATION_REPORT"\n'
        "  elif [[ \"$1\" == 'exec' && \"$*\" == *'redis-cli ping'* ]]; then\n"
        "    printf '%s\\n' \"$FAKE_REDIS_PING\"\n"
        "  elif [[ \"$1\" == 'inspect' && \"$*\" == *'RestartCount'* ]]; then\n"
        "    printf '0\\n'\n"
        "  elif [[ \"$1\" == 'inspect' && \"$*\" == *'Config.Image'* ]]; then\n"
        '    case "${@: -1}" in\n'
        "      pastexam-nginx) printf '%s\\n' \"$FAKE_NGINX_IMAGE\" ;;\n"
        "      pastexam-backend) printf '%s\\n' \"$FAKE_BACKEND_IMAGE\" ;;\n"
        "      pastexam-frontend) printf '%s\\n' \"$FAKE_FRONTEND_IMAGE\" ;;\n"
        "    esac\n"
        "  elif [[ \"$1\" == 'inspect' && \"$*\" == *'State.Status'* ]]; then\n"
        "    printf '%s\\n' \"$FAKE_PERSISTENT_STATE\"\n"
        "  elif [[ \"$1\" == 'logs' ]]; then\n"
        "    printf '%s' \"$FAKE_CRITICAL_LOG\"\n"
        "    printf '%s' \"$FAKE_CRITICAL_LOG_STDERR\" >&2\n"
        "    return \"$FAKE_CRITICAL_LOG_EXIT\"\n"
        "  elif [[ \"$1\" == 'inspect' ]]; then\n"
        '    cat "$FAKE_CURRENT_PORTS_JSON"\n'
        "  fi\n"
        "}\n"
        "curl() { return 0; }\n"
        "flock() { return 0; }\n"
        "sleep() { return 0; }\n"
        "python3() {\n"
        "  if [[ \"$*\" == *'count-critical-log-lines'* && \"$FAKE_CRITICAL_PARSER_EXIT\" != '0' ]]; then\n"
        "    cat >/dev/null\n"
        "    return \"$FAKE_CRITICAL_PARSER_EXIT\"\n"
        "  fi\n"
        f"  '{_bash_path(Path(sys.executable))}' \"$@\"\n"
        "}\n",
        encoding="utf-8",
    )

    config_files = [
        tmp_path / name for name in ("compose.env", "backend.env", "migrator.env")
    ]
    edge_file = tmp_path / "edge.yml"
    config_files[0].write_text(
        "POSTGRES_USER=postgres_owner\n"
        f"POSTGRES_PASSWORD={SECRET_SENTINEL}\n"
        "POSTGRES_DB=archive_db\n"
        f"MINIO_ROOT_USER={SECRET_SENTINEL}\n"
        f"MINIO_ROOT_PASSWORD={SECRET_SENTINEL}\n"
        "PRODUCTION_NGINX_PROXY_IP=172.30.0.2\n"
        f"PRODUCTION_TLS_CERT_FILE={certificate.resolve()}\n"
        f"PRODUCTION_TLS_KEY_FILE={certificate_key.resolve()}\n",
        encoding="utf-8",
    )
    config_files[1].write_text(
        "DB_HOST=db\n"
        "DB_PORT=5432\n"
        "DB_USER=runtime\n"
        f"DB_PASSWORD={SECRET_SENTINEL}\n"
        "DB_NAME=archive_db\n"
        f"MINIO_ACCESS_KEY={SECRET_SENTINEL}\n"
        f"MINIO_SECRET_KEY={SECRET_SENTINEL}\n"
        "MINIO_BUCKET_NAME=exam-archive\n",
        encoding="utf-8",
    )
    config_files[2].write_text(
        "DB_HOST=db\n"
        "DB_PORT=5432\n"
        "DB_USER=migrator\n"
        f"DB_PASSWORD={SECRET_SENTINEL}\n"
        "DB_NAME=archive_db\n",
        encoding="utf-8",
    )
    edge_file.write_text("contract-test=true\n", encoding="utf-8")

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": _path_with(fake_bin),
            "BASH_ENV": _bash_path(bash_env),
            "PRODUCTION_DEPLOY_ENABLED": "true",
            "ACTIVATION_CONFIRMATION": "activate-reviewed-production-release",
            "RELEASE_DIRECTORY": _bash_path(release),
            "RELEASE_MANIFEST": _bash_path(manifest),
            "RELEASE_MANIFEST_SHA256": hashlib.sha256(
                manifest.read_bytes()
            ).hexdigest(),
            "PRODUCTION_COMPOSE_ENV_FILE": _bash_path(config_files[0]),
            "PRODUCTION_BACKEND_ENV_FILE": _bash_path(config_files[1]),
            "PRODUCTION_MIGRATOR_ENV_FILE": _bash_path(config_files[2]),
            "PRODUCTION_EDGE_COMPOSE_FILE": _bash_path(edge_file),
            "PRODUCTION_BACKUP_DIRECTORY": _bash_path(tmp_path / "backups"),
            "PRODUCTION_LOCK_FILE": _bash_path(tmp_path / "activation.lock"),
            "EXTERNAL_HEALTH_URL": "https://example.invalid/api/health",
            "HEALTH_CHECK_ATTEMPTS": "3",
            "HEALTH_CHECK_INITIAL_DELAY_SECONDS": "0",
            "HEALTH_CHECK_MAX_DELAY_SECONDS": "0",
            "OBSERVATION_SNAPSHOTS": "1",
            "OBSERVATION_INTERVAL_SECONDS": "0",
            "ACTIVATION_CONTRACT_HELPER": _bash_path(
                host_helpers / CONTRACT_HELPER.name
            ),
            "POSTGRES_BACKUP_HELPER": _bash_path(
                host_helpers / "postgres-logical-backup.sh"
            ),
            "MINIO_PREFLIGHT_HELPER": _bash_path(host_helpers / STORAGE_PREFLIGHT.name),
            "MINIO_MANIFEST_HELPER": _bash_path(
                host_helpers / "minio-readonly-manifest.sh"
            ),
            "NGINX_IMAGE_OVERRIDE": _bash_path(nginx_override),
            "FAKE_COMPOSE_JSON": _bash_path(compose_json),
            "FAKE_CURRENT_PORTS_JSON": _bash_path(ports_json),
            "FAKE_MIGRATION_REPORT": _bash_path(migration_report),
            "FAKE_DOCKER_LOG": _bash_path(docker_log),
            "FAKE_NGINX_IMAGE": NGINX_IMAGE,
            "FAKE_BACKEND_IMAGE": BACKEND_IMAGE,
            "FAKE_FRONTEND_IMAGE": FRONTEND_IMAGE,
            "FAKE_CRITICAL_LOG": "",
            "FAKE_CRITICAL_LOG_STDERR": "",
            "FAKE_CRITICAL_LOG_EXIT": "0",
            "FAKE_CRITICAL_PARSER_EXIT": "0",
            "FAKE_PERSISTENT_STATE": "running:healthy",
            "FAKE_REDIS_PING": "PONG",
            "FAKE_COMPOSE_QUIET_EXIT": str(compose_quiet_exit),
            "FAKE_COMPOSE_QUIET_STDERR": "",
            "FAKE_COMPOSE_HELP": COMPOSE_CONFIG_HELP,
            "FAKE_COMPOSE_HELP_STDERR": "",
            "FAKE_COMPOSE_HELP_EXIT": "0",
            "FAKE_EDGE_FILE": _bash_path(edge_file),
            "FAKE_EDGE_MODE": edge_mode,
            "FAKE_CONFIG_OWNER": config_owner,
            "FAKE_TLS_MODE": tls_mode,
            "FAKE_TLS_OWNER": tls_owner,
            "FAKE_CONTRACT_DIRECTORY": _bash_path(
                tmp_path / "activation-contract"
            ),
        }
    )
    for inherited in (
        "BACKUP_DIRECTORY",
        "DATABASE_CONTAINER",
        "DATABASE_NAME",
        "DATABASE_USER",
        "MINIO_CONTAINER",
        "MINIO_BUCKET_NAME",
        "REDIS_CONTAINER",
    ):
        environment.pop(inherited, None)
    return environment, backup_log, docker_log


def _set_health_failures(
    tmp_path: Path, environment: dict[str, str], failures: int
) -> Path:
    health_log = tmp_path / "health.log"
    health_state = tmp_path / "health-state"
    health_state.write_text("0\n", encoding="utf-8")
    bash_env = tmp_path / "activation-bash-env"
    with bash_env.open("a", encoding="utf-8") as stream:
        stream.write(
            "curl() {\n"
            '  count="$(cat "$FAKE_HEALTH_STATE")"\n'
            '  printf "%s\\n" "$*" >>"$FAKE_HEALTH_LOG"\n'
            '  printf "%s\\n" "$((count + 1))" >"$FAKE_HEALTH_STATE"\n'
            '  [ "$count" -ge "$FAKE_HEALTH_FAILURES" ]\n'
            "}\n"
        )
    environment.update(
        {
            "FAKE_HEALTH_FAILURES": str(failures),
            "FAKE_HEALTH_LOG": _bash_path(health_log),
            "FAKE_HEALTH_STATE": _bash_path(health_state),
        }
    )
    return health_log


def _activate(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_bash()), str(ACTIVATION_SCRIPT)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )


def _enable_failure_evidence(
    tmp_path: Path, environment: dict[str, str]
) -> Path:
    evidence = tmp_path / "activation-engine-failure.json"
    environment.update(
        {
            "ACTIVATION_FAILURE_EVIDENCE_PATH": _bash_path(evidence),
            "ACTIVATION_REQUEST_ID": "activation-100-1",
            "ACTIVATION_TARGET_SHA": RELEASE_SHA,
        }
    )
    return evidence


def _assert_failure_evidence(
    evidence: Path, *, stage: str, exit_code: int
) -> dict[str, object]:
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "request_id": "activation-100-1",
        "target_sha": RELEASE_SHA,
        "stage": stage,
        "exit_code": exit_code,
        "observed_at": payload["observed_at"],
    }
    assert payload["observed_at"].endswith("Z")
    if os.name != "nt":
        assert stat.S_IMODE(evidence.stat().st_mode) == 0o600
    assert not list(evidence.parent.glob(f".{evidence.name}.partial-*"))
    return payload


def test_common_preflight_failure_writes_only_sanitized_stage_evidence(
    tmp_path: Path,
) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    environment["FAKE_PERSISTENT_STATE"] = "exited:none"
    evidence = _enable_failure_evidence(tmp_path, environment)

    process = _activate(environment)

    assert process.returncode == 2
    _assert_failure_evidence(evidence, stage="persistent-services", exit_code=2)


def test_postgres_backup_failure_records_first_actual_only_stage(
    tmp_path: Path,
) -> None:
    environment, _, docker_log = _activation_environment(tmp_path, postgres_exit=9)
    evidence = _enable_failure_evidence(tmp_path, environment)

    process = _activate(environment)

    assert process.returncode == 9
    _assert_failure_evidence(evidence, stage="postgres-backup", exit_code=9)
    assert " up -d " not in docker_log.read_text(encoding="utf-8")


def test_minio_manifest_failure_records_later_precutover_stage(
    tmp_path: Path,
) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)
    _write_executable(
        tmp_path / "host-helpers" / "minio-readonly-manifest.sh",
        "#!/usr/bin/env bash\nexit 8\n",
    )
    evidence = _enable_failure_evidence(tmp_path, environment)

    process = _activate(environment)

    assert process.returncode == 8
    _assert_failure_evidence(evidence, stage="minio-manifest", exit_code=8)
    assert " up -d " not in docker_log.read_text(encoding="utf-8")


def test_health_failure_records_post_cutover_stage_without_success_evidence(
    tmp_path: Path,
) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)
    _set_health_failures(tmp_path, environment, failures=3)
    evidence = _enable_failure_evidence(tmp_path, environment)
    engine_evidence = tmp_path / "engine-evidence.json"
    environment["ACTIVATION_EVIDENCE_PATH"] = _bash_path(engine_evidence)

    process = _activate(environment)

    assert process.returncode == 1
    _assert_failure_evidence(evidence, stage="internal-health", exit_code=1)
    assert " up -d --no-deps backend frontend nginx" in docker_log.read_text(
        encoding="utf-8"
    )
    assert not engine_evidence.exists()
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()


def test_raw_failure_stderr_is_not_written_to_sanitized_evidence(
    tmp_path: Path,
) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    _write_executable(
        tmp_path / "host-helpers" / STORAGE_PREFLIGHT.name,
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{SECRET_SENTINEL}' >&2\n"
        "exit 7\n",
    )
    evidence = _enable_failure_evidence(tmp_path, environment)

    process = _activate(environment)

    assert process.returncode == 7
    payload = _assert_failure_evidence(
        evidence, stage="minio-preflight", exit_code=7
    )
    assert SECRET_SENTINEL in process.stderr
    assert SECRET_SENTINEL not in json.dumps(payload)


def test_successful_activation_does_not_create_failure_evidence(
    tmp_path: Path,
) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    evidence = _enable_failure_evidence(tmp_path, environment)

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    assert not evidence.exists()


def test_failure_evidence_contract_rejects_unknown_stage(tmp_path: Path) -> None:
    evidence = tmp_path / "activation-engine-failure.json"

    process = subprocess.run(
        [
            sys.executable,
            str(CONTRACT_HELPER),
            "write-engine-failure-evidence",
            "--output",
            str(evidence),
            "--request-id",
            "activation-100-1",
            "--target-sha",
            RELEASE_SHA,
            "--stage",
            "candidate-controlled-stage",
            "--exit-code",
            "2",
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert process.returncode == 2
    assert "stage is unsupported" in process.stderr
    assert not evidence.exists()


def test_failure_evidence_write_fsyncs_file_replace_then_directory(
    contract, tmp_path: Path, monkeypatch
) -> None:
    evidence = tmp_path / "activation-engine-failure.json"
    events: list[tuple[str, object]] = []
    original_fsync = contract.os.fsync
    original_replace = contract.os.replace

    def tracked_fsync(descriptor: int) -> None:
        events.append(("file-fsync", descriptor))
        original_fsync(descriptor)

    def tracked_replace(source: Path, destination: Path) -> None:
        events.append(("replace", destination))
        original_replace(source, destination)

    monkeypatch.setattr(contract.os, "fsync", tracked_fsync)
    monkeypatch.setattr(contract.os, "replace", tracked_replace)
    monkeypatch.setattr(
        contract,
        "_fsync_directory",
        lambda path: events.append(("directory-fsync", path)),
        raising=False,
    )

    contract._write_engine_failure_evidence(
        evidence,
        "activation-100-1",
        RELEASE_SHA,
        "postgres-backup",
        17,
    )

    assert [event for event, _ in events] == [
        "file-fsync",
        "replace",
        "directory-fsync",
    ]
    assert events[1][1] == evidence
    assert events[2][1] == evidence.parent


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows cannot open a directory descriptor for fsync; Linux CI covers it.",
)
def test_directory_fsync_uses_supported_platform_descriptor(
    contract, tmp_path: Path, monkeypatch
) -> None:
    events: list[tuple[str, object]] = []
    directory_descriptor = 73

    def tracked_open(path: Path, flags: int) -> int:
        events.append(("open", (path, flags)))
        return directory_descriptor

    monkeypatch.setattr(contract.os, "open", tracked_open)
    monkeypatch.setattr(
        contract.os,
        "fsync",
        lambda descriptor: events.append(("fsync", descriptor)),
    )
    monkeypatch.setattr(
        contract.os,
        "close",
        lambda descriptor: events.append(("close", descriptor)),
    )

    contract._fsync_directory(tmp_path)

    assert events == [
        (
            "open",
            (
                tmp_path,
                contract.os.O_RDONLY | getattr(contract.os, "O_DIRECTORY", 0),
            ),
        ),
        ("fsync", directory_descriptor),
        ("close", directory_descriptor),
    ]


def test_candidate_helper_cannot_become_failure_evidence_authority(
    tmp_path: Path,
) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    invoked = tmp_path / "candidate-helper-invoked"
    candidate_helper = tmp_path / RELEASE_SHA / "candidate-helper"
    _write_executable(
        candidate_helper,
        "#!/usr/bin/env bash\n"
        f"touch '{_bash_path(invoked)}'\n"
        "exit 2\n",
    )
    environment["ACTIVATION_CONTRACT_HELPER"] = _bash_path(candidate_helper)
    evidence = _enable_failure_evidence(tmp_path, environment)

    process = _activate(environment)

    assert process.returncode == 2
    assert "cannot be privileged activation authority" in process.stderr.lower()
    assert not invoked.exists()
    assert not evidence.exists()


def test_activation_supplies_all_backup_contract_inputs(tmp_path: Path) -> None:
    environment, backup_log, _ = _activation_environment(tmp_path)
    environment.update(
        {
            "DATABASE_CONTAINER": "inherited-wrong-database",
            "DATABASE_NAME": "inherited_wrong_database",
            "DATABASE_USER": "inherited_wrong_role",
            "MINIO_CONTAINER": "inherited-wrong-minio",
            "MINIO_BUCKET_NAME": "inherited-wrong-bucket",
        }
    )

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    lines = backup_log.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "preflight:pastexam-minio:exam-archive",
        (
            "postgres:"
            f"{environment['PRODUCTION_BACKUP_DIRECTORY']}:"
            "pastexam-postgres:archive_db:postgres_owner"
        ),
        (
            "minio:"
            f"{environment['PRODUCTION_BACKUP_DIRECTORY']}:"
            "pastexam-minio:exam-archive"
        ),
        "preflight:pastexam-minio:exam-archive",
    ]


@pytest.mark.parametrize("legacy_name", ["MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"])
def test_activation_rejects_legacy_backend_minio_contract(
    tmp_path: Path, legacy_name: str
) -> None:
    environment, backup_log, _ = _activation_environment(tmp_path)
    backend_environment = tmp_path / "backend.env"
    with backend_environment.open("a", encoding="utf-8") as stream:
        stream.write(f"{legacy_name}=forbidden\n")

    process = _activate(environment)

    assert process.returncode != 0
    assert "root-named contract" in process.stderr
    assert not backup_log.exists()


@pytest.mark.parametrize("required_name", ["MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"])
def test_activation_requires_scoped_backend_minio_contract(
    tmp_path: Path, required_name: str
) -> None:
    environment, backup_log, _ = _activation_environment(tmp_path)
    backend_environment = tmp_path / "backend.env"
    lines = backend_environment.read_text(encoding="utf-8").splitlines()
    backend_environment.write_text(
        "\n".join(line for line in lines if not line.startswith(f"{required_name}="))
        + "\n",
        encoding="utf-8",
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert required_name in process.stderr
    assert not backup_log.exists()


def test_compose_capability_precheck_passes_before_production_config_processing(
    tmp_path: Path,
) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    commands = docker_log.read_text(encoding="utf-8").splitlines()
    assert commands[0] == "compose config --help"
    _assert_sentinel_absent(process.stdout, process.stderr)


@pytest.mark.parametrize(
    "missing_flag",
    ["--no-env-resolution", "--no-interpolate", "--no-path-resolution", "--format"],
)
def test_compose_capability_precheck_fails_closed_for_each_missing_flag(
    tmp_path: Path, missing_flag: str
) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    environment["FAKE_COMPOSE_HELP"] = COMPOSE_CONFIG_HELP.replace(
        f"      {missing_flag}", "      --unrelated-option"
    )
    environment["PRODUCTION_COMPOSE_ENV_FILE"] = _bash_path(
        tmp_path / "missing-production-config.env"
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert f"capability is missing: {missing_flag}" in process.stderr
    assert "external production configuration" not in process.stderr.lower()
    assert docker_log.read_text(encoding="utf-8").splitlines() == [
        "compose config --help"
    ]
    assert not backup_log.exists()
    _assert_sentinel_absent(process.stdout, process.stderr)


def test_compose_capability_precheck_rejects_similar_substring(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    environment["FAKE_COMPOSE_HELP"] = COMPOSE_CONFIG_HELP.replace(
        "--format string", "--formatting string"
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "capability is missing: --format" in process.stderr
    assert docker_log.read_text(encoding="utf-8").splitlines() == [
        "compose config --help"
    ]
    assert not backup_log.exists()


def test_compose_capability_precheck_suppresses_command_failure_output(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    environment["FAKE_COMPOSE_HELP_EXIT"] = "2"
    environment["FAKE_COMPOSE_HELP_STDERR"] = SECRET_SENTINEL

    process = _activate(environment)

    assert process.returncode != 0
    assert "configuration capabilities are unavailable" in process.stderr
    assert docker_log.read_text(encoding="utf-8").splitlines() == [
        "compose config --help"
    ]
    assert not backup_log.exists()
    _assert_sentinel_absent(process.stdout, process.stderr)


@pytest.mark.parametrize(
    ("log_bytes", "expected_count"),
    [
        (b"ordinary runtime line\n", 0),
        (b"PANIC: failure\n", 1),
        (b"fatal and traceback on one line\n", 1),
        (b"fatality is not fatalistic\n", 0),
        (b"prefix [emerg] suffix\nprefix [crit] suffix\n", 2),
        (b"\xff\xfefatal: invalid utf8 remains countable\n", 1),
        (b"x" * (2 * 1024 * 1024) + b" fatal\n", 1),
    ],
    ids=[
        "ordinary",
        "uppercase-panic",
        "multiple-signatures-one-line",
        "word-boundary-nonmatch",
        "nginx-emerg-and-crit",
        "invalid-utf8",
        "large-line",
    ],
)
def test_critical_log_counter_emits_only_matching_line_count(
    log_bytes: bytes, expected_count: int
) -> None:
    process = subprocess.run(
        [sys.executable, str(CONTRACT_HELPER), "count-critical-log-lines"],
        input=log_bytes,
        capture_output=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert process.stdout == f"{expected_count}\n".encode()
    assert process.stderr == b""
    assert SECRET_SENTINEL.encode() not in process.stdout


@pytest.mark.parametrize(
    ("file_name", "mutation", "expected_error"),
    [
        (
            "compose.env",
            "POSTGRES_DB=duplicate_archive\n",
            "POSTGRES_DB is duplicated",
        ),
        ("backend.env", "not-an-assignment\n", "assignment is malformed"),
        ("migrator.env", "DB_PASSWORD=\n", "DB_PASSWORD is duplicated"),
    ],
)
def test_external_environment_metadata_fails_closed_on_invalid_syntax(
    tmp_path: Path, file_name: str, mutation: str, expected_error: str
) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    with (tmp_path / file_name).open("a", encoding="utf-8") as stream:
        stream.write(mutation)

    process = _activate(environment)

    assert process.returncode != 0
    assert expected_error in process.stderr
    assert not backup_log.exists()
    _assert_sentinel_absent(
        process.stdout,
        process.stderr,
        docker_log.read_text(encoding="utf-8"),
    )


def test_external_environment_metadata_rejects_empty_required_value(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    migrator_environment = tmp_path / "migrator.env"
    migrator_environment.write_text(
        migrator_environment.read_text(encoding="utf-8").replace(
            f"DB_PASSWORD={SECRET_SENTINEL}", "DB_PASSWORD="
        ),
        encoding="utf-8",
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "DB_PASSWORD is empty" in process.stderr
    assert not backup_log.exists()
    _assert_sentinel_absent(
        process.stdout,
        process.stderr,
        docker_log.read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize("file_name", ["compose.env", "backend.env", "migrator.env"])
def test_external_environment_metadata_rejects_forbidden_key_name(
    tmp_path: Path, file_name: str
) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    with (tmp_path / file_name).open("a", encoding="utf-8") as stream:
        stream.write(f"DEFAULT_ADMIN_PASSWORD={SECRET_SENTINEL}\n")

    process = _activate(environment)

    assert process.returncode != 0
    assert "forbidden key names: DEFAULT_ADMIN_PASSWORD" in process.stderr
    assert not backup_log.exists()
    assert "config --quiet" not in docker_log.read_text(encoding="utf-8")
    _assert_sentinel_absent(
        process.stdout,
        process.stderr,
        docker_log.read_text(encoding="utf-8"),
    )


def test_structural_compose_rejects_unreviewed_service_environment(
    tmp_path: Path,
) -> None:
    contract = _compose_contract(
        tmp_path / RELEASE_SHA,
        tmp_path / "origin.pem",
        tmp_path / "origin-key.pem",
    )
    contract["services"]["nginx"]["environment"] = {
        "UNREVIEWED": SECRET_SENTINEL
    }
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, compose_contract=contract
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "nginx" in process.stderr and "privilege" in process.stderr
    assert not backup_log.exists()
    commands = docker_log.read_text(encoding="utf-8")
    _assert_sentinel_absent(process.stdout, process.stderr, commands)
    assert "up --detach" not in commands
    assert not (tmp_path / "activation-contract").exists()


@pytest.mark.parametrize(
    "bypass_kind",
    ["api_socket", "backend_port", "external_network", "code_overlay"],
)
def test_structural_compose_rejects_host_authority_bypasses(
    tmp_path: Path, bypass_kind: str
) -> None:
    contract = _compose_contract(
        tmp_path / RELEASE_SHA,
        tmp_path / "origin.pem",
        tmp_path / "origin-key.pem",
    )
    backend = contract["services"]["backend"]
    if bypass_kind == "api_socket":
        backend["use_api_socket"] = True
    elif bypass_kind == "backend_port":
        backend["ports"] = [
            {"published": "8000", "target": 8000, "protocol": "tcp"}
        ]
    elif bypass_kind == "external_network":
        contract["networks"]["escape"] = {"external": True}
        backend["networks"]["escape"] = {}
    else:
        contract["volumes"]["code_overlay"] = {"external": True}
        backend["volumes"] = [
            {
                "type": "volume",
                "source": "code_overlay",
                "target": "/app",
                "volume": {},
            }
        ]
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, compose_contract=contract
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "Production activation contract failed" in process.stderr
    assert not backup_log.exists()
    commands = docker_log.read_text(encoding="utf-8")
    assert "config --quiet" not in commands
    assert "up --detach" not in commands


def test_runtime_compose_validation_error_cannot_echo_secret_value(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, compose_quiet_exit=2
    )
    environment["FAKE_COMPOSE_QUIET_STDERR"] = SECRET_SENTINEL

    process = _activate(environment)

    assert process.returncode != 0
    assert "runtime configuration is invalid" in process.stderr
    _assert_sentinel_absent(process.stdout, process.stderr)
    assert not backup_log.exists()
    assert "config --quiet" in docker_log.read_text(encoding="utf-8")
    assert not (tmp_path / "activation-contract").exists()


def test_structural_compose_error_cannot_retain_or_echo_secret_value(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    (tmp_path / "compose.json").write_text(SECRET_SENTINEL, encoding="utf-8")

    process = _activate(environment)

    assert process.returncode != 0
    assert "structural configuration is invalid" in process.stderr
    commands = docker_log.read_text(encoding="utf-8")
    _assert_sentinel_absent(process.stdout, process.stderr, commands)
    assert not backup_log.exists()
    assert not (tmp_path / "activation-contract").exists()


def _assert_sentinel_absent(*surfaces: str) -> None:
    assert all(SECRET_SENTINEL not in surface for surface in surfaces)


def test_real_compose_structural_model_matches_activation_contract(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is unavailable in this environment.")
    command = [
        docker,
        "compose",
        "--project-directory",
        str(REPOSITORY_ROOT),
        "--file",
        str(REPOSITORY_ROOT / "docker" / "docker-compose.prod.yml"),
        "--file",
        str(REPOSITORY_ROOT / "docker" / "docker-compose.prod-edge.example.yml"),
        "--file",
        str(REPOSITORY_ROOT / "docker" / "docker-compose.nginx-immutable.yml"),
        "config",
        "--no-env-resolution",
        "--no-interpolate",
        "--no-path-resolution",
        "--format",
        "json",
    ]
    rendered = subprocess.run(command, text=True, capture_output=True, check=False)
    assert rendered.returncode == 0, rendered.stderr
    structural_compose = tmp_path / "compose-structure.json"
    structural_compose.write_text(rendered.stdout, encoding="utf-8")
    compose_environment = tmp_path / "compose.env"
    backend_environment = tmp_path / "backend.env"
    migrator_environment = tmp_path / "migrator.env"
    compose_environment.write_text(
        "POSTGRES_USER=postgres_owner\n"
        f"POSTGRES_PASSWORD={SECRET_SENTINEL}\n"
        "POSTGRES_DB=archive_db\n"
        f"MINIO_ROOT_USER={SECRET_SENTINEL}\n"
        f"MINIO_ROOT_PASSWORD={SECRET_SENTINEL}\n"
        "PRODUCTION_NGINX_PROXY_IP=172.30.0.2\n"
        f"PRODUCTION_TLS_CERT_FILE={tmp_path / 'origin.pem'}\n"
        f"PRODUCTION_TLS_KEY_FILE={tmp_path / 'origin-key.pem'}\n",
        encoding="utf-8",
    )
    backend_environment.write_text(
        "DB_HOST=db\nDB_PORT=5432\nDB_USER=runtime\n"
        f"DB_PASSWORD={SECRET_SENTINEL}\nDB_NAME=archive_db\n"
        f"MINIO_ACCESS_KEY={SECRET_SENTINEL}\n"
        f"MINIO_SECRET_KEY={SECRET_SENTINEL}\n"
        "MINIO_BUCKET_NAME=exam-archive\n",
        encoding="utf-8",
    )
    migrator_environment.write_text(
        "DB_HOST=db\nDB_PORT=5432\nDB_USER=migrator\n"
        f"DB_PASSWORD={SECRET_SENTINEL}\nDB_NAME=archive_db\n",
        encoding="utf-8",
    )
    validated = subprocess.run(
        [
            sys.executable,
            str(CONTRACT_HELPER),
            "compose-values",
            "--compose-json",
            str(structural_compose),
            "--compose-env",
            str(compose_environment),
            "--backend-env",
            str(backend_environment),
            "--migrator-env",
            str(migrator_environment),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert validated.returncode == 0, validated.stderr
    _assert_sentinel_absent(rendered.stdout, rendered.stderr, validated.stdout, validated.stderr)


def test_release_metadata_disagreement_fails_before_backup(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, source_sha="0" * 40
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "release" in process.stderr.lower()
    assert not backup_log.exists()
    assert docker_log.read_text(encoding="utf-8").splitlines() == [
        "compose config --help"
    ]


def test_activation_uses_candidate_compose_environment(tmp_path: Path) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    release = tmp_path / RELEASE_SHA
    commands = docker_log.read_text(encoding="utf-8")
    external = f"--env-file {environment['PRODUCTION_COMPOSE_ENV_FILE']}"
    candidate = f"--env-file {_bash_path(release / 'compose.prod.env')}"
    assert external in commands
    assert candidate in commands
    assert commands.index(external) < commands.index(candidate)
    structural_commands = [
        line for line in commands.splitlines() if "--no-env-resolution" in line
    ]
    assert len(structural_commands) == 1
    structural = structural_commands[0]
    assert "--no-interpolate" in structural
    assert "--no-path-resolution" in structural
    assert "--env-file" not in structural


def test_secret_sentinel_never_enters_success_path_evidence(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    engine_evidence = tmp_path / "engine-evidence.json"
    environment["ACTIVATION_EVIDENCE_PATH"] = _bash_path(engine_evidence)

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    release = tmp_path / RELEASE_SHA
    _assert_sentinel_absent(
        process.stdout,
        process.stderr,
        backup_log.read_text(encoding="utf-8"),
        docker_log.read_text(encoding="utf-8"),
        engine_evidence.read_text(encoding="utf-8"),
        (release / "release-manifest.env").read_text(encoding="utf-8"),
        (release / "compose.prod.env").read_text(encoding="utf-8"),
    )
    assert not (tmp_path / "activation-contract").exists()


def test_secret_sentinel_never_enters_failure_path_evidence(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, storage_preflight_exit=2
    )
    engine_evidence = tmp_path / "engine-evidence.json"
    environment["ACTIVATION_EVIDENCE_PATH"] = _bash_path(engine_evidence)

    process = _activate(environment)

    assert process.returncode != 0
    _assert_sentinel_absent(
        process.stdout,
        process.stderr,
        backup_log.read_text(encoding="utf-8"),
        docker_log.read_text(encoding="utf-8"),
    )
    assert not (tmp_path / "activation-contract").exists()
    assert not engine_evidence.exists()


def test_storage_preflight_failure_stops_before_backup_or_migration(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, storage_preflight_exit=2
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert backup_log.read_text(encoding="utf-8").splitlines() == [
        "preflight:pastexam-minio:exam-archive"
    ]
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_preflight_never_starts_missing_persistent_dependencies(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    environment["ACTIVATION_PREFLIGHT_ONLY"] = "true"
    environment["FAKE_PERSISTENT_STATE"] = "exited:none"

    process = _activate(environment)

    assert process.returncode != 0
    assert "not already running and healthy" in process.stderr.lower()
    assert not backup_log.exists()
    commands = docker_log.read_text(encoding="utf-8")
    assert "require-head --json" not in commands
    assert " up -d " not in commands


def test_preflight_rejects_running_but_unresponsive_redis(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    environment["ACTIVATION_PREFLIGHT_ONLY"] = "true"
    environment["FAKE_PERSISTENT_STATE"] = "running:none"
    environment["FAKE_REDIS_PING"] = "LOADING"

    process = _activate(environment)

    assert process.returncode != 0
    assert "redis did not pass" in process.stderr.lower()
    assert not backup_log.exists()
    commands = docker_log.read_text(encoding="utf-8")
    assert "redis-cli ping" in commands
    assert "require-head --json" not in commands
    assert " up -d " not in commands


@pytest.mark.parametrize("service", ["frontend", "backend", "migrate"])
def test_rendered_image_mismatch_fails_before_backup(
    tmp_path: Path, service: str
) -> None:
    release = tmp_path / RELEASE_SHA
    certificate = tmp_path / "origin.pem"
    certificate_key = tmp_path / "origin-key.pem"
    contract = _compose_contract(release, certificate, certificate_key)
    contract["services"][service]["image"] = "ghcr.io/example/pastexam:old"
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, compose_contract=contract
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "images disagree" in process.stderr
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("trusted_peer", "nginx_address"),
    [
        ("*", "172.30.0.2"),
        ("172.30.0.0/24", "172.30.0.2"),
        ("203.0.113.2", "203.0.113.2"),
        ("172.30.0.3", "172.30.0.2"),
    ],
)
def test_unsafe_or_mismatched_uvicorn_proxy_trust_fails_before_backup(
    tmp_path: Path, trusted_peer: str, nginx_address: str
) -> None:
    release = tmp_path / RELEASE_SHA
    contract = _compose_contract(
        release,
        tmp_path / "origin.pem",
        tmp_path / "origin-key.pem",
    )
    contract["services"]["backend"]["environment"]["FORWARDED_ALLOW_IPS"] = trusted_peer
    contract["services"]["nginx"]["networks"]["trusted_proxy_network"][
        "ipv4_address"
    ] = nginx_address
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=contract,
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "proxy trust" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "nginx_address",
    ["172.30.0.0", "172.30.0.1", "172.30.0.9", "172.30.0.15", "172.30.1.2"],
)
def test_unreserved_nginx_proxy_address_fails_before_backup(
    tmp_path: Path, nginx_address: str
) -> None:
    release = tmp_path / RELEASE_SHA
    contract = _compose_contract(
        release,
        tmp_path / "origin.pem",
        tmp_path / "origin-key.pem",
    )
    contract["services"]["backend"]["environment"]["FORWARDED_ALLOW_IPS"] = (
        nginx_address
    )
    contract["services"]["nginx"]["networks"]["trusted_proxy_network"][
        "ipv4_address"
    ] = nginx_address
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=contract,
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "proxy" in process.stderr.lower() or "ipam" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_dynamic_range_cannot_include_static_nginx_peer(tmp_path: Path) -> None:
    release = tmp_path / RELEASE_SHA
    contract = _compose_contract(
        release,
        tmp_path / "origin.pem",
        tmp_path / "origin-key.pem",
    )
    contract["networks"]["trusted_proxy_network"]["ipam"]["config"][0]["ip_range"] = (
        "172.30.0.2/31"
    )
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=contract,
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "reserved" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "service", ["frontend", "migrate", "db", "minio", "redis", "future_worker"]
)
def test_unrelated_service_cannot_join_trusted_proxy_network(
    tmp_path: Path, service: str
) -> None:
    release = tmp_path / RELEASE_SHA
    contract = _compose_contract(
        release,
        tmp_path / "origin.pem",
        tmp_path / "origin-key.pem",
    )
    contract["services"].setdefault(service, {"networks": {}})
    contract["services"][service]["networks"]["trusted_proxy_network"] = {}
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=contract,
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert (
        "unrelated service" in process.stderr.lower()
        or "reviewed production set" in process.stderr.lower()
    )
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("service_name", "field", "value"),
    [
        ("backend", "privileged", True),
        ("backend", "network_mode", "host"),
        ("backend", "pid", "host"),
        ("backend", "devices", ["/dev/sda:/dev/sda"]),
        ("backend", "cap_add", ["SYS_ADMIN"]),
        ("backend", "entrypoint", ["/bin/sh"]),
        ("backend", "security_opt", ["apparmor=unconfined"]),
        ("backend", "user", "root"),
        ("backend", "volumes_from", ["pastexam-postgres"]),
        ("backend", "secrets", [{"source": "host-secret"}]),
    ],
)
def test_rendered_compose_privilege_expansion_fails_before_backup(
    tmp_path: Path, service_name: str, field: str, value: object
) -> None:
    release = tmp_path / RELEASE_SHA
    certificate = tmp_path / "origin.pem"
    certificate_key = tmp_path / "origin-key.pem"
    compose = _compose_contract(release, certificate, certificate_key)
    compose["services"][service_name][field] = value
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, compose_contract=compose
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert (
        "privilege" in process.stderr.lower()
        or "entrypoint" in process.stderr.lower()
        or "security" in process.stderr.lower()
    )
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_nginx_extra_writable_bind_mount_fails_before_backup(tmp_path: Path) -> None:
    release = tmp_path / RELEASE_SHA
    compose = _compose_contract(
        release, tmp_path / "origin.pem", tmp_path / "origin-key.pem"
    )
    compose["services"]["nginx"]["volumes"].append(
        {
            "type": "bind",
            "source": "/",
            "target": "/host",
            "read_only": False,
        }
    )
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, compose_contract=compose
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "exact reviewed read-only set" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_health_retries_initial_connection_failure_then_succeeds(
    tmp_path: Path,
) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    health_log = _set_health_failures(tmp_path, environment, failures=1)

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    # Three immediate probes (one retry plus external) and two observation probes.
    assert len(health_log.read_text(encoding="utf-8").splitlines()) == 5
    assert (tmp_path / RELEASE_SHA / ".activated").is_file()


def test_permanent_health_failure_does_not_activate(tmp_path: Path) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    health_log = _set_health_failures(tmp_path, environment, failures=99)

    process = _activate(environment)

    assert process.returncode != 0
    assert len(health_log.read_text(encoding="utf-8").splitlines()) == 3
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()
    assert not (tmp_path / RELEASE_SHA / ".activated.partial").exists()


def test_external_edge_contract_must_remain_mode_0600(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, edge_mode="644"
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "0600" in process.stderr
    assert not backup_log.exists()
    assert docker_log.read_text(encoding="utf-8").splitlines() == [
        "compose config --help"
    ]


def test_external_production_contracts_must_remain_root_owned(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, config_owner="1000"
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "root-owned" in process.stderr
    assert not backup_log.exists()
    assert docker_log.read_text(encoding="utf-8").splitlines() == [
        "compose config --help"
    ]


@pytest.mark.parametrize(
    ("tls_mode", "tls_owner", "message"),
    [("644", "0", "0600"), ("600", "1000", "root-owned")],
)
def test_external_tls_files_are_permission_checked_before_backup(
    tmp_path: Path, tls_mode: str, tls_owner: str, message: str
) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, tls_mode=tls_mode, tls_owner=tls_owner
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert message in process.stderr
    assert not backup_log.exists()
    assert " inspect " not in docker_log.read_text(encoding="utf-8")


def test_missing_external_tls_file_fails_before_backup(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    (tmp_path / "origin-key.pem").unlink()

    process = _activate(environment)

    assert process.returncode != 0
    assert "missing" in process.stderr.lower()
    assert not backup_log.exists()
    assert " inspect " not in docker_log.read_text(encoding="utf-8")


def test_backup_failure_stops_before_migration_or_compose_up(tmp_path: Path) -> None:
    environment, _, docker_log = _activation_environment(tmp_path, postgres_exit=9)

    process = _activate(environment)

    assert process.returncode == 9
    commands = docker_log.read_text(encoding="utf-8")
    assert "migrate.py require-head --json" in commands
    assert "migrate.py upgrade" not in commands
    assert " up -d " not in commands


def test_nonzero_migration_delta_fails_before_backup_or_application_mutation(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        migration_revision="6f3a9c2d8e41",
        repository_head="9f1c2a7e4b63",
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "delta" in process.stderr.lower() or "head" in process.stderr.lower()
    assert backup_log.read_text(encoding="utf-8").splitlines() == [
        "preflight:pastexam-minio:exam-archive"
    ]
    commands = docker_log.read_text(encoding="utf-8")
    assert " up -d " not in commands
    assert " migrate.py upgrade" not in commands


def test_activation_never_runs_upgrade_or_dependency_migration(tmp_path: Path) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    commands = docker_log.read_text(encoding="utf-8")
    assert "migrate.py upgrade" not in commands
    assert (
        "run --rm --no-deps migrate python migrate.py require-head --json" in commands
    )
    assert "up -d --no-deps backend frontend nginx" in commands


def test_observation_fails_if_running_image_authority_changes(tmp_path: Path) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    environment["FAKE_BACKEND_IMAGE"] = "ghcr.io/example/backend@sha256:" + "f" * 64

    process = _activate(environment)

    assert process.returncode != 0
    assert "image authority changed" in process.stderr.lower()
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()


def test_observation_fails_on_bounded_critical_error_evidence(tmp_path: Path) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    environment["FAKE_CRITICAL_LOG"] = "fatal: simulated fixture failure\n"

    process = _activate(environment)

    assert process.returncode != 0
    assert "critical runtime errors" in process.stderr.lower()
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()


def test_runtime_log_stream_discards_noncritical_sentinel_text(tmp_path: Path) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)
    engine_evidence = tmp_path / "engine-evidence.json"
    environment["ACTIVATION_EVIDENCE_PATH"] = _bash_path(engine_evidence)
    environment["FAKE_CRITICAL_LOG"] = f"ordinary {SECRET_SENTINEL} line\n"
    environment["FAKE_CRITICAL_LOG_STDERR"] = (
        f"ordinary stderr {SECRET_SENTINEL} line\n"
    )

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    _assert_sentinel_absent(
        process.stdout,
        process.stderr,
        docker_log.read_text(encoding="utf-8"),
        engine_evidence.read_text(encoding="utf-8"),
    )
    assert not list(tmp_path.rglob("*.critical.log"))
    assert ".critical.log" not in ACTIVATION_SCRIPT.read_text(encoding="utf-8")


def test_runtime_log_stream_discards_sentinel_surrounding_critical_match(
    tmp_path: Path,
) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)
    environment["FAKE_CRITICAL_LOG"] = (
        f"{SECRET_SENTINEL} fatal {SECRET_SENTINEL}\n"
        f"{SECRET_SENTINEL} traceback {SECRET_SENTINEL}\n"
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "critical runtime errors" in process.stderr.lower()
    _assert_sentinel_absent(
        process.stdout, process.stderr, docker_log.read_text(encoding="utf-8")
    )
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()
    assert not list(tmp_path.rglob("*.critical.log"))


def test_runtime_log_producer_failure_is_not_treated_as_zero_matches(
    tmp_path: Path,
) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)
    environment["FAKE_CRITICAL_LOG_EXIT"] = "2"
    environment["FAKE_CRITICAL_LOG_STDERR"] = SECRET_SENTINEL

    process = _activate(environment)

    assert process.returncode != 0
    assert "could not process container logs" in process.stderr.lower()
    assert "critical runtime errors" not in process.stderr.lower()
    _assert_sentinel_absent(
        process.stdout, process.stderr, docker_log.read_text(encoding="utf-8")
    )
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()


def test_runtime_log_parser_failure_is_fail_closed(tmp_path: Path) -> None:
    environment, _, docker_log = _activation_environment(tmp_path)
    environment["FAKE_CRITICAL_PARSER_EXIT"] = "2"
    environment["FAKE_CRITICAL_LOG"] = SECRET_SENTINEL

    process = _activate(environment)

    assert process.returncode != 0
    assert "could not process container logs" in process.stderr.lower()
    _assert_sentinel_absent(
        process.stdout, process.stderr, docker_log.read_text(encoding="utf-8")
    )
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()


def test_read_only_preflight_stops_before_backup_and_application_mutation(
    tmp_path: Path,
) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    failure_evidence = _enable_failure_evidence(tmp_path, environment)
    environment["ACTIVATION_PREFLIGHT_ONLY"] = "true"

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    payload = json.loads(process.stdout.splitlines()[-1])
    assert payload == {
        "database_revision": "9f1c2a7e4b63",
        "outcome": "eligible",
        "schema_version": 1,
        "target_sha": RELEASE_SHA,
    }
    assert backup_log.read_text(encoding="utf-8").splitlines() == [
        "preflight:pastexam-minio:exam-archive"
    ]
    commands = docker_log.read_text(encoding="utf-8")
    assert "migrate.py require-head --json" in commands
    assert " up -d " not in commands
    assert not (tmp_path / RELEASE_SHA / ".activated").exists()
    assert not failure_evidence.exists()


def test_target_ports_cannot_drop_current_production_ingress(tmp_path: Path) -> None:
    release = tmp_path / RELEASE_SHA
    certificate = tmp_path / "origin.pem"
    certificate_key = tmp_path / "origin-key.pem"
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=_compose_contract(
            release,
            certificate,
            certificate_key,
            ports=[(80, 8080), (8080, 8080)],
        ),
        current_ports={
            "8080/tcp": [
                {"HostIp": "0.0.0.0", "HostPort": "80"},
                {"HostIp": "0.0.0.0", "HostPort": "8080"},
            ],
            "8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "443"}],
        },
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "ingress" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_compose_targets_must_match_nginx_listeners(tmp_path: Path) -> None:
    release = tmp_path / RELEASE_SHA
    certificate = tmp_path / "origin.pem"
    certificate_key = tmp_path / "origin-key.pem"
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=_compose_contract(
            release,
            certificate,
            certificate_key,
            ports=[(8081, 8081)],
        ),
        current_ports={"8081/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8081"}]},
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "listener" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_missing_8443_tls_listener_fails_before_backup(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(tmp_path)
    release = tmp_path / RELEASE_SHA
    (release / "proxy" / "nginx.production-listeners.conf").write_text(
        "listen 8080;\n", encoding="utf-8"
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "listener" in process.stderr.lower() or "tls" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_missing_certificate_mounts_fail_before_backup(tmp_path: Path) -> None:
    release = tmp_path / RELEASE_SHA
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=_compose_contract(
            release,
            tmp_path / "origin.pem",
            tmp_path / "origin-key.pem",
            include_certificate_mounts=False,
        ),
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "certificate" in process.stderr.lower() or "mount" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def test_compose_cannot_mount_a_different_nginx_config_than_is_validated(
    tmp_path: Path,
) -> None:
    release = tmp_path / RELEASE_SHA
    alternate_config = tmp_path / "alternate-nginx.conf"
    alternate_config.write_text(
        "events {}\nhttp { server { include /etc/nginx/pastexam-listeners.conf; } }\n",
        encoding="utf-8",
    )
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=_compose_contract(
            release,
            tmp_path / "origin.pem",
            tmp_path / "origin-key.pem",
            nginx_config=alternate_config,
        ),
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "nginx" in process.stderr.lower()
    assert not backup_log.exists()
    assert "require-head --json" not in docker_log.read_text(encoding="utf-8")


def _backup_environment(tmp_path: Path, application_sha: str) -> dict[str, str]:
    release = tmp_path / "git-archive-release"
    scripts = release / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(BACKUP_SCRIPT, scripts / BACKUP_SCRIPT.name)
    assert not (release / ".git").exists()

    fake_bin = tmp_path / "backup-bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'arguments="$*"\n'
        "if [[ \"$1\" == 'inspect' ]]; then\n"
        "  exit 0\n"
        "elif [[ \"$arguments\" == *'SELECT current_database()'* ]]; then\n"
        "  printf 'archive_db\\n'\n"
        "elif [[ \"$arguments\" == *'alembic_version'* ]]; then\n"
        "  printf '9f1c2a7e4b63\\n'\n"
        "elif [[ \"$arguments\" == *'SHOW server_version'* ]]; then\n"
        "  printf '15.14\\n'\n"
        "elif [[ \"$arguments\" == *'pg_dump'* ]]; then\n"
        "  printf 'verified-fake-custom-dump'\n"
        "elif [[ \"$arguments\" == *'pg_restore --list'* ]]; then\n"
        "  exit 0\n"
        "else\n"
        "  printf 'unexpected docker call: %s\\n' \"$arguments\" >&2\n"
        "  exit 97\n"
        "fi\n",
    )
    bash_env = tmp_path / "backup-bash-env"
    bash_env.write_text(
        "docker() {\n"
        '  arguments="$*"\n'
        "  if [[ \"$1\" == 'inspect' ]]; then\n"
        "    return 0\n"
        "  elif [[ \"$arguments\" == *'SELECT current_database()'* ]]; then\n"
        "    printf 'archive_db\\n'\n"
        "  elif [[ \"$arguments\" == *'alembic_version'* ]]; then\n"
        "    printf '9f1c2a7e4b63\\n'\n"
        "  elif [[ \"$arguments\" == *'SHOW server_version'* ]]; then\n"
        "    printf '15.14\\n'\n"
        "  elif [[ \"$arguments\" == *'pg_dump'* ]]; then\n"
        "    printf 'verified-fake-custom-dump'\n"
        "  elif [[ \"$arguments\" == *'pg_restore --list'* ]]; then\n"
        "    return 0\n"
        "  else\n"
        "    printf 'unexpected docker call: %s\\n' \"$arguments\" >&2\n"
        "    return 97\n"
        "  fi\n"
        "}\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": _path_with(fake_bin),
            "BASH_ENV": _bash_path(bash_env),
            "BACKUP_DIRECTORY": _bash_path(tmp_path / "logical-backups"),
            "DATABASE_CONTAINER": "pastexam-postgres",
            "DATABASE_NAME": "archive_db",
            "DATABASE_USER": "postgres_owner",
            "APPLICATION_RELEASE_SHA": application_sha,
        }
    )
    environment["BACKUP_SCRIPT_COPY"] = _bash_path(scripts / BACKUP_SCRIPT.name)
    return environment


def test_git_archive_backup_records_exact_release_sha_without_git(
    tmp_path: Path,
) -> None:
    environment = _backup_environment(tmp_path, RELEASE_SHA)

    process = subprocess.run(
        [str(_bash()), environment["BACKUP_SCRIPT_COPY"]],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )

    assert process.returncode == 0, process.stderr
    metadata_files = list((tmp_path / "logical-backups").glob("*.metadata.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert metadata["application_release_sha"] == RELEASE_SHA
    assert "repository_head" not in metadata


@pytest.mark.parametrize("invalid_sha", ["main", "A" * 40, "0" * 39])
def test_backup_rejects_invalid_explicit_release_sha(
    tmp_path: Path, invalid_sha: str
) -> None:
    environment = _backup_environment(tmp_path, invalid_sha)

    process = subprocess.run(
        [str(_bash()), environment["BACKUP_SCRIPT_COPY"]],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )

    assert process.returncode != 0
    assert "release" in process.stderr.lower()
    assert not (tmp_path / "logical-backups").exists()


def test_full_ci_executes_runtime_release_and_nginx_contract_tests() -> None:
    workflow = TEST_WORKFLOW.read_text(encoding="utf-8")

    for test_file in (
        "test_backend_runtime_health.py",
        "test_candidate_preparation_governance.py",
        "test_nginx_oauth_access_logging.py",
        "test_production_activation_contract.py",
        "test_release_workflow_contract.py",
    ):
        assert workflow.count(test_file) == 1
    assert workflow.count("./scripts/validate-compose-safety.sh") == 1
