"""Authorize production operations from exact-main provenance and an allowlist."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
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
AUTHORITY_KEYS = {"schema_version", "authorized_deployers"}
AUTHORITY_SENTINELS = {
    "*",
    "all",
    "any",
    "authenticated",
    "everyone",
    "users",
}


class ProductionDeployAuthorityError(RuntimeError):
    """Production deployment authority evidence did not validate."""


class GitHubEvidenceAPI(Protocol):
    def get_object(self, path: str) -> dict[str, Any]: ...

    def get_paginated(self, path: str) -> list[Any]: ...


class GitHubAPI:
    """Small fail-closed REST client for deployment authority evidence."""

    def __init__(self, api_url: str, token: str) -> None:
        if not api_url.startswith(("https://", "http://")):
            raise ProductionDeployAuthorityError("GitHub API URL is malformed.")
        if not token:
            raise ProductionDeployAuthorityError("GITHUB_TOKEN is required.")
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
                    raise ProductionDeployAuthorityError(
                        "GitHub API returned a non-success response."
                    )
                try:
                    return json.load(response)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise ProductionDeployAuthorityError(
                        "GitHub API returned malformed JSON."
                    ) from error
        except HTTPError as error:
            raise ProductionDeployAuthorityError(
                f"GitHub API request failed with status {error.code}."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ProductionDeployAuthorityError(
                "GitHub API request could not be completed."
            ) from error

    def get_object(self, path: str) -> dict[str, Any]:
        payload = self._request_json(path)
        if not isinstance(payload, dict):
            raise ProductionDeployAuthorityError(
                "GitHub API object response is malformed."
            )
        return payload

    def get_paginated(self, path: str) -> list[Any]:
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            payload = self._request_json(
                path, f"per_page={PAGE_SIZE}&page={page}"
            )
            if not isinstance(payload, list):
                raise ProductionDeployAuthorityError(
                    "GitHub API list response is malformed."
                )
            items.extend(payload)
            if len(payload) < PAGE_SIZE:
                return items
        raise ProductionDeployAuthorityError(
            "GitHub API pagination exceeded the fail-closed evidence limit."
        )


def _required(mapping: dict[str, Any], key: str, label: str) -> Any:
    if key not in mapping:
        raise ProductionDeployAuthorityError(f"{label} is malformed.")
    return mapping[key]


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductionDeployAuthorityError(f"{label} is malformed.")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or FULL_SHA.fullmatch(value) is None:
        raise ProductionDeployAuthorityError(f"{label} is malformed.")
    return value


def _login(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or LOGIN.fullmatch(value) is None
        or "--" in value
        or value.casefold().endswith("[bot]")
    ):
        raise ProductionDeployAuthorityError(
            f"{label} must be a valid non-bot GitHub login."
        )
    return value


def _merged_timestamp(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        raise ProductionDeployAuthorityError("Pull request merged_at is malformed.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ProductionDeployAuthorityError(
            "Pull request merged_at is malformed."
        ) from error
    if parsed.tzinfo is None:
        raise ProductionDeployAuthorityError("Pull request merged_at is malformed.")
    return True


def _validate_inputs(
    repository: str,
    authority_sha: str,
    base_branch: str,
    actor: str,
    triggering_actor: str,
) -> tuple[str, str]:
    if REPOSITORY.fullmatch(repository) is None:
        raise ProductionDeployAuthorityError("Repository must be an owner/name pair.")
    if FULL_SHA.fullmatch(authority_sha) is None:
        raise ProductionDeployAuthorityError(
            "Authority SHA must be a full lowercase commit SHA."
        )
    if (
        BRANCH.fullmatch(base_branch) is None
        or ".." in base_branch
        or "//" in base_branch
    ):
        raise ProductionDeployAuthorityError("Expected base branch is malformed.")
    return _login(actor, "Original actor"), _login(
        triggering_actor, "Current triggering actor"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionDeployAuthorityError(
                "Production deploy authority file contains a duplicate JSON key."
            )
        result[key] = value
    return result


def load_authorized_deployers(authority_file: Path) -> dict[str, str]:
    """Load canonical logins keyed by case-folded identity."""

    try:
        metadata = authority_file.lstat()
        if authority_file.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ProductionDeployAuthorityError(
                "Production deploy authority file must be a regular non-symlink file."
            )
        content = authority_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ProductionDeployAuthorityError(
            "Production deploy authority file could not be read as UTF-8."
        ) from error

    try:
        document = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ProductionDeployAuthorityError(
            "Production deploy authority file contains malformed JSON."
        ) from error
    if not isinstance(document, dict) or set(document) != AUTHORITY_KEYS:
        raise ProductionDeployAuthorityError(
            "Production deploy authority file has an unexpected schema."
        )
    schema_version = document["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise ProductionDeployAuthorityError(
            "Production deploy authority schema_version must be integer 1."
        )
    members = document["authorized_deployers"]
    if not isinstance(members, list) or not members:
        raise ProductionDeployAuthorityError(
            "Production deploy authority authorized_deployers must be a non-empty list."
        )

    authorized: dict[str, str] = {}
    for member in members:
        login = _login(member, "Authorized deployer")
        normalized = login.casefold()
        if normalized in AUTHORITY_SENTINELS:
            raise ProductionDeployAuthorityError(
                "Production deploy authority contains a forbidden sentinel."
            )
        if normalized in authorized:
            raise ProductionDeployAuthorityError(
                "Production deploy authority contains duplicate logins."
            )
        authorized[normalized] = login
    return authorized


def authorize_production_deploy(
    repository: str,
    authority_sha: str,
    base_branch: str,
    actor: str,
    triggering_actor: str,
    authority_file: Path,
    api: GitHubEvidenceAPI,
) -> dict[str, str]:
    """Authorize one allowlisted human against exact-main merge provenance."""

    actor, triggering_actor = _validate_inputs(
        repository, authority_sha, base_branch, actor, triggering_actor
    )
    if actor.casefold() != triggering_actor.casefold():
        raise ProductionDeployAuthorityError(
            "Original actor and current triggering actor must be the same account."
        )
    authorized_deployers = load_authorized_deployers(authority_file)
    authorized_actor = authorized_deployers.get(actor.casefold())
    if authorized_actor is None:
        raise ProductionDeployAuthorityError(
            "Actor is not listed in the production deploy authority file."
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
    if branch_name != base_branch or current_main != authority_sha:
        raise ProductionDeployAuthorityError(
            "Authority SHA is not the exact current main head."
        )

    commit = api.get_object(f"{prefix}/commits/{authority_sha}")
    commit_sha = _sha(
        _required(commit, "sha", "Commit response"), "Commit response SHA"
    )
    if commit_sha != authority_sha:
        raise ProductionDeployAuthorityError(
            "Commit response disagrees with authority SHA."
        )
    parents = _required(commit, "parents", "Commit parent data")
    if not isinstance(parents, list):
        raise ProductionDeployAuthorityError("Commit parent data is malformed.")
    if len(parents) != 2:
        raise ProductionDeployAuthorityError(
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
        raise ProductionDeployAuthorityError("Commit parent data is malformed.")

    associated = api.get_paginated(f"{prefix}/commits/{authority_sha}/pulls")
    numbers: list[int] = []
    for summary in associated:
        number = _required(
            _object(summary, "Associated pull request response"),
            "number",
            "Associated pull request response",
        )
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ProductionDeployAuthorityError(
                "Associated pull request response is malformed."
            )
        if number in numbers:
            raise ProductionDeployAuthorityError(
                "Associated pull request response is ambiguous."
            )
        numbers.append(number)

    qualifying: list[dict[str, Any]] = []
    for number in numbers:
        pull = api.get_object(f"{prefix}/pulls/{number}")
        observed_number = _required(pull, "number", "Pull request detail")
        if observed_number != number:
            raise ProductionDeployAuthorityError(
                "Pull request detail is malformed."
            )
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
            raise ProductionDeployAuthorityError(
                "Pull request detail is malformed."
            )
        base_repository = _object(
            _required(base, "repo", "Pull request detail"), "Pull request detail"
        )
        full_name = _required(base_repository, "full_name", "Pull request detail")
        if not isinstance(full_name, str) or REPOSITORY.fullmatch(full_name) is None:
            raise ProductionDeployAuthorityError(
                "Pull request detail is malformed."
            )
        _required(pull, "merged_by", "Pull request detail")
        if (
            full_name.casefold() == repository.casefold()
            and base_ref == base_branch
            and merged
            and merge_commit_sha == authority_sha
        ):
            qualifying.append(pull)

    if len(qualifying) != 1:
        raise ProductionDeployAuthorityError(
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
        raise ProductionDeployAuthorityError(
            "Pull request merger must be an authoritative human account."
        )
    try:
        merger_login = _login(merger_login_value, "Pull request merger")
    except ProductionDeployAuthorityError as error:
        raise ProductionDeployAuthorityError(
            "Pull request merger must be an authoritative human account."
        ) from error
    return {
        "authority_sha": authority_sha,
        "pr_number": str(pull["number"]),
        "merged_by": merger_login,
        "authorized_actor": authorized_actor,
        "authority_source": authority_file.as_posix(),
        "outcome": "authorized",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--authority-sha", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--triggering-actor", required=True)
    parser.add_argument(
        "--authority-file",
        type=Path,
        default=Path(".github/production-deploy-authority.json"),
    )
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        api = GitHubAPI(
            os.environ.get("GITHUB_API_URL", "https://api.github.com"), token
        )
        result = authorize_production_deploy(
            repository=args.repository,
            authority_sha=args.authority_sha,
            base_branch=args.base_branch,
            actor=args.actor,
            triggering_actor=args.triggering_actor,
            authority_file=args.authority_file,
            api=api,
        )
        if args.output is not None:
            with args.output.open("a", encoding="utf-8", newline="\n") as output:
                for key, value in result.items():
                    output.write(f"{key}={value}\n")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ProductionDeployAuthorityError, OSError) as error:
        print(f"Production deploy authorization denied: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
