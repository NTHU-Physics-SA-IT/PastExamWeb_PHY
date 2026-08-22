from __future__ import annotations

import base64
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = REPOSITORY_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
gate = importlib.import_module("trusted_governance_gate")
trusted = importlib.import_module("trusted_activation")

VERIFIER_WORKFLOW = (
    REPOSITORY_ROOT / ".github" / "workflows" / "trusted-governance-gate.yml"
)
ISSUANCE_WORKFLOW = (
    REPOSITORY_ROOT / ".github" / "workflows" / "issue-coordination-grant.yml"
)
APP_ID = 7654321
RULESET_ID = 991
ACTIVATION_ID = "123e4567-e89b-42d3-a456-426614174000"
MAIN_SHA = "a" * 40
PARENT_SHA = "b" * 40


def _ruleset() -> dict[str, Any]:
    return {
        "id": RULESET_ID,
        "name": "trusted-integration-lifecycle",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": ["refs/heads/integration/*"],
                "exclude": [],
            }
        },
        "bypass_actors": [
            {
                "actor_id": APP_ID,
                "actor_type": "Integration",
                "bypass_mode": "always",
            }
        ],
        "rules": [
            {"type": "creation"},
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 1,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": True,
                    "require_last_push_approval": True,
                    "required_review_thread_resolution": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": "check-branch", "integration_id": 15368},
                        {"context": "CI Gate", "integration_id": 15368},
                        {
                            "context": "Trusted Governance Gate",
                            "integration_id": APP_ID,
                        },
                    ],
                },
            },
        ],
    }


class TrustRootAPI:
    def __init__(
        self,
        *,
        app_id: int = APP_ID,
        ruleset: dict[str, Any] | None = None,
    ) -> None:
        self.app_id = app_id
        self.ruleset_payload = ruleset or _ruleset()

    def app(self, slug: str) -> dict[str, Any]:
        assert slug == "test-trusted-app"
        return {"id": self.app_id, "slug": "test-trusted-app"}

    def ruleset(self, ruleset_id: int) -> dict[str, Any]:
        assert ruleset_id == RULESET_ID
        return self.ruleset_payload


def test_privileged_workflows_are_dormant_and_main_sourced() -> None:
    verifier_text = VERIFIER_WORKFLOW.read_text(encoding="utf-8")
    verifier = yaml.load(verifier_text, Loader=yaml.BaseLoader)
    issuance_text = ISSUANCE_WORKFLOW.read_text(encoding="utf-8")
    issuance = yaml.load(issuance_text, Loader=yaml.BaseLoader)

    assert set(verifier["on"]) == {"workflow_run"}
    assert verifier["on"]["workflow_run"]["workflows"] == ["CI/CD Pipeline"]
    assert "pull_request_target" not in verifier["on"]
    job = verifier["jobs"]["trusted_governance_gate"]
    assert job["if"] == "${{ vars.TRUSTED_GOVERNANCE_ENABLED == 'true' }}"
    assert job["environment"] == "trusted-governance-verifier"
    checkout = next(
        step for step in job["steps"] if step["name"] == "Checkout current protected main only"
    )
    assert checkout["with"] == {
        "fetch-depth": "1",
        "persist-credentials": "false",
        "ref": "${{ github.event.repository.default_branch }}",
    }
    assert "github.event.workflow_run.head_sha" not in verifier_text
    assert "download-artifact" not in verifier_text
    assert "actions/cache" not in verifier_text
    assert "restore-keys" not in verifier_text
    assert "trusted_governance_gate.py" in verifier_text
    assert "actions/create-github-app-token@" in verifier_text
    assert "client-id: ${{ vars.TRUSTED_GOVERNANCE_APP_CLIENT_ID }}" in verifier_text
    assert "EXPECTED_APP_SLUG: ${{ steps.app-token.outputs.app-slug }}" in verifier_text
    assert '--expected-app-slug "$EXPECTED_APP_SLUG"' in verifier_text
    assert "permission-checks: write" in verifier_text
    assert "permission-contents: read" in verifier_text
    assert "permission-actions: read" in verifier_text
    assert "permission-pull-requests: read" in verifier_text
    assert "permission-administration: read" in verifier_text
    assert "permission-contents: write" not in verifier_text

    assert set(issuance["on"]) == {"workflow_dispatch"}
    issuance_job = issuance["jobs"]["trusted_ref_lifecycle"]
    assert issuance_job["if"] == "${{ vars.TRUSTED_GOVERNANCE_ENABLED == 'true' }}"
    assert issuance_job["environment"] == "trusted-coordination-issuance"
    assert "permission-contents: write" in issuance_text
    assert "EXPECTED_APP_SLUG: ${{ steps.app-token.outputs.app-slug }}" in issuance_text
    assert '--expected-app-slug "$EXPECTED_APP_SLUG"' in issuance_text
    assert "permission-checks: write" not in issuance_text
    assert "download-artifact" not in issuance_text
    assert "actions/cache" not in issuance_text
    assert "github.event.pull_request" not in issuance_text


def test_ruleset_digest_is_order_normalized() -> None:
    first = _ruleset()
    second = json.loads(json.dumps(first))
    second["rules"].reverse()
    second["bypass_actors"].reverse()

    assert gate.ruleset_digest(first) == gate.ruleset_digest(second)


def test_repository_content_accepts_github_wrapped_base64() -> None:
    api = object.__new__(gate.GitHubAPI)
    api.repository = "owner/repository"
    encoded = base64.b64encode(b"trusted content").decode()
    api.get = lambda *_args, **_kwargs: {
        "type": "file",
        "encoding": "base64",
        "content": f"{encoded[:8]}\n{encoded[8:]}",
        "sha": "a" * 40,
    }

    assert api.content("policy.json", "main") == (b"trusted content", "a" * 40)


def test_trusted_check_is_idempotently_updated_by_workflow_run() -> None:
    api = object.__new__(gate.GitHubAPI)
    api.repository = "owner/repository"
    calls: list[tuple[str, str, dict[str, Any]]] = []
    api.get = lambda *_args, **_kwargs: {
        "check_runs": [
            {
                "id": 77,
                "external_id": "trusted-governance:42",
            }
        ]
    }
    api.post = lambda path, payload: calls.append(("POST", path, payload))

    def record_patch(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(("PATCH", path, payload))
        return {
            "id": 77,
            "name": gate.TRUSTED_CHECK_NAME,
            "app": {"id": APP_ID},
        }

    api.patch = record_patch
    result = api.upsert_check(
        sha="a" * 40,
        conclusion="success",
        summary="accepted",
        external_id="trusted-governance:42",
        details_url="https://example.invalid/run/42",
    )

    assert result["id"] == 77
    assert len(calls) == 1
    method, path, payload = calls[0]
    assert method == "PATCH"
    assert path.endswith("/check-runs/77")
    assert "head_sha" not in payload
    assert "name" not in payload


def test_live_trust_root_requires_distinct_exact_app_and_ruleset() -> None:
    payload = _ruleset()
    digest = gate.ruleset_digest(payload)

    app, observed = gate.validate_live_trust_root(
        TrustRootAPI(),
        expected_app_slug="test-trusted-app",
        expected_app_id=APP_ID,
        ruleset_id=RULESET_ID,
        expected_ruleset_digest=digest,
    )

    assert app["id"] == APP_ID
    assert observed["id"] == RULESET_ID

    with pytest.raises(trusted.AuthorityError, match="App identity"):
        gate.validate_live_trust_root(
            TrustRootAPI(app_id=15368),
            expected_app_slug="test-trusted-app",
            expected_app_id=15368,
            ruleset_id=RULESET_ID,
            expected_ruleset_digest=digest,
        )
    with pytest.raises(trusted.AuthorityError, match="digest"):
        gate.validate_live_trust_root(
            TrustRootAPI(),
            expected_app_slug="test-trusted-app",
            expected_app_id=APP_ID,
            ruleset_id=RULESET_ID,
            expected_ruleset_digest="0" * 64,
        )


def test_ruleset_requires_exact_app_bypass() -> None:
    payload = _ruleset()
    payload["bypass_actors"] = []
    digest = gate.ruleset_digest(payload)

    with pytest.raises(trusted.AuthorityError, match="bypass"):
        gate.validate_live_trust_root(
            TrustRootAPI(ruleset=payload),
            expected_app_slug="test-trusted-app",
            expected_app_id=APP_ID,
            ruleset_id=RULESET_ID,
            expected_ruleset_digest=digest,
        )

    broad = _ruleset()
    broad["bypass_actors"].append(
        {"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}
    )
    with pytest.raises(trusted.AuthorityError, match="unique"):
        gate.validate_live_trust_root(
            TrustRootAPI(ruleset=broad),
            expected_app_slug="test-trusted-app",
            expected_app_id=APP_ID,
            ruleset_id=RULESET_ID,
            expected_ruleset_digest=gate.ruleset_digest(broad),
        )


@pytest.mark.parametrize(
    ("rule_type", "message"),
    [
        ("non_fast_forward", "rule set"),
        ("pull_request", "rule set"),
        ("required_status_checks", "rule set"),
    ],
)
def test_ruleset_cannot_weaken_required_contract(
    rule_type: str,
    message: str,
) -> None:
    payload = _ruleset()
    payload["rules"] = [
        item for item in payload["rules"] if item["type"] != rule_type
    ]

    with pytest.raises(trusted.AuthorityError, match=message):
        gate.validate_live_trust_root(
            TrustRootAPI(ruleset=payload),
            expected_app_slug="test-trusted-app",
            expected_app_id=APP_ID,
            ruleset_id=RULESET_ID,
            expected_ruleset_digest=gate.ruleset_digest(payload),
        )


class JobsAPI:
    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.jobs = jobs

    def run_jobs(self, run_id: int, attempt: int) -> list[dict[str, Any]]:
        assert run_id == 42
        assert attempt == 3
        return self.jobs


def test_transition_full_evidence_is_exact() -> None:
    accepted = {
        "name": gate.FULL_ATTESTATION_NAME,
        "status": "completed",
        "conclusion": "success",
        "head_sha": "a" * 40,
        "run_id": 42,
        "run_attempt": 3,
    }

    gate._require_full_run(
        JobsAPI([accepted]),
        run_id=42,
        attempt=3,
        head_sha="a" * 40,
    )

    for changed in (
        {"conclusion": "failure"},
        {"head_sha": "b" * 40},
        {"run_attempt": 2},
    ):
        job = {**accepted, **changed}
        with pytest.raises(trusted.AuthorityError, match="Full"):
            gate._require_full_run(
                JobsAPI([job]),
                run_id=42,
                attempt=3,
                head_sha="a" * 40,
            )


def test_transition_success_does_not_imply_active_authority() -> None:
    verdict = gate.GateVerdict(
        True,
        "ACTIVATION_TRANSITION",
        False,
        "valid_activation_transition",
        "valid but not merged",
        "integration/rehearsal",
        "123e4567-e89b-42d3-a456-426614174000",
    )
    payload = json.loads(verdict.summary())

    assert payload["accepted"] is True
    assert payload["coordination_authority_active"] is False
    assert payload["state"] == "ACTIVATION_TRANSITION"


class OrdinaryAPI:
    def __init__(self, *, claim: dict[str, Any] | None, coordination: str | None) -> None:
        self.claim = claim
        self.coordination = coordination

    def content(
        self,
        path: str,
        revision: str,
        *,
        required: bool = True,
    ) -> tuple[bytes, str] | None:
        if path == trusted.CLAIM_PATH:
            if self.claim is None:
                return None
            return json.dumps(self.claim).encode(), "a" * 40
        assert path == trusted.PROJECT_GOVERNANCE_PATH
        return (
            json.dumps(
                {
                    "schema_version": 1,
                    "default_development_base": "main",
                    "coordination_branch": self.coordination,
                }
            ).encode(),
            "b" * 40,
        )


def test_return_while_active_is_rejected() -> None:
    claim = {
        "activation_id": "123e4567-e89b-42d3-a456-426614174000"
    }
    result = gate._ordinary_candidate(
        OrdinaryAPI(claim=claim, coordination="integration/rehearsal"),
        revision="a" * 40,
        branch="return-candidate",
    )

    assert not result.accepted
    assert not result.authority_active
    assert result.reason_code == "active_return_or_self_authority"


def _write_lifecycle_records(root: Path, *, retired: bool = False) -> str:
    branch = "integration/trusted-activation-rehearsal"
    grant = {
        "schema_version": 1,
        "record_type": "grant",
        "repository_id": gate.EXPECTED_REPOSITORY_ID,
        "repository": gate.EXPECTED_REPOSITORY,
        "branch": branch,
        "activation_id": ACTIVATION_ID,
        "grant_parent_sha": PARENT_SHA,
        "policy_version": trusted.POLICY_VERSION,
        "policy_digest": "c" * 64,
        "ruleset_id": RULESET_ID,
        "ruleset_digest": "d" * 64,
        "verifier_app_id": APP_ID,
        "issuance_contract": trusted.ISSUANCE_CONTRACT,
        "issued_at": "2026-08-23T00:00:00Z",
    }
    grant_path = root / trusted.GRANTS_PATH / f"{ACTIVATION_ID}.json"
    grant_path.parent.mkdir(parents=True)
    grant_path.write_text(json.dumps(grant))
    if retired:
        revocation = {
            "schema_version": 1,
            "record_type": "revocation",
            "repository_id": gate.EXPECTED_REPOSITORY_ID,
            "repository": gate.EXPECTED_REPOSITORY,
            "branch": branch,
            "activation_id": ACTIVATION_ID,
            "frozen_head_sha": MAIN_SHA,
            "reason": "bounded rehearsal retired",
            "revoked_at": "2026-08-23T01:00:00Z",
        }
        tombstone = {
            "schema_version": 1,
            "record_type": "tombstone",
            "repository_id": gate.EXPECTED_REPOSITORY_ID,
            "repository": gate.EXPECTED_REPOSITORY,
            "branch": branch,
            "activation_id": ACTIVATION_ID,
            "reason": "bounded rehearsal retired",
            "retired_at": "2026-08-23T01:00:00Z",
        }
        for directory, payload in (
            (trusted.REVOCATIONS_PATH, revocation),
            (trusted.TOMBSTONES_PATH, tombstone),
        ):
            path = root / directory / f"{ACTIVATION_ID}.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(payload))
    else:
        (root / trusted.TOMBSTONES_PATH).mkdir(parents=True)
        (root / trusted.REVOCATIONS_PATH).mkdir(parents=True)
    return branch


class LifecycleAPI:
    def __init__(self, branch: str) -> None:
        self.branch_name = branch
        self.created: tuple[str, str] | None = None

    def ref_sha(self, branch: str, *, required: bool = True) -> str | None:
        if branch == "main":
            return MAIN_SHA
        assert branch == self.branch_name
        return None

    def commit(self, sha: str) -> dict[str, Any]:
        assert sha == MAIN_SHA
        return {"parents": [{"sha": PARENT_SHA}]}

    def create_ref(self, branch: str, sha: str) -> dict[str, Any]:
        self.created = (branch, sha)
        return {"object": {"sha": sha}}

    def branch(self, branch: str) -> dict[str, Any]:
        assert self.created == (branch, MAIN_SHA)
        return {"protected": True}


def test_trusted_issue_creates_only_exact_granted_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    branch = _write_lifecycle_records(tmp_path)
    api = LifecycleAPI(branch)
    monkeypatch.setattr(gate, "validate_live_trust_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate, "validate_repository_ledgers", lambda *_args: None)
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{MAIN_SHA}\n", stderr=""
        ),
    )

    result = gate.operate_ref(
        api,
        root=tmp_path,
        operation="issue",
        activation_id=ACTIVATION_ID,
        expected_main_sha=MAIN_SHA,
        expected_app_slug="trusted-test",
        expected_app_id=APP_ID,
        ruleset_id=RULESET_ID,
        expected_ruleset_digest="d" * 64,
    )

    assert result["result"] == "created"
    assert api.created == (branch, MAIN_SHA)


def test_replay_preflight_rejects_without_ref_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    branch = _write_lifecycle_records(tmp_path, retired=True)
    api = LifecycleAPI(branch)
    monkeypatch.setattr(gate, "validate_live_trust_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate, "validate_repository_ledgers", lambda *_args: None)
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{MAIN_SHA}\n", stderr=""
        ),
    )

    result = gate.operate_ref(
        api,
        root=tmp_path,
        operation="replay-preflight",
        activation_id=ACTIVATION_ID,
        expected_main_sha=MAIN_SHA,
        expected_app_slug="trusted-test",
        expected_app_id=APP_ID,
        ruleset_id=RULESET_ID,
        expected_ruleset_digest="d" * 64,
    )

    assert result["result"] == "rejected"
    assert result["reason_code"] == "retired_or_revoked_identity"
    assert api.created is None
