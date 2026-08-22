#!/usr/bin/env python3
"""Pure, fail-closed Trusted Activation record and authority validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

POLICY_PATH = ".github/trusted-activation/policy.json"
CLAIM_PATH = ".github/trusted-activation/claim.json"
GRANTS_PATH = ".github/trusted-activation/grants"
REVOCATIONS_PATH = ".github/trusted-activation/revocations"
TOMBSTONES_PATH = ".github/trusted-activation/tombstones"
PROJECT_GOVERNANCE_PATH = ".github/project-governance.json"
POLICY_VERSION = "trusted-activation-v1"
SUPPORTED_SCHEMA_VERSION = 1
ISSUANCE_CONTRACT = "protected-main-app-environment-v1"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BRANCH_PATTERN = re.compile(r"^integration/[A-Za-z0-9][A-Za-z0-9._-]*$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class AuthorityError(RuntimeError):
    """Trusted Activation data or evidence is missing, malformed, or ambiguous."""


class AuthorityState(str, Enum):
    ORDINARY = "ORDINARY"
    PROTECTED_INACTIVE = "PROTECTED_INACTIVE"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    REVOKED = "REVOKED"
    RETURN_READY = "RETURN_READY"
    INVALID = "INVALID"


@dataclass(frozen=True)
class LedgerRecord:
    path: str
    commit_sha: str
    blob_sha: str
    commit_parents: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class AuthorityContext:
    repository_id: int
    repository: str
    branch: str
    branch_head_sha: str
    main_sha: str
    main_is_ancestor: bool
    policy: dict[str, Any]
    policy_digest: str
    verifier_app_id: int
    ruleset_id: int
    ruleset_digest: str
    claim: dict[str, Any] | None
    grants: tuple[LedgerRecord, ...]
    revocations: tuple[LedgerRecord, ...]
    tombstones: tuple[LedgerRecord, ...]


@dataclass(frozen=True)
class AuthorityResolution:
    state: AuthorityState
    active: bool
    branch: str
    activation_id: str | None
    reason_code: str
    reason: str
    grant_commit_sha: str | None = None
    grant_blob_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "active": self.active,
            "branch": self.branch,
            "activation_id": self.activation_id,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "grant_commit_sha": self.grant_commit_sha,
            "grant_blob_sha": self.grant_blob_sha,
        }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise AuthorityError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def parse_json_bytes(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthorityError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise AuthorityError(f"{label} must be a JSON object")
    return payload


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_exact_keys(
    payload: dict[str, Any],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    observed = frozenset(payload)
    if observed != expected:
        missing = sorted(expected - observed)
        unknown = sorted(observed - expected)
        raise AuthorityError(
            f"{label} keys are unsupported: missing={missing!r}, unknown={unknown!r}"
        )


def _require_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AuthorityError(f"{label} must be a positive integer")
    return value


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AuthorityError(f"{label} must be a non-empty normalized string")
    return value


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise AuthorityError(f"{label} must be a lowercase 40-character SHA")
    return value


def _require_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not DIGEST_PATTERN.fullmatch(value):
        raise AuthorityError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_uuid(value: Any, *, label: str) -> str:
    text = _require_string(value, label=label)
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise AuthorityError(f"{label} must be a UUID") from error
    if parsed.version != 4 or str(parsed) != text:
        raise AuthorityError(f"{label} must be a normalized UUIDv4")
    return text


def _require_branch(value: Any, *, label: str) -> str:
    branch = _require_string(value, label=label)
    if not BRANCH_PATTERN.fullmatch(branch):
        raise AuthorityError(f"{label} must be a one-level integration branch")
    return branch


def _require_repository(value: Any, *, label: str) -> str:
    repository = _require_string(value, label=label)
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise AuthorityError(f"{label} must be an owner/repository identity")
    return repository


def _require_timestamp(value: Any, *, label: str) -> str:
    timestamp = _require_string(value, label=label)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise AuthorityError(f"{label} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise AuthorityError(f"{label} must include a timezone")
    return timestamp


COMMON_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "repository_id",
        "repository",
        "branch",
        "activation_id",
    }
)
GRANT_KEYS = COMMON_KEYS | {
    "grant_parent_sha",
    "policy_version",
    "policy_digest",
    "ruleset_id",
    "ruleset_digest",
    "verifier_app_id",
    "issuance_contract",
    "issued_at",
}
CLAIM_KEYS = COMMON_KEYS | {
    "grant_path",
    "grant_commit_sha",
    "grant_blob_sha",
    "policy_version",
    "policy_digest",
    "ruleset_id",
    "ruleset_digest",
    "verifier_app_id",
}
REVOCATION_KEYS = COMMON_KEYS | {"frozen_head_sha", "reason", "revoked_at"}
TOMBSTONE_KEYS = COMMON_KEYS | {"reason", "retired_at"}


def _validate_common(
    payload: dict[str, Any],
    *,
    record_type: str,
    label: str,
) -> dict[str, Any]:
    if payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise AuthorityError(f"{label} has an unsupported schema version")
    if payload.get("record_type") != record_type:
        raise AuthorityError(f"{label} record_type must be {record_type!r}")
    _require_int(payload.get("repository_id"), label=f"{label}.repository_id")
    _require_repository(payload.get("repository"), label=f"{label}.repository")
    _require_branch(payload.get("branch"), label=f"{label}.branch")
    _require_uuid(payload.get("activation_id"), label=f"{label}.activation_id")
    return payload


def validate_grant(payload: dict[str, Any], *, label: str = "grant") -> dict[str, Any]:
    _require_exact_keys(payload, frozenset(GRANT_KEYS), label=label)
    _validate_common(payload, record_type="grant", label=label)
    _require_sha(payload["grant_parent_sha"], label=f"{label}.grant_parent_sha")
    if payload["policy_version"] != POLICY_VERSION:
        raise AuthorityError(f"{label}.policy_version is unsupported")
    _require_digest(payload["policy_digest"], label=f"{label}.policy_digest")
    _require_int(payload["ruleset_id"], label=f"{label}.ruleset_id")
    _require_digest(payload["ruleset_digest"], label=f"{label}.ruleset_digest")
    _require_int(payload["verifier_app_id"], label=f"{label}.verifier_app_id")
    if payload["issuance_contract"] != ISSUANCE_CONTRACT:
        raise AuthorityError(f"{label}.issuance_contract is unsupported")
    _require_timestamp(payload["issued_at"], label=f"{label}.issued_at")
    return payload


def validate_claim(payload: dict[str, Any], *, label: str = "claim") -> dict[str, Any]:
    _require_exact_keys(payload, frozenset(CLAIM_KEYS), label=label)
    _validate_common(payload, record_type="claim", label=label)
    activation_id = payload["activation_id"]
    expected_path = f"{GRANTS_PATH}/{activation_id}.json"
    if payload["grant_path"] != expected_path:
        raise AuthorityError(f"{label}.grant_path must be {expected_path!r}")
    _require_sha(payload["grant_commit_sha"], label=f"{label}.grant_commit_sha")
    _require_sha(payload["grant_blob_sha"], label=f"{label}.grant_blob_sha")
    if payload["policy_version"] != POLICY_VERSION:
        raise AuthorityError(f"{label}.policy_version is unsupported")
    _require_digest(payload["policy_digest"], label=f"{label}.policy_digest")
    _require_int(payload["ruleset_id"], label=f"{label}.ruleset_id")
    _require_digest(payload["ruleset_digest"], label=f"{label}.ruleset_digest")
    _require_int(payload["verifier_app_id"], label=f"{label}.verifier_app_id")
    return payload


def validate_revocation(
    payload: dict[str, Any],
    *,
    label: str = "revocation",
) -> dict[str, Any]:
    _require_exact_keys(payload, frozenset(REVOCATION_KEYS), label=label)
    _validate_common(payload, record_type="revocation", label=label)
    _require_sha(payload["frozen_head_sha"], label=f"{label}.frozen_head_sha")
    reason = _require_string(payload["reason"], label=f"{label}.reason")
    if len(reason) > 240:
        raise AuthorityError(f"{label}.reason is too long")
    _require_timestamp(payload["revoked_at"], label=f"{label}.revoked_at")
    return payload


def validate_tombstone(
    payload: dict[str, Any],
    *,
    label: str = "tombstone",
) -> dict[str, Any]:
    _require_exact_keys(payload, frozenset(TOMBSTONE_KEYS), label=label)
    _validate_common(payload, record_type="tombstone", label=label)
    reason = _require_string(payload["reason"], label=f"{label}.reason")
    if len(reason) > 240:
        raise AuthorityError(f"{label}.reason is too long")
    _require_timestamp(payload["retired_at"], label=f"{label}.retired_at")
    return payload


def validate_policy(payload: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version",
        "policy_version",
        "repository",
        "integration_branch_pattern",
        "claim_path",
        "ledger_paths",
        "trusted_check",
        "ruleset",
    }
    _require_exact_keys(payload, frozenset(expected), label="policy")
    if payload["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        raise AuthorityError("policy schema version is unsupported")
    if payload["policy_version"] != POLICY_VERSION:
        raise AuthorityError("policy version is unsupported")
    repository = payload["repository"]
    if not isinstance(repository, dict) or set(repository) != {
        "id",
        "full_name",
        "default_branch",
    }:
        raise AuthorityError("policy repository identity is malformed")
    _require_int(repository["id"], label="policy.repository.id")
    _require_repository(repository["full_name"], label="policy.repository.full_name")
    if repository["default_branch"] != "main":
        raise AuthorityError("policy default branch must remain main")
    if payload["integration_branch_pattern"] != "integration/*":
        raise AuthorityError("policy integration branch pattern is unsupported")
    if payload["claim_path"] != CLAIM_PATH:
        raise AuthorityError("policy claim path is unsupported")
    if payload["ledger_paths"] != {
        "grants": GRANTS_PATH,
        "revocations": REVOCATIONS_PATH,
        "tombstones": TOMBSTONES_PATH,
    }:
        raise AuthorityError("policy ledger paths are unsupported")
    trusted_check = payload["trusted_check"]
    if not isinstance(trusted_check, dict) or trusted_check != {
        "name": "Trusted Governance Gate",
        "candidate_actions_app_id": 15368,
    }:
        raise AuthorityError("policy trusted check identity is malformed")
    ruleset = payload["ruleset"]
    required_ruleset_keys = {
        "name",
        "target",
        "include",
        "required_checks",
        "require_pull_request",
        "required_approvals",
        "require_code_owner_review",
        "dismiss_stale_reviews",
        "require_last_push_approval",
        "require_conversation_resolution",
        "block_force_push",
        "restrict_creation",
        "restrict_deletion",
    }
    if not isinstance(ruleset, dict) or set(ruleset) != required_ruleset_keys:
        raise AuthorityError("policy ruleset contract is malformed")
    if ruleset["name"] != "trusted-integration-lifecycle":
        raise AuthorityError("policy ruleset name is unsupported")
    if ruleset["target"] != "branch":
        raise AuthorityError("policy ruleset target is unsupported")
    if ruleset["include"] != ["refs/heads/integration/*"]:
        raise AuthorityError("policy ruleset include pattern is unsupported")
    if ruleset["required_checks"] != [
        "check-branch",
        "CI Gate",
        "Trusted Governance Gate",
    ]:
        raise AuthorityError("policy required checks are unsupported")
    boolean_keys = required_ruleset_keys - {
        "name",
        "target",
        "include",
        "required_checks",
        "required_approvals",
    }
    if any(ruleset[key] is not True for key in boolean_keys):
        raise AuthorityError("policy ruleset protections must all be enabled")
    if ruleset["required_approvals"] != 1:
        raise AuthorityError("policy ruleset must require exactly one approval")
    return payload


def _validated_record(
    record: LedgerRecord,
    *,
    expected_kind: str,
) -> LedgerRecord:
    _require_sha(record.commit_sha, label=f"{record.path}.commit_sha")
    _require_sha(record.blob_sha, label=f"{record.path}.blob_sha")
    if not record.commit_parents or any(
        not SHA_PATTERN.fullmatch(parent) for parent in record.commit_parents
    ):
        raise AuthorityError(f"{record.path} commit parents are malformed")
    validators = {
        "grant": validate_grant,
        "revocation": validate_revocation,
        "tombstone": validate_tombstone,
    }
    validators[expected_kind](record.payload, label=record.path)
    expected_path = {
        "grant": GRANTS_PATH,
        "revocation": REVOCATIONS_PATH,
        "tombstone": TOMBSTONES_PATH,
    }[expected_kind]
    activation_id = record.payload["activation_id"]
    if record.path != f"{expected_path}/{activation_id}.json":
        raise AuthorityError(f"{record.path} is not the canonical UUID record path")
    return record


def _matching(
    records: Iterable[LedgerRecord],
    *,
    branch: str,
    activation_id: str | None = None,
) -> tuple[LedgerRecord, ...]:
    return tuple(
        record
        for record in records
        if record.payload["branch"] == branch
        and (
            activation_id is None
            or record.payload["activation_id"] == activation_id
        )
    )


def _validate_ledger_relations(
    grants: tuple[LedgerRecord, ...],
    revocations: tuple[LedgerRecord, ...],
    tombstones: tuple[LedgerRecord, ...],
) -> None:
    grant_by_identity = {
        (item.payload["branch"], item.payload["activation_id"]): item
        for item in grants
    }
    if len(grant_by_identity) != len(grants):
        raise AuthorityError("duplicate grant identity")
    grant_branches = [item.payload["branch"] for item in grants]
    grant_activations = [item.payload["activation_id"] for item in grants]
    if len(grant_branches) != len(set(grant_branches)):
        raise AuthorityError("a protected coordination branch name was reused")
    if len(grant_activations) != len(set(grant_activations)):
        raise AuthorityError("a protected activation UUID was reused")
    revocation_identities = {
        (item.payload["branch"], item.payload["activation_id"])
        for item in revocations
    }
    tombstone_identities = {
        (item.payload["branch"], item.payload["activation_id"])
        for item in tombstones
    }
    if len(revocation_identities) != len(revocations):
        raise AuthorityError("duplicate revocation identity")
    if len(tombstone_identities) != len(tombstones):
        raise AuthorityError("duplicate tombstone identity")
    if revocation_identities != tombstone_identities:
        raise AuthorityError("revocations and tombstones must be exact pairs")
    if not revocation_identities.issubset(grant_by_identity):
        raise AuthorityError("revocation or tombstone has no matching grant")


def resolve_authority(context: AuthorityContext) -> AuthorityResolution:
    """Resolve live branch authority from already collected immutable facts."""

    try:
        validate_policy(context.policy)
        _require_int(context.repository_id, label="repository_id")
        _require_repository(context.repository, label="repository")
        _require_branch(context.branch, label="branch")
        _require_sha(context.branch_head_sha, label="branch_head_sha")
        _require_sha(context.main_sha, label="main_sha")
        _require_int(context.verifier_app_id, label="verifier_app_id")
        _require_int(context.ruleset_id, label="ruleset_id")
        _require_digest(context.ruleset_digest, label="ruleset_digest")
        if context.policy_digest != canonical_digest(context.policy):
            raise AuthorityError("policy digest does not match canonical policy")
        policy_repository = context.policy["repository"]
        if (
            policy_repository["id"] != context.repository_id
            or policy_repository["full_name"] != context.repository
        ):
            raise AuthorityError("policy repository identity does not match")

        grants = tuple(
            _validated_record(record, expected_kind="grant")
            for record in context.grants
        )
        revocations = tuple(
            _validated_record(record, expected_kind="revocation")
            for record in context.revocations
        )
        tombstones = tuple(
            _validated_record(record, expected_kind="tombstone")
            for record in context.tombstones
        )
        _validate_ledger_relations(grants, revocations, tombstones)

        branch_grants = _matching(grants, branch=context.branch)
        branch_revocations = _matching(revocations, branch=context.branch)
        branch_tombstones = _matching(tombstones, branch=context.branch)
        if context.claim is None:
            if branch_tombstones or branch_revocations:
                if not context.main_is_ancestor:
                    return AuthorityResolution(
                        AuthorityState.STALE,
                        False,
                        context.branch,
                        None,
                        "deactivated_branch_missing_current_main",
                        "A deactivated branch must incorporate current main before return.",
                    )
                return AuthorityResolution(
                    AuthorityState.RETURN_READY,
                    False,
                    context.branch,
                    None,
                    "claim_absent_after_revocation",
                    "The claim is absent and immutable revocation authority is present.",
                )
            if len(branch_grants) > 1:
                raise AuthorityError("multiple grants exist for the branch")
            if len(branch_grants) == 1:
                return AuthorityResolution(
                    AuthorityState.PROTECTED_INACTIVE,
                    False,
                    context.branch,
                    branch_grants[0].payload["activation_id"],
                    "grant_without_claim",
                    "A protected-main grant exists but no branch-local claim is active.",
                    branch_grants[0].commit_sha,
                    branch_grants[0].blob_sha,
                )
            return AuthorityResolution(
                AuthorityState.ORDINARY,
                False,
                context.branch,
                None,
                "no_claim_or_grant",
                "No Trusted Activation claim or grant applies.",
            )

        claim = validate_claim(context.claim)
        activation_id = claim["activation_id"]
        if (
            claim["repository_id"] != context.repository_id
            or claim["repository"] != context.repository
            or claim["branch"] != context.branch
        ):
            raise AuthorityError("claim repository or branch identity does not match")
        if (
            claim["policy_version"] != context.policy["policy_version"]
            or claim["policy_digest"] != context.policy_digest
        ):
            raise AuthorityError("claim policy binding does not match")
        if (
            claim["verifier_app_id"] != context.verifier_app_id
            or claim["ruleset_id"] != context.ruleset_id
            or claim["ruleset_digest"] != context.ruleset_digest
        ):
            raise AuthorityError("claim live App or ruleset binding does not match")

        matches = _matching(
            grants,
            branch=context.branch,
            activation_id=activation_id,
        )
        if len(matches) != 1:
            raise AuthorityError("claim must resolve to exactly one grant")
        grant_record = matches[0]
        grant = grant_record.payload
        if (
            grant_record.path != claim["grant_path"]
            or grant_record.commit_sha != claim["grant_commit_sha"]
            or grant_record.blob_sha != claim["grant_blob_sha"]
        ):
            raise AuthorityError("claim grant path, commit, or blob binding does not match")
        if grant_record.commit_parents[0] != grant["grant_parent_sha"]:
            raise AuthorityError(
                "grant commit first parent does not match protected-main grant parent"
            )
        for key in (
            "repository_id",
            "repository",
            "branch",
            "activation_id",
            "policy_version",
            "policy_digest",
            "ruleset_id",
            "ruleset_digest",
            "verifier_app_id",
        ):
            if grant[key] != claim[key]:
                raise AuthorityError(f"claim and grant differ for {key}")

        matching_tombstones = _matching(
            tombstones,
            branch=context.branch,
            activation_id=activation_id,
        )
        reused_names = tuple(
            record
            for record in tombstones
            if record.payload["branch"] == context.branch
            or record.payload["activation_id"] == activation_id
        )
        if matching_tombstones or reused_names:
            return AuthorityResolution(
                AuthorityState.REVOKED,
                False,
                context.branch,
                activation_id,
                "retired_identity",
                "The branch name or activation ID is permanently retired.",
                grant_record.commit_sha,
                grant_record.blob_sha,
            )
        matching_revocations = _matching(
            revocations,
            branch=context.branch,
            activation_id=activation_id,
        )
        if len(matching_revocations) > 1:
            raise AuthorityError("multiple revocations exist for the activation")
        if matching_revocations:
            return AuthorityResolution(
                AuthorityState.REVOKED,
                False,
                context.branch,
                activation_id,
                "activation_revoked",
                "Protected main contains an immutable matching revocation.",
                grant_record.commit_sha,
                grant_record.blob_sha,
            )
        if not context.main_is_ancestor:
            return AuthorityResolution(
                AuthorityState.STALE,
                False,
                context.branch,
                activation_id,
                "current_main_not_ancestor",
                "Current protected main is not an ancestor of the branch head.",
                grant_record.commit_sha,
                grant_record.blob_sha,
            )
        return AuthorityResolution(
            AuthorityState.ACTIVE,
            True,
            context.branch,
            activation_id,
            "trusted_activation_valid",
            "Protected-main grant, branch claim, live policy, App, ruleset, and freshness all match.",
            grant_record.commit_sha,
            grant_record.blob_sha,
        )
    except AuthorityError as error:
        return AuthorityResolution(
            AuthorityState.INVALID,
            False,
            context.branch,
            context.claim.get("activation_id")
            if isinstance(context.claim, dict)
            and isinstance(context.claim.get("activation_id"), str)
            else None,
            "invalid_or_ambiguous_authority",
            str(error),
        )


class GitAuthorityRepository:
    """Read Git objects without changing refs, indexes, or worktrees."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            capture_output=True,
            check=check,
        )

    def rev_parse(self, revision: str) -> str:
        value = self._run("rev-parse", revision).stdout.decode().strip()
        return _require_sha(value, label=f"revision {revision}")

    def read_path(self, commit: str, path: str, *, required: bool = True) -> bytes | None:
        process = self._run("show", f"{commit}:{path}", check=False)
        if process.returncode == 0:
            return process.stdout
        if not required:
            return None
        raise AuthorityError(f"required Git path is unavailable: {commit}:{path}")

    def blob_sha(self, commit: str, path: str) -> str:
        value = self._run("rev-parse", f"{commit}:{path}").stdout.decode().strip()
        return _require_sha(value, label=f"blob {commit}:{path}")

    def parents(self, commit: str) -> tuple[str, ...]:
        fields = self._run("rev-list", "--parents", "-n", "1", commit).stdout.decode().split()
        if not fields or fields[0] != commit:
            raise AuthorityError(f"commit parent identity is unavailable: {commit}")
        return tuple(_require_sha(parent, label="commit parent") for parent in fields[1:])

    def list_json_paths(self, commit: str, directory: str) -> tuple[str, ...]:
        output = self._run(
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            commit,
            "--",
            directory,
        ).stdout.decode()
        return tuple(
            path
            for path in output.split("\0")
            if path.endswith(".json")
        )

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        process = self._run(
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            check=False,
        )
        if process.returncode not in (0, 1):
            raise AuthorityError("Git ancestry query failed")
        return process.returncode == 0


def _load_record(
    git: GitAuthorityRepository,
    *,
    commit: str,
    path: str,
) -> LedgerRecord:
    data = git.read_path(commit, path)
    assert data is not None
    return LedgerRecord(
        path=path,
        commit_sha=commit,
        blob_sha=git.blob_sha(commit, path),
        commit_parents=git.parents(commit),
        payload=parse_json_bytes(data, label=path),
    )


def _load_current_ledger(
    git: GitAuthorityRepository,
    *,
    main_sha: str,
    directory: str,
) -> tuple[LedgerRecord, ...]:
    return tuple(
        _load_record(git, commit=main_sha, path=path)
        for path in git.list_json_paths(main_sha, directory)
    )


def resolve_git_authority(
    *,
    repository_root: Path,
    repository_id: int,
    repository: str,
    branch: str,
    branch_revision: str,
    main_revision: str,
    verifier_app_id: int,
    ruleset_id: int,
    ruleset_digest: str,
) -> AuthorityResolution:
    git = GitAuthorityRepository(repository_root)
    branch_sha = git.rev_parse(branch_revision)
    main_sha = git.rev_parse(main_revision)
    policy_data = git.read_path(main_sha, POLICY_PATH)
    assert policy_data is not None
    policy = validate_policy(parse_json_bytes(policy_data, label=POLICY_PATH))
    claim_data = git.read_path(branch_sha, CLAIM_PATH, required=False)
    claim = (
        validate_claim(parse_json_bytes(claim_data, label=CLAIM_PATH))
        if claim_data is not None
        else None
    )
    grants = list(
        _load_current_ledger(git, main_sha=main_sha, directory=GRANTS_PATH)
    )
    if claim is not None:
        exact_grant = _load_record(
            git,
            commit=claim["grant_commit_sha"],
            path=claim["grant_path"],
        )
        if not git.is_ancestor(exact_grant.commit_sha, main_sha):
            raise AuthorityError("claim grant commit is not an ancestor of current main")
        current_blob = git.blob_sha(main_sha, exact_grant.path)
        if current_blob != exact_grant.blob_sha:
            raise AuthorityError("protected-main grant record was mutated")
        grants = [
            record
            for record in grants
            if record.payload.get("activation_id") != claim["activation_id"]
        ]
        grants.append(exact_grant)
    context = AuthorityContext(
        repository_id=repository_id,
        repository=repository,
        branch=branch,
        branch_head_sha=branch_sha,
        main_sha=main_sha,
        main_is_ancestor=git.is_ancestor(main_sha, branch_sha),
        policy=policy,
        policy_digest=canonical_digest(policy),
        verifier_app_id=verifier_app_id,
        ruleset_id=ruleset_id,
        ruleset_digest=ruleset_digest,
        claim=claim,
        grants=tuple(grants),
        revocations=_load_current_ledger(
            git,
            main_sha=main_sha,
            directory=REVOCATIONS_PATH,
        ),
        tombstones=_load_current_ledger(
            git,
            main_sha=main_sha,
            directory=TOMBSTONES_PATH,
        ),
    )
    return resolve_authority(context)


def validate_repository_ledgers(root: Path, revision: str) -> dict[str, Any]:
    git = GitAuthorityRepository(root)
    sha = git.rev_parse(revision)
    policy_data = git.read_path(sha, POLICY_PATH)
    assert policy_data is not None
    policy = validate_policy(parse_json_bytes(policy_data, label=POLICY_PATH))
    counts: dict[str, int] = {}
    records: dict[str, tuple[LedgerRecord, ...]] = {}
    for kind, directory, validator in (
        ("grants", GRANTS_PATH, validate_grant),
        ("revocations", REVOCATIONS_PATH, validate_revocation),
        ("tombstones", TOMBSTONES_PATH, validate_tombstone),
    ):
        parsed_records: list[LedgerRecord] = []
        paths = git.list_json_paths(sha, directory)
        for path in paths:
            record = _load_record(git, commit=sha, path=path)
            payload = validator(record.payload, label=path)
            expected = f"{directory}/{payload['activation_id']}.json"
            if path != expected:
                raise AuthorityError(f"record path must be {expected}: {path}")
            parsed_records.append(record)
        counts[kind] = len(paths)
        records[kind] = tuple(parsed_records)
    _validate_ledger_relations(
        records["grants"],
        records["revocations"],
        records["tombstones"],
    )
    claim = git.read_path(sha, CLAIM_PATH, required=False)
    if claim is not None:
        validate_claim(parse_json_bytes(claim, label=CLAIM_PATH))
    governance_data = git.read_path(sha, PROJECT_GOVERNANCE_PATH)
    assert governance_data is not None
    governance = parse_json_bytes(governance_data, label=PROJECT_GOVERNANCE_PATH)
    if (
        governance.get("default_development_base") == "main"
        and governance.get("coordination_branch") is None
        and claim is not None
    ):
        raise AuthorityError("main-null governance cannot carry an active claim")
    return {
        "revision": sha,
        "policy_digest": canonical_digest(policy),
        "claim_present": claim is not None,
        **counts,
    }


def validate_append_only_ledger_diff(
    root: Path,
    *,
    base_revision: str,
    head_revision: str,
) -> dict[str, Any]:
    git = GitAuthorityRepository(root)
    base_sha = git.rev_parse(base_revision)
    head_sha = git.rev_parse(head_revision)
    output = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "--no-renames",
            base_sha,
            head_sha,
            "--",
            GRANTS_PATH,
            REVOCATIONS_PATH,
            TOMBSTONES_PATH,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    additions: list[str] = []
    for line in output.splitlines():
        status, separator, path = line.partition("\t")
        if not separator:
            raise AuthorityError("ledger diff output is malformed")
        if not path.endswith(".json"):
            continue
        if status != "A":
            raise AuthorityError(
                f"immutable ledger record changed with status {status}: {path}"
            )
        additions.append(path)
    validate_repository_ledgers(root, head_sha)
    return {
        "base_revision": base_sha,
        "head_revision": head_sha,
        "added_records": sorted(additions),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    digest = subparsers.add_parser("policy-digest")
    digest.add_argument("--repository-root", type=Path, default=Path.cwd())
    digest.add_argument("--revision", default="HEAD")
    ledgers = subparsers.add_parser("validate-ledgers")
    ledgers.add_argument("--repository-root", type=Path, default=Path.cwd())
    ledgers.add_argument("--revision", default="HEAD")
    ledger_diff = subparsers.add_parser("validate-ledger-diff")
    ledger_diff.add_argument("--repository-root", type=Path, default=Path.cwd())
    ledger_diff.add_argument("--base-revision", required=True)
    ledger_diff.add_argument("--head-revision", default="HEAD")
    live = subparsers.add_parser("resolve-live")
    live.add_argument("--repository-root", type=Path, default=Path.cwd())
    live.add_argument("--repository-id", type=int, required=True)
    live.add_argument("--repository", required=True)
    live.add_argument("--branch", required=True)
    live.add_argument("--branch-revision", required=True)
    live.add_argument("--main-revision", required=True)
    live.add_argument("--verifier-app-id", type=int, required=True)
    live.add_argument("--ruleset-id", type=int, required=True)
    live.add_argument("--ruleset-digest", required=True)
    live.add_argument("--require-state", choices=[state.value for state in AuthorityState])
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "policy-digest":
            git = GitAuthorityRepository(arguments.repository_root)
            sha = git.rev_parse(arguments.revision)
            data = git.read_path(sha, POLICY_PATH)
            assert data is not None
            policy = validate_policy(parse_json_bytes(data, label=POLICY_PATH))
            print(canonical_digest(policy))
            return 0
        if arguments.command == "validate-ledgers":
            print(
                json.dumps(
                    validate_repository_ledgers(
                        arguments.repository_root,
                        arguments.revision,
                    ),
                    sort_keys=True,
                )
            )
            return 0
        if arguments.command == "validate-ledger-diff":
            print(
                json.dumps(
                    validate_append_only_ledger_diff(
                        arguments.repository_root,
                        base_revision=arguments.base_revision,
                        head_revision=arguments.head_revision,
                    ),
                    sort_keys=True,
                )
            )
            return 0
        resolution = resolve_git_authority(
            repository_root=arguments.repository_root,
            repository_id=arguments.repository_id,
            repository=arguments.repository,
            branch=arguments.branch,
            branch_revision=arguments.branch_revision,
            main_revision=arguments.main_revision,
            verifier_app_id=arguments.verifier_app_id,
            ruleset_id=arguments.ruleset_id,
            ruleset_digest=arguments.ruleset_digest,
        )
        print(json.dumps(resolution.as_dict(), sort_keys=True))
        if (
            arguments.require_state is not None
            and resolution.state.value != arguments.require_state
        ):
            return 1
        return 0 if resolution.state is not AuthorityState.INVALID else 1
    except (AuthorityError, OSError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {
                    "state": AuthorityState.INVALID.value,
                    "active": False,
                    "reason_code": "authority_evidence_unavailable",
                    "reason": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
