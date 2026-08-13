#!/usr/bin/env python3
"""Validate aggregate CI checks without rerunning any test or build."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import os
from pathlib import Path
import sys
import time
from typing import Any

from classify_ci_mode import (
    APPROVED_WORKFLOW_PATH,
    GitHubActionsAPI,
    GitRepository,
    SHA_PATTERN,
)


REQUIRED_EXECUTION_JOBS = frozenset(
    {
        "Detect CI mode",
        "lint / backend",
        "lint / frontend",
        "test / migration-safety",
        "test / backend-shard-a",
        "test / backend-shard-b",
        "test / backend-coverage",
        "test / frontend-unit",
        "test / frontend-e2e-chromium",
        "test / frontend-e2e-firefox",
        "test / frontend-e2e-webkit",
        "test / frontend-e2e",
        "build / backend",
        "build / frontend",
    }
)

FULL_ATTESTATION_MAX_OBSERVATIONS = 5
FULL_ATTESTATION_POLL_INTERVAL_SECONDS = 2.0
SUPPORTED_FULL_ATTESTATION_EVENTS = frozenset({"push", "pull_request"})

CI_GATE_RESULT_LABELS = {
    "classifier_result": "classifier",
    "lint_result": "lint workflow",
    "test_result": "test workflow",
    "build_result": "build workflow",
    "full_attestation_result": "Full CI Attestation",
    "equivalent_result": "equivalent provenance",
    "docs_result": "docs gate",
}

CI_GATE_EXPECTED_RESULTS = {
    "full": {
        "classifier_result": "success",
        "lint_result": "success",
        "test_result": "success",
        "build_result": "success",
        "full_attestation_result": "success",
        "equivalent_result": "skipped",
        "docs_result": "skipped",
    },
    "equivalent-merge": {
        "classifier_result": "success",
        "lint_result": "skipped",
        "test_result": "skipped",
        "build_result": "skipped",
        "full_attestation_result": "skipped",
        "equivalent_result": "success",
        "docs_result": "skipped",
    },
    "docs-only": {
        "classifier_result": "success",
        "lint_result": "skipped",
        "test_result": "skipped",
        "build_result": "skipped",
        "full_attestation_result": "skipped",
        "equivalent_result": "skipped",
        "docs_result": "success",
    },
}


def _require_result(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} result is {actual!r}; expected {expected!r}")


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise RuntimeError(f"{label} is malformed")
    return value


def _require_workflow_run_authority(
    run: dict[str, Any],
    *,
    run_id: int,
    run_attempt: int,
    event_name: str,
    execution_head_sha: str,
) -> None:
    if run.get("id") != run_id:
        raise RuntimeError(
            f"workflow run ID mismatch: observed {run.get('id')!r}, expected {run_id}"
        )
    if run.get("run_attempt") != run_attempt:
        raise RuntimeError(
            "workflow run attempt mismatch: "
            f"observed {run.get('run_attempt')!r}, expected {run_attempt}"
        )
    if run.get("event") != event_name:
        raise RuntimeError(
            "workflow run event mismatch: "
            f"observed {run.get('event')!r}, expected {event_name!r}"
        )
    if run.get("head_sha") != execution_head_sha:
        raise RuntimeError(
            "workflow run execution-head SHA mismatch: "
            f"observed {run.get('head_sha')!r}, expected {execution_head_sha!r}"
        )


def _require_pull_request_authority(
    *,
    api: GitHubActionsAPI,
    git: GitRepository,
    repository: str,
    pr_number: int,
    base_sha: str,
    execution_head_sha: str,
    attested_sha: str,
) -> None:
    pull_request = api.pull_request(pr_number)
    if pull_request.get("number") != pr_number:
        raise RuntimeError("current pull request number does not match")
    if pull_request.get("state") != "open":
        raise RuntimeError("current pull request is not open")

    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise RuntimeError("current pull request base or head is malformed")
    base_repository = base.get("repo")
    head_repository = head.get("repo")
    if (
        not isinstance(base_repository, dict)
        or base_repository.get("full_name") != repository
        or not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
    ):
        raise RuntimeError("current pull request repository does not match")
    if base.get("sha") != base_sha:
        raise RuntimeError("current pull request base SHA does not match")
    if head.get("sha") != execution_head_sha:
        raise RuntimeError("current pull request head SHA does not match")

    expected_parents = (base_sha, execution_head_sha)
    attested_parents = git.commit_object_parents(attested_sha)
    if attested_parents != expected_parents:
        raise RuntimeError(
            "attested pull request merge parents do not match: "
            f"observed {attested_parents!r}, expected {expected_parents!r}"
        )

    current_merge_sha = _require_sha(
        pull_request.get("merge_commit_sha"),
        "current pull request merge SHA",
    )
    if current_merge_sha == attested_sha:
        return

    current_merge = api.commit_object(current_merge_sha)
    if current_merge.get("sha") != current_merge_sha:
        raise RuntimeError("current pull request merge commit identity does not match")
    current_parents_payload = current_merge.get("parents")
    if not isinstance(current_parents_payload, list) or not all(
        isinstance(parent, dict) for parent in current_parents_payload
    ):
        raise RuntimeError("current pull request merge parents are malformed")
    current_parents = tuple(parent.get("sha") for parent in current_parents_payload)
    if current_parents != expected_parents:
        raise RuntimeError(
            "current pull request merge parents do not match: "
            f"observed {current_parents!r}, expected {expected_parents!r}"
        )

    current_tree = current_merge.get("tree")
    if not isinstance(current_tree, dict):
        raise RuntimeError("current pull request merge tree is malformed")
    current_tree_sha = _require_sha(
        current_tree.get("sha"),
        "current pull request merge tree SHA",
    )
    if current_tree_sha != git.tree_sha(attested_sha):
        raise RuntimeError(
            "current pull request merge tree does not match attested tree"
        )


def _inspect_required_job_snapshot(
    jobs: list[dict[str, Any]],
    required_names: frozenset[str],
    *,
    run_id: int,
    run_attempt: int,
    execution_head_sha: str,
    observation: int,
    max_observations: int,
) -> tuple[str, ...]:
    matching_jobs: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        name = job.get("name")
        if isinstance(name, str) and name in required_names:
            matching_jobs.setdefault(name, []).append(job)

    incomplete: list[str] = []
    for name in sorted(required_names):
        matches = matching_jobs.get(name, [])
        if not matches:
            incomplete.append(f"{name}: missing")
            continue
        if len(matches) != 1:
            raise RuntimeError(
                "required full-CI job identity is ambiguous at "
                f"observation {observation}/{max_observations}: "
                f"{name}: observed {len(matches)} entries"
            )

        job = matches[0]
        observed_run_id = job.get("run_id")
        if observed_run_id != run_id:
            raise RuntimeError(
                "required full-CI job run ID mismatch at "
                f"observation {observation}/{max_observations}: "
                f"{name}: observed {observed_run_id!r}, expected {run_id}"
            )
        observed_attempt = job.get("run_attempt")
        if observed_attempt != run_attempt:
            raise RuntimeError(
                "required full-CI job attempt mismatch at "
                f"observation {observation}/{max_observations}: "
                f"{name}: observed {observed_attempt!r}, expected {run_attempt}"
            )
        observed_sha = job.get("head_sha")
        if observed_sha != execution_head_sha:
            raise RuntimeError(
                "required full-CI job execution-head SHA mismatch at "
                f"observation {observation}/{max_observations}: "
                f"{name}: observed {observed_sha!r}, "
                f"expected {execution_head_sha!r}"
            )

        status = job.get("status")
        conclusion = job.get("conclusion")
        if conclusion not in (None, "success"):
            raise RuntimeError(
                "required full-CI job terminal non-success at "
                f"observation {observation}/{max_observations}: "
                f"{name}: status={status!r}, conclusion={conclusion!r}"
            )
        if status == "completed" and conclusion == "success":
            continue
        if status == "completed":
            incomplete.append(
                f"{name}: conclusion unavailable "
                f"(status={status!r}, conclusion={conclusion!r})"
            )
        else:
            incomplete.append(
                f"{name}: nonterminal (status={status!r}, conclusion={conclusion!r})"
            )
    return tuple(incomplete)


def _require_unique_successes(
    *,
    load_jobs: Callable[[], list[dict[str, Any]]],
    required_names: frozenset[str],
    run_id: int,
    run_attempt: int,
    execution_head_sha: str,
    max_observations: int = FULL_ATTESTATION_MAX_OBSERVATIONS,
    poll_interval_seconds: float = FULL_ATTESTATION_POLL_INTERVAL_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        raise RuntimeError("workflow run ID is malformed")
    if run_id < 1:
        raise RuntimeError("workflow run ID must be positive")
    if isinstance(run_attempt, bool) or not isinstance(run_attempt, int):
        raise RuntimeError("workflow run attempt is malformed")
    if run_attempt < 1:
        raise RuntimeError("workflow run attempt must be positive")
    _require_sha(execution_head_sha, "workflow execution-head SHA")
    if max_observations < 1:
        raise ValueError("full-CI observation bound must be positive")
    if poll_interval_seconds < 0:
        raise ValueError("full-CI polling interval cannot be negative")

    for observation in range(1, max_observations + 1):
        incomplete = _inspect_required_job_snapshot(
            load_jobs(),
            required_names,
            run_id=run_id,
            run_attempt=run_attempt,
            execution_head_sha=execution_head_sha,
            observation=observation,
            max_observations=max_observations,
        )
        if not incomplete:
            return

        diagnostic = "; ".join(incomplete)
        if observation == max_observations:
            raise RuntimeError(
                "required full-CI evidence incomplete at "
                f"observation {observation}/{max_observations}: {diagnostic}"
            )
        print(
            "Full CI evidence incomplete at "
            f"observation {observation}/{max_observations}: {diagnostic}; "
            f"retrying in {poll_interval_seconds:g} seconds.",
            file=sys.stderr,
        )
        sleeper(poll_interval_seconds)


def attest_full_ci(arguments: argparse.Namespace) -> None:
    _require_result(arguments.mode, "full", "CI mode")
    _require_result(arguments.classifier_result, "success", "classifier")
    _require_result(arguments.lint_result, "success", "lint workflow")
    _require_result(arguments.test_result, "success", "test workflow")
    _require_result(arguments.build_result, "success", "build workflow")

    event_name = arguments.event_name
    if event_name not in SUPPORTED_FULL_ATTESTATION_EVENTS:
        raise RuntimeError(f"unsupported Full CI event: {event_name!r}")
    attested_sha = _require_sha(arguments.attested_sha, "attested SHA")
    execution_head_sha = _require_sha(
        arguments.execution_head_sha,
        "execution-head SHA",
    )
    if event_name == "push":
        if attested_sha != execution_head_sha:
            raise RuntimeError("push attested SHA and execution-head SHA differ")
        if arguments.pr_number != 0 or arguments.base_sha:
            raise RuntimeError("push Full CI received pull request identity")
    else:
        if arguments.pr_number < 1:
            raise RuntimeError("pull request number must be positive")
        _require_sha(arguments.base_sha, "pull request base SHA")

    api = GitHubActionsAPI(
        api_url=arguments.api_url,
        repository=arguments.repository,
        token=os.environ.get("GITHUB_TOKEN", ""),
    )
    run = api.workflow_run(arguments.run_id)
    _require_workflow_run_authority(
        run,
        run_id=arguments.run_id,
        run_attempt=arguments.run_attempt,
        event_name=event_name,
        execution_head_sha=execution_head_sha,
    )

    git = GitRepository(arguments.repository_root)
    if event_name == "pull_request":
        _require_pull_request_authority(
            api=api,
            git=git,
            repository=arguments.repository,
            pr_number=arguments.pr_number,
            base_sha=arguments.base_sha,
            execution_head_sha=execution_head_sha,
            attested_sha=attested_sha,
        )

    _require_unique_successes(
        load_jobs=lambda: api.run_attempt_jobs(
            arguments.run_id,
            arguments.run_attempt,
        ),
        required_names=REQUIRED_EXECUTION_JOBS,
        run_id=arguments.run_id,
        run_attempt=arguments.run_attempt,
        execution_head_sha=execution_head_sha,
    )

    tree = git.tree_sha(attested_sha)
    revision = git.blob_sha(attested_sha, APPROVED_WORKFLOW_PATH)
    if arguments.github_output:
        with arguments.github_output.open("a", encoding="utf-8") as output:
            output.write("mode=full\n")
            output.write(f"sha={attested_sha}\n")
            output.write(f"tree_sha={tree}\n")
            output.write(f"workflow_revision={revision}\n")
    print("Full CI dependencies and required jobs are successful.")
    print(f"event_name={event_name}")
    print(f"sha={attested_sha}")
    print(f"execution_head_sha={execution_head_sha}")
    if event_name == "pull_request":
        print(f"pull_request_base_sha={arguments.base_sha}")
    print(f"tree_sha={tree}")
    print(f"workflow_revision={revision}")


def validate_gate(arguments: argparse.Namespace) -> None:
    mode = getattr(arguments, "mode", None)
    expected_results = CI_GATE_EXPECTED_RESULTS.get(mode)
    if expected_results is None:
        raise RuntimeError(f"unsupported CI mode: {mode!r}")

    missing = object()
    for result_name, expected in expected_results.items():
        label = CI_GATE_RESULT_LABELS[result_name]
        actual = getattr(arguments, result_name, missing)
        if actual is missing:
            raise RuntimeError(f"CI mode {mode!r}: missing result for {label}")
        _require_result(actual, expected, f"CI mode {mode!r} {label}")

    print(f"CI Gate accepted mode={mode}")


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
    attestation.add_argument("--run-attempt", type=int, required=True)
    attestation.add_argument("--event-name", required=True)
    attestation.add_argument("--attested-sha", required=True)
    attestation.add_argument("--execution-head-sha", required=True)
    attestation.add_argument("--pr-number", type=int, default=0)
    attestation.add_argument("--base-sha", default="")
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
