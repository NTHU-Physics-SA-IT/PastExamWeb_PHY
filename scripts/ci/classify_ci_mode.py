#!/usr/bin/env python3
"""Fail-closed CI mode classification and merge-equivalence attestation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


CI_MODES = frozenset({"full", "equivalent-merge", "docs-only"})
IMPLEMENTATION_BRANCH = "integration/stage-5bd"
STAGED_IMPLEMENTATION_BRANCH = "integration/stage-5bd"
IMPLEMENTATION_BRANCHES = frozenset(
    {IMPLEMENTATION_BRANCH, STAGED_IMPLEMENTATION_BRANCH}
)
LIVE_EQUIVALENT_TARGET_REFS: frozenset[str] = frozenset(
    f"refs/heads/{branch}" for branch in IMPLEMENTATION_BRANCHES
)
LIVE_EQUIVALENT_PR_BASE_REFS: frozenset[str] = IMPLEMENTATION_BRANCHES
SUPPORTED_PR_ACTIONS = frozenset(
    {"opened", "reopened", "synchronize", "ready_for_review"}
)
APPROVED_WORKFLOW_PATH = ".github/workflows/main.yml"
APPROVED_WORKFLOW_ID = 299724871
SOURCE_CI_FRESHNESS = timedelta(hours=72)
ZERO_SHA = "0" * 40
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_SOURCE_JOBS = frozenset(
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
        "Full CI Attestation",
        "CI Gate",
    }
)

FINAL_FULL_REFS = frozenset()
FINAL_FULL_PREFIXES = (
    "refs/heads/release/",
    "refs/heads/production/",
    "refs/heads/hotfix/production/",
)

GOVERNANCE_EXACT_PATHS = frozenset(
    {
        "scripts/validate-compose-safety.sh",
        "scripts/package-production-candidate.sh",
        "scripts/prepare-production-candidate.sh",
        "scripts/activate-production-release.sh",
        "scripts/minio-readonly-manifest.sh",
        "scripts/dev-compose.sh",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        "package.json",
        "pnpm-lock.yaml",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/alembic.ini",
        "backend/migrate.py",
        "backend/audit.py",
        "backend/app/db/migration_safety.py",
        "scripts/tests/test_dev_compose_schema_controls.py",
        "scripts/tests/test_postgres_test_bootstrap_contract.py",
    }
)
GOVERNANCE_PREFIXES = (
    ".github/workflows/",
    ".github/actions/",
    ".github/scripts/",
    "scripts/ci/",
    "backend/alembic/",
    "backend/app/db/schema_manifests/",
    "backend/app/db/audit/",
)
GOVERNANCE_GLOBS = (
    "scripts/postgres-logical-*.sh",
    "docker/docker-compose*.yml",
    "docker/.env*.example",
    "backend/.env.production*.example",
)


class ClassificationFailure(RuntimeError):
    """An expected uncertainty that must fall back to full CI."""


@dataclass(frozen=True)
class CIEvent:
    event_name: str
    before_sha: str
    current_sha: str
    ref: str
    forced: bool
    repository: str
    repository_id: int
    comparison_ref_ready: bool = True
    action: str = ""
    pr_number: int = 0
    draft: bool = False
    base_ref: str = ""
    base_sha: str = ""
    head_ref: str = ""
    head_sha: str = ""
    head_repository: str = ""
    head_repository_id: int = 0


@dataclass(frozen=True)
class Classification:
    ci_mode: str
    reason: str
    comparison_base: str = ""
    source_sha: str = ""
    source_run_id: str = ""
    source_tree: str = ""
    workflow_revision: str = ""

    def __post_init__(self) -> None:
        if self.ci_mode not in CI_MODES:
            raise ValueError(f"invalid CI mode: {self.ci_mode}")


class ActionsEvidence(Protocol):
    def workflow_runs(self, source_sha: str) -> list[dict[str, Any]]: ...

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]: ...

    def ref_sha(self, ref_name: str) -> str: ...

    def pull_request(self, number: int) -> dict[str, Any]: ...


class GitRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _run(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=check,
        )

    def merge_base(self, left: str, right: str) -> str:
        return self._run("merge-base", left, right).stdout.strip()

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        output = self._run("diff", "--name-only", "--no-renames", base, head).stdout
        return tuple(line for line in output.splitlines() if line)

    def parents(self, commit: str) -> tuple[str, ...]:
        fields = self._run("rev-list", "--parents", "-n", "1", commit).stdout.split()
        if not fields:
            raise ClassificationFailure("commit parent query returned no result")
        return tuple(fields[1:])

    def first_parent_count(self, base: str, head: str) -> int:
        output = self._run(
            "rev-list", "--first-parent", "--count", f"{base}..{head}"
        ).stdout.strip()
        return int(output)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        process = self._run(
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            check=False,
        )
        if process.returncode not in (0, 1):
            raise ClassificationFailure("git ancestry query failed")
        return process.returncode == 0

    def tree_sha(self, commit: str) -> str:
        return self._run("rev-parse", f"{commit}^{{tree}}").stdout.strip()

    def trees_are_equal(self, left: str, right: str) -> bool:
        return self.tree_sha(left) == self.tree_sha(right)

    def diff_is_empty(self, left: str, right: str) -> bool:
        process = self._run("diff", "--exit-code", left, right, check=False)
        if process.returncode not in (0, 1):
            raise ClassificationFailure("git tree diff failed")
        return process.returncode == 0

    def blob_sha(self, commit: str, path: str) -> str:
        return self._run("rev-parse", f"{commit}:{path}").stdout.strip()


class GitHubActionsAPI:
    def __init__(
        self,
        *,
        api_url: str,
        repository: str,
        token: str,
        timeout: float = 15.0,
    ) -> None:
        if not token:
            raise ClassificationFailure("GitHub Actions token is unavailable")
        self.api_url = api_url.rstrip("/")
        self.repository = repository
        self.token = token
        self.timeout = timeout

    def _get(self, url: str) -> tuple[Any, str]:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload, response.headers.get("Link", "")
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as error:
            raise ClassificationFailure(
                f"GitHub API evidence unavailable: {type(error).__name__}"
            ) from error

    def _url(self, path: str, parameters: dict[str, str] | None = None) -> str:
        url = f"{self.api_url}{path}"
        if parameters:
            url = f"{url}?{urlencode(parameters)}"
        return url

    @staticmethod
    def _next_link(link_header: str) -> str | None:
        for item in link_header.split(","):
            match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', item)
            if match and match.group(2) == "next":
                return match.group(1)
        return None

    def _paged_list(
        self,
        *,
        path: str,
        key: str,
        parameters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        url: str | None = self._url(path, parameters)
        items: list[dict[str, Any]] = []
        expected_total: int | None = None
        visited: set[str] = set()
        while url is not None:
            if not url.startswith(f"{self.api_url}/"):
                raise ClassificationFailure(
                    "GitHub API pagination left the approved API origin"
                )
            if url in visited:
                raise ClassificationFailure("GitHub API pagination loop detected")
            if len(visited) >= 100:
                raise ClassificationFailure(
                    "GitHub API pagination exceeded safety bound"
                )
            visited.add(url)
            payload, link = self._get(url)
            if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
                raise ClassificationFailure(
                    "GitHub API returned malformed pagination data"
                )
            total = payload.get("total_count")
            if total is not None:
                if not isinstance(total, int):
                    raise ClassificationFailure("GitHub API total_count is malformed")
                if expected_total is None:
                    expected_total = total
                elif expected_total != total:
                    raise ClassificationFailure("GitHub API pagination total changed")
            page_items = payload[key]
            if not all(isinstance(item, dict) for item in page_items):
                raise ClassificationFailure(
                    "GitHub API list contains malformed entries"
                )
            items.extend(page_items)
            url = self._next_link(link)
        if expected_total is not None and len(items) != expected_total:
            raise ClassificationFailure("GitHub API pagination is incomplete")
        return items

    def workflow_runs(self, source_sha: str) -> list[dict[str, Any]]:
        repository = quote(self.repository, safe="/")
        return self._paged_list(
            path=f"/repos/{repository}/actions/runs",
            key="workflow_runs",
            parameters={
                "head_sha": source_sha,
                "event": "push",
                "per_page": "100",
            },
        )

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        repository = quote(self.repository, safe="/")
        return self._paged_list(
            path=f"/repos/{repository}/actions/runs/{run_id}/jobs",
            key="jobs",
            parameters={"filter": "latest", "per_page": "100"},
        )

    def ref_sha(self, ref_name: str) -> str:
        repository = quote(self.repository, safe="/")
        encoded_ref = quote(ref_name, safe="")
        payload, _ = self._get(
            self._url(f"/repos/{repository}/git/ref/heads/{encoded_ref}")
        )
        try:
            sha = payload["object"]["sha"]
        except (KeyError, TypeError) as error:
            raise ClassificationFailure("GitHub ref response is malformed") from error
        if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
            raise ClassificationFailure("GitHub ref SHA is malformed")
        return sha

    def pull_request(self, number: int) -> dict[str, Any]:
        if number < 1:
            raise ClassificationFailure("pull request number is malformed")
        repository = quote(self.repository, safe="/")
        payload, _ = self._get(self._url(f"/repos/{repository}/pulls/{number}"))
        if not isinstance(payload, dict):
            raise ClassificationFailure("GitHub pull request response is malformed")
        return payload


def is_governance_path(path: str) -> bool:
    if path in GOVERNANCE_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in GOVERNANCE_PREFIXES):
        return True
    if any(fnmatch.fnmatchcase(path, pattern) for pattern in GOVERNANCE_GLOBS):
        return True
    name = Path(path).name
    return name == "Dockerfile" or name.startswith("Dockerfile.")


def is_docs_only_path(path: str) -> bool:
    if "/" not in path and (path.endswith(".md") or path.startswith("LICENSE")):
        return True
    if path.startswith("docs/"):
        return True
    if path.startswith(".github/ISSUE_TEMPLATE/"):
        return True
    if path == ".github/PULL_REQUEST_TEMPLATE.md":
        return True
    if path.startswith(".github/PULL_REQUEST_TEMPLATE/"):
        return True
    if path.startswith(".github/") and path.endswith(".md"):
        return True
    return path.startswith(".github/assets/")


def _full(reason: str, *, comparison_base: str = "") -> Classification:
    return Classification("full", reason, comparison_base=comparison_base)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ClassificationFailure("source run completion time is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ClassificationFailure(
            "source run completion time is malformed"
        ) from error
    if parsed.tzinfo is None:
        raise ClassificationFailure("source run completion time lacks timezone")
    return parsed.astimezone(timezone.utc)


def _require_source_ci(
    *,
    event: CIEvent,
    source_sha: str,
    git: GitRepository,
    api: ActionsEvidence,
    now: datetime,
) -> tuple[int, str]:
    runs = api.workflow_runs(source_sha)
    candidates: list[dict[str, Any]] = []
    for run in runs:
        repository = run.get("repository")
        if (
            run.get("head_sha") == source_sha
            and run.get("event") == "push"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("path") == APPROVED_WORKFLOW_PATH
            and run.get("workflow_id") == APPROVED_WORKFLOW_ID
            and isinstance(repository, dict)
            and repository.get("id") == event.repository_id
        ):
            candidates.append(run)
    if len(candidates) != 1:
        raise ClassificationFailure("source full-CI run is missing or ambiguous")

    run = candidates[0]
    run_id = run.get("id")
    if not isinstance(run_id, int):
        raise ClassificationFailure("source run ID is malformed")
    attempt = run.get("run_attempt")
    if not isinstance(attempt, int) or attempt < 1:
        raise ClassificationFailure("source run attempt is malformed")
    completed_at = _parse_timestamp(run.get("updated_at"))
    if completed_at > now + timedelta(minutes=5):
        raise ClassificationFailure("source run completion time is in the future")
    if now - completed_at > SOURCE_CI_FRESHNESS:
        raise ClassificationFailure("source full-CI evidence is older than 72 hours")

    jobs = api.run_jobs(run_id)
    conclusions: dict[str, list[Any]] = {}
    for job in jobs:
        name = job.get("name")
        if isinstance(name, str):
            conclusions.setdefault(name, []).append(job.get("conclusion"))
    for name in REQUIRED_SOURCE_JOBS:
        values = conclusions.get(name, [])
        if values != ["success"]:
            raise ClassificationFailure(
                f"source required job is not uniquely successful: {name}"
            )

    source_revision = git.blob_sha(source_sha, APPROVED_WORKFLOW_PATH)
    current_revision = git.blob_sha(event.current_sha, APPROVED_WORKFLOW_PATH)
    if source_revision != current_revision:
        raise ClassificationFailure("source workflow revision differs from current")
    return run_id, source_revision


def validate_equivalent_merge(
    *,
    event: CIEvent,
    git: GitRepository,
    api: ActionsEvidence,
    now: datetime,
) -> Classification:
    if event.event_name != "push":
        raise ClassificationFailure("equivalent mode requires a push event")
    if not SHA_PATTERN.fullmatch(event.before_sha) or event.before_sha == ZERO_SHA:
        raise ClassificationFailure("push before SHA is missing or zero")
    if not SHA_PATTERN.fullmatch(event.current_sha):
        raise ClassificationFailure("current SHA is malformed")
    if event.forced:
        raise ClassificationFailure("forced pushes cannot use equivalent mode")

    parents = git.parents(event.current_sha)
    if len(parents) != 2:
        raise ClassificationFailure("HEAD is not a two-parent merge commit")
    parent1, parent2 = parents
    if parent1 != event.before_sha:
        raise ClassificationFailure("first parent does not equal push before SHA")
    if git.first_parent_count(event.before_sha, event.current_sha) != 1:
        raise ClassificationFailure("push contains multiple first-parent commits")
    if not git.is_ancestor(parent1, parent2):
        raise ClassificationFailure("target parent is not an ancestor of source")

    ref_prefix = "refs/heads/"
    if not event.ref.startswith(ref_prefix):
        raise ClassificationFailure("target ref is not a branch")
    ref_name = event.ref.removeprefix(ref_prefix)
    if api.ref_sha(ref_name) != event.current_sha:
        raise ClassificationFailure("remote target ref advanced during validation")

    if not git.trees_are_equal(event.current_sha, parent2):
        raise ClassificationFailure("merge tree differs from source tree")
    if not git.diff_is_empty(parent2, event.current_sha):
        raise ClassificationFailure("merge contains merge-only content")

    source_paths = git.changed_paths(parent1, parent2)
    if not source_paths:
        raise ClassificationFailure("source change set is empty")
    governance_paths = tuple(path for path in source_paths if is_governance_path(path))
    if governance_paths:
        raise ClassificationFailure(
            f"source modifies governance path: {governance_paths[0]}"
        )

    run_id, workflow_revision = _require_source_ci(
        event=event,
        source_sha=parent2,
        git=git,
        api=api,
        now=now,
    )
    return Classification(
        "equivalent-merge",
        "two-parent merge tree matches an exactly attested full-CI source",
        comparison_base=parent1,
        source_sha=parent2,
        source_run_id=str(run_id),
        source_tree=git.tree_sha(parent2),
        workflow_revision=workflow_revision,
    )


def _pr_repository_identity(section: Any) -> tuple[str, int]:
    if not isinstance(section, dict):
        raise ClassificationFailure("pull request ref metadata is malformed")
    repository = section.get("repo")
    if not isinstance(repository, dict):
        raise ClassificationFailure("pull request repository metadata is malformed")
    full_name = repository.get("full_name")
    repository_id = repository.get("id")
    if not isinstance(full_name, str) or not isinstance(repository_id, int):
        raise ClassificationFailure("pull request repository identity is malformed")
    return full_name, repository_id


def validate_equivalent_pull_request(
    *,
    event: CIEvent,
    git: GitRepository,
    api: ActionsEvidence,
    now: datetime,
) -> Classification:
    if event.event_name != "pull_request":
        raise ClassificationFailure(
            "pull request equivalent mode requires a pull_request event"
        )
    if event.action not in SUPPORTED_PR_ACTIONS:
        raise ClassificationFailure("pull request action is unsupported")
    if event.draft:
        raise ClassificationFailure("draft pull requests cannot use equivalent mode")
    if event.pr_number < 1:
        raise ClassificationFailure("pull request number is malformed")
    if event.base_ref not in IMPLEMENTATION_BRANCHES:
        raise ClassificationFailure("pull request base is not approved")
    if (
        event.head_repository != event.repository
        or event.head_repository_id != event.repository_id
    ):
        raise ClassificationFailure("fork pull requests cannot use equivalent mode")
    if not SHA_PATTERN.fullmatch(event.current_sha):
        raise ClassificationFailure("synthetic merge SHA is malformed")
    if not SHA_PATTERN.fullmatch(event.base_sha):
        raise ClassificationFailure("pull request base SHA is malformed")
    if not SHA_PATTERN.fullmatch(event.head_sha):
        raise ClassificationFailure("pull request head SHA is malformed")
    if event.ref != f"refs/pull/{event.pr_number}/merge":
        raise ClassificationFailure("synthetic merge ref is malformed")

    parents = git.parents(event.current_sha)
    if parents != (event.base_sha, event.head_sha):
        raise ClassificationFailure(
            "synthetic merge parents do not match pull request base and head"
        )
    if not git.is_ancestor(event.base_sha, event.head_sha):
        raise ClassificationFailure(
            "pull request head is not descended from the current base"
        )
    if not git.trees_are_equal(event.current_sha, event.head_sha):
        raise ClassificationFailure(
            "synthetic merge tree differs from pull request head tree"
        )
    if not git.diff_is_empty(event.head_sha, event.current_sha):
        raise ClassificationFailure("synthetic merge contains candidate-only content")

    source_paths = git.changed_paths(event.base_sha, event.head_sha)
    if not source_paths:
        raise ClassificationFailure("pull request source change set is empty")
    governance_paths = tuple(path for path in source_paths if is_governance_path(path))
    if governance_paths:
        raise ClassificationFailure(
            f"source modifies governance path: {governance_paths[0]}"
        )

    pull_request = api.pull_request(event.pr_number)
    if (
        pull_request.get("number") != event.pr_number
        or pull_request.get("state") != "open"
        or pull_request.get("draft") is not False
        or pull_request.get("mergeable") is not True
        or pull_request.get("merge_commit_sha") != event.current_sha
    ):
        raise ClassificationFailure(
            "current pull request metadata does not match the candidate event"
        )
    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise ClassificationFailure("pull request base or head metadata is malformed")
    if base.get("ref") != event.base_ref or base.get("sha") != event.base_sha:
        raise ClassificationFailure("current pull request base has changed")
    if head.get("ref") != event.head_ref or head.get("sha") != event.head_sha:
        raise ClassificationFailure("current pull request head has changed")
    if _pr_repository_identity(base) != (event.repository, event.repository_id):
        raise ClassificationFailure("pull request base repository does not match")
    if _pr_repository_identity(head) != (event.repository, event.repository_id):
        raise ClassificationFailure("pull request head repository does not match")
    if api.ref_sha(event.base_ref) != event.base_sha:
        raise ClassificationFailure("pull request base branch advanced")
    if api.ref_sha(event.head_ref) != event.head_sha:
        raise ClassificationFailure("pull request head branch advanced")

    run_id, workflow_revision = _require_source_ci(
        event=event,
        source_sha=event.head_sha,
        git=git,
        api=api,
        now=now,
    )
    return Classification(
        "equivalent-merge",
        "synthetic merge tree matches an exactly attested full-CI PR head",
        comparison_base=event.base_sha,
        source_sha=event.head_sha,
        source_run_id=str(run_id),
        source_tree=git.tree_sha(event.head_sha),
        workflow_revision=workflow_revision,
    )


def classify_ci_mode(
    *,
    event: CIEvent,
    git: GitRepository,
    api: ActionsEvidence | None = None,
    equivalent_allowlist: frozenset[str] = LIVE_EQUIVALENT_TARGET_REFS,
    pr_equivalent_allowlist: frozenset[str] = LIVE_EQUIVALENT_PR_BASE_REFS,
    now: datetime | None = None,
) -> Classification:
    if event.ref == "refs/heads/main":
        return _full("main always runs full CI")
    if event.ref in FINAL_FULL_REFS or event.ref.startswith(FINAL_FULL_PREFIXES):
        return _full("final, release, or production branch always runs full CI")
    if event.event_name == "pull_request":
        if event.base_ref == "main":
            return _full("main pull request candidates always run full CI")
        if event.base_ref not in IMPLEMENTATION_BRANCHES:
            return _full("unapproved pull request base falls back to full CI")
        try:
            changed_paths = git.changed_paths(event.base_sha, event.head_sha)
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            return _full(
                f"pull request comparison failed closed: {type(error).__name__}"
            )
        if not changed_paths:
            return _full("empty pull request change set falls back to full CI")
        governance_paths = tuple(
            path for path in changed_paths if is_governance_path(path)
        )
        if governance_paths:
            return _full(
                f"governance path requires full CI: {governance_paths[0]}",
                comparison_base=event.base_sha,
            )
        if event.base_ref not in pr_equivalent_allowlist:
            return _full(
                "pull request equivalent rollout is disabled",
                comparison_base=event.base_sha,
            )
        if api is None:
            return _full("pull request equivalent evidence API is unavailable")
        try:
            return validate_equivalent_pull_request(
                event=event,
                git=git,
                api=api,
                now=(now or datetime.now(timezone.utc)),
            )
        except (
            ClassificationFailure,
            subprocess.SubprocessError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            return _full(f"pull request validation failed closed: {error}")

    if event.event_name != "push":
        return _full("unsupported event falls back to full CI")

    if event.ref in equivalent_allowlist:
        if api is None:
            return _full("equivalent evidence API is unavailable")
        try:
            return validate_equivalent_merge(
                event=event,
                git=git,
                api=api,
                now=(now or datetime.now(timezone.utc)),
            )
        except (
            ClassificationFailure,
            subprocess.SubprocessError,
            OSError,
            ValueError,
        ) as error:
            return _full(f"equivalent validation failed closed: {error}")

    if not event.comparison_ref_ready:
        return _full("comparison ref refresh failed; running full CI")

    try:
        comparison_base = git.merge_base(event.current_sha, "origin/main")
        changed_paths = git.changed_paths(comparison_base, event.current_sha)
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        return _full(f"comparison failed closed: {type(error).__name__}")

    if not changed_paths:
        return _full(
            "empty change set falls back to full CI", comparison_base=comparison_base
        )
    governance_paths = tuple(path for path in changed_paths if is_governance_path(path))
    if governance_paths:
        return _full(
            f"governance path requires full CI: {governance_paths[0]}",
            comparison_base=comparison_base,
        )
    if all(is_docs_only_path(path) for path in changed_paths):
        return Classification(
            "docs-only",
            "all changed paths are documentation-only",
            comparison_base=comparison_base,
        )
    return _full(
        "application or unknown path requires full CI", comparison_base=comparison_base
    )


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0", ""}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _write_outputs(classification: Classification, output_path: Path) -> None:
    reason = " ".join(classification.reason.splitlines())
    fields = {
        "ci_mode": classification.ci_mode,
        "reason": reason,
        "comparison_base": classification.comparison_base,
        "source_sha": classification.source_sha,
        "source_run_id": classification.source_run_id,
        "source_tree": classification.source_tree,
        "workflow_revision": classification.workflow_revision,
        "run_checks": str(classification.ci_mode == "full").lower(),
    }
    with output_path.open("a", encoding="utf-8") as output:
        for name, value in fields.items():
            output.write(f"{name}={value}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--before-sha", required=True)
    parser.add_argument("--current-sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--forced", type=_boolean, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", type=int, required=True)
    parser.add_argument("--comparison-ref-ready", type=_boolean, default=True)
    parser.add_argument("--action", default="")
    parser.add_argument("--pr-number", type=int, default=0)
    parser.add_argument("--draft", type=_boolean, default=False)
    parser.add_argument("--base-ref", default="")
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--head-repository", default="")
    parser.add_argument("--head-repository-id", type=int, default=0)
    parser.add_argument("--api-url", default="https://api.github.com")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--expect-mode", choices=sorted(CI_MODES))
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    event = CIEvent(
        event_name=arguments.event_name,
        before_sha=arguments.before_sha,
        current_sha=arguments.current_sha,
        ref=arguments.ref,
        forced=arguments.forced,
        repository=arguments.repository,
        repository_id=arguments.repository_id,
        comparison_ref_ready=arguments.comparison_ref_ready,
        action=arguments.action,
        pr_number=arguments.pr_number,
        draft=arguments.draft,
        base_ref=arguments.base_ref,
        base_sha=arguments.base_sha,
        head_ref=arguments.head_ref,
        head_sha=arguments.head_sha,
        head_repository=arguments.head_repository,
        head_repository_id=arguments.head_repository_id,
    )
    git = GitRepository(arguments.repository_root)
    api: GitHubActionsAPI | None = None
    if (
        event.ref in LIVE_EQUIVALENT_TARGET_REFS
        or event.base_ref in LIVE_EQUIVALENT_PR_BASE_REFS
    ):
        try:
            api = GitHubActionsAPI(
                api_url=arguments.api_url,
                repository=event.repository,
                token=os.environ.get("GITHUB_TOKEN", ""),
            )
        except ClassificationFailure:
            api = None
    classification = classify_ci_mode(event=event, git=git, api=api)
    if arguments.github_output:
        _write_outputs(classification, arguments.github_output)
    print(f"ci_mode={classification.ci_mode}")
    print(f"reason={classification.reason}")
    if arguments.expect_mode and classification.ci_mode != arguments.expect_mode:
        print(
            f"expected {arguments.expect_mode}, received {classification.ci_mode}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
