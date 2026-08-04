from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "check-backend-runtime.py"
SPEC = importlib.util.spec_from_file_location("backend_runtime", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


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
        link.symlink_to(tmp_path / "outside.py")
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
        ["python3", str(SCRIPT), "--backend-container-id", "short"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 2


def test_unpushed_branch_upstream_is_a_nullable_evidence_field() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'upstream_result.returncode == 0 else None' in source


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
