from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

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


def initialize_authority_pair(parent: Path) -> tuple[Path, Path]:
    parent.mkdir()
    canonical_root = parent / "canonical"
    subject_root = parent / "subject"
    canonical_root.mkdir()
    script = canonical_root / "scripts" / "dev-compose.sh"
    script.parent.mkdir()
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=canonical_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "scripts/dev-compose.sh"],
        cwd=canonical_root,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Runner Contract",
            "-c",
            "user.email=runner@example.invalid",
            "commit",
            "-m",
            "test fixture",
        ],
        cwd=canonical_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "worktree", "add", "-b", "fix/subject", str(subject_root)],
        cwd=canonical_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return canonical_root, subject_root


def schema_status(
    *,
    checksum: str = "state-checksum",
    expected_ledger: str = "d4b7e2a9c6f1",
) -> str:
    return "\n".join(
        (
            "audit=archive-submission-self-delete-eligibility@4",
            "status=complete",
            f"expected_ledger={expected_ledger}",
            "explicit_rollback=true",
            (
                "aggregates=total:30,active:26,deleted:4,"
                "created_archive_id_non_null:19,created_archive_id_null:11,"
                "max_created_archive_cardinality:1,"
                "dangling_created_archive_links:0,"
                "created_archive_link_checksum:link-checksum,"
                f"submission_state_checksum:{checksum}"
            ),
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
        docker_run_timeout: bool = False,
        post_checksum: str = "state-checksum",
        volume_mount: bool = False,
        schema_expected_ledger: str | None = None,
        isolated_head: str | None = None,
        subject_dirty: bool = False,
    ) -> None:
        self.pytest_exit = pytest_exit
        self.migration_exit = migration_exit
        self.bootstrap_exit = bootstrap_exit
        self.image_exit = image_exit
        self.cleanup_exit = cleanup_exit
        self.docker_run_timeout = docker_run_timeout
        self.post_checksum = post_checksum
        self.volume_mount = volume_mount
        self.schema_expected_ledger = schema_expected_ledger
        self.isolated_head = isolated_head
        self.subject_dirty = subject_dirty
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
            return runner_module.CommandResult(
                0,
                " M subject-change\n" if self.subject_dirty else "",
            )
        if command[:2] == ("docker", "inspect") and command[-1] in {
            POSTGRES_ID,
            BACKEND_ID,
        }:
            return runner_module.CommandResult(0, inspect_payload(command[-1]))
        if "schema-status" in command:
            self.schema_calls += 1
            checksum = self.post_checksum if self.schema_calls > 1 else "state-checksum"
            expected_ledger = self.schema_expected_ledger or (
                command[command.index("--expected-ledger") + 1]
                if "--expected-ledger" in command
                else runner_module.EPHEMERAL_TARGET_HEAD
            )
            return runner_module.CommandResult(
                0,
                schema_status(
                    checksum=checksum,
                    expected_ledger=expected_ledger,
                ),
            )
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
            if self.docker_run_timeout:
                raise subprocess.TimeoutExpired(command, timeout)
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
                return runner_module.CommandResult(
                    0,
                    f"{self.isolated_head or runner_module.EPHEMERAL_TARGET_HEAD}\n",
                )
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


def args(
    *pytest_args: str,
    canonical_expected_ledger: str = "d4b7e2a9c6f1",
    canonical_authority_root: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        postgres_container_id=POSTGRES_ID,
        backend_container_id=BACKEND_ID,
        canonical_expected_ledger=canonical_expected_ledger,
        canonical_authority_root=canonical_authority_root,
        output="json",
        pytest_args=list(
            pytest_args or ("backend/tests/unit/test_submission_decision.py", "-q")
        ),
    )


def run(
    fake: FakeExecutor,
    *pytest_args: str,
    canonical_expected_ledger: str = "d4b7e2a9c6f1",
    canonical_authority_root: str | None = None,
):
    runner = runner_module.IsolatedPostgresRunner(
        args(
            *pytest_args,
            canonical_expected_ledger=canonical_expected_ledger,
            canonical_authority_root=canonical_authority_root,
        ),
        executor=fake,
    )
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
    assert payload["schema_version"] == 2
    assert payload["canonical_expected_ledger"] == "d4b7e2a9c6f1"
    assert payload["ephemeral_target_head"] == runner_module.HEAD_SCHEMA_REVISION
    assert payload["migration_head"] == runner_module.HEAD_SCHEMA_REVISION
    assert all(payload["cleanup"].values())


def test_runner_uses_canonical_schema_manifest_head() -> None:
    assert runner_module.EPHEMERAL_TARGET_HEAD == runner_module.HEAD_SCHEMA_REVISION


def test_explicit_canonical_baseline_is_distinct_from_ephemeral_target() -> None:
    parsed = runner_module.parse_args(
        [
            "--postgres-container-id",
            POSTGRES_ID,
            "--backend-container-id",
            BACKEND_ID,
            "--canonical-authority-root",
            "/canonical/main",
            "--canonical-expected-ledger",
            "c2a8e4f6b9d1",
            "--",
            "backend/tests/unit/test_submission_decision.py",
        ]
    )

    assert parsed.canonical_expected_ledger == "c2a8e4f6b9d1"
    assert parsed.canonical_authority_root == "/canonical/main"
    assert runner_module.EPHEMERAL_TARGET_HEAD == runner_module.HEAD_SCHEMA_REVISION


def test_ephemeral_target_head_has_no_cli_override() -> None:
    with pytest.raises(SystemExit):
        runner_module.parse_args(
            [
                "--postgres-container-id",
                POSTGRES_ID,
                "--backend-container-id",
                BACKEND_ID,
                "--ephemeral-target-head",
                "c2a8e4f6b9d1",
                "--",
                "backend/tests/unit/test_submission_decision.py",
            ]
        )


def test_unknown_and_nonancestor_canonical_baselines_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(runner_module.RunnerFailure, match="malformed"):
        runner_module.validate_canonical_expected_ledger("bad")

    with pytest.raises(runner_module.RunnerFailure, match="reviewed"):
        runner_module.validate_canonical_expected_ledger("ffffffffffff")

    monkeypatch.setattr(
        runner_module,
        "is_revision_ancestor",
        lambda *_args, **_kwargs: False,
    )
    with pytest.raises(runner_module.RunnerFailure, match="ancestor"):
        runner_module.validate_canonical_expected_ledger("c2a8e4f6b9d1")


def test_invalid_baselines_are_rejected_before_ephemeral_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown = FakeExecutor()
    unknown_runner = run(
        unknown,
        canonical_expected_ledger="ffffffffffff",
    )
    assert unknown_runner.evidence.exit_code == 20
    assert not any(command[:2] == ("docker", "run") for command in unknown.commands)

    monkeypatch.setattr(
        runner_module,
        "is_revision_ancestor",
        lambda *_args, **_kwargs: False,
    )
    nonancestor = FakeExecutor()
    nonancestor_runner = run(
        nonancestor,
        canonical_expected_ledger="c2a8e4f6b9d1",
    )
    assert nonancestor_runner.evidence.exit_code == 20
    assert not any(command[:2] == ("docker", "run") for command in nonancestor.commands)


def test_older_canonical_baseline_never_changes_ephemeral_target() -> None:
    fake = FakeExecutor()
    runner = run(fake, canonical_expected_ledger="c2a8e4f6b9d1")

    assert runner.evidence.exit_code == 0
    assert runner.evidence.canonical_expected_ledger == "c2a8e4f6b9d1"
    assert runner.evidence.canonical_pre["alembic_head"] == "c2a8e4f6b9d1"
    assert runner.evidence.migration_head == runner_module.EPHEMERAL_TARGET_HEAD


def test_persistent_baseline_and_ephemeral_head_mismatches_fail_closed() -> None:
    persistent_mismatch = run(FakeExecutor(schema_expected_ledger="c2a8e4f6b9d1"))
    assert persistent_mismatch.evidence.exit_code == 20
    assert persistent_mismatch.evidence.generated_resource_name is None

    ephemeral_mismatch = run(FakeExecutor(isolated_head="c2a8e4f6b9d1"))
    assert ephemeral_mismatch.evidence.exit_code == 21
    assert ephemeral_mismatch.evidence.migration_status == "not_started"
    assert ephemeral_mismatch.evidence.cleanup["container_absent"] is True


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


def test_dev_compose_command_passes_exact_canonical_baseline() -> None:
    command = runner_module.dev_compose_command(
        "schema-status", expected_ledger="c2a8e4f6b9d1"
    )

    assert command[-3:] == (
        "schema-status",
        "--expected-ledger",
        "c2a8e4f6b9d1",
    )


def test_registered_clean_main_authority_is_accepted_and_selects_its_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    canonical_root, subject_root = initialize_authority_pair(tmp_path / "valid")
    monkeypatch.setattr(runner_module, "REPOSITORY_ROOT", subject_root)

    resolved = runner_module.validate_canonical_authority_root(
        runner_module.CommandExecutor(),
        str(canonical_root),
    )
    command = runner_module.dev_compose_command(
        "schema-status",
        canonical_authority_root=resolved,
        expected_ledger="f3a7c1e9d5b2",
    )

    assert resolved == canonical_root
    assert str(canonical_root / "scripts" / "dev-compose.sh") in command
    assert command[-3:] == (
        "schema-status",
        "--expected-ledger",
        "f3a7c1e9d5b2",
    )


def test_external_authority_rejects_relative_nonworktree_and_other_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _canonical_root, subject_root = initialize_authority_pair(tmp_path / "subject")
    other_root, _other_subject = initialize_authority_pair(tmp_path / "other")
    nonworktree = tmp_path / "nonworktree"
    script = nonworktree / "scripts" / "dev-compose.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(runner_module, "REPOSITORY_ROOT", subject_root)
    executor = runner_module.CommandExecutor()

    with pytest.raises(runner_module.RunnerFailure, match="must be absolute"):
        runner_module.validate_canonical_authority_root(executor, "relative/path")
    with pytest.raises(runner_module.RunnerFailure, match="not a Git worktree"):
        runner_module.validate_canonical_authority_root(executor, str(nonworktree))
    with pytest.raises(runner_module.RunnerFailure, match="another repository"):
        runner_module.validate_canonical_authority_root(executor, str(other_root))


def test_external_authority_rejects_unregistered_copy_and_non_main_worktree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    canonical_root, subject_root = initialize_authority_pair(tmp_path / "registered")
    copied_root = tmp_path / "copied"
    shutil.copytree(subject_root, copied_root)
    monkeypatch.setattr(runner_module, "REPOSITORY_ROOT", subject_root)
    executor = runner_module.CommandExecutor()

    with pytest.raises(runner_module.RunnerFailure, match="not a registered worktree"):
        runner_module.validate_canonical_authority_root(executor, str(copied_root))
    with pytest.raises(runner_module.RunnerFailure, match="registered main worktree"):
        runner_module.validate_canonical_authority_root(executor, str(subject_root))

    assert canonical_root.exists()


def test_external_authority_rejects_dirty_ambiguous_and_missing_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    canonical_root, subject_root = initialize_authority_pair(tmp_path / "safety")
    monkeypatch.setattr(runner_module, "REPOSITORY_ROOT", subject_root)
    executor = runner_module.CommandExecutor()

    ambiguous_root = tmp_path / "canonical-link"
    ambiguous_root.symlink_to(canonical_root, target_is_directory=True)
    with pytest.raises(runner_module.RunnerFailure, match="path is ambiguous"):
        runner_module.validate_canonical_authority_root(executor, str(ambiguous_root))

    dirty_path = canonical_root / "dirty.txt"
    dirty_path.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(runner_module.RunnerFailure, match="must be clean"):
        runner_module.validate_canonical_authority_root(executor, str(canonical_root))
    dirty_path.unlink()

    wrapper = canonical_root / "scripts" / "dev-compose.sh"
    wrapper.unlink()
    with pytest.raises(runner_module.RunnerFailure, match="unavailable"):
        runner_module.validate_canonical_authority_root(executor, str(canonical_root))


def test_external_authority_selects_canonical_dev_compose_for_pre_and_post(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    monkeypatch.setattr(
        runner_module,
        "validate_canonical_authority_root",
        lambda _executor, value: Path(value).resolve(),
    )
    fake = FakeExecutor()

    runner = run(
        fake,
        canonical_authority_root=str(canonical_root),
    )

    schema_commands = [
        command for command in fake.commands if "schema-status" in command
    ]
    expected_script = canonical_root / "scripts" / "dev-compose.sh"
    assert runner.evidence.exit_code == 0
    assert len(schema_commands) == 2
    assert all(str(expected_script) in command for command in schema_commands)
    assert runner.evidence.cleanup["postflight_matches"] is True


def test_dirty_subject_still_fails_before_ephemeral_resource() -> None:
    fake = FakeExecutor(subject_dirty=True)

    runner = run(fake)

    assert runner.evidence.exit_code == 20
    assert runner.evidence.generated_resource_name is None
    assert not any(command[:2] == ("docker", "run") for command in fake.commands)


def test_cleanup_targets_only_exact_generated_resource() -> None:
    fake = FakeExecutor()
    runner = run(fake)
    resource = runner.evidence.generated_resource_name
    assert resource
    assert ("docker", "rm", "-f", resource) in fake.commands
    assert not any("compose" in command for command in fake.commands)
    assert not any("*" in " ".join(command) for command in fake.commands)


def test_docker_run_timeout_cleans_exact_created_resource() -> None:
    fake = FakeExecutor(docker_run_timeout=True)
    runner = run(fake)
    resource = runner.evidence.generated_resource_name

    assert runner.evidence.exit_code == 21
    assert resource
    assert ("docker", "rm", "-f", resource) in fake.commands
    assert fake.removed is True
    assert runner.evidence.cleanup["container_removed"] is True
    assert runner.evidence.cleanup["container_absent"] is True


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
    runner = run(fake, *supplied)
    assert runner.evidence.exit_code == 0
    command = next(item for item in fake.commands if "-m" in item and "pytest" in item)
    assert command[3 : 3 + len(supplied)] == supplied
    if os.name == "nt":
        assert command[-2] == "--basetemp"
        assert Path(command[-1]).parent == runner.temp_dir
    else:
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
