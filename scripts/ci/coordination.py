"""Minimal protected coordination lifecycle for PastExamWeb_PHY.

The human supplies only an operation and a short name. Protected-main workflow
code resolves main, validates the integration ruleset, creates all machine
metadata, and uses the existing GitHub App only for exact ref lifecycle writes.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

PROJECT_GOVERNANCE_PATH = ".github/project-governance.json"
RETIRED_IDENTITIES_PATH = ".github/coordination/retired-identities.json"
INTEGRATION_PREFIX = "integration/"
INTEGRATION_REF_PREFIX = "refs/heads/integration/"
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
GENERATED_BRANCH_PATTERN = re.compile(
    r"^integration/[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?-[0-9a-f]{8}$"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
EXPECTED_REPOSITORY = "NTHU-Physics-SA-IT/PastExamWeb_PHY"
EXPECTED_RULESET_NAME = "trusted-integration-lifecycle"
EXPECTED_CHECKS = {
    ("check-branch", 15368),
    ("CI Gate", 15368),
}
EXPECTED_MERGE_METHODS = frozenset({"merge", "squash", "rebase"})
EXPECTED_PULL_REQUEST_PARAMETER_KEYS = frozenset(
    {
        "allowed_merge_methods",
        "dismiss_stale_reviews_on_push",
        "dismissal_restriction",
        "require_code_owner_review",
        "require_extra_approval_for_unattributed_changes",
        "require_last_push_approval",
        "required_approving_review_count",
        "required_review_thread_resolution",
        "required_reviewers",
    }
)
EXPECTED_STATUS_PARAMETER_KEYS = frozenset(
    {
        "do_not_enforce_on_create",
        "required_status_checks",
        "strict_required_status_checks_policy",
    }
)
START_ATTESTATION_SCHEMA_VERSION = 1


class CoordinationError(RuntimeError):
    """Live coordination evidence is unsafe, incomplete, or ambiguous."""


def parse_strict_json(data: bytes, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CoordinationError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CoordinationError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise CoordinationError(f"{label} must be a JSON object")
    return payload


def normalize_name(value: str) -> str:
    name = value.strip().lower()
    if (
        value != name
        or not NAME_PATTERN.fullmatch(name)
        or name.isdigit()
        or SHA_PATTERN.fullmatch(name)
        or UUID_PATTERN.fullmatch(name)
    ):
        raise CoordinationError(
            "name must be 1-40 lowercase letters, digits, or interior hyphens "
            "and must not be a machine identifier"
        )
    return name


def require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise CoordinationError(f"{label} must be an exact lowercase Git SHA")
    return value


def validate_governance(
    payload: dict[str, Any],
    *,
    expected_coordination: str | None,
    label: str,
) -> None:
    expected = {
        "schema_version": 1,
        "default_development_base": "main",
        "coordination_branch": expected_coordination,
    }
    if payload != expected:
        raise CoordinationError(f"{label} does not match {expected!r}")


def governance_bytes(coordination_branch: str | None) -> bytes:
    payload = {
        "schema_version": 1,
        "default_development_base": "main",
        "coordination_branch": coordination_branch,
    }
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def validate_retired_identities(payload: dict[str, Any]) -> frozenset[str]:
    if set(payload) != {"schema_version", "retired_identities"}:
        raise CoordinationError("retired identity ledger has unsupported keys")
    if payload.get("schema_version") != 1:
        raise CoordinationError("retired identity ledger schema is unsupported")
    records = payload.get("retired_identities")
    if not isinstance(records, list):
        raise CoordinationError("retired identity ledger must contain a list")
    branches: set[str] = set()
    activation_ids: set[str] = set()
    for index, record in enumerate(records):
        label = f"retired identity {index}"
        if not isinstance(record, dict) or set(record) != {
            "activation_id",
            "branch",
            "retirement_kind",
            "reason",
            "retired_at",
        }:
            raise CoordinationError(f"{label} is malformed")
        branch = record["branch"]
        activation_id = record["activation_id"]
        if (
            not isinstance(branch, str)
            or not branch.startswith(INTEGRATION_PREFIX)
            or not isinstance(activation_id, str)
            or not activation_id
        ):
            raise CoordinationError(f"{label} identity is malformed")
        if record["retirement_kind"] != "aborted-before-issuance":
            raise CoordinationError(f"{label} has an unsupported retirement kind")
        if branch in branches or activation_id in activation_ids:
            raise CoordinationError("retired identity ledger contains a duplicate")
        branches.add(branch)
        activation_ids.add(activation_id)
    return frozenset(branches)


def validate_ruleset(payload: dict[str, Any], *, expected_app_id: int) -> None:
    if payload.get("name") != EXPECTED_RULESET_NAME:
        raise CoordinationError("integration ruleset name is unexpected")
    if payload.get("target") != "branch" or payload.get("enforcement") != "active":
        raise CoordinationError("integration ruleset must be active for branches")
    conditions = payload.get("conditions")
    if conditions != {
        "ref_name": {
            "exclude": [],
            "include": [INTEGRATION_REF_PREFIX + "*"],
        }
    }:
        raise CoordinationError("integration ruleset ref scope is unexpected")
    bypass = payload.get("bypass_actors")
    if bypass != [
        {
            "actor_id": expected_app_id,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]:
        raise CoordinationError("only the lifecycle App may bypass the ruleset")

    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise CoordinationError("integration ruleset rules are unavailable")
    expected_rule_types = {
        "creation",
        "deletion",
        "non_fast_forward",
        "pull_request",
        "required_status_checks",
    }
    observed_rule_types = [
        rule.get("type")
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("type"), str)
    ]
    if (
        len(observed_rule_types) != len(rules)
        or len(set(observed_rule_types)) != len(observed_rule_types)
        or set(observed_rule_types) != expected_rule_types
    ):
        raise CoordinationError("integration ruleset is not the exact minimal contract")
    by_type = {rule["type"]: rule for rule in rules}
    for rule_type in ("creation", "deletion", "non_fast_forward"):
        if by_type[rule_type] != {"type": rule_type}:
            raise CoordinationError(
                f"integration {rule_type} rule has unexpected parameters"
            )

    pull_request_rule = by_type["pull_request"]
    if set(pull_request_rule) != {"type", "parameters"}:
        raise CoordinationError("pull-request rule shape is unexpected")
    pull_request = pull_request_rule.get("parameters")
    if (
        not isinstance(pull_request, dict)
        or set(pull_request) != EXPECTED_PULL_REQUEST_PARAMETER_KEYS
    ):
        raise CoordinationError("pull-request protection is malformed")
    merge_methods = pull_request["allowed_merge_methods"]
    if (
        not isinstance(merge_methods, list)
        or len(merge_methods) != len(EXPECTED_MERGE_METHODS)
        or not all(isinstance(method, str) for method in merge_methods)
        or frozenset(merge_methods) != EXPECTED_MERGE_METHODS
    ):
        raise CoordinationError("integration merge methods are unexpected")
    expected_pull_request = {
        "dismiss_stale_reviews_on_push": True,
        "dismissal_restriction": {"allowed_actors": [], "enabled": False},
        "require_code_owner_review": False,
        "require_extra_approval_for_unattributed_changes": False,
        "require_last_push_approval": False,
        "required_approving_review_count": 0,
        "required_review_thread_resolution": True,
        "required_reviewers": [],
    }
    observed_pull_request = {
        key: value
        for key, value in pull_request.items()
        if key != "allowed_merge_methods"
    }
    if observed_pull_request != expected_pull_request:
        raise CoordinationError("pull-request protection is not the minimal contract")

    status_rule = by_type["required_status_checks"]
    if set(status_rule) != {"type", "parameters"}:
        raise CoordinationError("required-status-check rule shape is unexpected")
    status_parameters = status_rule.get("parameters")
    if (
        not isinstance(status_parameters, dict)
        or set(status_parameters) != EXPECTED_STATUS_PARAMETER_KEYS
    ):
        raise CoordinationError("required status checks are malformed")
    if status_parameters.get("strict_required_status_checks_policy") is not True:
        raise CoordinationError("integration status checks must remain strict")
    if status_parameters.get("do_not_enforce_on_create") is not False:
        raise CoordinationError("integration status checks must apply on creation")
    checks = status_parameters.get("required_status_checks")
    if not isinstance(checks, list):
        raise CoordinationError("integration required checks are unavailable")
    observed = [
        (check.get("context"), check.get("integration_id"))
        for check in checks
        if isinstance(check, dict) and set(check) == {"context", "integration_id"}
    ]
    if len(observed) != len(checks) or len(observed) != 2 or set(observed) != EXPECTED_CHECKS:
        raise CoordinationError("integration required checks are not the minimal baseline")


def build_start_attestation(
    *,
    result: dict[str, Any],
    ruleset: dict[str, Any],
    expected_app_id: int,
    app_slug: str,
    repository: str,
    repository_id: int,
    lifecycle_run_id: int,
    lifecycle_run_attempt: int,
) -> dict[str, Any]:
    """Build non-secret evidence emitted only by the protected lifecycle run."""

    validate_ruleset(ruleset, expected_app_id=expected_app_id)
    if repository != EXPECTED_REPOSITORY or repository_id < 1:
        raise CoordinationError("start attestation repository identity is malformed")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?", app_slug):
        raise CoordinationError("lifecycle App slug is malformed")
    if lifecycle_run_id < 1 or lifecycle_run_attempt < 1:
        raise CoordinationError("lifecycle workflow identity is malformed")
    ruleset_id = ruleset.get("id")
    updated_at = ruleset.get("updated_at")
    if (
        isinstance(ruleset_id, bool)
        or not isinstance(ruleset_id, int)
        or ruleset_id < 1
        or not isinstance(updated_at, str)
        or not updated_at
        or ruleset.get("source") != EXPECTED_REPOSITORY
        or ruleset.get("source_type") != "Repository"
    ):
        raise CoordinationError("ruleset attestation metadata is malformed")

    return {
        "schema_version": START_ATTESTATION_SCHEMA_VERSION,
        "kind": "coordination-start",
        "repository": repository,
        "repository_id": repository_id,
        "lifecycle_run_id": lifecycle_run_id,
        "lifecycle_run_attempt": lifecycle_run_attempt,
        "app_slug": app_slug,
        "expected_app_id": expected_app_id,
        "branch": result["branch"],
        "head_sha": result["head_sha"],
        "parent_main_sha": result["base_main_sha"],
        "ruleset": ruleset,
    }


def write_start_attestation(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class RefLifecycleClient:
    def __init__(self, *, api_url: str, repository: str, token: str) -> None:
        if repository != EXPECTED_REPOSITORY:
            raise CoordinationError("repository identity is not authorized")
        if not token:
            raise CoordinationError("required GitHub token is unavailable")
        self.api_url = api_url.rstrip("/")
        self.repository = repository
        self.token = token

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/"):
            raise CoordinationError("GitHub API path must be absolute")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.api_url + path,
            method=method,
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "pastexam-coordination-lifecycle",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read()
        except HTTPError as error:
            detail = error.read(512).decode("utf-8", errors="replace")
            raise CoordinationError(
                f"GitHub API {method} {path} failed with HTTP {error.code}: {detail}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise CoordinationError(f"GitHub API {method} {path} unavailable") from error
        if not data:
            return None
        try:
            return json.loads(data)
        except json.JSONDecodeError as error:
            raise CoordinationError("GitHub API returned malformed JSON") from error

    @property
    def repo_path(self) -> str:
        return f"/repos/{self.repository}"

    def main_ref(self) -> dict[str, Any]:
        return self._request("GET", self.repo_path + "/git/ref/heads/main")

    def integration_refs(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", self.repo_path + "/git/matching-refs/heads/integration/"
        )
        if not isinstance(payload, list):
            raise CoordinationError("integration ref inventory is malformed")
        return payload

    def commit(self, sha: str) -> dict[str, Any]:
        return self._request("GET", self.repo_path + f"/git/commits/{sha}")

    def contents(self, path: str, ref: str) -> bytes:
        payload = self._request(
            "GET",
            self.repo_path + f"/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}",
        )
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            raise CoordinationError(f"repository content is unavailable: {path}@{ref}")
        try:
            encoded = payload["content"]
            if not isinstance(encoded, str):
                raise TypeError("base64 content must be a string")
            normalized = encoded.replace("\r", "").replace("\n", "")
            return base64.b64decode(normalized, validate=True)
        except (KeyError, TypeError, ValueError) as error:
            raise CoordinationError(f"repository content is malformed: {path}@{ref}") from error

    def create_blob(self, data: bytes) -> str:
        payload = self._request(
            "POST",
            self.repo_path + "/git/blobs",
            {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"},
        )
        return require_sha(payload.get("sha"), label="created blob")

    def create_tree(self, *, base_tree: str, blob_sha: str) -> str:
        payload = self._request(
            "POST",
            self.repo_path + "/git/trees",
            {
                "base_tree": require_sha(base_tree, label="base tree"),
                "tree": [
                    {
                        "path": PROJECT_GOVERNANCE_PATH,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha,
                    }
                ],
            },
        )
        return require_sha(payload.get("sha"), label="created tree")

    def create_commit(self, *, message: str, tree: str, parents: list[str]) -> str:
        payload = self._request(
            "POST",
            self.repo_path + "/git/commits",
            {"message": message, "tree": tree, "parents": parents},
        )
        return require_sha(payload.get("sha"), label="created commit")

    def create_ref(self, *, branch: str, sha: str) -> None:
        _require_generated_branch(branch)
        self._request(
            "POST",
            self.repo_path + "/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": sha},
        )

    def update_ref(self, *, branch: str, sha: str) -> None:
        _require_generated_branch(branch)
        self._request(
            "PATCH",
            self.repo_path + f"/git/refs/heads/{quote(branch, safe='/')}",
            {"sha": sha, "force": False},
        )

    def delete_ref(self, branch: str) -> None:
        _require_generated_branch(branch)
        self._request(
            "DELETE",
            self.repo_path + f"/git/refs/heads/{quote(branch, safe='/')}",
        )

    def compare(self, base: str, head: str) -> dict[str, Any]:
        return self._request(
            "GET",
            self.repo_path + f"/compare/{quote(base, safe='')}...{quote(head, safe='')}",
        )



class ActionsReader:
    """Read exact main workflow status with a separate read-only token."""

    def __init__(self, *, api_url: str, repository: str, token: str) -> None:
        if repository != EXPECTED_REPOSITORY:
            raise CoordinationError("repository identity is not authorized")
        if not token:
            raise CoordinationError("Actions read token is unavailable")
        self.url = (
            api_url.rstrip("/")
            + f"/repos/{repository}/actions/workflows/main.yml/runs"
            + "?branch=main&event=push&status=completed&per_page=20"
        )
        self.token = token

    def successful_main_ci(self, main_sha: str) -> bool:
        request = Request(
            self.url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "pastexam-coordination-actions-reader",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
        except HTTPError as error:
            raise CoordinationError(
                f"exact-main CI read failed with HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise CoordinationError("exact-main CI evidence is unavailable") from error
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        return isinstance(runs, list) and any(
            run.get("head_sha") == main_sha and run.get("conclusion") == "success"
            for run in runs
            if isinstance(run, dict)
        )


class RulesetAuditor:
    """Expose one exact GET operation to an administration-write token."""

    def __init__(
        self,
        *,
        api_url: str,
        repository: str,
        token: str,
        ruleset_id: int,
    ) -> None:
        if repository != EXPECTED_REPOSITORY:
            raise CoordinationError("repository identity is not authorized")
        if not token:
            raise CoordinationError("ruleset auditor token is unavailable")
        if ruleset_id < 1:
            raise CoordinationError("ruleset identity is malformed")
        self.api_url = api_url.rstrip("/")
        self.path = f"/repos/{repository}/rulesets/{ruleset_id}"
        self.token = token

    def ruleset(self) -> dict[str, Any]:
        request = Request(
            self.api_url + self.path,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "pastexam-coordination-ruleset-auditor",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read()
        except HTTPError as error:
            raise CoordinationError(
                f"ruleset audit failed with HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise CoordinationError("ruleset audit is unavailable") from error
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as error:
            raise CoordinationError("ruleset audit returned malformed JSON") from error
        if not isinstance(payload, dict):
            raise CoordinationError("ruleset audit returned a non-object")
        return payload


def read_governance(client: RefLifecycleClient, revision: str) -> dict[str, Any]:
    return parse_strict_json(
        client.contents(PROJECT_GOVERNANCE_PATH, revision),
        label=f"{PROJECT_GOVERNANCE_PATH}@{revision}",
    )


def _ref_branch(ref: dict[str, Any]) -> str:
    value = ref.get("ref")
    if not isinstance(value, str) or not value.startswith("refs/heads/"):
        raise CoordinationError("integration ref inventory contains a malformed ref")
    return value.removeprefix("refs/heads/")


def _require_generated_branch(branch: str) -> str:
    if not GENERATED_BRANCH_PATTERN.fullmatch(branch):
        raise CoordinationError("ref lifecycle is limited to generated integration refs")
    return branch


def _ref_sha(ref: dict[str, Any]) -> str:
    obj = ref.get("object")
    if not isinstance(obj, dict):
        raise CoordinationError("integration ref inventory lacks an object")
    return require_sha(obj.get("sha"), label="integration ref SHA")


def start_coordination(
    *,
    content: RefLifecycleClient,
    actions: ActionsReader,
    ruleset: dict[str, Any],
    name: str,
    expected_app_id: int,
) -> dict[str, Any]:
    name = normalize_name(name)
    validate_ruleset(ruleset, expected_app_id=expected_app_id)
    refs = content.integration_refs()
    if refs:
        raise CoordinationError("another integration ref exists; coordination is singular")
    main_sha = require_sha(
        content.main_ref().get("object", {}).get("sha"), label="protected main SHA"
    )
    validate_governance(
        read_governance(content, main_sha),
        expected_coordination=None,
        label="protected main governance",
    )
    retired = validate_retired_identities(
        parse_strict_json(
            content.contents(RETIRED_IDENTITIES_PATH, main_sha),
            label=f"{RETIRED_IDENTITIES_PATH}@{main_sha}",
        )
    )
    if not actions.successful_main_ci(main_sha):
        raise CoordinationError("protected main lacks terminal successful exact-SHA CI")

    branch = f"{INTEGRATION_PREFIX}{name}-{secrets.token_hex(4)}"
    if branch in retired:
        raise CoordinationError("generated integration identity is permanently retired")
    main_commit = content.commit(main_sha)
    main_tree = require_sha(
        main_commit.get("tree", {}).get("sha"), label="protected main tree"
    )
    blob = content.create_blob(governance_bytes(branch))
    tree = content.create_tree(base_tree=main_tree, blob_sha=blob)
    head = content.create_commit(
        message=f"chore(coordination): start {name}",
        tree=tree,
        parents=[main_sha],
    )
    content.create_ref(branch=branch, sha=head)
    observed = content.integration_refs()
    if len(observed) != 1 or _ref_branch(observed[0]) != branch or _ref_sha(observed[0]) != head:
        raise CoordinationError("created integration ref did not read back exactly")
    validate_governance(
        read_governance(content, head),
        expected_coordination=branch,
        label="active integration governance",
    )
    return {
        "operation": "start",
        "name": name,
        "branch": branch,
        "base_main_sha": main_sha,
        "head_sha": head,
        "state": "ACTIVE",
        "expected_pr_base": branch,
    }


def _resolve_branch(refs: list[dict[str, Any]], name: str) -> tuple[str, str]:
    name = normalize_name(name)
    prefix = f"{INTEGRATION_PREFIX}{name}-"
    matches = [ref for ref in refs if _ref_branch(ref).startswith(prefix)]
    if len(matches) != 1:
        raise CoordinationError(
            f"name must resolve to exactly one integration ref; observed {len(matches)}"
        )
    return _ref_branch(matches[0]), _ref_sha(matches[0])


def close_coordination(
    *,
    content: RefLifecycleClient,
    actions: ActionsReader,
    ruleset: dict[str, Any],
    name: str,
    expected_app_id: int,
) -> dict[str, Any]:
    validate_ruleset(ruleset, expected_app_id=expected_app_id)
    branch, branch_sha = _resolve_branch(content.integration_refs(), name)
    branch_governance = read_governance(content, branch_sha)
    main_sha = require_sha(
        content.main_ref().get("object", {}).get("sha"), label="protected main SHA"
    )
    validate_governance(
        read_governance(content, main_sha),
        expected_coordination=None,
        label="protected main governance",
    )
    if not actions.successful_main_ci(main_sha):
        raise CoordinationError("protected main lacks terminal successful exact-SHA CI")
    active_governance = json.loads(governance_bytes(branch))
    null_governance = json.loads(governance_bytes(None))
    if branch_governance == null_governance:
        close_commit = content.commit(branch_sha)
        parents = close_commit.get("parents")
        if not isinstance(parents, list) or len(parents) != 2:
            raise CoordinationError("null coordination ref is not a valid closeout")
        parent_shas = [
            require_sha(parent.get("sha"), label="closeout parent")
            for parent in parents
            if isinstance(parent, dict)
        ]
        if len(parent_shas) != 2:
            raise CoordinationError("closeout parents are malformed")
        for parent_sha in parent_shas:
            comparison = content.compare(parent_sha, main_sha)
            merge_base = comparison.get("merge_base_commit")
            if (
                not isinstance(merge_base, dict)
                or merge_base.get("sha") != parent_sha
                or comparison.get("status") not in {"ahead", "identical"}
            ):
                raise CoordinationError("closeout parent is not contained in main")
        content.delete_ref(branch)
        if any(_ref_branch(ref) == branch for ref in content.integration_refs()):
            raise CoordinationError("retired integration ref still exists")
        return {
            "operation": "close",
            "name": normalize_name(name),
            "retired_branch": branch,
            "final_integration_sha": parent_shas[0],
            "closeout_sha": branch_sha,
            "main_sha": main_sha,
            "state": "RETIRED",
            "recovered": True,
        }
    if branch_governance != active_governance:
        raise CoordinationError("integration branch-local governance is invalid")

    comparison = content.compare(branch_sha, main_sha)
    merge_base = comparison.get("merge_base_commit")
    if (
        not isinstance(merge_base, dict)
        or merge_base.get("sha") != branch_sha
        or comparison.get("status") not in {"ahead", "identical"}
    ):
        raise CoordinationError(
            "integration is STALE or not returned; merge its final head to main first"
        )

    main_tree = require_sha(
        content.commit(main_sha).get("tree", {}).get("sha"),
        label="protected main tree",
    )
    close_head = content.create_commit(
        message=f"chore(coordination): close {normalize_name(name)}",
        tree=main_tree,
        parents=[branch_sha, main_sha],
    )
    content.update_ref(branch=branch, sha=close_head)
    observed = content.integration_refs()
    if len(observed) != 1 or _ref_branch(observed[0]) != branch or _ref_sha(observed[0]) != close_head:
        raise CoordinationError("closeout integration ref did not read back exactly")
    validate_governance(
        read_governance(content, close_head),
        expected_coordination=None,
        label="return-ready integration governance",
    )
    content.delete_ref(branch)
    if any(_ref_branch(ref) == branch for ref in content.integration_refs()):
        raise CoordinationError("retired integration ref still exists")
    return {
        "operation": "close",
        "name": normalize_name(name),
        "retired_branch": branch,
        "final_integration_sha": branch_sha,
        "closeout_sha": close_head,
        "main_sha": main_sha,
        "state": "RETIRED",
    }


def _read_ruleset(
    *, api_url: str, repository: str, token: str, ruleset_id: int
) -> dict[str, Any]:
    return RulesetAuditor(
        api_url=api_url,
        repository=repository,
        token=token,
        ruleset_id=ruleset_id,
    ).ruleset()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--expected-app-id", type=int, required=True)
    parser.add_argument("--ruleset-id", type=int, required=True)
    parser.add_argument("--repository-id", type=int, default=0)
    parser.add_argument("--app-slug", default="")
    parser.add_argument("--lifecycle-run-id", type=int, default=0)
    parser.add_argument("--lifecycle-run-attempt", type=int, default=0)
    parser.add_argument("--attestation-output", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("operation", choices=("start", "close"))
    parser.add_argument("name")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        content = RefLifecycleClient(
            api_url=arguments.api_url,
            repository=arguments.repository,
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
        actions = ActionsReader(
            api_url=arguments.api_url,
            repository=arguments.repository,
            token=os.environ.get("GITHUB_ACTIONS_READ_TOKEN", ""),
        )
        ruleset = _read_ruleset(
            api_url=arguments.api_url,
            repository=arguments.repository,
            token=os.environ.get("GITHUB_RULESET_AUDITOR_TOKEN", ""),
            ruleset_id=arguments.ruleset_id,
        )
        operation = (
            start_coordination if arguments.operation == "start" else close_coordination
        )
        result = operation(
            content=content,
            actions=actions,
            ruleset=ruleset,
            name=arguments.name,
            expected_app_id=arguments.expected_app_id,
        )
        if arguments.operation == "start":
            if arguments.attestation_output is None:
                raise CoordinationError("start attestation output is required")
            attestation = build_start_attestation(
                result=result,
                ruleset=ruleset,
                expected_app_id=arguments.expected_app_id,
                app_slug=arguments.app_slug,
                repository=arguments.repository,
                repository_id=arguments.repository_id,
                lifecycle_run_id=arguments.lifecycle_run_id,
                lifecycle_run_attempt=arguments.lifecycle_run_attempt,
            )
            write_start_attestation(arguments.attestation_output, attestation)
        if arguments.github_output is not None:
            with arguments.github_output.open("a", encoding="utf-8") as output:
                for key in ("operation", "branch", "head_sha", "base_main_sha"):
                    if key in result:
                        output.write(f"{key}={result[key]}\n")
    except (CoordinationError, OSError) as error:
        print(json.dumps({"state": "ERROR", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
