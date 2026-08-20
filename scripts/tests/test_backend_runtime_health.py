from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "check-backend-runtime.py"
SPEC = importlib.util.spec_from_file_location("backend_runtime", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


class SourceExecutor:
    def __init__(
        self,
        content: bytes,
        *,
        mismatch: bool = False,
        missing_hash: str | None = None,
    ) -> None:
        self.content = content
        self.mismatch = mismatch
        self.missing_hash = missing_hash
        self.commands: list[tuple[str, ...]] = []

    def run(self, args, *, cwd=REPOSITORY_ROOT, timeout=30):
        del cwd, timeout
        command = tuple(args)
        self.commands.append(command)
        if command[:2] == ("git", "show"):
            if self.missing_hash == "head":
                return checker.CommandResult(1)
            return checker.CommandResult(0, self.content.decode("utf-8"))
        if command[:2] == ("docker", "exec"):
            if self.missing_hash == "container":
                return checker.CommandResult(1)
            digest = checker.hashlib.sha256(self.content).hexdigest()
            if self.mismatch:
                digest = "0" * 64
            return checker.CommandResult(0, f"{len(self.content)}\n{digest}\n")
        raise AssertionError(f"unexpected command: {command[:2]}")


def test_dev_compose_command_matches_the_platform_execution_boundary() -> None:
    command = checker.dev_compose_command("schema-status")

    assert command[-1] == "schema-status"
    if os.name == "nt":
        assert Path(command[0]).name == "bash.exe"
        assert Path(command[1]) == checker.DEV_COMPOSE
    else:
        assert command == (str(checker.DEV_COMPOSE), "schema-status")


@pytest.mark.parametrize(
    "path",
    (
        "backend/app/main.py",
        "backend/alembic/versions/9f1c2a7e4b63_add_nthu_oauth_identity_unique.py",
        "backend/alembic/versions/b7e3d9a1c5f2_add_nthu_student_id.py",
        "backend/alembic/versions/c2a8e4f6b9d1_add_bilingual_course_catalog.py",
        "backend/alembic/versions/d4b7e2a9c6f1_add_bilingual_submission_snapshots.py",
        "backend/alembic/versions/e6a1b3c5d7f9_add_about_us_entries.py",
        "backend/alembic/versions/a9c4e7b2d6f1_add_bilingual_content_and_wish_pool.py",
    ),
)
def test_backend_python_sources_use_lf_checkout_policy(path: str) -> None:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={REPOSITORY_ROOT.as_posix()}",
            "check-attr",
            "eol",
            "--",
            path,
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == f"{path}: eol: lf"


def test_runtime_checker_tracks_current_schema_head() -> None:
    assert checker.EXPECTED_ALEMBIC_HEAD == "f3a7c1e9d5b2"


def test_posix_source_identity_is_unchanged() -> None:
    source = checker.validate_source_path("backend/app/main.py")

    assert checker.repository_identity_path(source) == "backend/app/main.py"


@pytest.mark.skipif(os.name != "nt", reason="Windows path normalization regression")
def test_windows_source_input_uses_posix_git_and_container_paths() -> None:
    args = checker.parse_args(
        [
            "--backend-container-id",
            "a" * 64,
            "--postgres-container-id",
            "b" * 64,
            "--source-file",
            r"backend\app\main.py",
        ]
    )
    assert args.source_file == ["backend/app/main.py"]

    content = (checker.REPOSITORY_ROOT / "backend/app/main.py").read_bytes()
    executor = SourceExecutor(content)
    records, all_match, parse_failure = checker.gather_source(
        executor,
        "c" * 64,
        args.source_file,
    )

    assert all_match is True
    assert parse_failure is False
    assert records[0]["head_sha256"] is not None
    assert records[0]["container_sha256"] is not None
    assert ("git", "show", "HEAD:backend/app/main.py") in executor.commands
    container_command = next(
        command for command in executor.commands if command[:2] == ("docker", "exec")
    )
    assert container_command[-1] == "/app/app/main.py"
    assert "\\" not in container_command[-1]


def test_genuine_source_mismatch_remains_a_failure() -> None:
    content = (checker.REPOSITORY_ROOT / "backend/app/main.py").read_bytes()
    executor = SourceExecutor(content, mismatch=True)

    records, all_match, parse_failure = checker.gather_source(
        executor,
        "c" * 64,
        ["backend/app/main.py"],
    )

    assert all_match is False
    assert parse_failure is False
    assert records[0]["head_sha256"] is not None
    assert records[0]["container_sha256"] is not None
    assert records[0]["head_sha256"] != records[0]["container_sha256"]
    assert checker.classify(report(source=all_match)) == "source_mismatch"


@pytest.mark.parametrize("missing_hash", ("head", "container"))
def test_missing_source_hash_remains_a_failure(missing_hash: str) -> None:
    content = (checker.REPOSITORY_ROOT / "backend/app/main.py").read_bytes()
    executor = SourceExecutor(content, missing_hash=missing_hash)

    records, all_match, parse_failure = checker.gather_source(
        executor,
        "c" * 64,
        ["backend/app/main.py"],
    )

    assert all_match is False
    assert parse_failure is False
    assert records[0][f"{missing_hash}_sha256"] is None
    assert checker.classify(report(source=all_match)) == "source_mismatch"


@pytest.mark.parametrize(
    ("max_cardinality", "dangling", "expected"),
    (
        (0, 0, True),
        (1, 0, True),
        (2, 0, False),
        (-1, 0, False),
        (1, 1, False),
    ),
)
def test_data_green_cardinality_boundaries(
    max_cardinality: int,
    dangling: int,
    expected: bool,
) -> None:
    postgres_id = "d" * 64
    postgres = {
        "id": postgres_id,
        "state": "running",
        "health": "healthy",
        "restart_count": 0,
        "oom_killed": False,
    }
    schema = {
        "status": "complete",
        "alembic_head": checker.EXPECTED_ALEMBIC_HEAD,
        "explicit_rollback": True,
        "max_cardinality": max_cardinality,
        "dangling": dangling,
    }

    assert checker.data_is_green(postgres, schema, postgres_id) is expected


def report(
    *,
    source=True,
    clean=True,
    parse=False,
    state="running",
    health="healthy",
    supervisor=True,
    child=True,
    listener=True,
    traceback=False,
    direct=True,
    proxy=True,
    postgres=True,
):
    value = checker.Report()
    value.evidence["git"] = {"clean": clean}
    value.evidence["source"] = {
        "all_match": source,
        "parse_failure": parse,
    }
    value.evidence["runtime"] = {
        "state": state,
        "health": health,
        "supervisor_present": supervisor,
        "application_child_present": child,
        "listener_present": listener,
        "startup_failure_signature": traceback,
    }
    value.evidence["service"] = {
        "internal": {"ok": direct},
        "proxy": {"ok": proxy},
    }
    value.evidence["data"] = {"green": postgres}
    return value


@pytest.mark.parametrize(
    ("value", "classification", "exit_code"),
    (
        (report(), "healthy", 0),
        (report(source=False), "source_mismatch", 10),
        (
            report(
                parse=True,
                supervisor=False,
                child=False,
                listener=False,
                direct=False,
                proxy=False,
            ),
            "current_code_startup_failure",
            11,
        ),
        (
            report(
                child=False,
                listener=False,
                traceback=True,
                direct=False,
                proxy=False,
            ),
            "reload_only_failure",
            12,
        ),
        (
            report(health="unhealthy"),
            "healthcheck_only_failure",
            13,
        ),
        (
            report(postgres=False),
            "postgres_environment_incident",
            14,
        ),
        (
            report(
                child=False,
                listener=False,
                direct=False,
                proxy=False,
            ),
            "inconclusive",
            15,
        ),
    ),
)
def test_classifications_and_exit_codes(value, classification, exit_code) -> None:
    assert checker.classify(value) == classification
    assert checker.EXIT_CODES[classification] == exit_code


def test_competing_source_and_postgres_failure_is_inconclusive() -> None:
    assert checker.classify(report(source=False, postgres=False)) == "inconclusive"


@pytest.mark.parametrize(
    "path",
    (
        "/absolute/backend/app/main.py",
        "../backend/app/main.py",
        "frontend/src/main.js",
        "backend",
    ),
)
def test_source_path_rejections(path: str) -> None:
    with pytest.raises(checker.CheckerFailure):
        checker.validate_source_path(path)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    link = checker.BACKEND_ROOT / "runtime-checker-test-link"
    try:
        try:
            link.symlink_to(tmp_path / "outside.py")
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc.__class__.__name__}")
        with pytest.raises(checker.CheckerFailure):
            checker.validate_source_path("backend/runtime-checker-test-link")
    finally:
        link.unlink(missing_ok=True)


def test_redaction_masks_url_userinfo_and_token_values() -> None:
    value = checker.Report()
    output = checker.sanitized(
        "postgresql://user:password@host/db authorization=abc cookie=xyz",
        value,
    )
    assert "user:password" not in output
    assert "abc" not in output
    assert "xyz" not in output
    assert value.redactions_applied == 3


def test_json_schema_and_text_projection_are_stable() -> None:
    value = report()
    value.classification = "healthy"
    value.exit_code = 0
    value.summary = "Green"
    value.findings.append(
        checker.Finding("overall", "healthy", "info", "Verified Fact", "Green")
    )
    payload = checker.asdict(value)
    assert payload["schema_version"] == 1
    assert set(payload["evidence"]) == {"git", "source", "runtime", "service", "data"}
    assert "Classification: healthy" in checker.render_text(value)
    json.dumps(payload)


def test_invalid_invocation_uses_exit_two() -> None:
    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--backend-container-id", "short"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 2


def test_unpushed_branch_upstream_is_a_nullable_evidence_field() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "upstream_result.returncode == 0 else None" in source


def test_source_contains_only_read_only_docker_operations() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "docker restart",
        "docker stop",
        "docker start",
        "docker rm",
        "docker compose",
        "shell=True",
        "import_module",
        "app.main",
    ):
        assert forbidden not in source
    assert "PYTHONDONTWRITEBYTECODE" not in source or "bytecode_writes" in source
