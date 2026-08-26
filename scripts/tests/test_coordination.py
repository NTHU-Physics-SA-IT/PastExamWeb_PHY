from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Self

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).parents[2]
CI_SCRIPTS = REPOSITORY_ROOT / "scripts" / "ci"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "coordination.yml"
sys.path.insert(0, str(CI_SCRIPTS))
coordination = importlib.import_module("coordination")

APP_ID = 4688858
MAIN_SHA = "1" * 40
BRANCH_SHA = "2" * 40
START_SHA = "3" * 40
CLOSE_SHA = "4" * 40
MAIN_TREE = "5" * 40


def _ruleset() -> dict[str, Any]:
    return {
        "id": 21226609,
        "name": "trusted-integration-lifecycle",
        "source": coordination.EXPECTED_REPOSITORY,
        "source_type": "Repository",
        "updated_at": "2026-08-26T01:00:00Z",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "exclude": [],
                "include": ["refs/heads/integration/*"],
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
                    "required_approving_review_count": 0,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
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
                    ],
                },
            },
        ],
    }


def _governance(branch: str | None) -> bytes:
    return coordination.governance_bytes(branch)


def _retired() -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "retired_identities": [
                {
                    "activation_id": "714d9c51-8b6b-405d-bd7c-4c92f6f26699",
                    "branch": (
                        "integration/"
                        "trusted-activation-rehearsal-714d9c51"
                    ),
                    "retirement_kind": "aborted-before-issuance",
                    "reason": "cancelled before issuance",
                    "retired_at": "2026-08-23T10:44:47Z",
                }
            ],
        }
    ).encode()


class StartClient:
    def __init__(self) -> None:
        self.refs: list[dict[str, Any]] = []
        self.created_branch = ""

    def integration_refs(self) -> list[dict[str, Any]]:
        return self.refs

    def main_ref(self) -> dict[str, Any]:
        return {"object": {"sha": MAIN_SHA}}

    def contents(self, path: str, ref: str) -> bytes:
        if path == coordination.RETIRED_IDENTITIES_PATH:
            return _retired()
        if ref == MAIN_SHA:
            return _governance(None)
        if ref == START_SHA:
            return _governance(self.created_branch)
        raise AssertionError((path, ref))

    def successful_main_ci(self, sha: str) -> bool:
        return sha == MAIN_SHA

    def commit(self, sha: str) -> dict[str, Any]:
        assert sha == MAIN_SHA
        return {"tree": {"sha": MAIN_TREE}}

    def create_blob(self, data: bytes) -> str:
        self.pending = json.loads(data)
        return "6" * 40

    def create_tree(self, *, base_tree: str, blob_sha: str) -> str:
        assert base_tree == MAIN_TREE
        assert blob_sha == "6" * 40
        return "7" * 40

    def create_commit(self, *, message: str, tree: str, parents: list[str]) -> str:
        assert message == "chore(coordination): start stage-5e"
        assert tree == "7" * 40
        assert parents == [MAIN_SHA]
        return START_SHA

    def create_ref(self, *, branch: str, sha: str) -> None:
        assert sha == START_SHA
        self.created_branch = branch
        assert self.pending["coordination_branch"] == branch
        self.refs = [{"ref": f"refs/heads/{branch}", "object": {"sha": sha}}]


class CloseClient:
    branch = "integration/governance-rehearsal-ab12cd34"

    def __init__(self) -> None:
        self.refs = [
            {"ref": f"refs/heads/{self.branch}", "object": {"sha": BRANCH_SHA}}
        ]
        self.updated = False

    def integration_refs(self) -> list[dict[str, Any]]:
        return self.refs

    def main_ref(self) -> dict[str, Any]:
        return {"object": {"sha": MAIN_SHA}}

    def contents(self, path: str, ref: str) -> bytes:
        assert path == coordination.PROJECT_GOVERNANCE_PATH
        if ref == BRANCH_SHA:
            return _governance(self.branch)
        if ref in {MAIN_SHA, CLOSE_SHA}:
            return _governance(None)
        raise AssertionError(ref)

    def successful_main_ci(self, sha: str) -> bool:
        return sha == MAIN_SHA

    def compare(self, base: str, head: str) -> dict[str, Any]:
        assert (base, head) == (BRANCH_SHA, MAIN_SHA)
        return {"status": "ahead", "merge_base_commit": {"sha": BRANCH_SHA}}

    def commit(self, sha: str) -> dict[str, Any]:
        assert sha == MAIN_SHA
        return {"tree": {"sha": MAIN_TREE}}

    def create_commit(self, *, message: str, tree: str, parents: list[str]) -> str:
        assert message == "chore(coordination): close governance-rehearsal"
        assert tree == MAIN_TREE
        assert parents == [BRANCH_SHA, MAIN_SHA]
        return CLOSE_SHA

    def update_ref(self, *, branch: str, sha: str) -> None:
        assert branch == self.branch
        assert sha == CLOSE_SHA
        self.updated = True
        self.refs = [
            {"ref": f"refs/heads/{self.branch}", "object": {"sha": CLOSE_SHA}}
        ]

    def delete_ref(self, branch: str) -> None:
        assert self.updated
        assert branch == self.branch
        self.refs = []


class RecoveryCloseClient(CloseClient):
    def __init__(self) -> None:
        super().__init__()
        self.refs = [
            {"ref": f"refs/heads/{self.branch}", "object": {"sha": CLOSE_SHA}}
        ]

    def contents(self, path: str, ref: str) -> bytes:
        assert path == coordination.PROJECT_GOVERNANCE_PATH
        if ref in {MAIN_SHA, CLOSE_SHA}:
            return _governance(None)
        raise AssertionError(ref)

    def commit(self, sha: str) -> dict[str, Any]:
        if sha == CLOSE_SHA:
            return {"parents": [{"sha": BRANCH_SHA}, {"sha": MAIN_SHA}]}
        return super().commit(sha)

    def compare(self, base: str, head: str) -> dict[str, Any]:
        assert head == MAIN_SHA
        assert base in {BRANCH_SHA, MAIN_SHA}
        return {"status": "ahead", "merge_base_commit": {"sha": base}}

    def delete_ref(self, branch: str) -> None:
        assert branch == self.branch
        self.refs = []


def test_human_name_rejects_machine_identifiers() -> None:
    assert coordination.normalize_name("stage-5e") == "stage-5e"
    for value in (
        "Stage-5E",
        "stage 5e",
        MAIN_SHA,
        "714d9c51-8b6b-405d-bd7c-4c92f6f26699",
        "4688858",
        "21226609",
        "integration/stage-5e",
    ):
        with pytest.raises(coordination.CoordinationError):
            coordination.normalize_name(value)


def test_retired_obsolete_rehearsal_is_permanent() -> None:
    payload = coordination.parse_strict_json(_retired(), label="retired")
    branches = coordination.validate_retired_identities(payload)
    assert branches == frozenset(
        {"integration/trusted-activation-rehearsal-714d9c51"}
    )


def test_start_generates_identity_and_establishes_branch_local_governance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(coordination.secrets, "token_hex", lambda length: "ab12cd34")
    client = StartClient()
    result = coordination.start_coordination(
        content=client,
        actions=client,
        ruleset=_ruleset(),
        name="stage-5e",
        expected_app_id=APP_ID,
    )
    assert result == {
        "operation": "start",
        "name": "stage-5e",
        "branch": "integration/stage-5e-ab12cd34",
        "base_main_sha": MAIN_SHA,
        "head_sha": START_SHA,
        "state": "ACTIVE",
        "expected_pr_base": "integration/stage-5e-ab12cd34",
    }


def test_start_requires_exact_main_ci() -> None:
    client = StartClient()
    client.successful_main_ci = lambda sha: False
    with pytest.raises(coordination.CoordinationError, match="exact-SHA CI"):
        coordination.start_coordination(
            content=client,
            actions=client,
            ruleset=_ruleset(),
            name="stage-5e",
            expected_app_id=APP_ID,
        )


def test_start_attestation_binds_generated_identity_and_live_authority() -> None:
    result = {
        "branch": "integration/stage-5e-ab12cd34",
        "head_sha": START_SHA,
        "base_main_sha": MAIN_SHA,
    }
    attestation = coordination.build_start_attestation(
        result=result,
        ruleset=_ruleset(),
        expected_app_id=APP_ID,
        app_slug="pastexam-phy-trusted-gate-0823",
        repository=coordination.EXPECTED_REPOSITORY,
        repository_id=1271339534,
        lifecycle_run_id=32918420724,
        lifecycle_run_attempt=1,
    )

    assert attestation["kind"] == "coordination-start"
    assert attestation["branch"] == result["branch"]
    assert attestation["head_sha"] == START_SHA
    assert attestation["parent_main_sha"] == MAIN_SHA
    assert attestation["ruleset"]["bypass_actors"] == _ruleset()["bypass_actors"]


def test_close_requires_containment_then_clears_and_retires() -> None:
    client = CloseClient()
    result = coordination.close_coordination(
        content=client,
        actions=client,
        ruleset=_ruleset(),
        name="governance-rehearsal",
        expected_app_id=APP_ID,
    )
    assert result["state"] == "RETIRED"
    assert result["retired_branch"] == client.branch
    assert result["final_integration_sha"] == BRANCH_SHA
    assert client.refs == []


def test_close_rejects_stale_or_unreturned_integration() -> None:
    client = CloseClient()
    client.compare = lambda base, head: {
        "status": "diverged",
        "merge_base_commit": {"sha": "9" * 40},
    }
    with pytest.raises(coordination.CoordinationError, match="STALE or not returned"):
        coordination.close_coordination(
            content=client,
            actions=client,
            ruleset=_ruleset(),
            name="governance-rehearsal",
            expected_app_id=APP_ID,
        )


def test_close_recovers_verified_null_governance_closeout() -> None:
    client = RecoveryCloseClient()
    result = coordination.close_coordination(
        content=client,
        actions=client,
        ruleset=_ruleset(),
        name="governance-rehearsal",
        expected_app_id=APP_ID,
    )
    assert result["state"] == "RETIRED"
    assert result["recovered"] is True
    assert result["final_integration_sha"] == BRANCH_SHA
    assert result["closeout_sha"] == CLOSE_SHA
    assert client.refs == []


@pytest.mark.parametrize(
    "mutation",
    (
        lambda rules: rules.update(enforcement="disabled"),
        lambda rules: rules["bypass_actors"].append(
            {"actor_id": 1, "actor_type": "RepositoryRole", "bypass_mode": "always"}
        ),
        lambda rules: rules["rules"].pop(0),
        lambda rules: rules["rules"][-1]["parameters"][
            "required_status_checks"
        ].append({"context": "Trusted Governance Gate", "integration_id": APP_ID}),
        lambda rules: rules["rules"].append({"type": "required_linear_history"}),
        lambda rules: rules["rules"][-1]["parameters"][
            "required_status_checks"
        ].append({"unexpected": "malformed"}),
    ),
)
def test_ruleset_validation_fails_closed(mutation: Any) -> None:
    rules = _ruleset()
    mutation(rules)
    with pytest.raises(coordination.CoordinationError):
        coordination.validate_ruleset(rules, expected_app_id=APP_ID)


def test_ruleset_auditor_exposes_only_exact_get(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[Any] = []

    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *arguments: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(_ruleset()).encode()

    def fake_urlopen(request: Any, timeout: int) -> Response:
        observed.append((request.full_url, request.method, timeout))
        return Response()

    monkeypatch.setattr(coordination, "urlopen", fake_urlopen)
    auditor = coordination.RulesetAuditor(
        api_url="https://api.github.test",
        repository=coordination.EXPECTED_REPOSITORY,
        token="redacted-test-token",
        ruleset_id=21226609,
    )

    assert auditor.ruleset() == _ruleset()
    expected_url = (
        "https://api.github.test/repos/"
        + "NTHU-Physics-SA-IT/PastExamWeb_PHY/rulesets/21226609"
    )
    assert observed == [
        (
            expected_url,
            "GET",
            30,
        )
    ]
    assert not hasattr(auditor, "request")
    assert not hasattr(auditor, "post")
    assert not hasattr(auditor, "patch")
    assert not hasattr(auditor, "delete")


def test_actions_reader_is_separate_exact_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[Any] = []

    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *arguments: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "workflow_runs": [
                        {"head_sha": MAIN_SHA, "conclusion": "success"}
                    ]
                }
            ).encode()

    def fake_urlopen(request: Any, timeout: int) -> Response:
        observed.append((request.full_url, request.method, timeout))
        return Response()

    monkeypatch.setattr(coordination, "urlopen", fake_urlopen)
    reader = coordination.ActionsReader(
        api_url="https://api.github.test",
        repository=coordination.EXPECTED_REPOSITORY,
        token="read-only-test-token",
    )

    assert reader.successful_main_ci(MAIN_SHA)
    expected_url = (
        "https://api.github.test/repos/NTHU-Physics-SA-IT/"
        + "PastExamWeb_PHY/actions/workflows/main.yml/runs?"
        + "branch=main&event=push&status=completed&per_page=20"
    )
    assert observed == [
        (
            expected_url,
            "GET",
            30,
        )
    ]
    assert not hasattr(reader, "request")
    assert not hasattr(reader, "post")
    assert not hasattr(reader, "patch")
    assert not hasattr(reader, "delete")


def test_workflow_accepts_only_human_intent_and_separates_tokens() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"operation", "name"}
    assert inputs["operation"]["options"] == ["start", "close"]
    for machine_input in (
        "activation_id",
        "expected_main_sha",
        "app_id",
        "installation_id",
        "ruleset_id",
        "ruleset_digest",
        "policy_digest",
        "blob_sha",
    ):
        assert machine_input not in inputs

    job = workflow["jobs"]["coordination_lifecycle"]
    assert job["environment"] == "trusted-coordination-issuance"
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    steps = job["steps"]
    ref_token = next(step for step in steps if step.get("id") == "ref-token")
    assert set(ref_token["with"]) == {
        "client-id",
        "private-key",
        "permission-contents",
    }
    assert ref_token["with"]["permission-contents"] == "write"
    auditor_token = next(
        step for step in steps if step.get("id") == "ruleset-auditor-token"
    )
    assert set(auditor_token["with"]) == {
        "client-id",
        "private-key",
        "permission-administration",
    }
    assert auditor_token["with"]["permission-administration"] == "write"

    operate = next(
        step for step in steps if step["name"] == "Resolve authority and apply intent"
    )
    assert operate["env"]["GITHUB_TOKEN"] == "${{ steps.ref-token.outputs.token }}"
    assert operate["env"]["GITHUB_ACTIONS_READ_TOKEN"] == "${{ github.token }}"
    assert operate["env"]["GITHUB_RULESET_AUDITOR_TOKEN"] == (
        "${{ steps.ruleset-auditor-token.outputs.token }}"
    )
    assert operate["env"]["APP_SLUG"] == "${{ steps.ref-token.outputs.app-slug }}"
    artifact = next(
        step for step in steps if step["name"] == "Publish canonical Start attestation"
    )
    assert artifact["if"] == "${{ inputs.operation == 'start' }}"
    assert artifact["with"]["retention-days"] == "3"
    assert "permission-actions" not in source
    assert "permission-checks" not in source


def test_ref_client_has_no_generic_request_and_rejects_non_integration_writes() -> None:
    client = coordination.RefLifecycleClient(
        api_url="https://api.github.test",
        repository=coordination.EXPECTED_REPOSITORY,
        token="contents-write-test-token",
    )
    assert not hasattr(client, "request")
    for branch in ("main", "feature/example", "integration/arbitrary"):
        with pytest.raises(coordination.CoordinationError, match="generated integration"):
            client.create_ref(branch=branch, sha=MAIN_SHA)
        with pytest.raises(coordination.CoordinationError, match="generated integration"):
            client.update_ref(branch=branch, sha=MAIN_SHA)
        with pytest.raises(coordination.CoordinationError, match="generated integration"):
            client.delete_ref(branch)


@pytest.mark.parametrize(
    ("encoded", "expected"),
    (("aGVs\nbG8=\n", b"hello"), ("aGVs bG8=", None)),
)
def test_contents_normalizes_only_github_line_wrapping(
    monkeypatch: pytest.MonkeyPatch,
    encoded: str,
    expected: bytes | None,
) -> None:
    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *arguments: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"encoding": "base64", "content": encoded}).encode()

    monkeypatch.setattr(
        coordination,
        "urlopen",
        lambda request, timeout: Response(),
    )
    client = coordination.RefLifecycleClient(
        api_url="https://api.github.test",
        repository=coordination.EXPECTED_REPOSITORY,
        token="contents-write-test-token",
    )

    if expected is None:
        with pytest.raises(coordination.CoordinationError, match="content is malformed"):
            client.contents(coordination.PROJECT_GOVERNANCE_PATH, MAIN_SHA)
    else:
        assert client.contents(coordination.PROJECT_GOVERNANCE_PATH, MAIN_SHA) == expected
