from __future__ import annotations

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = REPOSITORY_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
trusted = importlib.import_module("trusted_activation")

REPOSITORY_ID = 1271339534
REPOSITORY = "NTHU-Physics-SA-IT/PastExamWeb_PHY"
BRANCH = "integration/trusted-activation-rehearsal-test"
ACTIVATION_ID = "123e4567-e89b-42d3-a456-426614174000"
PARENT_SHA = "1" * 40
GRANT_COMMIT_SHA = "2" * 40
GRANT_BLOB_SHA = "3" * 40
BRANCH_SHA = "4" * 40
MAIN_SHA = "5" * 40
RULESET_ID = 991
RULESET_DIGEST = "6" * 64
APP_ID = 7654321


def _policy() -> dict[str, Any]:
    return json.loads(
        (REPOSITORY_ROOT / trusted.POLICY_PATH).read_text(encoding="utf-8")
    )


def _grant() -> dict[str, Any]:
    policy = _policy()
    return {
        "schema_version": 1,
        "record_type": "grant",
        "repository_id": REPOSITORY_ID,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "activation_id": ACTIVATION_ID,
        "grant_parent_sha": PARENT_SHA,
        "policy_version": trusted.POLICY_VERSION,
        "policy_digest": trusted.canonical_digest(policy),
        "ruleset_id": RULESET_ID,
        "ruleset_digest": RULESET_DIGEST,
        "verifier_app_id": APP_ID,
        "issuance_contract": trusted.ISSUANCE_CONTRACT,
        "issued_at": "2026-08-23T00:00:00Z",
    }


def _claim() -> dict[str, Any]:
    grant = _grant()
    return {
        "schema_version": 1,
        "record_type": "claim",
        "repository_id": REPOSITORY_ID,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "activation_id": ACTIVATION_ID,
        "grant_path": f"{trusted.GRANTS_PATH}/{ACTIVATION_ID}.json",
        "grant_commit_sha": GRANT_COMMIT_SHA,
        "grant_blob_sha": GRANT_BLOB_SHA,
        "policy_version": grant["policy_version"],
        "policy_digest": grant["policy_digest"],
        "ruleset_id": RULESET_ID,
        "ruleset_digest": RULESET_DIGEST,
        "verifier_app_id": APP_ID,
    }


def _record(kind: str, payload: dict[str, Any]) -> Any:
    directory = {
        "grant": trusted.GRANTS_PATH,
        "revocation": trusted.REVOCATIONS_PATH,
        "tombstone": trusted.TOMBSTONES_PATH,
    }[kind]
    return trusted.LedgerRecord(
        path=f"{directory}/{payload['activation_id']}.json",
        commit_sha=GRANT_COMMIT_SHA,
        blob_sha=GRANT_BLOB_SHA,
        commit_parents=(payload.get("grant_parent_sha", PARENT_SHA), "9" * 40),
        payload=payload,
    )


def _context(**overrides: Any) -> Any:
    policy = _policy()
    values = {
        "repository_id": REPOSITORY_ID,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "branch_head_sha": BRANCH_SHA,
        "main_sha": MAIN_SHA,
        "main_is_ancestor": True,
        "policy": policy,
        "policy_digest": trusted.canonical_digest(policy),
        "verifier_app_id": APP_ID,
        "ruleset_id": RULESET_ID,
        "ruleset_digest": RULESET_DIGEST,
        "claim": _claim(),
        "grants": (_record("grant", _grant()),),
        "revocations": (),
        "tombstones": (),
    }
    values.update(overrides)
    return trusted.AuthorityContext(**values)


def _revocation() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "revocation",
        "repository_id": REPOSITORY_ID,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "activation_id": ACTIVATION_ID,
        "frozen_head_sha": BRANCH_SHA,
        "reason": "bounded rehearsal complete",
        "revoked_at": "2026-08-23T01:00:00Z",
    }


def _tombstone() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "tombstone",
        "repository_id": REPOSITORY_ID,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "activation_id": ACTIVATION_ID,
        "reason": "permanent rehearsal retirement",
        "retired_at": "2026-08-23T02:00:00Z",
    }


def test_repository_policy_is_strict_and_main_remains_null() -> None:
    policy = trusted.validate_policy(_policy())
    governance = json.loads(
        (REPOSITORY_ROOT / trusted.PROJECT_GOVERNANCE_PATH).read_text(
            encoding="utf-8"
        )
    )

    assert policy["policy_version"] == trusted.POLICY_VERSION
    assert governance == {
        "schema_version": 1,
        "default_development_base": "main",
        "coordination_branch": None,
    }
    assert not (REPOSITORY_ROOT / trusted.CLAIM_PATH).exists()


def test_valid_external_grant_and_claim_are_active() -> None:
    result = trusted.resolve_authority(_context())

    assert result.state is trusted.AuthorityState.ACTIVE
    assert result.active
    assert result.activation_id == ACTIVATION_ID
    assert result.grant_commit_sha == GRANT_COMMIT_SHA
    assert result.grant_blob_sha == GRANT_BLOB_SHA


def test_grant_without_claim_is_protected_inactive() -> None:
    result = trusted.resolve_authority(_context(claim=None))

    assert result.state is trusted.AuthorityState.PROTECTED_INACTIVE
    assert not result.active
    assert result.reason_code == "grant_without_claim"


def test_local_claim_without_protected_main_grant_is_invalid() -> None:
    result = trusted.resolve_authority(_context(grants=()))

    assert result.state is trusted.AuthorityState.INVALID
    assert not result.active
    assert "exactly one grant" in result.reason


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository_id", 999),
        ("repository", "other/repository"),
        ("branch", "integration/other"),
        ("activation_id", "223e4567-e89b-42d3-a456-426614174000"),
        ("grant_commit_sha", "7" * 40),
        ("grant_blob_sha", "8" * 40),
        ("policy_digest", "7" * 64),
        ("ruleset_id", 992),
        ("ruleset_digest", "8" * 64),
        ("verifier_app_id", APP_ID + 1),
    ),
)
def test_wrong_claim_binding_fails_closed(field: str, value: Any) -> None:
    claim = _claim()
    claim[field] = value

    result = trusted.resolve_authority(_context(claim=claim))

    assert result.state is trusted.AuthorityState.INVALID
    assert not result.active


def test_wrong_live_app_or_ruleset_binding_fails_closed() -> None:
    for changes in (
        {"verifier_app_id": APP_ID + 1},
        {"ruleset_id": RULESET_ID + 1},
        {"ruleset_digest": "9" * 64},
    ):
        result = trusted.resolve_authority(_context(**changes))
        assert result.state is trusted.AuthorityState.INVALID
        assert not result.active


def test_main_advancement_makes_authority_stale_without_content_change() -> None:
    result = trusted.resolve_authority(_context(main_is_ancestor=False))

    assert result.state is trusted.AuthorityState.STALE
    assert not result.active
    assert result.reason_code == "current_main_not_ancestor"


def test_revocation_ends_authority_before_claim_removal() -> None:
    result = trusted.resolve_authority(
        _context(
            revocations=(_record("revocation", _revocation()),),
            tombstones=(_record("tombstone", _tombstone()),),
        )
    )

    assert result.state is trusted.AuthorityState.REVOKED
    assert not result.active
    assert result.reason_code == "retired_identity"


def test_removed_claim_after_revocation_is_return_ready_only_when_fresh() -> None:
    revocations = (_record("revocation", _revocation()),)
    tombstones = (_record("tombstone", _tombstone()),)

    ready = trusted.resolve_authority(
        _context(claim=None, revocations=revocations, tombstones=tombstones)
    )
    stale = trusted.resolve_authority(
        _context(
            claim=None,
            revocations=revocations,
            tombstones=tombstones,
            main_is_ancestor=False,
        )
    )

    assert ready.state is trusted.AuthorityState.RETURN_READY
    assert stale.state is trusted.AuthorityState.STALE
    assert not ready.active
    assert not stale.active


def test_tombstoned_name_or_activation_id_cannot_reactivate() -> None:
    exact = trusted.resolve_authority(
        _context(
            revocations=(_record("revocation", _revocation()),),
            tombstones=(_record("tombstone", _tombstone()),),
        )
    )
    reused_payload = _tombstone()
    reused_payload["activation_id"] = "323e4567-e89b-42d3-a456-426614174000"
    reused = trusted.resolve_authority(
        _context(tombstones=(_record("tombstone", reused_payload),))
    )

    assert exact.state is trusted.AuthorityState.REVOKED
    assert reused.state is trusted.AuthorityState.INVALID
    assert exact.reason_code == "retired_identity"
    assert reused.reason_code == "invalid_or_ambiguous_authority"


def test_duplicate_or_unknown_json_fails_closed() -> None:
    with pytest.raises(trusted.AuthorityError, match="duplicate JSON key"):
        trusted.parse_json_bytes(b'{"schema_version":1,"schema_version":1}', label="x")

    grant = _grant()
    grant["unknown"] = True
    with pytest.raises(trusted.AuthorityError, match="unsupported"):
        trusted.validate_grant(grant)


def test_duplicate_ledger_identity_fails_closed() -> None:
    first = _record("grant", _grant())
    duplicate = deepcopy(first)
    duplicate = trusted.LedgerRecord(
        path=first.path,
        commit_sha="7" * 40,
        blob_sha="8" * 40,
        commit_parents=(PARENT_SHA,),
        payload=deepcopy(first.payload),
    )

    result = trusted.resolve_authority(_context(grants=(first, duplicate)))

    assert result.state is trusted.AuthorityState.INVALID
    assert "duplicate grant identity" in result.reason


def test_revocation_and_tombstone_must_be_paired_with_one_grant() -> None:
    unpaired = trusted.resolve_authority(
        _context(revocations=(_record("revocation", _revocation()),))
    )
    assert unpaired.state is trusted.AuthorityState.INVALID
    assert "exact pairs" in unpaired.reason

    no_grant = trusted.resolve_authority(
        _context(
            grants=(),
            revocations=(_record("revocation", _revocation()),),
            tombstones=(_record("tombstone", _tombstone()),),
        )
    )
    assert no_grant.state is trusted.AuthorityState.INVALID
    assert "no matching grant" in no_grant.reason


def test_grant_branch_and_activation_id_are_never_reused() -> None:
    reused_branch = _grant()
    reused_branch["activation_id"] = "223e4567-e89b-42d3-a456-426614174001"
    result = trusted.resolve_authority(
        _context(grants=(_record("grant", _grant()), _record("grant", reused_branch)))
    )
    assert result.state is trusted.AuthorityState.INVALID
    assert "branch name was reused" in result.reason

    reused_activation = _grant()
    reused_activation["branch"] = "integration/different"
    result = trusted.resolve_authority(
        _context(
            grants=(_record("grant", _grant()), _record("grant", reused_activation))
        )
    )
    assert result.state is trusted.AuthorityState.INVALID
    assert "activation UUID was reused" in result.reason


def test_json_schemas_are_closed_and_match_record_contracts() -> None:
    schemas = {
        "grant": trusted.GRANT_KEYS,
        "claim": trusted.CLAIM_KEYS,
        "revocation": trusted.REVOCATION_KEYS,
        "tombstone": trusted.TOMBSTONE_KEYS,
    }
    for name, expected_keys in schemas.items():
        path = (
            REPOSITORY_ROOT
            / ".github"
            / "trusted-activation"
            / "schemas"
            / f"{name}.schema.json"
        )
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert frozenset(schema["required"]) == frozenset(expected_keys)
        assert frozenset(schema["properties"]) == frozenset(expected_keys)
