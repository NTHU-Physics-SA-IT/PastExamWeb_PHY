from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACTIVATION_SCRIPT = REPOSITORY_ROOT / "scripts" / "activate-production-release.sh"
BACKUP_SCRIPT = REPOSITORY_ROOT / "scripts" / "postgres-logical-backup.sh"
CONTRACT_HELPER = REPOSITORY_ROOT / "scripts" / "production-activation-contract.py"
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
RELEASE_SHA = "19782580b710924d8ccdb939600be72ecd44d303"
FRONTEND_IMAGE = f"ghcr.io/example/pastexam:frontend-{RELEASE_SHA}@sha256:{'1' * 64}"
BACKEND_IMAGE = f"ghcr.io/example/pastexam:backend-{RELEASE_SHA}@sha256:{'2' * 64}"


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


def _bind(source: Path, target: str) -> dict[str, object]:
    return {
        "type": "bind",
        "source": str(source.resolve()),
        "target": target,
        "read_only": True,
    }


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
        _bind(
            nginx_config or release / "proxy" / "nginx.conf", "/etc/nginx/nginx.conf"
        ),
        _bind(
            listener_config or release / "proxy" / "nginx.production-listeners.conf",
            "/etc/nginx/pastexam-listeners.conf",
        ),
    ]
    if include_certificate_mounts:
        nginx_volumes.extend(
            [
                _bind(certificate, "/etc/nginx/certs/origin.pem"),
                _bind(certificate_key, "/etc/nginx/certs/origin-key.pem"),
            ]
        )
    return {
        "services": {
            "backend": {
                "image": BACKEND_IMAGE,
                "environment": {"MINIO_BUCKET_NAME": "exam-archive"},
            },
            "frontend": {"image": FRONTEND_IMAGE},
            "migrate": {"image": BACKEND_IMAGE},
            "db": {
                "container_name": "pastexam-postgres",
                "environment": {
                    "POSTGRES_DB": "archive_db",
                    "POSTGRES_USER": "postgres_owner",
                },
            },
            "minio": {"container_name": "pastexam-minio"},
            "nginx": {
                "container_name": "pastexam-nginx",
                "ports": [
                    {
                        "host_ip": "0.0.0.0",
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
        }
    }


def _activation_environment(
    tmp_path: Path,
    *,
    compose_contract: dict | None = None,
    current_ports: dict | None = None,
    postgres_exit: int = 0,
    source_sha: str = RELEASE_SHA,
    edge_mode: str = "600",
    config_owner: str = "0",
    tls_mode: str = "600",
    tls_owner: str = "0",
) -> tuple[dict[str, str], Path, Path]:
    release = tmp_path / RELEASE_SHA
    scripts = release / "scripts"
    proxy = release / "proxy"
    docker_dir = release / "docker"
    scripts.mkdir(parents=True)
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
        f"backend_image={BACKEND_IMAGE}\n",
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
        shutil.copy2(CONTRACT_HELPER, scripts / CONTRACT_HELPER.name)

    backup_log = tmp_path / "backup-contract.log"
    _write_executable(
        scripts / "postgres-logical-backup.sh",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"printf 'postgres:%s:%s:%s:%s\\n' \"$BACKUP_DIRECTORY\" "
        f'"$DATABASE_CONTAINER" "$DATABASE_NAME" "$DATABASE_USER" '
        f">>'{_bash_path(backup_log)}'\n"
        f"exit {postgres_exit}\n",
    )
    _write_executable(
        scripts / "minio-readonly-manifest.sh",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"printf 'minio:%s:%s:%s\\n' \"$BACKUP_DIRECTORY\" "
        f'"$MINIO_CONTAINER" "$MINIO_BUCKET_NAME" '
        f">>'{_bash_path(backup_log)}'\n",
    )

    compose_json = tmp_path / "compose.json"
    compose_json.write_text(
        json.dumps(
            compose_contract or _compose_contract(release, certificate, certificate_key)
        ),
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
    docker_log = tmp_path / "docker.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'printf \'%s\\n\' "$*" >>"$FAKE_DOCKER_LOG"\n'
        "if [[ \"$1\" == 'compose' && \"$*\" == *'config --format json'* ]]; then\n"
        '  cat "$FAKE_COMPOSE_JSON"\n'
        "elif [[ \"$1\" == 'inspect' ]]; then\n"
        '  cat "$FAKE_CURRENT_PORTS_JSON"\n'
        "fi\n",
    )
    _write_executable(fake_bin / "curl", "#!/usr/bin/env bash\nset -eu\nexit 0\n")
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
        "  if [[ \"$1\" == 'compose' && \"$*\" == *'config --format json'* ]]; then\n"
        '    cat "$FAKE_COMPOSE_JSON"\n'
        "  elif [[ \"$1\" == 'inspect' ]]; then\n"
        '    cat "$FAKE_CURRENT_PORTS_JSON"\n'
        "  fi\n"
        "}\n"
        "curl() { return 0; }\n"
        "flock() { return 0; }\n"
        f"python3() {{ '{_bash_path(Path(sys.executable))}' \"$@\"; }}\n",
        encoding="utf-8",
    )

    config_files = [
        tmp_path / name for name in ("compose.env", "backend.env", "migrator.env")
    ]
    edge_file = tmp_path / "edge.yml"
    for path in [*config_files, edge_file]:
        path.write_text("contract-test=true\n", encoding="utf-8")

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
            "FAKE_COMPOSE_JSON": _bash_path(compose_json),
            "FAKE_CURRENT_PORTS_JSON": _bash_path(ports_json),
            "FAKE_DOCKER_LOG": _bash_path(docker_log),
            "FAKE_EDGE_FILE": _bash_path(edge_file),
            "FAKE_EDGE_MODE": edge_mode,
            "FAKE_CONFIG_OWNER": config_owner,
            "FAKE_TLS_MODE": tls_mode,
            "FAKE_TLS_OWNER": tls_owner,
        }
    )
    for inherited in (
        "BACKUP_DIRECTORY",
        "DATABASE_CONTAINER",
        "DATABASE_NAME",
        "DATABASE_USER",
        "MINIO_CONTAINER",
        "MINIO_BUCKET_NAME",
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
        "postgres:"
        f"{environment['PRODUCTION_BACKUP_DIRECTORY']}:"
        "pastexam-postgres:archive_db:postgres_owner",
        "minio:"
        f"{environment['PRODUCTION_BACKUP_DIRECTORY']}:"
        "pastexam-minio:exam-archive",
    ]


def test_release_metadata_disagreement_fails_before_backup(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path, source_sha="0" * 40
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "release" in process.stderr.lower()
    assert not backup_log.exists()
    assert not docker_log.exists()


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
    assert " run --rm migrate" not in docker_log.read_text(encoding="utf-8")


def test_health_retries_initial_connection_failure_then_succeeds(tmp_path: Path) -> None:
    environment, _, _ = _activation_environment(tmp_path)
    health_log = _set_health_failures(tmp_path, environment, failures=1)

    process = _activate(environment)

    assert process.returncode == 0, process.stderr
    assert len(health_log.read_text(encoding="utf-8").splitlines()) == 3
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
    assert not docker_log.exists()


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
    assert not docker_log.exists()


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
    assert " run --rm migrate" not in commands
    assert " up -d " not in commands


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
    assert " run --rm migrate" not in docker_log.read_text(encoding="utf-8")


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
    assert " run --rm migrate" not in docker_log.read_text(encoding="utf-8")


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
    assert " run --rm migrate" not in docker_log.read_text(encoding="utf-8")


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
    assert " run --rm migrate" not in docker_log.read_text(encoding="utf-8")


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
    assert " run --rm migrate" not in docker_log.read_text(encoding="utf-8")


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


def test_full_ci_executes_production_release_and_nginx_contract_tests() -> None:
    workflow = TEST_WORKFLOW.read_text(encoding="utf-8")

    for test_file in (
        "test_nginx_oauth_access_logging.py",
        "test_production_activation_contract.py",
        "test_release_workflow_contract.py",
    ):
        assert workflow.count(test_file) == 1
    assert workflow.count("./scripts/validate-compose-safety.sh") == 1
