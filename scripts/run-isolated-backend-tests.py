#!/usr/bin/env python3
"""Run focused backend tests against one guarded ephemeral PostgreSQL."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from typing import Any, Sequence
from urllib.parse import quote


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
BACKEND_PYTHON = (
    BACKEND_ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt"
    else BACKEND_ROOT / ".venv" / "bin" / "python"
)
DEV_COMPOSE = REPOSITORY_ROOT / "scripts" / "dev-compose.sh"
POSTGRES_IMAGE = "postgres:15.14-alpine3.22"
EXPECTED_ALEMBIC_HEAD = "b7e3d9a1c5f2"
NAME_PREFIX = "pastexam-test-postgres-s5a-"
ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class RunnerFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class RunnerInterrupted(RunnerFailure):
    def __init__(self, signum: int) -> None:
        super().__init__(
            f"interrupted by signal {signum}",
            130 if signum == signal.SIGINT else 143,
        )


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandExecutor:
    """Injectable subprocess boundary. Commands are always argument vectors."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path = REPOSITORY_ROOT,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
        timeout: float = 60,
    ) -> CommandResult:
        process = subprocess.run(
            list(args),
            cwd=cwd,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            shell=False,
        )
        return CommandResult(process.returncode, process.stdout, process.stderr)


def dev_compose_command(action: str) -> tuple[str, ...]:
    if os.name != "nt":
        return (str(DEV_COMPOSE), action)

    git_bash = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Git"
        / "bin"
        / "bash.exe"
    )
    if not git_bash.is_file():
        raise RunnerFailure("Git Bash is required on Windows", 20)
    return (str(git_bash), str(DEV_COMPOSE), action)


@dataclass(frozen=True)
class CanonicalSnapshot:
    postgres_id: str
    postgres_state: str
    postgres_health: str
    postgres_restart_count: int
    backend_id: str
    backend_state: str
    backend_health: str
    backend_restart_count: int
    alembic_head: str
    audit: str
    audit_status: str
    explicit_rollback: bool
    total: int
    active: int
    deleted: int
    linked: int
    unlinked: int
    max_cardinality: int
    dangling: int
    link_checksum: str
    state_checksum: str

    @property
    def baseline_digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class Evidence:
    schema_version: int = 1
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    generated_resource_name: str | None = None
    image_identity: str | None = None
    allocated_port: int | None = None
    lifecycle_stage: str = "invocation"
    migration_status: str = "not_started"
    migration_head: str | None = None
    pytest_arguments: list[str] = field(default_factory=list)
    pytest_exit_status: int | None = None
    cleanup: dict[str, bool] = field(
        default_factory=lambda: {
            "container_removed": False,
            "container_absent": False,
            "volume_absent": False,
            "credentials_removed": False,
            "postflight_matches": False,
        }
    )
    canonical_pre: dict[str, Any] | None = None
    canonical_post: dict[str, Any] | None = None
    sealed_baseline_digest: str | None = None
    redaction_count: int = 0
    errors: list[str] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    exit_code: int = 2


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-container-id", required=True)
    parser.add_argument("--backend-container-id", required=True)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.pytest_args and args.pytest_args[0] == "--":
        args.pytest_args = args.pytest_args[1:]
    if not args.pytest_args:
        parser.error("at least one pytest argument is required after --")
    for value in (args.postgres_container_id, args.backend_container_id):
        if not ID_PATTERN.fullmatch(value):
            parser.error("container IDs must be exact 64-character lowercase hex IDs")
    return args


def require(result: CommandResult, message: str, exit_code: int) -> str:
    if result.returncode != 0:
        raise RunnerFailure(message, exit_code)
    return result.stdout.strip()


def container_state(executor: CommandExecutor, container_id: str) -> dict[str, Any]:
    output = require(
        executor.run(("docker", "inspect", container_id), timeout=15),
        "canonical container inspection failed",
        20,
    )
    try:
        item = json.loads(output)[0]
        state = item["State"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RunnerFailure("canonical container inspection was malformed", 20) from exc
    if item.get("Id") != container_id:
        raise RunnerFailure("canonical container identity mismatch", 20)
    return {
        "id": item["Id"],
        "state": str(state.get("Status") or ""),
        "health": str((state.get("Health") or {}).get("Status") or ""),
        "restart_count": int(item.get("RestartCount") or 0),
        "oom_killed": bool(state.get("OOMKilled")),
    }


def parse_schema_status(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    aggregates: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("aggregates="):
            for item in line.removeprefix("aggregates=").split(","):
                key, separator, value = item.partition(":")
                if separator:
                    aggregates[key] = value
        else:
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
    required = {
        "audit",
        "status",
        "expected_ledger",
        "explicit_rollback",
    }
    aggregate_required = {
        "total",
        "active",
        "deleted",
        "created_archive_id_non_null",
        "created_archive_id_null",
        "max_created_archive_cardinality",
        "dangling_created_archive_links",
        "created_archive_link_checksum",
        "submission_state_checksum",
    }
    if not required.issubset(values) or not aggregate_required.issubset(aggregates):
        raise RunnerFailure("sealed schema-status output was incomplete", 20)
    return {**values, **aggregates}


def canonical_snapshot(
    executor: CommandExecutor,
    postgres_id: str,
    backend_id: str,
) -> CanonicalSnapshot:
    postgres = container_state(executor, postgres_id)
    backend = container_state(executor, backend_id)
    if (
        postgres["state"] != "running"
        or postgres["health"] != "healthy"
        or postgres["oom_killed"]
        or backend["oom_killed"]
    ):
        raise RunnerFailure("canonical runtime preflight is not Green", 20)
    schema = parse_schema_status(
        require(
            executor.run(dev_compose_command("schema-status"), timeout=60),
            "sealed schema-status failed",
            20,
        )
    )
    if (
        schema["status"] != "complete"
        or schema["expected_ledger"] != EXPECTED_ALEMBIC_HEAD
        or schema["explicit_rollback"].lower() != "true"
    ):
        raise RunnerFailure("sealed schema baseline is not Green", 20)
    return CanonicalSnapshot(
        postgres_id=postgres["id"],
        postgres_state=postgres["state"],
        postgres_health=postgres["health"],
        postgres_restart_count=postgres["restart_count"],
        backend_id=backend["id"],
        backend_state=backend["state"],
        backend_health=backend["health"],
        backend_restart_count=backend["restart_count"],
        alembic_head=schema["expected_ledger"],
        audit=schema["audit"],
        audit_status=schema["status"],
        explicit_rollback=True,
        total=int(schema["total"]),
        active=int(schema["active"]),
        deleted=int(schema["deleted"]),
        linked=int(schema["created_archive_id_non_null"]),
        unlinked=int(schema["created_archive_id_null"]),
        max_cardinality=int(schema["max_created_archive_cardinality"]),
        dangling=int(schema["dangling_created_archive_links"]),
        link_checksum=schema["created_archive_link_checksum"],
        state_checksum=schema["submission_state_checksum"],
    )


def public_snapshot(snapshot: CanonicalSnapshot) -> dict[str, Any]:
    return {
        "postgres_id": snapshot.postgres_id,
        "postgres_state": snapshot.postgres_state,
        "postgres_health": snapshot.postgres_health,
        "postgres_restart_count": snapshot.postgres_restart_count,
        "backend_id": snapshot.backend_id,
        "backend_state": snapshot.backend_state,
        "backend_health": snapshot.backend_health,
        "backend_restart_count": snapshot.backend_restart_count,
        "alembic_head": snapshot.alembic_head,
        "audit": snapshot.audit,
        "audit_status": snapshot.audit_status,
        "explicit_rollback": snapshot.explicit_rollback,
        "baseline_digest": snapshot.baseline_digest,
    }


def git_clean(executor: CommandExecutor) -> None:
    result = executor.run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"), timeout=15
    )
    if result.returncode != 0 or result.stdout.strip():
        raise RunnerFailure("Git working tree must be clean", 20)


def container_absent(executor: CommandExecutor, name: str) -> bool:
    result = executor.run(
        (
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^/{name}$",
            "--format",
            "{{.ID}}",
        ),
        timeout=15,
    )
    return result.returncode == 0 and not result.stdout.strip()


def volume_absent(executor: CommandExecutor, name: str) -> bool:
    result = executor.run(
        (
            "docker",
            "volume",
            "ls",
            "--filter",
            f"name=^{name}$",
            "--format",
            "{{.Name}}",
        ),
        timeout=15,
    )
    return result.returncode == 0 and not result.stdout.strip()


def wait_ready(
    executor: CommandExecutor, container_name: str, bootstrap_user: str
) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        logs = executor.run(
            ("docker", "logs", container_name),
            timeout=5,
        )
        initialization_complete = (
            logs.returncode == 0
            and "PostgreSQL init process complete; ready for start up."
            in f"{logs.stdout}\n{logs.stderr}"
        )
        result = executor.run(
            (
                "docker",
                "exec",
                container_name,
                "pg_isready",
                "-U",
                bootstrap_user,
                "-d",
                "postgres",
            ),
            timeout=5,
        )
        if initialization_complete and result.returncode == 0:
            return
        time.sleep(0.5)
    raise RunnerFailure("ephemeral PostgreSQL did not become ready", 21)


def inspect_ephemeral(
    executor: CommandExecutor, container_name: str
) -> tuple[str, int]:
    output = require(
        executor.run(("docker", "inspect", container_name), timeout=15),
        "ephemeral container inspection failed",
        21,
    )
    try:
        item = json.loads(output)[0]
        mounts = item.get("Mounts") or []
        tmpfs = item.get("HostConfig", {}).get("Tmpfs") or {}
        ports = item["NetworkSettings"]["Ports"]["5432/tcp"]
        host_ip = ports[0]["HostIp"]
        port = int(ports[0]["HostPort"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RunnerFailure("ephemeral container inspection was malformed", 21) from exc
    if any(mount.get("Type") == "volume" for mount in mounts):
        raise RunnerFailure("ephemeral PostgreSQL has a forbidden Docker volume", 21)
    if "/var/lib/postgresql/data" not in tmpfs:
        raise RunnerFailure("ephemeral PostgreSQL data is not on tmpfs", 21)
    if host_ip != "127.0.0.1" or not (1 <= port <= 65535):
        raise RunnerFailure("ephemeral PostgreSQL port is not loopback-only", 21)
    return str(item["Image"]), port


def bootstrap_database(
    executor: CommandExecutor,
    *,
    container_name: str,
    bootstrap_user: str,
    test_role: str,
    test_database: str,
    test_password: str,
) -> None:
    if not SAFE_IDENTIFIER.fullmatch(test_role) or not SAFE_IDENTIFIER.fullmatch(
        test_database
    ):
        raise RunnerFailure("generated PostgreSQL identifier was unsafe", 21)
    escaped_password = test_password.replace("'", "''")
    bootstrap_sql = f"""\\set ON_ERROR_STOP on
\\set test_password '{escaped_password}'
CREATE ROLE :\"test_role\"
  LOGIN PASSWORD :'test_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
SELECT format('CREATE DATABASE %I OWNER %I', :'test_database', :'test_role') \\gexec
"""
    require(
        executor.run(
            (
                "docker",
                "exec",
                "-i",
                "-u",
                "postgres",
                container_name,
                "psql",
                "--no-psqlrc",
                "--set",
                "ON_ERROR_STOP=1",
                "--set",
                f"test_role={test_role}",
                "--set",
                f"test_database={test_database}",
                "--username",
                bootstrap_user,
                "--dbname",
                "postgres",
            ),
            input_text=bootstrap_sql,
            timeout=30,
        ),
        "isolated database bootstrap failed",
        21,
    )
    metadata = require(
        executor.run(
            (
                "docker",
                "exec",
                "-i",
                "-u",
                "postgres",
                container_name,
                "psql",
                "--no-psqlrc",
                "--tuples-only",
                "--no-align",
                "--field-separator=|",
                "--set",
                "ON_ERROR_STOP=1",
                "--set",
                f"test_role={test_role}",
                "--set",
                f"test_database={test_database}",
                "--username",
                bootstrap_user,
                "--dbname",
                "postgres",
            ),
            input_text="""
SELECT database.datname, pg_get_userbyid(database.datdba),
       role.rolcanlogin, role.rolsuper, role.rolcreatedb, role.rolcreaterole,
       role.rolreplication, role.rolbypassrls,
       (SELECT count(*) FROM pg_database owned WHERE owned.datdba = role.oid)
FROM pg_database database
JOIN pg_roles role ON role.rolname = :'test_role'
WHERE database.datname = :'test_database';
""",
            timeout=20,
        ),
        "isolated database identity verification failed",
        21,
    )
    if metadata != f"{test_database}|{test_role}|t|f|f|f|f|f|1":
        raise RunnerFailure("isolated role/database privileges did not match", 21)


def database_head(
    executor: CommandExecutor,
    container_name: str,
    bootstrap_user: str,
    test_database: str,
) -> str:
    return require(
        executor.run(
            (
                "docker",
                "exec",
                "-i",
                "-u",
                "postgres",
                container_name,
                "psql",
                "--no-psqlrc",
                "--tuples-only",
                "--no-align",
                "--set",
                "ON_ERROR_STOP=1",
                "--username",
                bootstrap_user,
                "--dbname",
                test_database,
            ),
            input_text="SELECT version_num FROM alembic_version;\n",
            timeout=20,
        ),
        "failed to read isolated Alembic head",
        21,
    )


def redact(text: str, values: Sequence[str], evidence: Evidence) -> str:
    redacted = text
    for value in sorted((item for item in values if item), key=len, reverse=True):
        count = redacted.count(value)
        if count:
            evidence.redaction_count += count
            redacted = redacted.replace(value, "[REDACTED]")
    redacted, count = re.subn(
        r"(?i)(postgres(?:ql)?(?:\+asyncpg)?://)[^\s/@:]+:[^\s/@]+@",
        r"\1[REDACTED]@",
        redacted,
    )
    evidence.redaction_count += count
    return redacted


class IsolatedPostgresRunner:
    def __init__(
        self, args: argparse.Namespace, *, executor: CommandExecutor | None = None
    ) -> None:
        self.args = args
        self.executor = executor or CommandExecutor()
        self.evidence = Evidence(pytest_arguments=list(args.pytest_args))
        self.container_name: str | None = None
        self.temp_dir: Path | None = None
        self.pre_snapshot: CanonicalSnapshot | None = None
        self.secrets_to_mask: list[str] = []

    def install_signal_handlers(self) -> dict[int, Any]:
        previous: dict[int, Any] = {}

        def handler(signum, _frame):
            raise RunnerInterrupted(signum)

        supported_signals = (signal.SIGINT, signal.SIGTERM)
        if hasattr(signal, "SIGHUP"):
            supported_signals += (signal.SIGHUP,)
        for signum in supported_signals:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, handler)
        return previous

    @staticmethod
    def restore_signal_handlers(previous: dict[int, Any]) -> None:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    def cleanup(self) -> bool:
        cleanup_ok = True
        if self.container_name and not container_absent(
            self.executor, self.container_name
        ):
            removed = (
                self.executor.run(
                    ("docker", "rm", "-f", self.container_name), timeout=30
                ).returncode
                == 0
            )
            self.evidence.cleanup["container_removed"] = removed
            cleanup_ok = cleanup_ok and removed
        else:
            self.evidence.cleanup["container_removed"] = True
        if self.container_name:
            absent = container_absent(self.executor, self.container_name)
            no_volume = volume_absent(self.executor, self.container_name)
        else:
            absent = no_volume = True
        self.evidence.cleanup["container_absent"] = absent
        self.evidence.cleanup["volume_absent"] = no_volume
        cleanup_ok = cleanup_ok and absent and no_volume

        if self.temp_dir is not None:
            shutil.rmtree(self.temp_dir)
        credentials_removed = self.temp_dir is None or not self.temp_dir.exists()
        self.evidence.cleanup["credentials_removed"] = credentials_removed
        cleanup_ok = cleanup_ok and credentials_removed

        if self.pre_snapshot is not None:
            try:
                post = canonical_snapshot(
                    self.executor,
                    self.args.postgres_container_id,
                    self.args.backend_container_id,
                )
                self.evidence.canonical_post = public_snapshot(post)
                matches = post == self.pre_snapshot
                self.evidence.cleanup["postflight_matches"] = matches
                cleanup_ok = cleanup_ok and matches
            except RunnerFailure as exc:
                self.evidence.errors.append(str(exc))
                cleanup_ok = False
        return cleanup_ok

    def execute(self) -> int:
        previous_handlers = self.install_signal_handlers()
        intended_exit = 0
        cleanup_ok = False
        try:
            self.evidence.lifecycle_stage = "preflight"
            git_clean(self.executor)
            self.pre_snapshot = canonical_snapshot(
                self.executor,
                self.args.postgres_container_id,
                self.args.backend_container_id,
            )
            self.evidence.canonical_pre = public_snapshot(self.pre_snapshot)
            self.evidence.sealed_baseline_digest = self.pre_snapshot.baseline_digest
            self.evidence.image_identity = require(
                self.executor.run(
                    (
                        "docker",
                        "image",
                        "inspect",
                        POSTGRES_IMAGE,
                        "--format",
                        "{{.Id}}",
                    ),
                    timeout=15,
                ),
                "required PostgreSQL image is unavailable",
                21,
            )

            suffix = secrets.token_hex(6)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.container_name = f"{NAME_PREFIX}{timestamp}-{os.getpid()}-{suffix}"
            self.evidence.generated_resource_name = self.container_name
            if not container_absent(self.executor, self.container_name):
                raise RunnerFailure("generated container name already exists", 20)

            self.temp_dir = Path(tempfile.mkdtemp(prefix="pastexam-s5a-postgres-"))
            self.temp_dir.chmod(stat.S_IRWXU)
            bootstrap_user = f"bootstrap_{suffix}"
            bootstrap_password = secrets.token_urlsafe(32)
            test_role = f"pastexam_test_{suffix}"
            test_database = f"pastexam_test_{suffix}"
            test_password = secrets.token_urlsafe(32)
            self.secrets_to_mask.extend((bootstrap_password, test_password))
            env_file = self.temp_dir / "postgres.env"
            env_file.write_text(
                "\n".join(
                    (
                        f"POSTGRES_USER={bootstrap_user}",
                        f"POSTGRES_PASSWORD={bootstrap_password}",
                        "POSTGRES_DB=postgres",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

            self.evidence.lifecycle_stage = "container_start"
            require(
                self.executor.run(
                    (
                        "docker",
                        "run",
                        "--detach",
                        "--pull=never",
                        "--name",
                        self.container_name,
                        "--tmpfs",
                        "/var/lib/postgresql/data:rw,nosuid,nodev",
                        "-p",
                        "127.0.0.1::5432",
                        "--env-file",
                        str(env_file),
                        POSTGRES_IMAGE,
                    ),
                    timeout=45,
                ),
                "failed to start isolated PostgreSQL",
                21,
            )
            wait_ready(self.executor, self.container_name, bootstrap_user)
            image_id, host_port = inspect_ephemeral(self.executor, self.container_name)
            self.evidence.image_identity = image_id
            self.evidence.allocated_port = host_port

            self.evidence.lifecycle_stage = "database_bootstrap"
            bootstrap_database(
                self.executor,
                container_name=self.container_name,
                bootstrap_user=bootstrap_user,
                test_role=test_role,
                test_database=test_database,
                test_password=test_password,
            )

            self.evidence.lifecycle_stage = "migration"
            migration_env = os.environ.copy()
            migration_env.update(
                {
                    "DB_HOST": "127.0.0.1",
                    "DB_PORT": str(host_port),
                    "DB_USER": test_role,
                    "DB_PASSWORD": test_password,
                    "DB_NAME": test_database,
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            migration = self.executor.run(
                (str(BACKEND_PYTHON), "migrate.py", "upgrade", "--json"),
                cwd=BACKEND_ROOT,
                env=migration_env,
                timeout=180,
            )
            if migration.returncode != 0:
                raise RunnerFailure(
                    "isolated migration failed: "
                    + redact(
                        migration.stderr or migration.stdout,
                        self.secrets_to_mask,
                        self.evidence,
                    ),
                    21,
                )
            head = database_head(
                self.executor,
                self.container_name,
                bootstrap_user,
                test_database,
            )
            if head != EXPECTED_ALEMBIC_HEAD:
                raise RunnerFailure("isolated migration head mismatch", 21)
            self.evidence.migration_status = "complete"
            self.evidence.migration_head = head

            self.evidence.lifecycle_stage = "pytest"
            test_url = (
                "postgresql+asyncpg://"
                f"{quote(test_role, safe='')}:{quote(test_password, safe='')}"
                f"@127.0.0.1:{host_port}/{quote(test_database, safe='')}"
            )
            test_env = os.environ.copy()
            existing_pythonpath = test_env.get("PYTHONPATH", "")
            test_env.update(
                {
                    "TEST_DATABASE_URL": test_url,
                    "PASTEXAM_TEST_DATABASE_ISOLATED": "true",
                    "TEST_DATABASE_ALLOWED_HOSTS": "127.0.0.1,localhost",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": (
                        str(BACKEND_ROOT)
                        if not existing_pythonpath
                        else f"{BACKEND_ROOT}{os.pathsep}{existing_pythonpath}"
                    ),
                }
            )
            pytest_arguments = list(self.args.pytest_args)
            if os.name == "nt":
                pytest_arguments.extend(("--basetemp", str(self.temp_dir / "pytest")))
            self.evidence.pytest_arguments = pytest_arguments
            tests = self.executor.run(
                (str(BACKEND_PYTHON), "-m", "pytest", *pytest_arguments),
                cwd=REPOSITORY_ROOT,
                env=test_env,
                timeout=1800,
            )
            self.evidence.pytest_exit_status = tests.returncode
            if tests.returncode:
                intended_exit = 22
                self.evidence.errors.append(
                    redact(
                        tests.stderr or tests.stdout,
                        self.secrets_to_mask,
                        self.evidence,
                    )
                )
            else:
                self.evidence.findings.append(
                    {
                        "code": "isolated_tests_passed",
                        "classification": "Verified Fact",
                        "message": "Focused pytest command completed successfully.",
                    }
                )
        except RunnerFailure as exc:
            intended_exit = exc.exit_code
            self.evidence.errors.append(
                redact(str(exc), self.secrets_to_mask, self.evidence)
            )
        except (OSError, subprocess.SubprocessError) as exc:
            intended_exit = 21
            self.evidence.errors.append(
                redact(
                    f"{exc.__class__.__name__}: {exc}",
                    self.secrets_to_mask,
                    self.evidence,
                )
            )
        finally:
            self.evidence.lifecycle_stage = "cleanup"
            try:
                cleanup_ok = self.cleanup()
            except (OSError, RunnerFailure, subprocess.SubprocessError) as exc:
                self.evidence.errors.append(f"cleanup failed: {exc}")
            self.restore_signal_handlers(previous_handlers)
        self.evidence.lifecycle_stage = "complete"
        self.evidence.exit_code = intended_exit if cleanup_ok else 24
        return self.evidence.exit_code


def render_text(evidence: Evidence) -> str:
    lines = [
        "Isolated backend test runner",
        f"Result: {'PASS' if evidence.exit_code == 0 else 'FAIL'}",
        f"Exit code: {evidence.exit_code}",
        f"Stage: {evidence.lifecycle_stage}",
        f"Resource: {evidence.generated_resource_name or 'not-created'}",
        f"Image: {evidence.image_identity or 'unknown'}",
        f"Port: {evidence.allocated_port or 'unallocated'}",
        f"Migration: {evidence.migration_status}",
        f"Migration head: {evidence.migration_head or 'unknown'}",
        f"Pytest exit: {evidence.pytest_exit_status}",
        "Cleanup: " + json.dumps(evidence.cleanup, sort_keys=True),
    ]
    lines.extend(f"ERROR: {message}" for message in evidence.errors)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    runner = IsolatedPostgresRunner(args)
    exit_code = runner.execute()
    if args.output == "json":
        print(json.dumps(asdict(runner.evidence), indent=2, sort_keys=True))
    else:
        print(render_text(runner.evidence))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
