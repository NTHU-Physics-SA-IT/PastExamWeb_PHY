from __future__ import annotations

import os
from pathlib import Path
import subprocess


REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "dev-compose.sh"


def _script_command(action: str) -> list[str]:
    if os.name == "nt":
        bash = Path(os.environ["ProgramFiles"]) / "Git" / "bin" / "bash.exe"
        assert bash.is_file()
        return [str(bash), str(SCRIPT), action]
    return [str(SCRIPT), action]


def _environment(tmp_path: Path, *, audit_exit: int = 0) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    state = tmp_path / "backend-state"
    state.write_text("running", encoding="utf-8")

    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
if [[ "$1 $2" == "context show" ]]; then
  printf 'default\n'
elif [[ "$1" == "ps" ]]; then
  printf '%s\n' "${FAKE_DOCKER_WORKDIR:-$FAKE_REPO_ROOT/docker}"
elif [[ "$1" == "inspect" ]]; then
  name="${@: -1}"
  if [[ "$name" == "pastexam-dev-postgres" ]]; then
    printf '/pastexam-dev-postgres|pastexam-dev|db|running|healthy\n'
  else
    current="$(cat "$FAKE_BACKEND_STATE")"
    if [[ "$current" == "running" ]]; then
      printf '/pastexam-dev-backend|pastexam-dev|backend|running|healthy\n'
    else
      printf '/pastexam-dev-backend|pastexam-dev|backend|exited|\n'
    fi
  fi
elif [[ "$1 $2" == "compose stop" || "$*" == *" stop backend"* ]]; then
  printf 'exited' > "$FAKE_BACKEND_STATE"
elif [[ "$1 $2" == "compose start" || "$*" == *" start backend"* ]]; then
  printf 'running' > "$FAKE_BACKEND_STATE"
fi
""",
        encoding="utf-8",
    )
    docker.chmod(0o700)

    audit_python = tmp_path / "audit-python"
    audit_python.write_text(
        "#!/bin/sh\n"
        "printf 'status=complete\\nexplicit_rollback=true\\n'\n"
        f"exit {audit_exit}\n",
        encoding="utf-8",
    )
    audit_python.chmod(0o700)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "COMPOSE_PROJECT_NAME=pastexam-dev",
                "POSTGRES_DB=archive_db",
                "MINIO_BUCKET_NAME=archive-bucket",
                "DEV_HTTP_PORT=8080",
                "POSTGRES_VOLUME_NAME=pastexam-postgres-data",
                "MINIO_VOLUME_NAME=pastexam-minio-data",
                "REDIS_VOLUME_NAME=pastexam-redis-data",
                "TARGET_NETWORK_NAME=pastexam-dev-network",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{environment['PATH']}",
            "FAKE_DOCKER_LOG": str(log),
            "FAKE_BACKEND_STATE": str(state),
            "FAKE_REPO_ROOT": str(REPOSITORY_ROOT),
            "PASTEXAM_DEV_COMPOSE_ENV_FILE": str(env_file),
            "PASTEXAM_DEV_AUDIT_PYTHON": str(audit_python),
        }
    )
    environment.pop("DOCKER_HOST", None)
    return environment


def test_schema_status_uses_sealed_audit_without_compose_mutation(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    process = subprocess.run(
        _script_command("schema-status"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )

    assert process.returncode == 0
    assert "status=complete" in process.stdout
    log = Path(environment["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert " stop " not in log
    assert " start " not in log
    assert " up " not in log


def test_preflight_accepts_equivalent_backslash_checkout_path(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    environment["FAKE_DOCKER_WORKDIR"] = str(REPOSITORY_ROOT / "docker").replace(
        "/", "\\"
    )

    process = subprocess.run(
        _script_command("preflight"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )

    assert process.returncode == 0
    assert "project=pastexam-dev" in process.stdout


def test_backend_resume_refuses_when_schema_audit_fails(tmp_path: Path) -> None:
    environment = _environment(tmp_path, audit_exit=2)
    Path(environment["FAKE_BACKEND_STATE"]).write_text("exited", encoding="utf-8")
    process = subprocess.run(
        _script_command("backend-resume"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )

    assert process.returncode != 0
    log = Path(environment["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert " start backend" not in log


def test_backend_pause_and_guarded_resume_use_existing_service(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)

    pause = subprocess.run(
        _script_command("backend-pause"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )
    resume = subprocess.run(
        _script_command("backend-resume"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )

    assert pause.returncode == 0
    assert resume.returncode == 0
    assert "backend=running/healthy" in resume.stdout
    log = Path(environment["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert " stop backend" in log
    assert " start backend" in log
    assert " up " not in log
