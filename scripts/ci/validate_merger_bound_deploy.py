"""Authorize production self-deploy only for the exact current main merger."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote

FULL_SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
BRANCH = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._/-]*[A-Za-z0-9])?")
PAGE_SIZE = 100
MAX_PAGES = 10


class MergerBoundAuthorityError(RuntimeError):
    """Authoritative merger-bound deployment evidence did not validate."""


class GitHubEvidenceAPI(Protocol):
    def get_object(self, path: str) -> dict[str, Any]: ...

    def get_paginated(self, path: str) -> list[Any]: ...


class GitHubAPI:
    """Small fail-closed REST client for deployment authority evidence."""

    def __init__(self, api_url: str, token: str) -> None:
        if not api_url.startswith(("https://", "http://")):
            raise MergerBoundAuthorityError("GitHub API URL is malformed.")
        if not token:
            raise MergerBoundAuthorityError("GITHUB_TOKEN is required.")
        self.api_url = api_url.rstrip("/")
        self._token = token

    def _request_json(self, path: str, query: str = "") -> Any:
        url = f"{self.api_url}/{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = getattr(response, "status", None)
                if not isinstance(status, int) or not 200 <= status < 300:
                    raise MergerBoundAuthorityError(
                        "GitHub API returned a non-success response."
                    )
                try:
                    return json.load(response)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise MergerBoundAuthorityError(
                        "GitHub API returned malformed JSON."
                    ) from error
        except HTTPError as error:
            raise MergerBoundAuthorityError(
                f"GitHub API request failed with status {error.code}."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise MergerBoundAuthorityError(
                "GitHub API request could not be completed."
            ) from error

    def get_object(self, path: str) -> dict[str, Any]:
        payload = self._request_json(path)
        if not isinstance(payload, dict):
            raise MergerBoundAuthorityError("GitHub API object response is malformed.")
        return payload

    def get_paginated(self, path: str) -> list[Any]:
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            payload = self._request_json(
                path, f"per_page={PAGE_SIZE}&page={page}"
            )
            if not isinstance(payload, list):
                raise MergerBoundAuthorityError(
                    "GitHub API list response is malformed."
                )
            items.extend(payload)
            if len(payload) < PAGE_SIZE:
                return items
        raise MergerBoundAuthorityError(
            "GitHub API pagination exceeded the fail-closed evidence limit."
        )


def _required(mapping: dict[str, Any], key: str, label: str) -> Any:
    if key not in mapping:
        raise MergerBoundAuthorityError(f"{label} is malformed.")
    return mapping[key]


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MergerBoundAuthorityError(f"{label} is malformed.")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or FULL_SHA.fullmatch(value) is None:
        raise MergerBoundAuthorityError(f"{label} is malformed.")
    return value


def _login(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or LOGIN.fullmatch(value) is None
        or "--" in value
        or value.casefold().endswith("[bot]")
    ):
        raise MergerBoundAuthorityError(
            f"{label} must be a valid non-bot GitHub login."
        )
    return value


def _merged_timestamp(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        raise MergerBoundAuthorityError("Pull request merged_at is malformed.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MergerBoundAuthorityError(
            "Pull request merged_at is malformed."
        ) from error
    if parsed.tzinfo is None:
        raise MergerBoundAuthorityError("Pull request merged_at is malformed.")
    return True


def _validate_inputs(
    repository: str,
    target_sha: str,
    base_branch: str,
    actor: str,
    triggering_actor: str,
) -> tuple[str, str]:
    if REPOSITORY.fullmatch(repository) is None:
        raise MergerBoundAuthorityError("Repository must be an owner/name pair.")
    if FULL_SHA.fullmatch(target_sha) is None:
        raise MergerBoundAuthorityError(
            "Target SHA must be a full lowercase commit SHA."
        )
    if (
        BRANCH.fullmatch(base_branch) is None
        or ".." in base_branch
        or "//" in base_branch
    ):
        raise MergerBoundAuthorityError("Expected base branch is malformed.")
    return _login(actor, "Original actor"), _login(
        triggering_actor, "Current triggering actor"
    )


def authorize_merger_bound_deploy(
    repository: str,
    target_sha: str,
    base_branch: str,
    actor: str,
    triggering_actor: str,
    api: GitHubEvidenceAPI,
) -> dict[str, str]:
    """Resolve exact PR/merger evidence and authorize only one bound human."""

    actor, triggering_actor = _validate_inputs(
        repository, target_sha, base_branch, actor, triggering_actor
    )
    encoded_repository = "/".join(quote(part, safe="") for part in repository.split("/"))
    prefix = f"repos/{encoded_repository}"

    branch = api.get_object(f"{prefix}/branches/{quote(base_branch, safe='')}")
    branch_name = _required(branch, "name", "Current main response")
    branch_commit = _object(
        _required(branch, "commit", "Current main response"),
        "Current main response",
    )
    current_main = _sha(
        _required(branch_commit, "sha", "Current main response"),
        "Current main SHA",
    )
    if branch_name != base_branch or current_main != target_sha:
        raise MergerBoundAuthorityError(
            "Target SHA is not the exact current main head."
        )

    commit = api.get_object(f"{prefix}/commits/{target_sha}")
    commit_sha = _sha(
        _required(commit, "sha", "Commit response"), "Commit response SHA"
    )
    if commit_sha != target_sha:
        raise MergerBoundAuthorityError("Commit response disagrees with target SHA.")
    parents = _required(commit, "parents", "Commit parent data")
    if not isinstance(parents, list):
        raise MergerBoundAuthorityError("Commit parent data is malformed.")
    if len(parents) != 2:
        raise MergerBoundAuthorityError(
            "Target commit must have exactly two parents for a normal merge."
        )
    parent_shas = [
        _sha(
            _required(_object(parent, "Commit parent data"), "sha", "Commit parent data"),
            "Commit parent SHA",
        )
        for parent in parents
    ]
    if len(set(parent_shas)) != 2:
        raise MergerBoundAuthorityError("Commit parent data is malformed.")

    associated = api.get_paginated(f"{prefix}/commits/{target_sha}/pulls")
    numbers: list[int] = []
    for summary in associated:
        number = _required(
            _object(summary, "Associated pull request response"),
            "number",
            "Associated pull request response",
        )
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise MergerBoundAuthorityError(
                "Associated pull request response is malformed."
            )
        if number in numbers:
            raise MergerBoundAuthorityError(
                "Associated pull request response is ambiguous."
            )
        numbers.append(number)

    qualifying: list[dict[str, Any]] = []
    for number in numbers:
        pull = api.get_object(f"{prefix}/pulls/{number}")
        observed_number = _required(pull, "number", "Pull request detail")
        if observed_number != number:
            raise MergerBoundAuthorityError("Pull request detail is malformed.")
        merge_commit_sha = _required(
            pull, "merge_commit_sha", "Pull request detail"
        )
        if merge_commit_sha is not None:
            _sha(merge_commit_sha, "Pull request merge_commit_sha")
        merged = _merged_timestamp(
            _required(pull, "merged_at", "Pull request detail")
        )
        base = _object(
            _required(pull, "base", "Pull request detail"), "Pull request detail"
        )
        base_ref = _required(base, "ref", "Pull request detail")
        if not isinstance(base_ref, str) or not base_ref:
            raise MergerBoundAuthorityError("Pull request detail is malformed.")
        base_repository = _object(
            _required(base, "repo", "Pull request detail"), "Pull request detail"
        )
        full_name = _required(base_repository, "full_name", "Pull request detail")
        if not isinstance(full_name, str) or REPOSITORY.fullmatch(full_name) is None:
            raise MergerBoundAuthorityError("Pull request detail is malformed.")
        _required(pull, "merged_by", "Pull request detail")
        if (
            full_name.casefold() == repository.casefold()
            and base_ref == base_branch
            and merged
            and merge_commit_sha == target_sha
        ):
            qualifying.append(pull)

    if len(qualifying) != 1:
        raise MergerBoundAuthorityError(
            "Expected exactly one merged PR bound to the target; "
            f"found {len(qualifying)}."
        )

    pull = qualifying[0]
    merged_by = _object(
        _required(pull, "merged_by", "Pull request merged_by"),
        "Pull request merged_by",
    )
    merger_type = _required(merged_by, "type", "Pull request merged_by")
    merger_login_value = _required(merged_by, "login", "Pull request merged_by")
    if merger_type != "User":
        raise MergerBoundAuthorityError(
            "Pull request merger must be an authoritative human account."
        )
    try:
        merger_login = _login(merger_login_value, "Pull request merger")
    except MergerBoundAuthorityError as error:
        raise MergerBoundAuthorityError(
            "Pull request merger must be an authoritative human account."
        ) from error
    if actor.casefold() != merger_login.casefold():
        raise MergerBoundAuthorityError(
            "The original actor is not the pull request merger."
        )
    if triggering_actor.casefold() != merger_login.casefold():
        raise MergerBoundAuthorityError(
            "The current triggering actor is not the pull request merger."
        )

    return {
        "target_sha": target_sha,
        "pr_number": str(pull["number"]),
        "merged_by": merger_login,
        "authorized_actor": merger_login,
        "base_branch": base_branch,
        "outcome": "authorized",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--triggering-actor", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        api = GitHubAPI(
            os.environ.get("GITHUB_API_URL", "https://api.github.com"), token
        )
        result = authorize_merger_bound_deploy(
            repository=args.repository,
            target_sha=args.target_sha,
            base_branch=args.base_branch,
            actor=args.actor,
            triggering_actor=args.triggering_actor,
            api=api,
        )
        if args.output is not None:
            with args.output.open("a", encoding="utf-8", newline="\n") as output:
                for key, value in result.items():
                    output.write(f"{key}={value}\n")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (MergerBoundAuthorityError, OSError) as error:
        print(f"Merger-bound deploy authorization denied: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
