#!/usr/bin/env python3
"""Fail-closed CI mode classification and merge-equivalence attestation."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from project_governance import (
    GovernanceConfigError,
    ProjectGovernance,
    load_project_governance,
)

CI_MODES = frozenset({"full", "equivalent-merge", "docs-only", "coordination-start"})
SUPPORTED_PR_ACTIONS = frozenset(
    {"opened", "reopened", "synchronize", "ready_for_review"}
)
APPROVED_WORKFLOW_PATH = ".github/workflows/main.yml"
APPROVED_WORKFLOW_ID = 299724871
SOURCE_CI_FRESHNESS = timedelta(hours=72)
START_EVIDENCE_MAX_OBSERVATIONS = 10
START_EVIDENCE_POLL_INTERVAL_SECONDS = 2.0
COORDINATION_WORKFLOW_PATH = ".github/workflows/coordination.yml"
START_ARTIFACT_FILE = "coordination-start-attestation.json"
MAX_JOB_LOG_BYTES = 1_000_000
ZERO_SHA = "0" * 40
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RUNNER_LOG_LINE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z (.*)$"
)

REQUIRED_SOURCE_JOBS = frozenset(
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
        ".github/production-deploy-authority.json",
        ".github/project-governance.json",
        "scripts/validate-compose-safety.sh",
        "scripts/package-production-candidate.sh",
        "scripts/prepare-production-candidate.sh",
        "scripts/activate-production-release.sh",
        "scripts/install-production-activation-framework.sh",
        "scripts/pastexam-activate-ssh-wrapper.sh",
        "scripts/production-activation-contract.py",
        "scripts/production-deployment-control.py",
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
    ".github/trusted-activation/",
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
    def workflow_runs(
        self,
        source_sha: str,
        event: str | None = "push",
    ) -> list[dict[str, Any]]: ...

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]: ...

    def run_attempt_jobs(
        self,
        run_id: int,
        run_attempt: int,
    ) -> list[dict[str, Any]]: ...

    def job_log(self, job_id: int) -> bytes: ...

    def ref_sha(self, ref_name: str) -> str: ...

    def pull_request(self, number: int) -> dict[str, Any]: ...

    def pull_requests_for_commit(self, commit: str) -> list[dict[str, Any]]: ...

    def commit_object(self, commit: str) -> dict[str, Any]: ...


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

    def commit_object_parents(self, commit: str) -> tuple[str, ...]:
        """Read parent identities from the commit object, even in a shallow clone."""
        output = self._run("cat-file", "-p", commit).stdout
        parents: list[str] = []
        for line in output.splitlines():
            if not line:
                break
            if line.startswith("parent "):
                parent = line.removeprefix("parent ")
                if not SHA_PATTERN.fullmatch(parent):
                    raise ClassificationFailure("commit parent identity is malformed")
                parents.append(parent)
        return tuple(parents)

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

    def tracked_paths(self, commit: str) -> tuple[str, ...]:
        output = self._run(
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            commit,
        ).stdout
        return tuple(path for path in output.split("\0") if path)

    def path_identity(self, commit: str, path: str) -> tuple[str, str, str]:
        output = self._run("ls-tree", "-z", commit, "--", path).stdout
        entries = tuple(entry for entry in output.split("\0") if entry)
        if len(entries) != 1 or "\t" not in entries[0]:
            raise ClassificationFailure("governance path identity is unavailable")
        metadata, observed_path = entries[0].split("\t", 1)
        fields = metadata.split()
        if (
            len(fields) != 3
            or observed_path != path
            or not re.fullmatch(r"[0-7]{6}", fields[0])
            or fields[1] not in {"blob", "commit"}
            or not SHA_PATTERN.fullmatch(fields[2])
        ):
            raise ClassificationFailure("governance path identity is malformed")
        return fields[0], fields[1], fields[2]

    def blob_bytes(self, commit: str, path: str) -> bytes:
        process = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        return process.stdout

    def tree_entries(self, commit: str) -> dict[str, tuple[str, str, str]]:
        process = subprocess.run(
            ["git", "ls-tree", "-r", "-z", commit],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        entries: dict[str, tuple[str, str, str]] = {}
        for raw_entry in process.stdout.split(b"\0"):
            if not raw_entry:
                continue
            try:
                metadata, raw_path = raw_entry.split(b"\t", 1)
                mode, kind, raw_sha = metadata.split()
                path = raw_path.decode("utf-8")
                identity = (
                    mode.decode("ascii"),
                    kind.decode("ascii"),
                    raw_sha.decode("ascii"),
                )
            except (UnicodeDecodeError, ValueError) as error:
                raise ClassificationFailure("Git tree entry is malformed") from error
            if (
                path in entries
                or not re.fullmatch(r"[0-7]{6}", identity[0])
                or identity[1] not in {"blob", "commit"}
                or not SHA_PATTERN.fullmatch(identity[2])
            ):
                raise ClassificationFailure("Git tree entry identity is malformed")
            entries[path] = identity
        return entries


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

    def _get_bytes(self, url: str) -> bytes:
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(
                self,
                request: Request,
                file_pointer: Any,
                code: int,
                message: str,
                headers: Any,
                new_url: str,
            ) -> None:
                return None

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
            with build_opener(NoRedirect).open(
                request, timeout=self.timeout
            ) as response:
                return response.read()
        except HTTPError as redirect:
            if redirect.code != 302:
                raise ClassificationFailure(
                    f"GitHub artifact evidence unavailable: HTTP {redirect.code}"
                ) from redirect
            location = redirect.headers.get("Location", "")
            parsed = urlparse(location)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ClassificationFailure(
                    "GitHub artifact redirect is malformed"
                ) from redirect
            unsigned_request = Request(
                location,
                headers={"Accept": "application/octet-stream"},
                method="GET",
            )
            try:
                with urlopen(unsigned_request, timeout=self.timeout) as response:
                    return response.read()
            except (HTTPError, URLError, TimeoutError) as error:
                raise ClassificationFailure(
                    f"GitHub artifact download unavailable: {type(error).__name__}"
                ) from error
        except (URLError, TimeoutError) as error:
            raise ClassificationFailure(
                f"GitHub artifact evidence unavailable: {type(error).__name__}"
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

    def workflow_runs(
        self,
        source_sha: str,
        event: str | None = "push",
    ) -> list[dict[str, Any]]:
        repository = quote(self.repository, safe="/")
        parameters = {
            "head_sha": source_sha,
            "per_page": "100",
        }
        if event is not None:
            parameters["event"] = event
        return self._paged_list(
            path=f"/repos/{repository}/actions/runs",
            key="workflow_runs",
            parameters=parameters,
        )

    def workflow_run(self, run_id: int) -> dict[str, Any]:
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
            raise ClassificationFailure("workflow run identity is malformed")
        repository = quote(self.repository, safe="/")
        payload, _ = self._get(self._url(f"/repos/{repository}/actions/runs/{run_id}"))
        if not isinstance(payload, dict):
            raise ClassificationFailure("GitHub workflow run response is malformed")
        return payload

    def workflow_definition(self, path: str) -> dict[str, Any]:
        repository = quote(self.repository, safe="/")
        encoded = quote(path, safe="")
        payload, _ = self._get(
            self._url(f"/repos/{repository}/actions/workflows/{encoded}")
        )
        if not isinstance(payload, dict):
            raise ClassificationFailure("GitHub workflow response is malformed")
        return payload

    def run_artifacts(self, run_id: int) -> list[dict[str, Any]]:
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
            raise ClassificationFailure("workflow run identity is malformed")
        repository = quote(self.repository, safe="/")
        return self._paged_list(
            path=f"/repos/{repository}/actions/runs/{run_id}/artifacts",
            key="artifacts",
            parameters={"per_page": "100"},
        )

    def artifact_archive(self, artifact_id: int) -> bytes:
        if (
            isinstance(artifact_id, bool)
            or not isinstance(artifact_id, int)
            or artifact_id < 1
        ):
            raise ClassificationFailure("artifact identity is malformed")
        repository = quote(self.repository, safe="/")
        return self._get_bytes(
            self._url(f"/repos/{repository}/actions/artifacts/{artifact_id}/zip")
        )

    def ruleset(self, ruleset_id: int) -> dict[str, Any]:
        if (
            isinstance(ruleset_id, bool)
            or not isinstance(ruleset_id, int)
            or ruleset_id < 1
        ):
            raise ClassificationFailure("ruleset identity is malformed")
        repository = quote(self.repository, safe="/")
        payload, _ = self._get(self._url(f"/repos/{repository}/rulesets/{ruleset_id}"))
        if not isinstance(payload, dict):
            raise ClassificationFailure("GitHub ruleset response is malformed")
        return payload

    def github_app(self, slug: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?", slug):
            raise ClassificationFailure("GitHub App slug is malformed")
        payload, _ = self._get(self._url(f"/apps/{quote(slug, safe='')}"))
        if not isinstance(payload, dict):
            raise ClassificationFailure("GitHub App response is malformed")
        return payload

    def user(self, login: str) -> dict[str, Any]:
        if not isinstance(login, str) or not login:
            raise ClassificationFailure("GitHub user login is malformed")
        payload, _ = self._get(self._url(f"/users/{quote(login, safe='')}"))
        if not isinstance(payload, dict):
            raise ClassificationFailure("GitHub user response is malformed")
        return payload

    def repository_commit(self, commit: str) -> dict[str, Any]:
        if not isinstance(commit, str) or not SHA_PATTERN.fullmatch(commit):
            raise ClassificationFailure("commit identity is malformed")
        repository = quote(self.repository, safe="/")
        payload, _ = self._get(self._url(f"/repos/{repository}/commits/{commit}"))
        if not isinstance(payload, dict):
            raise ClassificationFailure(
                "GitHub repository commit response is malformed"
            )
        return payload

    def commit_object(self, commit: str) -> dict[str, Any]:
        if not isinstance(commit, str) or not SHA_PATTERN.fullmatch(commit):
            raise ClassificationFailure("commit identity is malformed")
        repository = quote(self.repository, safe="/")
        payload, _ = self._get(self._url(f"/repos/{repository}/git/commits/{commit}"))
        if not isinstance(payload, dict):
            raise ClassificationFailure("GitHub commit response is malformed")
        return payload

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        repository = quote(self.repository, safe="/")
        return self._paged_list(
            path=f"/repos/{repository}/actions/runs/{run_id}/jobs",
            key="jobs",
            parameters={"filter": "latest", "per_page": "100"},
        )

    def run_attempt_jobs(
        self,
        run_id: int,
        run_attempt: int,
    ) -> list[dict[str, Any]]:
        if (
            isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id < 1
            or isinstance(run_attempt, bool)
            or not isinstance(run_attempt, int)
            or run_attempt < 1
        ):
            raise ClassificationFailure("workflow run attempt identity is malformed")
        repository = quote(self.repository, safe="/")
        return self._paged_list(
            path=(
                f"/repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}/jobs"
            ),
            key="jobs",
            parameters={"per_page": "100"},
        )

    def job_log(self, job_id: int) -> bytes:
        if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
            raise ClassificationFailure("workflow job identity is malformed")
        repository = quote(self.repository, safe="/")
        return self._get_bytes(
            self._url(f"/repos/{repository}/actions/jobs/{job_id}/logs")
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

    def pull_requests_for_commit(self, commit: str) -> list[dict[str, Any]]:
        if not isinstance(commit, str) or not SHA_PATTERN.fullmatch(commit):
            raise ClassificationFailure("commit identity is malformed")
        repository = quote(self.repository, safe="/")
        url: str | None = self._url(
            f"/repos/{repository}/commits/{commit}/pulls",
            {"per_page": "100"},
        )
        pull_requests: list[dict[str, Any]] = []
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
            if not isinstance(payload, list) or not all(
                isinstance(item, dict) for item in payload
            ):
                raise ClassificationFailure(
                    "GitHub commit pull-request response is malformed"
                )
            pull_requests.extend(payload)
            url = self._next_link(link)
        return pull_requests


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
    if path == ".github/CODEOWNERS":
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


def classify_main_pull_request(
    *,
    event: CIEvent,
    git: GitRepository,
) -> Classification:
    if event.action not in SUPPORTED_PR_ACTIONS:
        raise ClassificationFailure("pull request action is unsupported")
    if event.pr_number < 1:
        raise ClassificationFailure("pull request number is malformed")
    if event.base_ref != "main":
        raise ClassificationFailure("pull request base is not main")
    if not event.repository or event.repository_id < 1:
        raise ClassificationFailure("base repository identity is malformed")
    if not event.head_ref:
        raise ClassificationFailure("pull request head ref is malformed")
    if not event.head_repository or event.head_repository_id < 1:
        raise ClassificationFailure("head repository identity is malformed")
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

    changed_paths = git.changed_paths(event.base_sha, event.head_sha)
    if not changed_paths:
        raise ClassificationFailure("pull request change set is empty")
    governance_paths = tuple(path for path in changed_paths if is_governance_path(path))
    if governance_paths:
        return _full(
            f"governance path requires full CI: {governance_paths[0]}",
            comparison_base=event.base_sha,
        )
    if all(is_docs_only_path(path) for path in changed_paths):
        return Classification(
            "docs-only",
            "all pull request paths are documentation-only",
            comparison_base=event.base_sha,
        )
    return _full(
        "main pull request contains an application or unknown path",
        comparison_base=event.base_sha,
    )


def _full(reason: str, *, comparison_base: str = "") -> Classification:
    return Classification("full", reason, comparison_base=comparison_base)


def _parse_named_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ClassificationFailure(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ClassificationFailure(f"{label} is malformed") from error
    if parsed.tzinfo is None:
        raise ClassificationFailure(f"{label} lacks timezone")
    return parsed.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime:
    return _parse_named_timestamp(value, "source run completion time")


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


def _strict_json_object(data: bytes, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ClassificationFailure(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClassificationFailure(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ClassificationFailure(f"{label} must be a JSON object")
    return payload


def _require_exact_governance(
    *,
    git: GitRepository,
    commit: str,
    expected_coordination: str | None,
    label: str,
) -> None:
    payload = _strict_json_object(
        git.blob_bytes(commit, ".github/project-governance.json"),
        label=label,
    )
    expected = {
        "schema_version": 1,
        "default_development_base": "main",
        "coordination_branch": expected_coordination,
    }
    if payload != expected:
        raise ClassificationFailure(f"{label} does not match canonical schema")


def _require_start_tree_identity(
    *,
    git: GitRepository,
    parent_sha: str,
    head_sha: str,
) -> None:
    governance_path = ".github/project-governance.json"
    parent_entries = git.tree_entries(parent_sha)
    head_entries = git.tree_entries(head_sha)
    if set(parent_entries) != set(head_entries):
        raise ClassificationFailure("Start tracked-tree inventory differs from main")
    if governance_path not in parent_entries:
        raise ClassificationFailure("canonical governance path is missing")
    parent_governance = parent_entries[governance_path]
    head_governance = head_entries[governance_path]
    if (
        parent_governance[:2] != ("100644", "blob")
        or head_governance[:2] != ("100644", "blob")
        or parent_governance[2] == head_governance[2]
    ):
        raise ClassificationFailure("Start governance blob identity is invalid")
    for path in sorted(parent_entries):
        if path == governance_path:
            continue
        if parent_entries[path] != head_entries[path]:
            raise ClassificationFailure(
                f"Start non-governance tree identity differs: {path}"
            )
    if git.changed_paths(parent_sha, head_sha) != (governance_path,):
        raise ClassificationFailure("Start source difference is not governance-only")


def _require_parent_full_ci(
    *,
    event: CIEvent,
    git: GitRepository,
    api: Any,
    parent_sha: str,
    not_after: datetime,
    now: datetime,
) -> tuple[int, int]:
    candidates: list[dict[str, Any]] = []
    for run in api.workflow_runs(parent_sha, event="push"):
        repository = run.get("repository")
        if (
            run.get("head_sha") == parent_sha
            and run.get("head_branch") == "main"
            and run.get("event") == "push"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("path") == APPROVED_WORKFLOW_PATH
            and run.get("workflow_id") == APPROVED_WORKFLOW_ID
            and isinstance(repository, dict)
            and repository.get("id") == event.repository_id
            and repository.get("full_name") == event.repository
        ):
            candidates.append(run)
    if len(candidates) != 1:
        raise ClassificationFailure("parent Full run is missing or ambiguous")

    run = candidates[0]
    run_id = run.get("id")
    attempt = run.get("run_attempt")
    if (
        isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id < 1
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt < 1
    ):
        raise ClassificationFailure("parent Full run attempt identity is malformed")
    created_at = _parse_named_timestamp(
        run.get("created_at"), "parent run creation time"
    )
    completed_at = _parse_named_timestamp(
        run.get("updated_at"), "parent run completion time"
    )
    if (
        created_at > completed_at
        or completed_at > not_after
        or completed_at > now + timedelta(minutes=5)
        or now - completed_at > SOURCE_CI_FRESHNESS
    ):
        raise ClassificationFailure("parent Full run freshness is invalid")

    conclusions: dict[str, list[tuple[Any, ...]]] = {}
    for job in api.run_attempt_jobs(run_id, attempt):
        name = job.get("name")
        if isinstance(name, str):
            conclusions.setdefault(name, []).append(
                (
                    job.get("status"),
                    job.get("conclusion"),
                    job.get("run_id"),
                    job.get("run_attempt"),
                    job.get("head_sha"),
                )
            )
    expected = [("completed", "success", run_id, attempt, parent_sha)]
    for name in REQUIRED_SOURCE_JOBS:
        if conclusions.get(name, []) != expected:
            raise ClassificationFailure(
                f"parent required Full job is not uniquely successful: {name}"
            )
    if git.blob_sha(parent_sha, APPROVED_WORKFLOW_PATH) != git.blob_sha(
        event.current_sha, APPROVED_WORKFLOW_PATH
    ):
        raise ClassificationFailure("parent Full workflow revision differs from Start")
    return run_id, attempt


def _read_start_artifact(archive: bytes, *, expected_digest: str) -> dict[str, Any]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest):
        raise ClassificationFailure("Start artifact digest is malformed")
    observed_digest = "sha256:" + hashlib.sha256(archive).hexdigest()
    if observed_digest != expected_digest:
        raise ClassificationFailure("Start artifact digest does not match")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if (
                len(members) != 1
                or members[0].filename != START_ARTIFACT_FILE
                or members[0].is_dir()
                or members[0].file_size > 131_072
            ):
                raise ClassificationFailure("Start artifact archive is malformed")
            return _strict_json_object(
                bundle.read(members[0]), label="Start lifecycle attestation"
            )
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        if isinstance(error, ClassificationFailure):
            raise
        raise ClassificationFailure("Start artifact archive is unreadable") from error


def _load_start_lifecycle_evidence(
    *,
    event: CIEvent,
    api: Any,
    parent_sha: str,
    now: datetime,
    max_observations: int = START_EVIDENCE_MAX_OBSERVATIONS,
    poll_interval_seconds: float = START_EVIDENCE_POLL_INTERVAL_SECONDS,
    sleeper: Any = time.sleep,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = api.workflow_definition(COORDINATION_WORKFLOW_PATH)
    workflow_id = workflow.get("id")
    if (
        isinstance(workflow_id, bool)
        or not isinstance(workflow_id, int)
        or workflow_id < 1
        or workflow.get("path") != COORDINATION_WORKFLOW_PATH
        or workflow.get("state") != "active"
    ):
        raise ClassificationFailure("canonical coordination workflow is unavailable")

    for observation in range(1, max_observations + 1):
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for run in api.workflow_runs(parent_sha, event="workflow_dispatch"):
            repository = run.get("repository")
            if not (
                run.get("workflow_id") == workflow_id
                and run.get("path") == COORDINATION_WORKFLOW_PATH
                and run.get("event") == "workflow_dispatch"
                and run.get("head_branch") == "main"
                and run.get("head_sha") == parent_sha
                and run.get("status") == "completed"
                and run.get("conclusion") == "success"
                and isinstance(repository, dict)
                and repository.get("id") == event.repository_id
                and repository.get("full_name") == event.repository
            ):
                continue
            run_id = run.get("id")
            attempt = run.get("run_attempt")
            if (
                isinstance(run_id, bool)
                or not isinstance(run_id, int)
                or run_id < 1
                or isinstance(attempt, bool)
                or not isinstance(attempt, int)
                or attempt < 1
            ):
                raise ClassificationFailure("lifecycle run identity is malformed")
            created_at = _parse_named_timestamp(
                run.get("created_at"), "lifecycle run creation time"
            )
            completed_at = _parse_named_timestamp(
                run.get("updated_at"), "lifecycle run completion time"
            )
            if (
                created_at > completed_at
                or completed_at > now + timedelta(minutes=5)
                or now - completed_at > SOURCE_CI_FRESHNESS
            ):
                raise ClassificationFailure("lifecycle run freshness is invalid")
            artifact_name = f"coordination-start-{run_id}-{attempt}"
            artifacts = [
                artifact
                for artifact in api.run_artifacts(run_id)
                if artifact.get("name") == artifact_name
            ]
            if not artifacts:
                continue
            if len(artifacts) != 1:
                raise ClassificationFailure("Start lifecycle artifact is ambiguous")
            artifact = artifacts[0]
            artifact_id = artifact.get("id")
            workflow_run = artifact.get("workflow_run")
            if (
                artifact.get("expired") is not False
                or not isinstance(workflow_run, dict)
                or workflow_run.get("id") != run_id
                or workflow_run.get("repository_id") != event.repository_id
                or workflow_run.get("head_repository_id") != event.repository_id
                or workflow_run.get("head_branch") != "main"
                or workflow_run.get("head_sha") != parent_sha
            ):
                raise ClassificationFailure("Start artifact authority is malformed")
            attestation = _read_start_artifact(
                api.artifact_archive(artifact_id),
                expected_digest=artifact.get("digest"),
            )
            if attestation.get("head_sha") == event.current_sha:
                matches.append((attestation, run))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ClassificationFailure("Start lifecycle evidence is ambiguous")
        if observation < max_observations:
            sleeper(poll_interval_seconds)
    raise ClassificationFailure("Start lifecycle evidence is unavailable")


def _require_start_origin(
    *,
    event: CIEvent,
    api: Any,
    attestation: dict[str, Any],
) -> int:
    app_slug = attestation.get("app_slug")
    expected_app_id = attestation.get("expected_app_id")
    if not isinstance(app_slug, str):
        raise ClassificationFailure("Start lifecycle App slug is malformed")
    app = api.github_app(app_slug)
    if app.get("id") != expected_app_id or app.get("slug") != app_slug:
        raise ClassificationFailure("Start lifecycle App identity does not match")
    bot_login = f"{app_slug}[bot]"
    bot = api.user(bot_login)
    bot_id = bot.get("id")
    if (
        isinstance(bot_id, bool)
        or not isinstance(bot_id, int)
        or bot_id < 1
        or bot.get("login") != bot_login
        or bot.get("type") != "Bot"
    ):
        raise ClassificationFailure("Start lifecycle bot identity is malformed")

    commit = api.repository_commit(event.current_sha)
    verification = commit.get("commit", {}).get("verification")
    author = commit.get("author")
    if (
        commit.get("sha") != event.current_sha
        or not isinstance(verification, dict)
        or verification.get("verified") is not True
        or verification.get("reason") != "valid"
        or not isinstance(author, dict)
        or author.get("id") != bot_id
        or author.get("login") != bot_login
        or author.get("type") != "Bot"
    ):
        raise ClassificationFailure("Start commit lacks verified lifecycle-App origin")

    runs = []
    for run in api.workflow_runs(event.current_sha, event="push"):
        repository = run.get("repository")
        actor = run.get("actor")
        triggering_actor = run.get("triggering_actor")
        if (
            run.get("head_sha") == event.current_sha
            and run.get("head_branch") == attestation.get("branch")
            and run.get("event") == "push"
            and run.get("path") == APPROVED_WORKFLOW_PATH
            and run.get("workflow_id") == APPROVED_WORKFLOW_ID
            and isinstance(repository, dict)
            and repository.get("id") == event.repository_id
            and repository.get("full_name") == event.repository
            and isinstance(actor, dict)
            and actor.get("id") == bot_id
            and actor.get("login") == bot_login
            and isinstance(triggering_actor, dict)
            and triggering_actor.get("id") == bot_id
            and triggering_actor.get("login") == bot_login
        ):
            runs.append(run)
    if len(runs) != 1:
        raise ClassificationFailure("Start push lifecycle-App origin is ambiguous")
    return expected_app_id


def _require_start_ruleset(
    *,
    event: CIEvent,
    api: Any,
    attestation: dict[str, Any],
    expected_app_id: int,
) -> None:
    from coordination import CoordinationError, validate_ruleset

    ruleset = attestation.get("ruleset")
    if not isinstance(ruleset, dict):
        raise ClassificationFailure("Start ruleset attestation is malformed")
    try:
        validate_ruleset(ruleset, expected_app_id=expected_app_id)
    except CoordinationError as error:
        raise ClassificationFailure(
            f"Start ruleset attestation is invalid: {error}"
        ) from error
    ruleset_id = ruleset.get("id")
    if (
        isinstance(ruleset_id, bool)
        or not isinstance(ruleset_id, int)
        or ruleset_id < 1
        or ruleset.get("source") != event.repository
        or ruleset.get("source_type") != "Repository"
        or not isinstance(ruleset.get("updated_at"), str)
    ):
        raise ClassificationFailure("Start ruleset metadata is malformed")
    live = api.ruleset(ruleset_id)
    observable = {
        "id",
        "name",
        "target",
        "source",
        "source_type",
        "enforcement",
        "conditions",
        "rules",
        "updated_at",
    }
    if {key: live.get(key) for key in observable} != {
        key: ruleset.get(key) for key in observable
    }:
        raise ClassificationFailure("live integration ruleset differs from attestation")


def validate_coordination_start(
    *,
    event: CIEvent,
    git: GitRepository,
    api: Any,
    governance: ProjectGovernance,
    now: datetime,
) -> Classification:
    branch = governance.coordination_branch
    if (
        event.event_name != "push"
        or branch is None
        or event.ref != f"refs/heads/{branch}"
        or event.before_sha != ZERO_SHA
        or event.forced
        or not SHA_PATTERN.fullmatch(event.current_sha)
        or not re.fullmatch(
            r"integration/[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?-[0-9a-f]{8}",
            branch,
        )
    ):
        raise ClassificationFailure("event is not a canonical Start push")
    if not event.repository or event.repository_id < 1:
        raise ClassificationFailure("Start repository identity is malformed")

    parents = git.commit_object_parents(event.current_sha)
    if len(parents) != 1:
        raise ClassificationFailure("Start HEAD is not a one-parent commit")
    parent_sha = parents[0]
    if api.ref_sha(branch) != event.current_sha:
        raise ClassificationFailure("remote integration ref drifted")
    if api.ref_sha("main") != parent_sha:
        raise ClassificationFailure("live main advanced beyond Start parent")

    _require_exact_governance(
        git=git,
        commit=parent_sha,
        expected_coordination=None,
        label="parent main governance",
    )
    _require_exact_governance(
        git=git,
        commit=event.current_sha,
        expected_coordination=branch,
        label="Start governance",
    )
    _require_start_tree_identity(
        git=git,
        parent_sha=parent_sha,
        head_sha=event.current_sha,
    )

    attestation, lifecycle_run = _load_start_lifecycle_evidence(
        event=event,
        api=api,
        parent_sha=parent_sha,
        now=now,
    )
    expected_keys = {
        "schema_version",
        "kind",
        "repository",
        "repository_id",
        "lifecycle_run_id",
        "lifecycle_run_attempt",
        "app_slug",
        "expected_app_id",
        "branch",
        "head_sha",
        "parent_main_sha",
        "ruleset",
    }
    if set(attestation) != expected_keys:
        raise ClassificationFailure("Start lifecycle attestation schema is unsupported")
    if (
        attestation.get("schema_version") != 1
        or attestation.get("kind") != "coordination-start"
        or attestation.get("repository") != event.repository
        or attestation.get("repository_id") != event.repository_id
        or attestation.get("lifecycle_run_id") != lifecycle_run.get("id")
        or attestation.get("lifecycle_run_attempt") != lifecycle_run.get("run_attempt")
        or attestation.get("branch") != branch
        or attestation.get("head_sha") != event.current_sha
        or attestation.get("parent_main_sha") != parent_sha
    ):
        raise ClassificationFailure("Start lifecycle attestation does not match event")

    lifecycle_created_at = _parse_named_timestamp(
        lifecycle_run.get("created_at"), "lifecycle run creation time"
    )
    parent_run_id, _ = _require_parent_full_ci(
        event=event,
        git=git,
        api=api,
        parent_sha=parent_sha,
        not_after=lifecycle_created_at,
        now=now,
    )
    expected_app_id = _require_start_origin(
        event=event,
        api=api,
        attestation=attestation,
    )
    _require_start_ruleset(
        event=event,
        api=api,
        attestation=attestation,
        expected_app_id=expected_app_id,
    )

    if api.ref_sha("main") != parent_sha:
        raise ClassificationFailure("live main drifted during Start validation")
    if api.ref_sha(branch) != event.current_sha:
        raise ClassificationFailure("integration ref drifted during Start validation")
    return Classification(
        "coordination-start",
        "canonical App-created Start bootstrap reuses exact parent Full CI",
        comparison_base=parent_sha,
        source_sha=parent_sha,
        source_run_id=str(parent_run_id),
        source_tree=git.tree_sha(parent_sha),
        workflow_revision=git.blob_sha(parent_sha, APPROVED_WORKFLOW_PATH),
    )


def _require_main_derived_governance(
    *,
    git: GitRepository,
    source_sha: str,
    main_sha: str,
) -> None:
    source_paths = frozenset(
        path for path in git.tracked_paths(source_sha) if is_governance_path(path)
    )
    main_paths = frozenset(
        path for path in git.tracked_paths(main_sha) if is_governance_path(path)
    )
    if source_paths != main_paths:
        raise ClassificationFailure(
            "source governance path inventory differs from main authority"
        )
    for path in sorted(main_paths):
        if git.path_identity(source_sha, path) != git.path_identity(main_sha, path):
            raise ClassificationFailure(
                f"source governance identity differs from main authority: {path}"
            )


def _require_merged_pull_request(
    *,
    event: CIEvent,
    api: ActionsEvidence,
    coordination_branch: str,
    base_sha: str,
    source_sha: str,
    now: datetime,
) -> tuple[str, int, datetime, datetime]:
    merge_associations = api.pull_requests_for_commit(event.current_sha)
    source_associations = api.pull_requests_for_commit(source_sha)

    def is_exact_association(pull_request: dict[str, Any]) -> bool:
        base = pull_request.get("base")
        head = pull_request.get("head")
        return (
            pull_request.get("merge_commit_sha") == event.current_sha
            and isinstance(base, dict)
            and base.get("ref") == coordination_branch
            and base.get("sha") == base_sha
            and isinstance(head, dict)
            and head.get("sha") == source_sha
        )

    exact_merge_associations = tuple(
        pull_request
        for pull_request in merge_associations
        if is_exact_association(pull_request)
    )
    exact_source_associations = tuple(
        pull_request
        for pull_request in source_associations
        if is_exact_association(pull_request)
    )
    if len(exact_merge_associations) != 1 or len(exact_source_associations) != 1:
        raise ClassificationFailure("merged pull request association is ambiguous")

    pull_request = exact_merge_associations[0]
    source_pull_request = exact_source_associations[0]
    number = pull_request.get("number")
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or source_pull_request.get("number") != number
    ):
        raise ClassificationFailure("merged pull request identity is malformed")
    if (
        pull_request.get("state") != "closed"
        or pull_request.get("merge_commit_sha") != event.current_sha
    ):
        raise ClassificationFailure("pull request is not the exact merged commit")

    created_at = _parse_named_timestamp(
        pull_request.get("created_at"),
        "pull request creation time",
    )
    merged_at = _parse_named_timestamp(
        pull_request.get("merged_at"),
        "pull request merge time",
    )
    if created_at > merged_at:
        raise ClassificationFailure("pull request merge predates its creation time")
    if merged_at > now + timedelta(minutes=5):
        raise ClassificationFailure("pull request merge time is in the future")
    if now - merged_at > SOURCE_CI_FRESHNESS:
        raise ClassificationFailure(
            "merged pull request evidence is older than 72 hours"
        )

    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise ClassificationFailure("merged pull request refs are malformed")
    if base.get("ref") != coordination_branch or base.get("sha") != base_sha:
        raise ClassificationFailure("merged pull request base does not match")
    head_ref = head.get("ref")
    if not isinstance(head_ref, str) or not head_ref or head.get("sha") != source_sha:
        raise ClassificationFailure("merged pull request head does not match")
    expected_repository = (event.repository, event.repository_id)
    if _pr_repository_identity(base) != expected_repository:
        raise ClassificationFailure(
            "merged pull request base repository does not match"
        )
    if _pr_repository_identity(head) != expected_repository:
        raise ClassificationFailure(
            "merged pull request head repository does not match"
        )
    return head_ref, number, created_at, merged_at


def _require_live_merged_pull_request(
    *,
    event: CIEvent,
    api: ActionsEvidence,
    pull_request_number: int,
    coordination_branch: str,
    base_sha: str,
    source_ref: str,
    source_sha: str,
    merged_at: datetime,
) -> None:
    pull_request = api.pull_request(pull_request_number)
    if (
        pull_request.get("number") != pull_request_number
        or pull_request.get("state") != "closed"
        or pull_request.get("merged") is not True
        or pull_request.get("merge_commit_sha") != event.current_sha
        or _parse_named_timestamp(
            pull_request.get("merged_at"),
            "current pull request merge time",
        )
        != merged_at
    ):
        raise ClassificationFailure("current pull request merge identity drifted")

    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise ClassificationFailure("current pull request refs are malformed")
    if base.get("ref") != coordination_branch or base.get("sha") != base_sha:
        raise ClassificationFailure("current pull request base drifted")
    if head.get("ref") != source_ref or head.get("sha") != source_sha:
        raise ClassificationFailure("current pull request head drifted")
    expected_repository = (event.repository, event.repository_id)
    if _pr_repository_identity(base) != expected_repository:
        raise ClassificationFailure("current pull request base repository drifted")
    if _pr_repository_identity(head) != expected_repository:
        raise ClassificationFailure("current pull request head repository drifted")


def _require_pr_full_job_log_binding(
    *,
    raw_log: bytes,
    pull_request_number: int,
    pull_request_base_ref: str,
    pull_request_base_sha: str,
    source_sha: str,
    expected_tree: str,
    workflow_revision: str,
) -> str:
    if not isinstance(raw_log, bytes) or len(raw_log) > MAX_JOB_LOG_BYTES:
        raise ClassificationFailure("Full CI Attestation job log is malformed")
    try:
        text = raw_log.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ClassificationFailure(
            "Full CI Attestation job log is not UTF-8"
        ) from error

    messages: list[str] = []
    for line in text.splitlines():
        match = RUNNER_LOG_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise ClassificationFailure("Full CI Attestation job log line is malformed")
        messages.append(match.group(1))

    authority_patterns = {
        "event_environment": re.compile(r"  EVENT_NAME: (.*)"),
        "pr_number_environment": re.compile(r"  EVENT_PR_NUMBER: (.*)"),
        "head_environment": re.compile(r"  EXECUTION_HEAD_SHA: (.*)"),
        "attested_sha_environment": re.compile(r"  ATTESTED_SHA: (.*)"),
        "base_ref_environment": re.compile(r"  EVENT_BASE_REF: (.*)"),
        "base_sha_environment": re.compile(r"  EVENT_BASE_SHA: (.*)"),
        "event_output": re.compile(r"event_name=(.*)"),
        "attested_sha_output": re.compile(r"sha=(.*)"),
        "head_output": re.compile(r"execution_head_sha=(.*)"),
        "base_ref_output": re.compile(r"pull_request_base_ref=(.*)"),
        "base_sha_output": re.compile(r"pull_request_base_sha=(.*)"),
        "tree_output": re.compile(r"tree_sha=(.*)"),
        "workflow_revision_output": re.compile(r"workflow_revision=(.*)"),
    }
    authority_values: dict[str, list[str]] = {key: [] for key in authority_patterns}
    for message in messages:
        for key, pattern in authority_patterns.items():
            if (match := pattern.fullmatch(message)) is not None:
                authority_values[key].append(match.group(1))

    def require_single_value(key: str, expected: str, label: str) -> str:
        values = authority_values[key]
        if len(values) != 1:
            raise ClassificationFailure(
                f"Full CI Attestation job log {label} is missing or ambiguous"
            )
        if values[0] != expected:
            raise ClassificationFailure(
                f"Full CI Attestation job log {label} does not match"
            )
        return values[0]

    require_single_value("event_environment", "pull_request", "event")
    require_single_value(
        "pr_number_environment",
        str(pull_request_number),
        "pull request number",
    )
    require_single_value("head_environment", source_sha, "head SHA")
    require_single_value("event_output", "pull_request", "attested event")
    require_single_value("head_output", source_sha, "attested head SHA")
    require_single_value("tree_output", expected_tree, "attested tree")
    require_single_value(
        "workflow_revision_output",
        workflow_revision,
        "workflow revision",
    )

    attested_sha_values = authority_values["attested_sha_environment"]
    if (
        len(attested_sha_values) != 1
        or SHA_PATTERN.fullmatch(attested_sha_values[0]) is None
    ):
        raise ClassificationFailure(
            "Full CI Attestation job log attested SHA is missing or ambiguous"
        )
    require_single_value(
        "attested_sha_output",
        attested_sha_values[0],
        "attested SHA output",
    )

    ref_keys = ("base_ref_environment", "base_ref_output")
    sha_keys = ("base_sha_environment", "base_sha_output")
    ref_present = any(authority_values[key] for key in ref_keys)
    sha_present = any(authority_values[key] for key in sha_keys)
    if ref_present == sha_present:
        raise ClassificationFailure(
            "Full CI Attestation job log base identity is missing or ambiguous"
        )
    if ref_present:
        require_single_value(
            "base_ref_environment",
            pull_request_base_ref,
            "base ref environment",
        )
        require_single_value(
            "base_ref_output",
            pull_request_base_ref,
            "base ref output",
        )
    else:
        require_single_value(
            "base_sha_environment",
            pull_request_base_sha,
            "base SHA environment",
        )
        require_single_value(
            "base_sha_output",
            pull_request_base_sha,
            "base SHA output",
        )
    return attested_sha_values[0]


def _require_exact_full_run(
    *,
    event: CIEvent,
    api: ActionsEvidence,
    runs: list[dict[str, Any]],
    source_sha: str,
    source_ref: str,
    run_event: str,
    pull_request_number: int | None,
    pull_request_base_ref: str | None,
    pull_request_base_sha: str | None,
    expected_tree: str,
    workflow_revision: str,
    not_before: datetime | None,
    merged_at: datetime,
    now: datetime,
) -> tuple[int, str | None]:
    candidates: list[dict[str, Any]] = []
    for run in runs:
        repository = run.get("repository")
        if (
            run.get("head_sha") == source_sha
            and run.get("head_branch") == source_ref
            and run.get("event") == run_event
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("path") == APPROVED_WORKFLOW_PATH
            and run.get("workflow_id") == APPROVED_WORKFLOW_ID
            and isinstance(repository, dict)
            and repository.get("id") == event.repository_id
            and repository.get("full_name") == event.repository
        ):
            candidates.append(run)
    if len(candidates) != 1:
        raise ClassificationFailure(f"{run_event} full-CI run is missing or ambiguous")

    run = candidates[0]
    run_id = run.get("id")
    attempt = run.get("run_attempt")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise ClassificationFailure(f"{run_event} run ID is malformed")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ClassificationFailure(f"{run_event} run attempt is malformed")
    created_at = _parse_named_timestamp(
        run.get("created_at"),
        f"{run_event} run creation time",
    )
    completed_at = _parse_named_timestamp(
        run.get("updated_at"),
        f"{run_event} run completion time",
    )
    if created_at > completed_at:
        raise ClassificationFailure(f"{run_event} full-CI predates its creation time")
    if not_before is not None and created_at < not_before:
        raise ClassificationFailure(
            f"{run_event} full-CI started before the exact pull request existed"
        )
    if completed_at > now + timedelta(minutes=5):
        raise ClassificationFailure(f"{run_event} run completion time is in the future")
    if now - completed_at > SOURCE_CI_FRESHNESS:
        raise ClassificationFailure(
            f"{run_event} full-CI evidence is older than 72 hours"
        )
    if completed_at > merged_at:
        raise ClassificationFailure(f"{run_event} full-CI completed after the merge")
    attested_sha: str | None = None
    if pull_request_number is not None:
        pull_requests = run.get("pull_requests")
        if not isinstance(pull_requests, list) or not all(
            isinstance(pull_request, dict) for pull_request in pull_requests
        ):
            raise ClassificationFailure("pull_request run association is malformed")
        if pull_requests and [
            pull_request.get("number") for pull_request in pull_requests
        ] != [pull_request_number]:
            raise ClassificationFailure("pull_request run association does not match")

    jobs_by_name: dict[str, list[dict[str, Any]]] = {}
    for job in api.run_attempt_jobs(run_id, attempt):
        name = job.get("name")
        if isinstance(name, str):
            jobs_by_name.setdefault(name, []).append(job)
    expected = ("completed", "success", run_id, attempt, source_sha)
    for name in REQUIRED_SOURCE_JOBS:
        jobs = jobs_by_name.get(name, [])
        observed = [
            (
                job.get("status"),
                job.get("conclusion"),
                job.get("run_id"),
                job.get("run_attempt"),
                job.get("head_sha"),
            )
            for job in jobs
        ]
        if observed != [expected]:
            raise ClassificationFailure(
                f"{run_event} required job is not uniquely successful: {name}"
            )
    if pull_request_number is not None:
        if pull_request_base_ref is None or pull_request_base_sha is None:
            raise ClassificationFailure("pull_request base identity is missing")
        attestation_job = jobs_by_name["Full CI Attestation"][0]
        job_id = attestation_job.get("id")
        if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
            raise ClassificationFailure("Full CI Attestation job ID is malformed")
        attested_sha = _require_pr_full_job_log_binding(
            raw_log=api.job_log(job_id),
            pull_request_number=pull_request_number,
            pull_request_base_ref=pull_request_base_ref,
            pull_request_base_sha=pull_request_base_sha,
            source_sha=source_sha,
            expected_tree=expected_tree,
            workflow_revision=workflow_revision,
        )
    return run_id, attested_sha


def _require_supported_exact_state_source_history(
    *,
    git: GitRepository,
    base_sha: str,
    source_sha: str,
) -> None:
    """Allow a linear PR source or one exact merge from C, never a merge tail."""

    current = source_sha
    visited: set[str] = set()
    for _ in range(1000):
        if current in visited:
            raise ClassificationFailure("source first-parent history contains a cycle")
        visited.add(current)
        parents = git.parents(current)
        if current == source_sha and len(parents) == 2 and parents[0] == base_sha:
            return
        if len(parents) != 1:
            raise ClassificationFailure(
                "source contains an unsupported merge or reconciliation tail"
            )
        current = parents[0]
        if current == base_sha:
            return
    raise ClassificationFailure("source first-parent history exceeds safety bound")


def _require_synthetic_merge_commit(
    *,
    api: ActionsEvidence,
    synthetic_sha: str,
    base_sha: str,
    source_sha: str,
    expected_tree: str,
) -> None:
    commit = api.commit_object(synthetic_sha)
    if commit.get("sha") != synthetic_sha:
        raise ClassificationFailure("PR Full synthetic merge identity does not match")
    parents = commit.get("parents")
    if not isinstance(parents, list) or not all(
        isinstance(parent, dict) for parent in parents
    ):
        raise ClassificationFailure("PR Full synthetic merge parents are malformed")
    if [parent.get("sha") for parent in parents] != [base_sha, source_sha]:
        raise ClassificationFailure("PR Full synthetic merge parents do not match")
    tree = commit.get("tree")
    if not isinstance(tree, dict) or tree.get("sha") != expected_tree:
        raise ClassificationFailure("PR Full synthetic merge tree does not match")


def validate_protected_coordination_exact_state_reuse(
    *,
    event: CIEvent,
    git: GitRepository,
    api: ActionsEvidence,
    coordination_branch: str,
    default_branch: str,
    now: datetime,
) -> Classification:
    if event.event_name != "push":
        raise ClassificationFailure("protected exact-state reuse requires a push")
    if event.ref != f"refs/heads/{coordination_branch}":
        raise ClassificationFailure(
            "protected exact-state reuse requires the exact ref"
        )
    if not event.repository or event.repository_id < 1:
        raise ClassificationFailure("repository identity is malformed")
    if not SHA_PATTERN.fullmatch(event.before_sha) or event.before_sha == ZERO_SHA:
        raise ClassificationFailure("push before SHA is missing or zero")
    if not SHA_PATTERN.fullmatch(event.current_sha):
        raise ClassificationFailure("current SHA is malformed")
    if event.forced:
        raise ClassificationFailure("forced pushes cannot reuse exact-state evidence")

    parents = git.parents(event.current_sha)
    if len(parents) != 2:
        raise ClassificationFailure("final Q is not a normal two-parent merge")
    base_sha, source_sha = parents
    if base_sha != event.before_sha:
        raise ClassificationFailure(
            "final Q first parent does not equal push before SHA"
        )
    if git.first_parent_count(base_sha, event.current_sha) != 1:
        raise ClassificationFailure("push contains multiple first-parent commits")
    if not git.is_ancestor(base_sha, source_sha):
        raise ClassificationFailure("final Q base is not an ancestor of PR head")
    _require_supported_exact_state_source_history(
        git=git,
        base_sha=base_sha,
        source_sha=source_sha,
    )
    if not git.trees_are_equal(event.current_sha, source_sha):
        raise ClassificationFailure("final Q tree differs from PR head tree")
    if not git.diff_is_empty(source_sha, event.current_sha):
        raise ClassificationFailure("final Q contains merge-only content")

    if api.ref_sha(coordination_branch) != event.current_sha:
        raise ClassificationFailure("remote coordination ref advanced")
    main_sha = api.ref_sha(default_branch)
    if not git.is_ancestor(main_sha, source_sha):
        raise ClassificationFailure("current main is not contained in the PR head")

    (
        source_ref,
        pull_request_number,
        pull_request_created_at,
        merged_at,
    ) = _require_merged_pull_request(
        event=event,
        api=api,
        coordination_branch=coordination_branch,
        base_sha=base_sha,
        source_sha=source_sha,
        now=now,
    )
    source_tree = git.tree_sha(source_sha)
    workflow_revision = git.blob_sha(source_sha, APPROVED_WORKFLOW_PATH)
    runs = api.workflow_runs(source_sha, event=None)
    source_run_id, source_attested_sha = _require_exact_full_run(
        event=event,
        api=api,
        runs=runs,
        source_sha=source_sha,
        source_ref=source_ref,
        run_event="push",
        pull_request_number=None,
        pull_request_base_ref=None,
        pull_request_base_sha=None,
        expected_tree=source_tree,
        workflow_revision=workflow_revision,
        not_before=None,
        merged_at=merged_at,
        now=now,
    )
    if source_attested_sha is not None:
        raise ClassificationFailure("Source Full returned an unexpected PR attestation")
    pr_run_id, synthetic_sha = _require_exact_full_run(
        event=event,
        api=api,
        runs=runs,
        source_sha=source_sha,
        source_ref=source_ref,
        run_event="pull_request",
        pull_request_number=pull_request_number,
        pull_request_base_ref=coordination_branch,
        pull_request_base_sha=base_sha,
        expected_tree=source_tree,
        workflow_revision=workflow_revision,
        not_before=pull_request_created_at,
        merged_at=merged_at,
        now=now,
    )
    if synthetic_sha is None:
        raise ClassificationFailure("PR Full synthetic merge identity is missing")
    if source_run_id == pr_run_id:
        raise ClassificationFailure("Source and PR Full reused one run ID")
    _require_synthetic_merge_commit(
        api=api,
        synthetic_sha=synthetic_sha,
        base_sha=base_sha,
        source_sha=source_sha,
        expected_tree=source_tree,
    )

    if api.ref_sha(coordination_branch) != event.current_sha:
        raise ClassificationFailure("coordination ref drifted during validation")
    if api.ref_sha(default_branch) != main_sha:
        raise ClassificationFailure("main ref drifted during validation")
    _require_live_merged_pull_request(
        event=event,
        api=api,
        pull_request_number=pull_request_number,
        coordination_branch=coordination_branch,
        base_sha=base_sha,
        source_ref=source_ref,
        source_sha=source_sha,
        merged_at=merged_at,
    )

    return Classification(
        "equivalent-merge",
        "protected merge Q exactly matches Source Full H and PR Full P",
        comparison_base=base_sha,
        source_sha=source_sha,
        source_run_id=str(source_run_id),
        source_tree=source_tree,
        workflow_revision=workflow_revision,
    )


def validate_coordination_postmerge_full_reuse(
    *,
    event: CIEvent,
    git: GitRepository,
    api: ActionsEvidence,
    coordination_branch: str,
    default_branch: str,
    base_sha: str,
    source_sha: str,
    now: datetime,
) -> Classification:
    # Historical ADR-0006 verifier. Active ADR-0013 protected coordination no
    # longer routes here; keep the bounded proof for historical contracts and
    # independently allowlisted generic callers.
    if event.ref != f"refs/heads/{coordination_branch}":
        raise ClassificationFailure(
            "governance postmerge reuse requires the exact coordination ref"
        )
    if not event.repository or event.repository_id < 1:
        raise ClassificationFailure("repository identity is malformed")

    source_parents = git.parents(source_sha)
    if len(source_parents) != 2 or source_parents[0] != base_sha:
        raise ClassificationFailure("source is not the exact Case-B merge shape")
    main_sha = source_parents[1]
    _require_main_derived_governance(
        git=git,
        source_sha=source_sha,
        main_sha=main_sha,
    )

    # All candidate and governance checks above are local. Network evidence is
    # deliberately reached only after the exact Case-B shape is plausible.
    if api.ref_sha(coordination_branch) != event.current_sha:
        raise ClassificationFailure("remote coordination ref advanced")
    if api.ref_sha(default_branch) != main_sha:
        raise ClassificationFailure(
            "current main advanced beyond the refresh authority"
        )

    (
        source_ref,
        pull_request_number,
        pull_request_created_at,
        merged_at,
    ) = _require_merged_pull_request(
        event=event,
        api=api,
        coordination_branch=coordination_branch,
        base_sha=base_sha,
        source_sha=source_sha,
        now=now,
    )
    source_tree = git.tree_sha(source_sha)
    workflow_revision = git.blob_sha(source_sha, APPROVED_WORKFLOW_PATH)
    runs = api.workflow_runs(source_sha, event=None)
    source_run_id, _ = _require_exact_full_run(
        event=event,
        api=api,
        runs=runs,
        source_sha=source_sha,
        source_ref=source_ref,
        run_event="push",
        pull_request_number=None,
        pull_request_base_ref=None,
        pull_request_base_sha=None,
        expected_tree=source_tree,
        workflow_revision=workflow_revision,
        not_before=None,
        merged_at=merged_at,
        now=now,
    )
    pr_run_id, _ = _require_exact_full_run(
        event=event,
        api=api,
        runs=runs,
        source_sha=source_sha,
        source_ref=source_ref,
        run_event="pull_request",
        pull_request_number=pull_request_number,
        pull_request_base_ref=coordination_branch,
        pull_request_base_sha=base_sha,
        expected_tree=source_tree,
        workflow_revision=workflow_revision,
        not_before=pull_request_created_at,
        merged_at=merged_at,
        now=now,
    )
    if source_run_id == pr_run_id:
        raise ClassificationFailure("source and PR Full evidence reused one run ID")

    if api.ref_sha(coordination_branch) != event.current_sha:
        raise ClassificationFailure(
            "remote coordination ref drifted during postmerge validation"
        )
    if api.ref_sha(default_branch) != main_sha:
        raise ClassificationFailure("current main drifted during postmerge validation")

    return Classification(
        "equivalent-merge",
        "exact Case-B coordination merge reuses successful Source Full and PR Full",
        comparison_base=base_sha,
        source_sha=source_sha,
        source_run_id=str(source_run_id),
        source_tree=source_tree,
        workflow_revision=workflow_revision,
    )


def validate_equivalent_merge(
    *,
    event: CIEvent,
    git: GitRepository,
    api: ActionsEvidence,
    coordination_branch: str,
    default_branch: str,
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

    if not git.trees_are_equal(event.current_sha, parent2):
        raise ClassificationFailure("merge tree differs from source tree")
    if not git.diff_is_empty(parent2, event.current_sha):
        raise ClassificationFailure("merge contains merge-only content")

    source_paths = git.changed_paths(parent1, parent2)
    if not source_paths:
        raise ClassificationFailure("source change set is empty")
    governance_paths = tuple(path for path in source_paths if is_governance_path(path))
    if governance_paths:
        return validate_coordination_postmerge_full_reuse(
            event=event,
            git=git,
            api=api,
            coordination_branch=coordination_branch,
            default_branch=default_branch,
            base_sha=parent1,
            source_sha=parent2,
            now=now,
        )

    ref_prefix = "refs/heads/"
    if not event.ref.startswith(ref_prefix):
        raise ClassificationFailure("target ref is not a branch")
    ref_name = event.ref.removeprefix(ref_prefix)
    if api.ref_sha(ref_name) != event.current_sha:
        raise ClassificationFailure("remote target ref advanced during validation")

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
    coordination_branch: str,
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
    if event.base_ref != coordination_branch:
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
    governance: ProjectGovernance | None = None,
    equivalent_allowlist: frozenset[str] | None = None,
    pr_equivalent_allowlist: frozenset[str] | None = None,
    now: datetime | None = None,
) -> Classification:
    if event.ref == "refs/heads/main":
        return _full("main always runs full CI")
    if event.ref in FINAL_FULL_REFS or event.ref.startswith(FINAL_FULL_PREFIXES):
        return _full("final, release, or production branch always runs full CI")
    if event.event_name == "pull_request" and event.base_ref == "main":
        try:
            return classify_main_pull_request(event=event, git=git)
        except (
            ClassificationFailure,
            subprocess.SubprocessError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            return _full(f"main pull request validation failed closed: {error}")

    if governance is None:
        try:
            governance = load_project_governance()
        except GovernanceConfigError as error:
            return _full(f"project governance failed closed: {error}")
    coordination_branch = governance.coordination_branch
    coordination_branches = (
        frozenset({coordination_branch})
        if coordination_branch is not None
        else frozenset()
    )
    if coordination_branch is not None and (
        event.ref == governance.coordination_ref
        or (
            event.event_name == "pull_request" and event.base_ref == coordination_branch
        )
    ):
        if event.event_name == "push" and event.ref == governance.coordination_ref:
            if event.before_sha != ZERO_SHA:
                if api is None:
                    return _full(
                        "protected coordination exact-state evidence API is unavailable"
                    )
                try:
                    return validate_protected_coordination_exact_state_reuse(
                        event=event,
                        git=git,
                        api=api,
                        coordination_branch=coordination_branch,
                        default_branch=governance.default_development_base,
                        now=(now or datetime.now(timezone.utc)),
                    )
                except (
                    AttributeError,
                    ClassificationFailure,
                    KeyError,
                    subprocess.SubprocessError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as error:
                    return _full(
                        "protected coordination exact-state validation failed "
                        f"closed: {error}"
                    )
            if api is None:
                return _full("coordination Start evidence API is unavailable")
            try:
                return validate_coordination_start(
                    event=event,
                    git=git,
                    api=api,
                    governance=governance,
                    now=(now or datetime.now(timezone.utc)),
                )
            except (
                AttributeError,
                ClassificationFailure,
                KeyError,
                subprocess.SubprocessError,
                OSError,
                TypeError,
                ValueError,
            ) as error:
                return _full(f"coordination Start validation failed closed: {error}")
        return _full("protected coordination pull requests remain Full-only")
    if equivalent_allowlist is None:
        equivalent_allowlist = frozenset()
    if pr_equivalent_allowlist is None:
        pr_equivalent_allowlist = frozenset()

    if event.event_name == "pull_request":
        if event.base_ref not in coordination_branches:
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
            assert coordination_branch is not None
            return validate_equivalent_pull_request(
                event=event,
                git=git,
                api=api,
                coordination_branch=coordination_branch,
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
                coordination_branch=coordination_branch or "",
                default_branch=governance.default_development_base,
                now=(now or datetime.now(timezone.utc)),
            )
        except (
            ClassificationFailure,
            subprocess.SubprocessError,
            OSError,
            TypeError,
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
    try:
        governance = load_project_governance(arguments.repository_root)
    except GovernanceConfigError as error:
        classification = _full(f"project governance failed closed: {error}")
    else:
        token = os.environ.get("GITHUB_TOKEN", "")
        api = (
            GitHubActionsAPI(
                api_url=arguments.api_url,
                repository=arguments.repository,
                token=token,
            )
            if token
            else None
        )
        classification = classify_ci_mode(
            event=event,
            git=git,
            api=api,
            governance=governance,
        )
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
