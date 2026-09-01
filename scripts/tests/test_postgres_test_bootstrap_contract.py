from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).parents[2]
DEV_COMPOSE = REPOSITORY_ROOT / "docker" / "docker-compose.dev.yml"
PROD_COMPOSE = REPOSITORY_ROOT / "docker" / "docker-compose.prod.yml"
INIT_SCRIPT = REPOSITORY_ROOT / "docker" / "postgres" / "init-isolated-roles.sh"
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
VERIFY_SCRIPT = (
    REPOSITORY_ROOT / "scripts" / "ci" / "verify-isolated-test-database.sh"
)


def _backend_job() -> str:
    workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
    return workflow.split("\n  backend:\n", maxsplit=1)[1].split(
        "\n  frontend-unit:\n", maxsplit=1
    )[0]


def _example_environment_value(name: str) -> str:
    environment = (REPOSITORY_ROOT / "docker" / ".env.example").read_text(
        encoding="utf-8"
    )
    prefix = f"{name}="
    return next(
        line.removeprefix(prefix)
        for line in environment.splitlines()
        if line.startswith(prefix)
    )


def test_frontend_e2e_bootstrap_password_matches_playwright_password() -> None:
    workflow = yaml.load(TEST_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["frontend-e2e-family"]["steps"]
    }
    bootstrap_password = _example_environment_value("BOOTSTRAP_ADMIN_PASSWORD")

    assert bootstrap_password
    for step_name in (
        "List selected frontend E2E cases",
        "Run frontend E2E tests",
    ):
        assert steps[step_name]["env"]["PLAYWRIGHT_ADMIN_PASSWORD"] == bootstrap_password


def test_dev_postgres_healthcheck_requires_final_tcp_server() -> None:
    compose = DEV_COMPOSE.read_text(encoding="utf-8")

    assert (
        'pg_isready -h 127.0.0.1 -U $$POSTGRES_USER -d $$POSTGRES_DB'
        in compose
    )


def test_backend_ci_is_verify_only_and_init_script_is_the_single_creator() -> None:
    backend_job = _backend_job()
    init_script = INIT_SCRIPT.read_text(encoding="utf-8")

    assert "name: Verify isolated test database" in backend_job
    assert "scripts/ci/verify-isolated-test-database.sh" in backend_job
    for creator in ("dropdb", "createdb", "CREATE DATABASE", "DROP DATABASE"):
        assert creator not in backend_job
    assert "CREATE DATABASE %I OWNER %I" in init_script


def test_production_compose_has_no_test_bootstrap_contract() -> None:
    production = PROD_COMPOSE.read_text(encoding="utf-8")

    assert "init-isolated-roles.sh" not in production
    assert "TEST_DB_USER" not in production
    assert "TEST_DB_PASSWORD" not in production
    assert "TEST_DATABASE_NAME" not in production


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


def _run_verifier(
    tmp_path: Path,
    *,
    metadata: str = (
        "pastexam_test_local|pastexam_test_local|t|f|f|f|f|f|t|t|f"
    ),
    identity: str = "pastexam_test_local|pastexam_test_local",
    readiness_exit: int = 0,
    admin_query_exit: int = 0,
    test_connect_exit: int = 0,
    unset_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "pg_isready",
        "#!/bin/sh\n"
        'exit "${FAKE_READINESS_EXIT}"\n',
    )
    _write_executable(
        bin_dir / "psql",
        """#!/bin/sh
set -eu
test_connection=false
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--username" ]; then
    shift
    [ "${1:-}" = "$TEST_DB_USER" ] && test_connection=true
  fi
  shift
done
if [ "$test_connection" = true ]; then
  [ "$FAKE_TEST_CONNECT_EXIT" -eq 0 ] || exit "$FAKE_TEST_CONNECT_EXIT"
  printf '%s\n' "$FAKE_IDENTITY"
else
  [ "$FAKE_ADMIN_QUERY_EXIT" -eq 0 ] || exit "$FAKE_ADMIN_QUERY_EXIT"
  printf '%s\n' "$FAKE_METADATA"
fi
""",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "POSTGRES_USER": "pgadmin",
            "POSTGRES_PASSWORD": "admin-password-must-not-leak",
            "POSTGRES_DB": "archive_db",
            "MIGRATOR_DB_USER": "pastexam_migrator_local",
            "TEST_DB_USER": "pastexam_test_local",
            "TEST_DB_PASSWORD": "test-password-must-not-leak",
            "TEST_DATABASE_NAME": "pastexam_test_local",
            "FAKE_METADATA": metadata,
            "FAKE_IDENTITY": identity,
            "FAKE_READINESS_EXIT": str(readiness_exit),
            "FAKE_ADMIN_QUERY_EXIT": str(admin_query_exit),
            "FAKE_TEST_CONNECT_EXIT": str(test_connect_exit),
        }
    )
    if unset_name is not None:
        environment.pop(unset_name)
    return subprocess.run(
        [str(VERIFY_SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def test_verifier_accepts_exact_database_role_and_connect_contract(
    tmp_path: Path,
) -> None:
    process = _run_verifier(tmp_path)

    assert process.returncode == 0
    assert "Isolated test database verification passed" in process.stdout
    assert "admin-password-must-not-leak" not in process.stdout + process.stderr
    assert "test-password-must-not-leak" not in process.stdout + process.stderr


@pytest.mark.parametrize(
    "metadata",
    (
        "",
        "pastexam_test_local|wrong_owner|t|f|f|f|f|f|t|t|f",
        "pastexam_test_local|pastexam_test_local|f|f|f|f|f|f|t|t|f",
        "pastexam_test_local|pastexam_test_local|t|t|f|f|f|f|t|t|f",
        "pastexam_test_local|pastexam_test_local|t|f|t|f|f|f|t|t|f",
        "pastexam_test_local|pastexam_test_local|t|f|f|t|f|f|t|t|f",
        "pastexam_test_local|pastexam_test_local|t|f|f|f|t|f|t|t|f",
        "pastexam_test_local|pastexam_test_local|t|f|f|f|f|t|t|t|f",
        "pastexam_test_local|pastexam_test_local|t|f|f|f|f|f|f|t|f",
        "pastexam_test_local|pastexam_test_local|t|f|f|f|f|f|t|f|f",
        "pastexam_test_local|pastexam_test_local|t|f|f|f|f|f|t|t|t",
    ),
)
def test_verifier_rejects_missing_or_privileged_database_contract(
    tmp_path: Path,
    metadata: str,
) -> None:
    assert _run_verifier(tmp_path, metadata=metadata).returncode != 0


@pytest.mark.parametrize(
    ("overrides"),
    (
        {"identity": "wrong_database|pastexam_test_local"},
        {"identity": "pastexam_test_local|wrong_role"},
        {"readiness_exit": 1},
        {"admin_query_exit": 2},
        {"test_connect_exit": 2},
        {"unset_name": "TEST_DATABASE_NAME"},
    ),
)
def test_verifier_fails_closed_on_connection_identity_or_command_error(
    tmp_path: Path,
    overrides: dict[str, str | int],
) -> None:
    assert _run_verifier(tmp_path, **overrides).returncode != 0


def test_verifier_contains_no_database_repair_commands() -> None:
    verifier = VERIFY_SCRIPT.read_text(encoding="utf-8")

    for mutation in (r"\bdropdb\b", r"\bcreatedb\b", "CREATE DATABASE", "DROP DATABASE"):
        assert re.search(mutation, verifier) is None
