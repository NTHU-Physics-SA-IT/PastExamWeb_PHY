from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = REPOSITORY_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_SCRIPTS))

governance = importlib.import_module("project_governance")


def _write_config(root: Path, payload: object) -> None:
    path = root / governance.CONFIG_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_payload(*, coordination_branch: str | None = "integration/current") -> dict:
    return {
        "schema_version": 1,
        "default_development_base": "main",
        "coordination_branch": coordination_branch,
    }


def test_repository_config_resolves_main_without_active_coordination() -> None:
    resolved = governance.load_project_governance(REPOSITORY_ROOT)

    assert resolved.schema_version == 1
    assert resolved.default_development_base == "main"
    assert resolved.default_development_ref == "refs/heads/main"
    assert resolved.coordination_branch is None
    assert resolved.coordination_ref is None
    assert resolved.allows_pr_base("main")
    assert not resolved.allows_pr_base("integration/current")


def test_schema_allows_coordination_branch_to_be_unconfigured(tmp_path: Path) -> None:
    _write_config(tmp_path, _valid_payload(coordination_branch=None))

    resolved = governance.load_project_governance(tmp_path)

    assert resolved.coordination_branch is None
    assert resolved.coordination_ref is None
    assert not resolved.allows_pr_base("integration/current")


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {},
        {**_valid_payload(), "schema_version": 1.0},
        {**_valid_payload(), "schema_version": 2},
        {**_valid_payload(), "unexpected": True},
        {**_valid_payload(), "default_development_base": "develop"},
        {**_valid_payload(), "coordination_branch": "refs/heads/integration/current"},
        {**_valid_payload(), "coordination_branch": "integration/../unsafe"},
        {**_valid_payload(), "coordination_branch": "feature/not-coordination"},
        {**_valid_payload(), "coordination_branch": "main"},
    ),
)
def test_invalid_config_fails_closed(tmp_path: Path, payload: object) -> None:
    _write_config(tmp_path, payload)

    with pytest.raises(governance.GovernanceConfigError):
        governance.load_project_governance(tmp_path)


def test_missing_and_malformed_config_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(governance.GovernanceConfigError):
        governance.load_project_governance(tmp_path)

    path = tmp_path / governance.CONFIG_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(governance.GovernanceConfigError):
        governance.load_project_governance(tmp_path)


def test_cli_reports_current_repository_has_no_active_coordination() -> None:
    for command in ("coordination-branch", "coordination-ref"):
        process = subprocess.run(
            [
                sys.executable,
                str(CI_SCRIPTS / "project_governance.py"),
                "--repository-root",
                str(REPOSITORY_ROOT),
                command,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert process.returncode == 3
        assert process.stdout == ""

    for base, expected in (("main", 0), ("integration/current", 1)):
        process = subprocess.run(
            [
                sys.executable,
                str(CI_SCRIPTS / "project_governance.py"),
                "--repository-root",
                str(REPOSITORY_ROOT),
                "validate-pr-base",
                "--base",
                base,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert process.returncode == expected


def test_cli_accepts_only_exact_configured_bases(tmp_path: Path) -> None:
    _write_config(tmp_path, _valid_payload())
    resolved = governance.load_project_governance(tmp_path)
    assert resolved.coordination_branch == "integration/current"

    for base, expected in (
        ("main", 0),
        (resolved.coordination_branch, 0),
        (f"{resolved.coordination_branch}-near-match", 1),
        ("feat/unrelated", 1),
    ):
        process = subprocess.run(
            [
                sys.executable,
                str(CI_SCRIPTS / "project_governance.py"),
                "--repository-root",
                str(tmp_path),
                "validate-pr-base",
                "--base",
                base,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert process.returncode == expected
