#!/usr/bin/env python3
"""Validate aggregate CI checks without rerunning any test or build."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

from classify_ci_mode import (
    APPROVED_WORKFLOW_PATH,
    GitHubActionsAPI,
    GitRepository,
)


REQUIRED_EXECUTION_JOBS = frozenset(
    {
        "Detect CI mode",
        "lint / backend",
        "lint / frontend",
        "test / migration-safety",
        "test / backend",
        "test / frontend-unit",
        "test / frontend-e2e",
        "build / backend",
        "build / frontend",
    }
)


def _require_result(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} result is {actual!r}; expected {expected!r}")


def _require_unique_successes(
    jobs: list[dict[str, Any]],
    required_names: frozenset[str],
) -> None:
    conclusions: dict[str, list[Any]] = {}
    for job in jobs:
        name = job.get("name")
        if isinstance(name, str):
            conclusions.setdefault(name, []).append(job.get("conclusion"))
    for name in required_names:
        if conclusions.get(name) != ["success"]:
            raise RuntimeError(f"required full-CI job is not successful: {name}")


def attest_full_ci(arguments: argparse.Namespace) -> None:
    _require_result(arguments.mode, "full", "CI mode")
    _require_result(arguments.classifier_result, "success", "classifier")
    _require_result(arguments.lint_result, "success", "lint workflow")
    _require_result(arguments.test_result, "success", "test workflow")
    _require_result(arguments.build_result, "success", "build workflow")

    api = GitHubActionsAPI(
        api_url=arguments.api_url,
        repository=arguments.repository,
        token=os.environ.get("GITHUB_TOKEN", ""),
    )
    _require_unique_successes(
        api.run_jobs(arguments.run_id),
        REQUIRED_EXECUTION_JOBS,
    )

    git = GitRepository(arguments.repository_root)
    tree = git.tree_sha(arguments.sha)
    revision = git.blob_sha(arguments.sha, APPROVED_WORKFLOW_PATH)
    if arguments.github_output:
        with arguments.github_output.open("a", encoding="utf-8") as output:
            output.write("mode=full\n")
            output.write(f"sha={arguments.sha}\n")
            output.write(f"tree_sha={tree}\n")
            output.write(f"workflow_revision={revision}\n")
    print("Full CI dependencies and required jobs are successful.")
    print(f"sha={arguments.sha}")
    print(f"tree_sha={tree}")
    print(f"workflow_revision={revision}")


def validate_gate(arguments: argparse.Namespace) -> None:
    _require_result(arguments.classifier_result, "success", "classifier")
    _require_result(arguments.lint_result, "success", "lint workflow")
    _require_result(arguments.test_result, "success", "test workflow")
    _require_result(arguments.build_result, "success", "build workflow")

    if arguments.mode == "full":
        _require_result(
            arguments.full_attestation_result,
            "success",
            "Full CI Attestation",
        )
        _require_result(arguments.equivalent_result, "skipped", "equivalent provenance")
        _require_result(arguments.docs_result, "skipped", "docs gate")
    elif arguments.mode == "equivalent-merge":
        _require_result(
            arguments.full_attestation_result,
            "skipped",
            "Full CI Attestation",
        )
        _require_result(arguments.equivalent_result, "success", "equivalent provenance")
        _require_result(arguments.docs_result, "skipped", "docs gate")
    elif arguments.mode == "docs-only":
        _require_result(
            arguments.full_attestation_result,
            "skipped",
            "Full CI Attestation",
        )
        _require_result(arguments.equivalent_result, "skipped", "equivalent provenance")
        _require_result(arguments.docs_result, "success", "docs gate")
    else:
        raise RuntimeError(f"unsupported CI mode: {arguments.mode!r}")
    print(f"CI Gate accepted mode={arguments.mode}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    attestation = subparsers.add_parser("full-attestation")
    attestation.add_argument("--mode", required=True)
    attestation.add_argument("--classifier-result", required=True)
    attestation.add_argument("--lint-result", required=True)
    attestation.add_argument("--test-result", required=True)
    attestation.add_argument("--build-result", required=True)
    attestation.add_argument("--api-url", required=True)
    attestation.add_argument("--repository", required=True)
    attestation.add_argument("--run-id", type=int, required=True)
    attestation.add_argument("--sha", required=True)
    attestation.add_argument("--repository-root", type=Path, default=Path.cwd())
    attestation.add_argument("--github-output", type=Path)

    gate = subparsers.add_parser("ci-gate")
    gate.add_argument("--mode", required=True)
    gate.add_argument("--classifier-result", required=True)
    gate.add_argument("--lint-result", required=True)
    gate.add_argument("--test-result", required=True)
    gate.add_argument("--build-result", required=True)
    gate.add_argument("--equivalent-result", required=True)
    gate.add_argument("--docs-result", required=True)
    gate.add_argument("--full-attestation-result", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "full-attestation":
            attest_full_ci(arguments)
        else:
            validate_gate(arguments)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"CI aggregate validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
