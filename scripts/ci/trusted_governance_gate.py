#!/usr/bin/env python3
"""Protected-main verifier and trusted integration-ref lifecycle operations."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from classify_ci_mode import (
    APPROVED_WORKFLOW_ID,
    APPROVED_WORKFLOW_PATH,
    is_governance_path,
)
from trusted_activation import (
    CLAIM_PATH,
    GRANTS_PATH,
    POLICY_PATH,
    PROJECT_GOVERNANCE_PATH,
    REVOCATIONS_PATH,
    TOMBSTONES_PATH,
    AuthorityContext,
    AuthorityError,
    AuthorityResolution,
    AuthorityState,
    LedgerRecord,
    canonical_digest,
    parse_json_bytes,
    resolve_authority,
    validate_claim,
    validate_grant,
    validate_policy,
    validate_repository_ledgers,
    validate_revocation,
    validate_tombstone,
)

TRUSTED_CHECK_NAME = "Trusted Governance Gate"
EXPECTED_REPOSITORY = "NTHU-Physics-SA-IT/PastExamWeb_PHY"
EXPECTED_REPOSITORY_ID = 1271339534
GITHUB_ACTIONS_APP_ID = 15368
FULL_ATTESTATION_NAME = "Full CI Attestation"


class APIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GitHubAPI:
    def __init__(self, *, api_url: str, repository: str, token: str) -> None:
        if not token:
            raise APIError("GitHub App installation token is unavailable")
        self.api_url = api_url.rstrip("/")
        self.repository = repository
        self.token = token

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        parameters: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.api_url}{path}"
        if parameters:
            url = f"{url}?{urlencode(parameters)}"
        data = (
            json.dumps(payload, sort_keys=True).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read()
        except HTTPError as error:
            try:
                message = json.loads(error.read().decode("utf-8")).get(
                    "message",
                    "GitHub API error",
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = "GitHub API error"
            raise APIError(
                f"GitHub API {method} {path} failed: {message}",
                status=error.code,
            ) from error
        except (URLError, TimeoutError) as error:
            raise APIError(
                f"GitHub API {method} {path} unavailable: {type(error).__name__}"
            ) from error
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise APIError("GitHub API returned malformed JSON") from error

    def get(self, path: str, parameters: dict[str, str] | None = None) -> Any:
        return self._request("GET", path, parameters=parameters)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload=payload)

    def patch(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("PATCH", path, payload=payload)

    def delete(self, path: str) -> None:
        self._request("DELETE", path)

    def workflow_run(self, run_id: int) -> dict[str, Any]:
        payload = self.get(f"/repos/{self.repository}/actions/runs/{run_id}")
        if not isinstance(payload, dict):
            raise APIError("workflow run response is malformed")
        return payload

    def run_jobs(self, run_id: int, attempt: int) -> list[dict[str, Any]]:
        payload = self.get(
            f"/repos/{self.repository}/actions/runs/{run_id}/attempts/{attempt}/jobs",
            {"per_page": "100"},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise APIError("workflow jobs response is malformed")
        jobs = payload["jobs"]
        if not all(isinstance(job, dict) for job in jobs):
            raise APIError("workflow jobs response contains malformed entries")
        return jobs

    def pull_request(self, number: int) -> dict[str, Any]:
        payload = self.get(f"/repos/{self.repository}/pulls/{number}")
        if not isinstance(payload, dict):
            raise APIError("pull request response is malformed")
        return payload

    def pulls_for_commit(self, sha: str) -> list[dict[str, Any]]:
        payload = self.get(
            f"/repos/{self.repository}/commits/{sha}/pulls",
            {"per_page": "100"},
        )
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise APIError("commit pull request response is malformed")
        return payload

    def pull_files(self, number: int) -> tuple[str, ...]:
        payload = self.get(
            f"/repos/{self.repository}/pulls/{number}/files",
            {"per_page": "100"},
        )
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) and isinstance(item.get("filename"), str)
            for item in payload
        ):
            raise APIError("pull request file response is malformed")
        if len(payload) == 100:
            raise APIError("pull request file list exceeds verifier safety bound")
        return tuple(item["filename"] for item in payload)

    def ref_sha(self, branch: str, *, required: bool = True) -> str | None:
        encoded = quote(f"heads/{branch}", safe="")
        try:
            payload = self.get(f"/repos/{self.repository}/git/ref/{encoded}")
        except APIError as error:
            if error.status == 404 and not required:
                return None
            raise
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("object"), dict)
            or not isinstance(payload["object"].get("sha"), str)
        ):
            raise APIError("Git ref response is malformed")
        return payload["object"]["sha"]

    def commit(self, sha: str) -> dict[str, Any]:
        payload = self.get(f"/repos/{self.repository}/git/commits/{sha}")
        if not isinstance(payload, dict):
            raise APIError("Git commit response is malformed")
        return payload

    def content(
        self,
        path: str,
        ref: str,
        *,
        required: bool = True,
    ) -> tuple[bytes, str] | None:
        encoded = quote(path, safe="/")
        try:
            payload = self.get(
                f"/repos/{self.repository}/contents/{encoded}",
                {"ref": ref},
            )
        except APIError as error:
            if error.status == 404 and not required:
                return None
            raise
        if (
            not isinstance(payload, dict)
            or payload.get("type") != "file"
            or payload.get("encoding") != "base64"
            or not isinstance(payload.get("content"), str)
            or not isinstance(payload.get("sha"), str)
        ):
            raise APIError(f"repository content response is malformed: {path}")
        try:
            encoded_content = "".join(payload["content"].split())
            data = base64.b64decode(encoded_content, validate=True)
        except (binascii.Error, ValueError) as error:
            raise APIError(f"repository content is not valid base64: {path}") from error
        return data, payload["sha"]

    def compare(self, base: str, head: str) -> dict[str, Any]:
        payload = self.get(
            f"/repos/{self.repository}/compare/{quote(base, safe='')}..."
            f"{quote(head, safe='')}"
        )
        if not isinstance(payload, dict):
            raise APIError("compare response is malformed")
        return payload

    def app(self, slug: str) -> dict[str, Any]:
        if not slug or quote(slug, safe="") != slug:
            raise APIError("GitHub App slug is malformed")
        payload = self.get(f"/apps/{slug}")
        if not isinstance(payload, dict):
            raise APIError("GitHub App response is malformed")
        return payload
    def branch(self, branch: str) -> dict[str, Any]:
        payload = self.get(
            f"/repos/{self.repository}/branches/{quote(branch, safe='')}"
        )
        if not isinstance(payload, dict):
            raise APIError("branch response is malformed")
        return payload

    def upsert_check(
        self,
        *,
        sha: str,
        conclusion: str,
        summary: str,
        external_id: str,
        details_url: str,
    ) -> dict[str, Any]:
        check_payload = {
                "name": TRUSTED_CHECK_NAME,
                "head_sha": sha,
                "status": "completed",
                "conclusion": conclusion,
                "external_id": external_id,
                "details_url": details_url,
                "output": {
                    "title": (
                        "Trusted governance accepted"
                        if conclusion == "success"
                        else "Trusted governance rejected"
                    ),
                    "summary": summary[:65000],
                },
            }
        existing_payload = self.get(
            f"/repos/{self.repository}/commits/{sha}/check-runs",
            {"check_name": TRUSTED_CHECK_NAME, "filter": "all", "per_page": "100"},
        )
        if not isinstance(existing_payload, dict) or not isinstance(
            existing_payload.get("check_runs"), list
        ):
            raise APIError("check-run list response is malformed")
        matches = [
            item
            for item in existing_payload["check_runs"]
            if isinstance(item, dict) and item.get("external_id") == external_id
        ]
        if len(matches) > 1:
            raise APIError("multiple trusted check runs share the same external ID")
        if matches:
            check_id = matches[0].get("id")
            if not isinstance(check_id, int):
                raise APIError("existing trusted check run has no numeric ID")
            update_payload = dict(check_payload)
            update_payload.pop("name")
            update_payload.pop("head_sha")
            payload = self.patch(
                f"/repos/{self.repository}/check-runs/{check_id}",
                update_payload,
            )
        else:
            payload = self.post(
                f"/repos/{self.repository}/check-runs",
                check_payload,
            )
        if not isinstance(payload, dict):
            raise APIError("check-run upsert response is malformed")
        return payload

    def create_ref(self, branch: str, sha: str) -> dict[str, Any]:
        payload = self.post(
            f"/repos/{self.repository}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if not isinstance(payload, dict):
            raise APIError("ref creation response is malformed")
        return payload

    def delete_ref(self, branch: str) -> None:
        self.delete(
            f"/repos/{self.repository}/git/refs/{quote(f'heads/{branch}', safe='')}"
        )


class RulesetAuditAPI:
    """GET-only boundary for the App's administration-capable token."""

    def __init__(self, *, api_url: str, repository: str, token: str) -> None:
        if not token:
            raise APIError("ruleset auditor installation token is unavailable")
        if repository.count("/") != 1 or any(
            not component or quote(component, safe="") != component
            for component in repository.split("/")
        ):
            raise APIError("ruleset auditor repository is malformed")
        self.api_url = api_url.rstrip("/")
        self.repository = repository
        self.token = token

    def _request(self, method: str, path: str) -> Any:
        expected_prefix = f"/repos/{self.repository}/rulesets/"
        ruleset_suffix = path.removeprefix(expected_prefix)
        if method != "GET":
            raise APIError("ruleset auditor permits only GET")
        if (
            not path.startswith(expected_prefix)
            or not ruleset_suffix.isascii()
            or not ruleset_suffix.isdigit()
            or int(ruleset_suffix) < 1
        ):
            raise APIError("ruleset auditor path is not allowlisted")
        request = Request(
            f"{self.api_url}{path}",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read()
        except HTTPError as error:
            try:
                message = json.loads(error.read().decode("utf-8")).get(
                    "message",
                    "GitHub API error",
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = "GitHub API error"
            raise APIError(
                f"GitHub API GET {path} failed: {message}",
                status=error.code,
            ) from error
        except (URLError, TimeoutError) as error:
            raise APIError(
                f"GitHub API GET {path} unavailable: {type(error).__name__}"
            ) from error
        if not raw:
            raise APIError("ruleset auditor returned an empty response")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise APIError("ruleset auditor returned malformed JSON") from error

    def ruleset(self, ruleset_id: int) -> dict[str, Any]:
        if (
            not isinstance(ruleset_id, int)
            or isinstance(ruleset_id, bool)
            or ruleset_id < 1
        ):
            raise APIError("ruleset ID is malformed")
        payload = self._request(
            "GET",
            f"/repos/{self.repository}/rulesets/{ruleset_id}",
        )
        if not isinstance(payload, dict):
            raise APIError("ruleset response is malformed")
        return payload


def normalize_ruleset(payload: dict[str, Any]) -> dict[str, Any]:
    rules = payload.get("rules")
    bypass = payload.get("bypass_actors")
    conditions = payload.get("conditions")
    if not isinstance(rules, list) or not isinstance(bypass, list):
        raise AuthorityError("ruleset rules or bypass actors are malformed")
    if not isinstance(conditions, dict):
        raise AuthorityError("ruleset conditions are malformed")
    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "target": payload.get("target"),
        "enforcement": payload.get("enforcement"),
        "conditions": conditions,
        "bypass_actors": sorted(
            bypass,
            key=lambda item: json.dumps(item, sort_keys=True),
        ),
        "rules": sorted(
            rules,
            key=lambda item: json.dumps(item, sort_keys=True),
        ),
    }


def ruleset_digest(payload: dict[str, Any]) -> str:
    return canonical_digest(normalize_ruleset(payload))


def _require_ruleset_contract(
    normalized: dict[str, Any],
    *,
    expected_app_id: int,
) -> None:
    rules = normalized["rules"]
    if not all(isinstance(item, dict) for item in rules):
        raise AuthorityError("trusted integration ruleset contains malformed rules")
    by_type = {item.get("type"): item for item in rules}
    required_types = {
        "creation",
        "deletion",
        "non_fast_forward",
        "pull_request",
        "required_status_checks",
    }
    if set(by_type) != required_types or len(rules) != len(required_types):
        raise AuthorityError("trusted integration ruleset rule set is not exact")
    pull_parameters = by_type["pull_request"].get("parameters")
    if not isinstance(pull_parameters, dict) or any(
        (
            pull_parameters.get("required_approving_review_count", 0) < 1,
            pull_parameters.get("dismiss_stale_reviews_on_push") is not True,
            pull_parameters.get("require_code_owner_review") is not True,
            pull_parameters.get("require_last_push_approval") is not True,
            pull_parameters.get("required_review_thread_resolution") is not True,
        )
    ):
        raise AuthorityError("trusted integration pull request rules are incomplete")
    status_parameters = by_type["required_status_checks"].get("parameters")
    if (
        not isinstance(status_parameters, dict)
        or status_parameters.get("strict_required_status_checks_policy") is not True
    ):
        raise AuthorityError("trusted integration status checks are not strict")
    required_checks = status_parameters.get("required_status_checks")
    if not isinstance(required_checks, list) or not all(
        isinstance(item, dict) for item in required_checks
    ):
        raise AuthorityError("trusted integration required checks are malformed")
    observed_checks = {
        (item.get("context"), item.get("integration_id")) for item in required_checks
    }
    expected_checks = {
        ("check-branch", GITHUB_ACTIONS_APP_ID),
        ("CI Gate", GITHUB_ACTIONS_APP_ID),
        (TRUSTED_CHECK_NAME, expected_app_id),
    }
    if observed_checks != expected_checks or len(required_checks) != len(expected_checks):
        raise AuthorityError("trusted integration required checks are not exact")


def validate_live_trust_root(
    api: GitHubAPI,
    ruleset_api: RulesetAuditAPI,
    *,
    expected_app_slug: str,
    expected_app_id: int,
    ruleset_id: int,
    expected_ruleset_digest: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    app = api.app(expected_app_slug)
    if app.get("id") != expected_app_id or expected_app_id == GITHUB_ACTIONS_APP_ID:
        raise AuthorityError("installation token App identity does not match")
    ruleset = ruleset_api.ruleset(ruleset_id)
    if ruleset.get("id") != ruleset_id:
        raise AuthorityError("ruleset identity does not match")
    if ruleset_digest(ruleset) != expected_ruleset_digest:
        raise AuthorityError("live ruleset digest does not match")
    normalized = normalize_ruleset(ruleset)
    if (
        normalized["name"] != "trusted-integration-lifecycle"
        or normalized["target"] != "branch"
        or normalized["enforcement"] != "active"
    ):
        raise AuthorityError("trusted integration ruleset is not active and exact")
    ref_condition = normalized["conditions"].get("ref_name")
    if (
        not isinstance(ref_condition, dict)
        or ref_condition.get("include") != ["refs/heads/integration/*"]
        or ref_condition.get("exclude") not in ([], None)
    ):
        raise AuthorityError("trusted integration ruleset pattern is not exact")
    bypass_matches = [
        item
        for item in normalized["bypass_actors"]
        if isinstance(item, dict)
        and item.get("actor_type") == "Integration"
        and item.get("actor_id") == expected_app_id
        and item.get("bypass_mode") == "always"
    ]
    if len(bypass_matches) != 1 or len(normalized["bypass_actors"]) != 1:
        raise AuthorityError("trusted App is not the unique required ruleset bypass")
    _require_ruleset_contract(normalized, expected_app_id=expected_app_id)
    return app, ruleset


def _local_json(root: Path, path: str) -> dict[str, Any]:
    return parse_json_bytes((root / path).read_bytes(), label=path)


def _commit_parents(payload: dict[str, Any]) -> tuple[str, ...]:
    parents = payload.get("parents")
    if not isinstance(parents, list) or not all(
        isinstance(parent, dict) and isinstance(parent.get("sha"), str)
        for parent in parents
    ):
        raise AuthorityError("commit parent response is malformed")
    return tuple(parent["sha"] for parent in parents)


def _local_records(
    root: Path,
    *,
    directory: str,
    main_sha: str,
    main_parents: tuple[str, ...],
    validator: Any,
) -> tuple[LedgerRecord, ...]:
    records: list[LedgerRecord] = []
    for path in sorted((root / directory).glob("*.json")):
        relative = path.relative_to(root).as_posix()
        payload = validator(parse_json_bytes(path.read_bytes(), label=relative), label=relative)
        blob_sha = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        records.append(
            LedgerRecord(relative, main_sha, blob_sha, main_parents, payload)
        )
    return tuple(records)


def _candidate_json(
    api: GitHubAPI,
    *,
    path: str,
    revision: str,
    required: bool = False,
) -> dict[str, Any] | None:
    content = api.content(path, revision, required=required)
    if content is None:
        return None
    return parse_json_bytes(content[0], label=f"{revision}:{path}")


def _authority_at(
    api: GitHubAPI,
    *,
    root: Path,
    branch: str,
    revision: str,
    main_sha: str,
    repository_id: int,
    repository: str,
    verifier_app_id: int,
    ruleset_id: int,
    live_ruleset_digest: str,
) -> AuthorityResolution:
    policy = validate_policy(_local_json(root, POLICY_PATH))
    main_commit = api.commit(main_sha)
    main_parents = _commit_parents(main_commit)
    claim = _candidate_json(api, path=CLAIM_PATH, revision=revision)
    if claim is not None:
        validate_claim(claim)
    grants = list(
        _local_records(
            root,
            directory=GRANTS_PATH,
            main_sha=main_sha,
            main_parents=main_parents,
            validator=validate_grant,
        )
    )
    if claim is not None:
        exact = api.content(
            claim["grant_path"],
            claim["grant_commit_sha"],
            required=True,
        )
        assert exact is not None
        grant_commit = api.commit(claim["grant_commit_sha"])
        exact_record = LedgerRecord(
            claim["grant_path"],
            claim["grant_commit_sha"],
            exact[1],
            _commit_parents(grant_commit),
            validate_grant(
                parse_json_bytes(exact[0], label=claim["grant_path"]),
                label=claim["grant_path"],
            ),
        )
        grant_compare = api.compare(exact_record.commit_sha, main_sha)
        if grant_compare.get("status") not in {"ahead", "identical"}:
            raise AuthorityError("grant commit is not an ancestor of current main")
        grants = [
            item
            for item in grants
            if item.payload["activation_id"] != claim["activation_id"]
        ]
        grants.append(exact_record)
    ancestry = api.compare(main_sha, revision)
    context = AuthorityContext(
        repository_id=repository_id,
        repository=repository,
        branch=branch,
        branch_head_sha=revision,
        main_sha=main_sha,
        main_is_ancestor=ancestry.get("status") in {"ahead", "identical"},
        policy=policy,
        policy_digest=canonical_digest(policy),
        verifier_app_id=verifier_app_id,
        ruleset_id=ruleset_id,
        ruleset_digest=live_ruleset_digest,
        claim=claim,
        grants=tuple(grants),
        revocations=_local_records(
            root,
            directory=REVOCATIONS_PATH,
            main_sha=main_sha,
            main_parents=main_parents,
            validator=validate_revocation,
        ),
        tombstones=_local_records(
            root,
            directory=TOMBSTONES_PATH,
            main_sha=main_sha,
            main_parents=main_parents,
            validator=validate_tombstone,
        ),
    )
    return resolve_authority(context)


def _governance_branch(
    api: GitHubAPI,
    *,
    revision: str,
) -> str | None:
    payload = _candidate_json(
        api,
        path=PROJECT_GOVERNANCE_PATH,
        revision=revision,
        required=True,
    )
    assert payload is not None
    if set(payload) != {
        "schema_version",
        "default_development_base",
        "coordination_branch",
    }:
        raise AuthorityError("candidate project governance keys are unsupported")
    if payload["schema_version"] != 1 or payload["default_development_base"] != "main":
        raise AuthorityError("candidate project governance main authority is malformed")
    value = payload["coordination_branch"]
    if value is not None and not isinstance(value, str):
        raise AuthorityError("candidate coordination branch is malformed")
    return value


def _require_full_run(
    api: GitHubAPI,
    *,
    run_id: int,
    attempt: int,
    head_sha: str,
) -> None:
    matches = [
        job
        for job in api.run_jobs(run_id, attempt)
        if job.get("name") == FULL_ATTESTATION_NAME
    ]
    if len(matches) != 1:
        raise AuthorityError("Full CI Attestation identity is missing or ambiguous")
    job = matches[0]
    if (
        job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or job.get("head_sha") != head_sha
        or job.get("run_id") != run_id
        or job.get("run_attempt") != attempt
    ):
        raise AuthorityError("transition does not have exact successful Full evidence")


@dataclass(frozen=True)
class GateVerdict:
    accepted: bool
    state: str
    authority_active: bool
    reason_code: str
    reason: str
    branch: str
    activation_id: str | None = None

    def summary(self) -> str:
        return json.dumps(
            {
                "accepted": self.accepted,
                "state": self.state,
                "coordination_authority_active": self.authority_active,
                "reason_code": self.reason_code,
                "reason": self.reason,
                "branch": self.branch,
                "activation_id": self.activation_id,
            },
            sort_keys=True,
        )


def _ordinary_candidate(
    api: GitHubAPI,
    *,
    revision: str,
    branch: str,
) -> GateVerdict:
    claim = _candidate_json(api, path=CLAIM_PATH, revision=revision)
    coordination = _governance_branch(api, revision=revision)
    if claim is not None or coordination is not None:
        return GateVerdict(
            False,
            AuthorityState.INVALID.value,
            False,
            "active_return_or_self_authority",
            "Ordinary or main-bound content cannot carry a branch-local claim.",
            branch,
            claim.get("activation_id") if isinstance(claim, dict) else None,
        )
    return GateVerdict(
        True,
        AuthorityState.ORDINARY.value,
        False,
        "ordinary_main_null",
        "Ordinary development remains main-null and has no branch-local claim.",
        branch,
    )


def _validate_main_ledger_changes(
    api: GitHubAPI,
    *,
    root: Path,
    base_sha: str,
    head_sha: str,
    changed_paths: tuple[str, ...],
    expected_app_id: int,
    ruleset_id: int,
    expected_ruleset_digest: str,
) -> None:
    ledger_paths = tuple(
        path
        for path in changed_paths
        if path.startswith(
            (f"{GRANTS_PATH}/", f"{REVOCATIONS_PATH}/", f"{TOMBSTONES_PATH}/")
        )
        and path.endswith(".json")
    )
    if not ledger_paths:
        return
    policy = validate_policy(_local_json(root, POLICY_PATH))
    policy_digest = canonical_digest(policy)
    additions: dict[str, dict[str, Any]] = {}
    for path in ledger_paths:
        if api.content(path, base_sha, required=False) is not None:
            raise AuthorityError(f"immutable main ledger record was modified: {path}")
        content = api.content(path, head_sha, required=True)
        assert content is not None
        payload = parse_json_bytes(content[0], label=path)
        if path.startswith(f"{GRANTS_PATH}/"):
            validate_grant(payload, label=path)
            if (
                payload["grant_parent_sha"] != base_sha
                or payload["policy_version"] != policy["policy_version"]
                or payload["policy_digest"] != policy_digest
                or payload["verifier_app_id"] != expected_app_id
                or payload["ruleset_id"] != ruleset_id
                or payload["ruleset_digest"] != expected_ruleset_digest
            ):
                raise AuthorityError("grant does not bind current main, policy, App, and ruleset")
        elif path.startswith(f"{REVOCATIONS_PATH}/"):
            validate_revocation(payload, label=path)
        else:
            validate_tombstone(payload, label=path)
        expected_path = (
            path.rsplit("/", 1)[0] + f"/{payload['activation_id']}.json"
        )
        if path != expected_path:
            raise AuthorityError(f"ledger record path is not UUID-bound: {path}")
        key = f"{payload['record_type']}:{payload['activation_id']}"
        if key in additions:
            raise AuthorityError("duplicate candidate ledger record identity")
        additions[key] = payload

    grants = [
        validate_grant(
            parse_json_bytes(path.read_bytes(), label=path.as_posix()),
            label=path.as_posix(),
        )
        for path in (root / GRANTS_PATH).glob("*.json")
    ]
    tombstones = [
        validate_tombstone(
            parse_json_bytes(path.read_bytes(), label=path.as_posix()),
            label=path.as_posix(),
        )
        for path in (root / TOMBSTONES_PATH).glob("*.json")
    ]
    for payload in additions.values():
        activation_id = payload["activation_id"]
        branch = payload["branch"]
        if payload["record_type"] == "grant":
            if any(
                item["activation_id"] == activation_id or item["branch"] == branch
                for item in grants + tombstones
            ):
                raise AuthorityError("grant reuses an existing or retired identity")
        elif payload["record_type"] == "revocation":
            matching_grants = [
                item
                for item in grants
                if item["activation_id"] == activation_id and item["branch"] == branch
            ]
            tombstone = additions.get(f"tombstone:{activation_id}")
            if len(matching_grants) != 1 or tombstone is None:
                raise AuthorityError("revocation requires one grant and a paired tombstone")
            if tombstone["branch"] != branch:
                raise AuthorityError("revocation and tombstone branch identities differ")
            if api.ref_sha(branch) != payload["frozen_head_sha"]:
                raise AuthorityError("revocation does not bind the live frozen branch head")
        elif payload["record_type"] == "tombstone":
            revocation = additions.get(f"revocation:{activation_id}")
            if revocation is None or revocation["branch"] != branch:
                raise AuthorityError("tombstone requires a paired matching revocation")


def evaluate_workflow_run(
    api: GitHubAPI,
    ruleset_api: RulesetAuditAPI,
    *,
    root: Path,
    run_id: int,
    run_attempt: int,
    expected_app_slug: str,
    expected_app_id: int,
    ruleset_id: int,
    expected_ruleset_digest: str,
) -> tuple[GateVerdict, dict[str, Any]]:
    run = api.workflow_run(run_id)
    if (
        run.get("id") != run_id
        or run.get("run_attempt") != run_attempt
        or run.get("workflow_id") != APPROVED_WORKFLOW_ID
        or run.get("path") != APPROVED_WORKFLOW_PATH
        or not isinstance(run.get("head_sha"), str)
        or not isinstance(run.get("head_branch"), str)
    ):
        raise AuthorityError("workflow run identity is malformed or untrusted")
    repository = run.get("repository")
    if not isinstance(repository, dict) or repository.get("id") != EXPECTED_REPOSITORY_ID:
        raise AuthorityError("workflow run repository identity does not match")
    validate_live_trust_root(
        api,
        ruleset_api,
        expected_app_slug=expected_app_slug,
        expected_app_id=expected_app_id,
        ruleset_id=ruleset_id,
        expected_ruleset_digest=expected_ruleset_digest,
    )
    local_main = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    live_main = api.ref_sha("main")
    if local_main != live_main:
        raise AuthorityError("protected-main verifier checkout is not current main")
    head_sha = run["head_sha"]
    head_branch = run["head_branch"]
    if run.get("event") != "pull_request":
        if head_branch.startswith("integration/"):
            resolution = _authority_at(
                api,
                root=root,
                branch=head_branch,
                revision=head_sha,
                main_sha=live_main,
                repository_id=EXPECTED_REPOSITORY_ID,
                repository=EXPECTED_REPOSITORY,
                verifier_app_id=expected_app_id,
                ruleset_id=ruleset_id,
                live_ruleset_digest=expected_ruleset_digest,
            )
            accepted = resolution.state in {
                AuthorityState.ACTIVE,
                AuthorityState.REVOKED,
                AuthorityState.RETURN_READY,
            }
            verdict = GateVerdict(
                accepted,
                resolution.state.value,
                resolution.active,
                resolution.reason_code,
                resolution.reason,
                head_branch,
                resolution.activation_id,
            )
            return verdict, run
        return _ordinary_candidate(
            api,
            revision=head_sha,
            branch=head_branch,
        ), run

    candidates = [
        item
        for item in api.pulls_for_commit(head_sha)
        if item.get("state") == "open"
        and isinstance(item.get("head"), dict)
        and item["head"].get("sha") == head_sha
    ]
    if len(candidates) != 1:
        raise AuthorityError("workflow run pull request identity is ambiguous")
    pr = api.pull_request(candidates[0]["number"])
    base = pr.get("base")
    head = pr.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise AuthorityError("pull request base or head identity is malformed")
    if head.get("sha") != head_sha or pr.get("state") != "open":
        raise AuthorityError("pull request is not current and open")
    base_branch = base.get("ref")
    base_sha = base.get("sha")
    if not isinstance(base_branch, str) or not isinstance(base_sha, str):
        raise AuthorityError("pull request base identity is malformed")
    if base_branch == "main":
        changed_paths = api.pull_files(pr["number"])
        _validate_main_ledger_changes(
            api,
            root=root,
            base_sha=base_sha,
            head_sha=head_sha,
            changed_paths=changed_paths,
            expected_app_id=expected_app_id,
            ruleset_id=ruleset_id,
            expected_ruleset_digest=expected_ruleset_digest,
        )
        return _ordinary_candidate(
            api,
            revision=head_sha,
            branch=head_branch,
        ), run
    if not base_branch.startswith("integration/"):
        return GateVerdict(
            False,
            AuthorityState.INVALID.value,
            False,
            "unapproved_base",
            "The pull request target is not main or a trusted integration branch.",
            base_branch,
        ), run
    branch = api.branch(base_branch)
    if branch.get("protected") is not True or api.ref_sha(base_branch) != base_sha:
        raise AuthorityError("integration base is not live and protected")
    base_state = _authority_at(
        api,
        root=root,
        branch=base_branch,
        revision=base_sha,
        main_sha=live_main,
        repository_id=EXPECTED_REPOSITORY_ID,
        repository=EXPECTED_REPOSITORY,
        verifier_app_id=expected_app_id,
        ruleset_id=ruleset_id,
        live_ruleset_digest=expected_ruleset_digest,
    )
    candidate_state = _authority_at(
        api,
        root=root,
        branch=base_branch,
        revision=head_sha,
        main_sha=live_main,
        repository_id=EXPECTED_REPOSITORY_ID,
        repository=EXPECTED_REPOSITORY,
        verifier_app_id=expected_app_id,
        ruleset_id=ruleset_id,
        live_ruleset_digest=expected_ruleset_digest,
    )
    candidate_governance = _governance_branch(api, revision=head_sha)
    paths = api.pull_files(pr["number"])
    governance_paths = tuple(path for path in paths if is_governance_path(path))

    if (
        base_state.state is AuthorityState.PROTECTED_INACTIVE
        and candidate_state.state is AuthorityState.ACTIVE
        and candidate_governance == base_branch
    ):
        _require_full_run(
            api,
            run_id=run_id,
            attempt=run_attempt,
            head_sha=head_sha,
        )
        return GateVerdict(
            True,
            "ACTIVATION_TRANSITION",
            False,
            "valid_activation_transition",
            "The external grant and candidate claim match; authority activates only after merge.",
            base_branch,
            candidate_state.activation_id,
        ), run

    if (
        base_state.state in {AuthorityState.STALE, AuthorityState.ACTIVE}
        and candidate_state.state is AuthorityState.ACTIVE
        and candidate_governance == base_branch
    ):
        if base_state.state is AuthorityState.STALE or governance_paths:
            _require_full_run(
                api,
                run_id=run_id,
                attempt=run_attempt,
                head_sha=head_sha,
            )
            reason_code = "valid_reconciliation_transition"
        else:
            reason_code = "active_coordination_valid"
        return GateVerdict(
            True,
            candidate_state.state.value,
            base_state.state is AuthorityState.ACTIVE,
            reason_code,
            "Trusted coordination authority and transition evidence are valid.",
            base_branch,
            candidate_state.activation_id,
        ), run

    if (
        base_state.state is AuthorityState.REVOKED
        and candidate_state.state is AuthorityState.RETURN_READY
        and candidate_governance is None
    ):
        _require_full_run(
            api,
            run_id=run_id,
            attempt=run_attempt,
            head_sha=head_sha,
        )
        return GateVerdict(
            True,
            "DEACTIVATION_TRANSITION",
            False,
            "valid_deactivation_transition",
            "Revocation is immutable, the claim is removed, and current main is incorporated.",
            base_branch,
            base_state.activation_id,
        ), run

    return GateVerdict(
        False,
        candidate_state.state.value,
        False,
        candidate_state.reason_code,
        candidate_state.reason,
        base_branch,
        candidate_state.activation_id,
    ), run


def _load_grant_for_operation(
    root: Path,
    activation_id: str,
) -> dict[str, Any]:
    path = root / GRANTS_PATH / f"{activation_id}.json"
    return validate_grant(
        parse_json_bytes(path.read_bytes(), label=path.as_posix()),
        label=path.as_posix(),
    )


def operate_ref(
    api: GitHubAPI,
    ruleset_api: RulesetAuditAPI,
    *,
    root: Path,
    operation: str,
    activation_id: str,
    expected_main_sha: str,
    expected_app_slug: str,
    expected_app_id: int,
    ruleset_id: int,
    expected_ruleset_digest: str,
) -> dict[str, Any]:
    validate_live_trust_root(
        api,
        ruleset_api,
        expected_app_slug=expected_app_slug,
        expected_app_id=expected_app_id,
        ruleset_id=ruleset_id,
        expected_ruleset_digest=expected_ruleset_digest,
    )
    live_main = api.ref_sha("main")
    local_main = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if live_main != expected_main_sha or local_main != expected_main_sha:
        raise AuthorityError("issuance checkout, expected main, and live main differ")
    validate_repository_ledgers(root, expected_main_sha)
    grant = _load_grant_for_operation(root, activation_id)
    branch = grant["branch"]
    existing = api.ref_sha(branch, required=False)
    tombstone = root / TOMBSTONES_PATH / f"{activation_id}.json"
    revocation = root / REVOCATIONS_PATH / f"{activation_id}.json"
    any_retired_name = any(
        validate_tombstone(
            parse_json_bytes(path.read_bytes(), label=path.as_posix()),
            label=path.as_posix(),
        )["branch"]
        == branch
        for path in (root / TOMBSTONES_PATH).glob("*.json")
    )
    if operation in {"issue", "replay-preflight"}:
        replay_blocked = tombstone.exists() or revocation.exists() or any_retired_name
        if operation == "replay-preflight":
            if not replay_blocked:
                raise AuthorityError("replay preflight unexpectedly remained eligible")
            if existing is not None:
                raise AuthorityError("replay preflight found a recreated ref")
            return {
                "operation": operation,
                "result": "rejected",
                "branch": branch,
                "activation_id": activation_id,
                "reason_code": "retired_or_revoked_identity",
            }
        if replay_blocked:
            raise AuthorityError("branch name or activation ID is retired or revoked")
        if existing is not None:
            raise AuthorityError("integration branch already exists")
        main_parents = _commit_parents(api.commit(expected_main_sha))
        if not main_parents or grant["grant_parent_sha"] != main_parents[0]:
            raise AuthorityError("grant parent is not the live main first-parent authority")
        created = api.create_ref(branch, expected_main_sha)
        created_object = created.get("object")
        if (
            not isinstance(created_object, dict)
            or created_object.get("sha") != expected_main_sha
        ):
            raise AuthorityError("trusted ref creation identity does not match")
        protected = api.branch(branch)
        if protected.get("protected") is not True:
            raise AuthorityError("new integration branch was not protected at creation")
        return {
            "operation": operation,
            "result": "created",
            "branch": branch,
            "activation_id": activation_id,
            "sha": expected_main_sha,
        }
    if operation != "retire":
        raise AuthorityError("unsupported ref operation")
    if not tombstone.exists() or not revocation.exists():
        raise AuthorityError("retirement requires matching revocation and tombstone")
    if existing is None:
        raise AuthorityError("integration branch is already absent")
    compare = api.compare(existing, live_main)
    if compare.get("status") not in {"ahead", "identical"}:
        raise AuthorityError("integration tip is not an ancestor of main")
    api.delete_ref(branch)
    if api.ref_sha(branch, required=False) is not None:
        raise AuthorityError("integration ref deletion did not become authoritative")
    return {
        "operation": operation,
        "result": "retired",
        "branch": branch,
        "activation_id": activation_id,
        "sha": existing,
    }


def validate_trusted_pr_base(
    api: GitHubAPI,
    *,
    root: Path,
    branch: str,
    expected_app_id: int,
    ruleset_id: int,
    expected_ruleset_digest: str,
) -> AuthorityResolution:
    if not branch.startswith("integration/"):
        raise AuthorityError("trusted pull request base must be an integration branch")
    live_main = api.ref_sha("main")
    local_main = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if local_main != live_main:
        raise AuthorityError("PR-base validator is not sourced from current main")
    branch_payload = api.branch(branch)
    branch_sha = api.ref_sha(branch)
    if branch_payload.get("protected") is not True:
        raise AuthorityError("integration pull request base is not protected")
    resolution = _authority_at(
        api,
        root=root,
        branch=branch,
        revision=branch_sha,
        main_sha=live_main,
        repository_id=EXPECTED_REPOSITORY_ID,
        repository=EXPECTED_REPOSITORY,
        verifier_app_id=expected_app_id,
        ruleset_id=ruleset_id,
        live_ruleset_digest=expected_ruleset_digest,
    )
    if resolution.state in {AuthorityState.INVALID, AuthorityState.ORDINARY}:
        raise AuthorityError(
            f"integration pull request base has no trusted lifecycle authority: "
            f"{resolution.reason_code}"
        )
    return resolution


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="https://api.github.com")
    parser.add_argument("--repository", default=EXPECTED_REPOSITORY)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-workflow-run")
    verify.add_argument("--run-id", type=int, required=True)
    verify.add_argument("--run-attempt", type=int, required=True)
    verify.add_argument("--expected-app-slug", required=True)
    verify.add_argument("--expected-app-id", type=int, required=True)
    verify.add_argument("--ruleset-id", type=int, required=True)
    verify.add_argument("--ruleset-digest", required=True)
    digest = subparsers.add_parser("ruleset-digest")
    digest.add_argument("--ruleset-id", type=int, required=True)
    base = subparsers.add_parser("validate-pr-base")
    base.add_argument("--base", required=True)
    base.add_argument("--expected-app-id", type=int, required=True)
    base.add_argument("--ruleset-id", type=int, required=True)
    base.add_argument("--ruleset-digest", required=True)
    operate = subparsers.add_parser("operate-ref")
    operate.add_argument(
        "--operation",
        choices=("issue", "retire", "replay-preflight"),
        required=True,
    )
    operate.add_argument("--activation-id", required=True)
    operate.add_argument("--expected-main-sha", required=True)
    operate.add_argument("--expected-app-slug", required=True)
    operate.add_argument("--expected-app-id", type=int, required=True)
    operate.add_argument("--ruleset-id", type=int, required=True)
    operate.add_argument("--ruleset-digest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        api = GitHubAPI(
            api_url=arguments.api_url,
            repository=arguments.repository,
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
        if arguments.command == "ruleset-digest":
            ruleset_api = RulesetAuditAPI(
                api_url=arguments.api_url,
                repository=arguments.repository,
                token=os.environ.get("GITHUB_RULESET_AUDITOR_TOKEN", ""),
            )
            print(ruleset_digest(ruleset_api.ruleset(arguments.ruleset_id)))
            return 0
        if arguments.command == "validate-pr-base":
            result = validate_trusted_pr_base(
                api,
                root=arguments.repository_root,
                branch=arguments.base,
                expected_app_id=arguments.expected_app_id,
                ruleset_id=arguments.ruleset_id,
                expected_ruleset_digest=arguments.ruleset_digest,
            )
            print(json.dumps(result.as_dict(), sort_keys=True))
            return 0
        if arguments.command == "operate-ref":
            ruleset_api = RulesetAuditAPI(
                api_url=arguments.api_url,
                repository=arguments.repository,
                token=os.environ.get("GITHUB_RULESET_AUDITOR_TOKEN", ""),
            )
            result = operate_ref(
                api,
                ruleset_api,
                root=arguments.repository_root,
                operation=arguments.operation,
                activation_id=arguments.activation_id,
                expected_main_sha=arguments.expected_main_sha,
                expected_app_slug=arguments.expected_app_slug,
                expected_app_id=arguments.expected_app_id,
                ruleset_id=arguments.ruleset_id,
                expected_ruleset_digest=arguments.ruleset_digest,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        run: dict[str, Any] | None = None
        ruleset_api = RulesetAuditAPI(
            api_url=arguments.api_url,
            repository=arguments.repository,
            token=os.environ.get("GITHUB_RULESET_AUDITOR_TOKEN", ""),
        )
        try:
            verdict, run = evaluate_workflow_run(
                api,
                ruleset_api,
                root=arguments.repository_root,
                run_id=arguments.run_id,
                run_attempt=arguments.run_attempt,
                expected_app_slug=arguments.expected_app_slug,
                expected_app_id=arguments.expected_app_id,
                ruleset_id=arguments.ruleset_id,
                expected_ruleset_digest=arguments.ruleset_digest,
            )
        except (
            APIError,
            AuthorityError,
            OSError,
            subprocess.SubprocessError,
            TypeError,
            ValueError,
        ) as error:
            try:
                run = api.workflow_run(arguments.run_id)
            except APIError:
                run = None
            verdict = GateVerdict(
                False,
                AuthorityState.INVALID.value,
                False,
                "verifier_failed_closed",
                str(error),
                "",
            )
        if run is None or not isinstance(run.get("head_sha"), str):
            raise AuthorityError("unable to bind failure check to workflow head")
        check = api.upsert_check(
            sha=run["head_sha"],
            conclusion="success" if verdict.accepted else "failure",
            summary=verdict.summary(),
            external_id=f"trusted-governance:{arguments.run_id}",
            details_url=run.get("html_url", ""),
        )
        app = check.get("app")
        if (
            check.get("name") != TRUSTED_CHECK_NAME
            or not isinstance(app, dict)
            or app.get("id") != arguments.expected_app_id
        ):
            raise AuthorityError("created check is not bound to the expected App")
        print(verdict.summary())
        print(f"check_run_id={check.get('id')}")
        return 0
    except (
        APIError,
        AuthorityError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as error:
        print(f"Trusted governance operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
