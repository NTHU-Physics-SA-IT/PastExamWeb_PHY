from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "run-isolated-backend-tests.py"
SPEC = importlib.util.spec_from_file_location("isolated_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner_module
SPEC.loader.exec_module(runner_module)

POSTGRES_ID = "a" * 64
BACKEND_ID = "b" * 64


def schema_status(*, checksum: str = "state-checksum") -> str:
    return "\n".join(
        (
            "audit=archive-submission-self-delete-eligibility@3",
            "status=complete",
            "expected_ledger=9f1c2a7e4b63",
            "explicit_rollback=true",
            "aggregates=total:30,active:26,deleted:4,"
            "created_archive_id_non_null:19,created_archive_id_null:11,"
            "max_created_archive_cardinality:1,dangling_created_archive_links:0,"
            "created_archive_link_checksum:link-checksum,"
            f"submission_state_checksum:{checksum}",
        )
    )


def inspect_payload(container_id: str, *, volume: bool = False) -> str:
    return json.dumps(
        [
            {
                "Id": container_id,
                "RestartCount": 0,
                "State": {
                    "Status": "running",
                    "Health": {"Status": "healthy"},
                    "OOMKilled": False,
                },
                "Image": "sha256:image",
                "HostConfig": {
                    "Tmpfs": {"/var/lib/postgresql/data": "rw,nosuid,nodev"}
                },
                "Mounts": (
                    [{"Type": "volume", "Destination": "/var/lib/postgresql/data"}]
                    if volume
                    else []
                ),
                "NetworkSettings": {
                    "Ports": {
                        "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49152"}]
                    }
                },
            }
        ]
    )


class FakeExecutor:
    def __init__(
        self,
        *,
        pytest_exit: int = 0,
        migration_exit: int = 0,
        bootstrap_exit: int = 0,
        image_exit: int = 0,
        cleanup_exit: int = 0,
        post_checksum: str = "state-checksum",
        volume_mount: bool = False,
    ) -> None:
        self.pytest_exit = pytest_exit
        self.migration_exit = migration_exit
        self.bootstrap_exit = bootstrap_exit
        self.image_exit = image_exit
        self.cleanup_exit = cleanup_exit
        self.post_checksum = post_checksum
        self.volume_mount = volume_mount
        self.commands: list[tuple[str, ...]] = []
        self.inputs: list[str] = []
        self.schema_calls = 0
        self.created = False
        self.removed = False

    def run(
        self,
        args,
        *,
        cwd=REPOSITORY_ROOT,
        env=None,
        input_text=None,
        timeout=60,
    ):
        command = tuple(str(item) for item in args)
        self.commands.append(command)
        if input_text:
            self.inputs.append(input_text)
        if command[:2] == ("git", "status"):
            return runner_module.CommandResult(0, "")
        if command[:2] == ("docker", "inspect") and command[-1] in {
            POSTGRES_ID,
            BACKEND_ID,
        }:
            return runner_module.CommandResult(0, inspect_payload(command[-1]))
        if command[-1:] == ("schema-status",):
            self.schema_calls += 1
            checksum = self.post_checksum if self.schema_calls > 1 else "state-checksum"
            return runner_module.CommandResult(0, schema_status(checksum=checksum))
        if command[:3] == ("docker", "image", "inspect"):
            return runner_module.CommandResult(self.image_exit, "sha256:image\n")
        if command[:2] == ("docker", "ps"):
            return runner_module.CommandResult(
                0, "container\n" if self.created and not self.removed else ""
            )
        if command[:3] == ("docker", "volume", "ls"):
            return runner_module.CommandResult(0, "")
        if command[:2] == ("docker", "run"):
            self.created = True
            return runner_module.CommandResult(0, "ephemeral-id\n")
        if command[:2] == ("docker", "inspect"):
            return runner_module.CommandResult(
                0, inspect_payload("ephemeral-id", volume=self.volume_mount)
            )
        if command[:2] == ("docker", "logs"):
            return runner_module.CommandResult(
                0,
                "PostgreSQL init process complete; ready for start up.\n",
            )
        if command[:2] == ("docker", "exec") and "pg_isready" in command:
            return runner_module.CommandResult(0, "accepting connections\n")
        if command[:2] == ("docker", "exec") and "psql" in command:
            sql = input_text or ""
            if "SELECT version_num FROM alembic_version" in sql:
                return runner_module.CommandResult(0, "9f1c2a7e4b63\n")
            if "CREATE ROLE" in sql:
                return runner_module.CommandResult(self.bootstrap_exit, "")
            database = next(
                item.split("=", 1)[1]
                for item in command
                if item.startswith("test_database=")
            )
            role = next(
                item.split("=", 1)[1]
                for item in command
                if item.startswith("test_role=")
            )
            return runner_module.CommandResult(0, f"{database}|{role}|t|f|f|f|f|f|1\n")
        if command[:2] == ("docker", "rm"):
            self.removed = self.cleanup_exit == 0
            return runner_module.CommandResult(self.cleanup_exit, "")
        if "migrate.py" in command:
            return runner_module.CommandResult(
                self.migration_exit,
                "{}" if self.migration_exit == 0 else "",
                "migration-secret" if self.migration_exit else "",
            )
        if "-m" in command and "pytest" in command:
            assert str(runner_module.BACKEND_ROOT) in (env or {}).get(
                "PYTHONPATH", ""
            ).split(runner_module.os.pathsep)
            return runner_module.CommandResult(
                self.pytest_exit,
                "tests complete",
                (env or {}).get("TEST_DATABASE_URL", "") if self.pytest_exit else "",
            )
        raise AssertionError(f"unexpected command: {command}")


def args(*pytest_args: str) -> argparse.Namespace:
    return argparse.Namespace(
        postgres_container_id=POSTGRES_ID,
        backend_container_id=BACKEND_ID,
        output="json",
        pytest_args=list(
            pytest_args or ("backend/tests/unit/test_submission_decision.py", "-q")
        ),
    )


def run(fake: FakeExecutor, *pytest_args: str):
    runner = runner_module.IsolatedPostgresRunner(args(*pytest_args), executor=fake)
    runner.execute()
    return runner


def test_invalid_invocation_rejects_empty_pytest_arguments() -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--postgres-container-id",
            POSTGRES_ID,
            "--backend-container-id",
            BACKEND_ID,
            "--",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 2


def test_success_has_stable_json_and_complete_cleanup() -> None:
    runner = run(FakeExecutor())
    payload = json.loads(json.dumps(runner_module.asdict(runner.evidence)))
    assert runner.evidence.exit_code == 0
    assert payload["schema_version"] == 1
    assert payload["migration_head"] == "9f1c2a7e4b63"
    assert all(payload["cleanup"].values())


@pytest.mark.parametrize(
    ("fake", "exit_code"),
    (
        (FakeExecutor(pytest_exit=1), 22),
        (FakeExecutor(migration_exit=1), 21),
        (FakeExecutor(bootstrap_exit=1), 21),
        (FakeExecutor(image_exit=1), 21),
        (FakeExecutor(cleanup_exit=1), 24),
        (FakeExecutor(post_checksum="changed"), 24),
        (FakeExecutor(volume_mount=True), 21),
    ),
)
def test_failure_and_cleanup_exit_codes(fake: FakeExecutor, exit_code: int) -> None:
    assert run(fake).evidence.exit_code == exit_code


def test_signal_exit_codes_are_stable() -> None:
    assert runner_module.RunnerInterrupted(signal.SIGINT).exit_code == 130
    assert runner_module.RunnerInterrupted(signal.SIGTERM).exit_code == 143


def test_signal_handlers_use_only_signals_supported_by_the_platform() -> None:
    runner = runner_module.IsolatedPostgresRunner(args(), executor=FakeExecutor())

    previous = runner.install_signal_handlers()
    try:
        expected = {signal.SIGINT, signal.SIGTERM}
        if hasattr(signal, "SIGHUP"):
            expected.add(signal.SIGHUP)
        assert set(previous) == expected
    finally:
        runner.restore_signal_handlers(previous)


def test_backend_python_path_matches_the_platform_virtualenv_layout() -> None:
    expected = (
        REPOSITORY_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else REPOSITORY_ROOT / "backend" / ".venv" / "bin" / "python"
    )
    assert runner_module.BACKEND_PYTHON == expected


def test_dev_compose_command_matches_the_platform_execution_boundary() -> None:
    command = runner_module.dev_compose_command("schema-status")

    assert command[-1] == "schema-status"
    if os.name == "nt":
        assert Path(command[0]).name == "bash.exe"
        assert Path(command[1]) == runner_module.DEV_COMPOSE
    else:
        assert command == (str(runner_module.DEV_COMPOSE), "schema-status")


def test_cleanup_targets_only_exact_generated_resource() -> None:
    fake = FakeExecutor()
    runner = run(fake)
    resource = runner.evidence.generated_resource_name
    assert resource
    assert ("docker", "rm", "-f", resource) in fake.commands
    assert not any("compose" in command for command in fake.commands)
    assert not any("*" in " ".join(command) for command in fake.commands)


def test_docker_run_is_loopback_tmpfs_pull_never_without_volume() -> None:
    fake = FakeExecutor()
    run(fake)
    command = next(item for item in fake.commands if item[:2] == ("docker", "run"))
    assert "--pull=never" in command
    assert "127.0.0.1::5432" in command
    assert "/var/lib/postgresql/data:rw,nosuid,nodev" in command
    assert "--volume" not in command
    assert "-v" not in command


def test_readiness_requires_completed_image_initialization_before_bootstrap() -> None:
    fake = FakeExecutor()
    run(fake)
    logs_index = next(
        index
        for index, command in enumerate(fake.commands)
        if command[:2] == ("docker", "logs")
    )
    ready_index = next(
        index
        for index, command in enumerate(fake.commands)
        if command[:2] == ("docker", "exec") and "pg_isready" in command
    )
    bootstrap_index = next(
        index
        for index, command in enumerate(fake.commands)
        if command[:2] == ("docker", "exec") and "psql" in command
    )
    assert logs_index < bootstrap_index
    assert ready_index < bootstrap_index


def test_generated_role_database_and_privilege_contract() -> None:
    fake = FakeExecutor()
    run(fake)
    bootstrap = next(item for item in fake.inputs if "CREATE ROLE" in item)
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in bootstrap
    assert any("pastexam_test_" in " ".join(item) for item in fake.commands)


def test_secrets_are_redacted_from_serialized_evidence() -> None:
    fake = FakeExecutor(pytest_exit=1)
    runner = run(fake)
    serialized = json.dumps(runner_module.asdict(runner.evidence))
    assert "postgresql+asyncpg://" in serialized
    assert all(secret not in serialized for secret in runner.secrets_to_mask)
    assert "[REDACTED]" in serialized


def test_pytest_arguments_are_direct_argument_vector() -> None:
    fake = FakeExecutor()
    supplied = (
        "backend/tests/api/test_archives.py::test_name",
        "-q",
        "-k",
        "literal;not-a-shell",
    )
    assert run(fake, *supplied).evidence.exit_code == 0
    command = next(item for item in fake.commands if "-m" in item and "pytest" in item)
    assert command[-len(supplied) :] == supplied


def test_temporary_credentials_are_removed() -> None:
    runner = run(FakeExecutor())
    assert runner.temp_dir is not None
    assert not runner.temp_dir.exists()
    assert runner.evidence.cleanup["credentials_removed"] is True


def test_source_has_no_shell_eval_compose_or_broad_cleanup() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "docker compose" not in source
    assert "eval(" not in source
    assert "docker volume prune" not in source
    assert "docker system prune" not in source
