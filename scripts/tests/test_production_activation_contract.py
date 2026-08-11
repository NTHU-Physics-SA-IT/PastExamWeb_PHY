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


def _compose_contract(*, published: int = 8080, target: int = 8080) -> dict:
    return {
        "services": {
            "backend": {"environment": {"MINIO_BUCKET_NAME": "exam-archive"}},
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
                ],
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
) -> tuple[dict[str, str], Path, Path]:
    release = tmp_path / RELEASE_SHA
    scripts = release / "scripts"
    proxy = release / "proxy"
    docker_dir = release / "docker"
    scripts.mkdir(parents=True)
    proxy.mkdir()
    docker_dir.mkdir()

    (release / ".release-source-sha").write_text(f"{source_sha}\n", encoding="utf-8")
    manifest = release / "release-manifest.env"
    manifest.write_text(f"release_sha={RELEASE_SHA}\n", encoding="utf-8")
    (docker_dir / "docker-compose.prod.yml").write_text(
        "services:\n  nginx:\n    image: nginx:contract-test\n",
        encoding="utf-8",
    )
    (proxy / "nginx.conf").write_text(
        "events {}\nhttp { server { listen 8080; } }\n", encoding="utf-8"
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
        json.dumps(compose_contract or _compose_contract()), encoding="utf-8"
    )
    ports_json = tmp_path / "current-ports.json"
    ports_json.write_text(
        json.dumps(
            current_ports or {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}
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
        "    printf '%s\\n' \"$FAKE_CONFIG_OWNER\"\n"
        '  elif [[ "${@: -1}" == "$FAKE_EDGE_FILE" ]]; then\n'
        "    printf '%s\\n' \"$FAKE_EDGE_MODE\"\n"
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
            "FAKE_COMPOSE_JSON": _bash_path(compose_json),
            "FAKE_CURRENT_PORTS_JSON": _bash_path(ports_json),
            "FAKE_DOCKER_LOG": _bash_path(docker_log),
            "FAKE_EDGE_FILE": _bash_path(edge_file),
            "FAKE_EDGE_MODE": edge_mode,
            "FAKE_CONFIG_OWNER": config_owner,
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


def test_backup_failure_stops_before_migration_or_compose_up(tmp_path: Path) -> None:
    environment, _, docker_log = _activation_environment(tmp_path, postgres_exit=9)

    process = _activate(environment)

    assert process.returncode == 9
    commands = docker_log.read_text(encoding="utf-8")
    assert " run --rm migrate" not in commands
    assert " up -d " not in commands


def test_target_ports_cannot_drop_current_production_ingress(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        current_ports={
            "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
            "8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}],
        },
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "ingress" in process.stderr.lower()
    assert not backup_log.exists()
    assert " run --rm migrate" not in docker_log.read_text(encoding="utf-8")


def test_compose_targets_must_match_nginx_listeners(tmp_path: Path) -> None:
    environment, backup_log, docker_log = _activation_environment(
        tmp_path,
        compose_contract=_compose_contract(published=8081, target=8081),
        current_ports={"8081/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8081"}]},
    )

    process = _activate(environment)

    assert process.returncode != 0
    assert "listener" in process.stderr.lower()
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
