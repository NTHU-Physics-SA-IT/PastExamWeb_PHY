"""Resolve canonical development and coordination branch authority."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_RELATIVE_PATH = Path(".github/project-governance.json")
SUPPORTED_SCHEMA_VERSION = 1
CURRENT_DEFAULT_DEVELOPMENT_BASE = "main"
COORDINATION_BRANCH_PREFIX = "integration/"


class GovernanceConfigError(RuntimeError):
    """The canonical project-governance source is unavailable or invalid."""


@dataclass(frozen=True)
class ProjectGovernance:
    schema_version: int
    default_development_base: str
    coordination_branch: str | None

    @property
    def default_development_ref(self) -> str:
        return normalize_head_ref(self.default_development_base)

    @property
    def coordination_ref(self) -> str | None:
        if self.coordination_branch is None:
            return None
        return normalize_head_ref(self.coordination_branch)

    def allows_pr_base(self, branch: str) -> bool:
        return branch == self.default_development_base or (
            self.coordination_branch is not None and branch == self.coordination_branch
        )

    def is_valid_branch_local_authority(self, branch: str) -> bool:
        if branch == self.default_development_base:
            return self.coordination_branch is None
        return (
            self.coordination_branch is not None
            and branch == self.coordination_branch
        )


def repository_root() -> Path:
    """Return the repository root derived from this tracked script."""

    return Path(__file__).resolve().parents[2]


def validate_branch_name(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GovernanceConfigError(f"{field} must be a non-empty normalized string")
    if value.startswith("refs/"):
        raise GovernanceConfigError(f"{field} must be a branch name, not a full ref")

    try:
        result = subprocess.run(
            ["git", "check-ref-format", "--branch", value],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise GovernanceConfigError(
            f"unable to validate {field}: {type(error).__name__}"
        ) from error
    if result.returncode != 0:
        raise GovernanceConfigError(f"{field} is not a safe Git branch name")
    return value


def normalize_head_ref(branch: str) -> str:
    validated = validate_branch_name(branch, field="branch")
    return f"refs/heads/{validated}"


def _config_path(root: Path) -> Path:
    resolved_root = root.resolve()
    candidate = resolved_root / CONFIG_RELATIVE_PATH
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (FileNotFoundError, ValueError) as error:
        raise GovernanceConfigError(
            f"canonical project governance is unavailable: {CONFIG_RELATIVE_PATH}"
        ) from error
    if not resolved.is_file():
        raise GovernanceConfigError("canonical project governance is not a file")
    return resolved


def load_project_governance(
    root: Path | None = None,
) -> ProjectGovernance:
    path = _config_path(root or repository_root())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GovernanceConfigError(
            "canonical project governance is not valid UTF-8 JSON"
        ) from error

    if not isinstance(payload, dict):
        raise GovernanceConfigError("canonical project governance must be an object")
    expected_keys = {
        "schema_version",
        "default_development_base",
        "coordination_branch",
    }
    if set(payload) != expected_keys:
        raise GovernanceConfigError(
            "canonical project governance has missing or unsupported keys"
        )

    schema_version = payload["schema_version"]
    if type(schema_version) is not int or schema_version != SUPPORTED_SCHEMA_VERSION:
        raise GovernanceConfigError("unsupported project-governance schema version")

    default_base = validate_branch_name(
        payload["default_development_base"],
        field="default_development_base",
    )
    if default_base != CURRENT_DEFAULT_DEVELOPMENT_BASE:
        raise GovernanceConfigError(
            "default_development_base must remain main under current policy"
        )

    coordination_value = payload["coordination_branch"]
    coordination_branch: str | None
    if coordination_value is None:
        coordination_branch = None
    else:
        coordination_branch = validate_branch_name(
            coordination_value,
            field="coordination_branch",
        )
        if not coordination_branch.startswith(COORDINATION_BRANCH_PREFIX):
            raise GovernanceConfigError(
                "coordination_branch must match the integration/** workflow family"
            )
        if coordination_branch == default_base:
            raise GovernanceConfigError(
                "coordination_branch must differ from default_development_base"
            )

    return ProjectGovernance(
        schema_version=schema_version,
        default_development_base=default_base,
        coordination_branch=coordination_branch,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=repository_root())
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("default-development-base")
    subparsers.add_parser("default-development-ref")
    subparsers.add_parser("coordination-branch")
    subparsers.add_parser("coordination-ref")
    validate = subparsers.add_parser("validate-pr-base")
    validate.add_argument("--base", required=True)
    branch_authority = subparsers.add_parser("validate-branch-authority")
    branch_authority.add_argument("--branch", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        governance = load_project_governance(arguments.repository_root)
    except GovernanceConfigError as error:
        print(f"project governance error: {error}", file=sys.stderr)
        return 2

    if arguments.command == "default-development-base":
        print(governance.default_development_base)
    elif arguments.command == "default-development-ref":
        print(governance.default_development_ref)
    elif arguments.command == "coordination-branch":
        if governance.coordination_branch is None:
            return 3
        print(governance.coordination_branch)
    elif arguments.command == "coordination-ref":
        if governance.coordination_ref is None:
            return 3
        print(governance.coordination_ref)
    elif arguments.command == "validate-pr-base":
        if not governance.allows_pr_base(arguments.base):
            print(
                f"pull request base is not approved: {arguments.base}",
                file=sys.stderr,
            )
            return 1
        print("Pull request base branch is allowed.")
    elif arguments.command == "validate-branch-authority":
        if not governance.is_valid_branch_local_authority(arguments.branch):
            print(
                "branch-local project governance does not match the exact branch",
                file=sys.stderr,
            )
            return 1
        print("Branch-local project governance matches the exact branch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
