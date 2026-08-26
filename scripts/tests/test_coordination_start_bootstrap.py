from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.message import Message
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import zipfile
from urllib.error import HTTPError

import pytest


CI_SCRIPTS = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
ci = importlib.import_module("classify_ci_mode")
coordination = importlib.import_module("coordination")
governance_module = importlib.import_module("project_governance")

NOW = datetime(2026, 8, 26, 3, tzinfo=UTC)
REPOSITORY = coordination.EXPECTED_REPOSITORY
REPOSITORY_ID = 1271339534
APP_ID = 4688858
APP_SLUG = "pastexam-phy-trusted-gate-0823"
BOT_LOGIN = f"{APP_SLUG}[bot]"
BOT_ID = 320087453
RULESET_ID = 21226609
BRANCH = "integration/bootstrap-fixture-ab12cd34"
LIFECYCLE_RUN_ID = 801
PARENT_RUN_ID = 701
START_RUN_ID = 901


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _governance(branch: str | None) -> str:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "default_development_base": "main",
                "coordination_branch": branch,
            },
            indent=2,
        )
        + "\n"
    )


def _ruleset() -> dict[str, Any]:
    return {
        "id": RULESET_ID,
        "name": coordination.EXPECTED_RULESET_NAME,
        "target": "branch",
        "source_type": "Repository",
        "source": REPOSITORY,
        "enforcement": "active",
        "updated_at": "2026-08-26T01:00:00Z",
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


def _fixture(tmp_path: Path) -> dict[str, Any]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "CI Fixture")
    _git(repository, "config", "user.email", "ci-fixture@example.invalid")
    workflows = repository / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "main.yml").write_text("name: fixture main\n", encoding="utf-8")
    (workflows / "coordination.yml").write_text(
        "name: fixture coordination\n", encoding="utf-8"
    )
    governance_path = repository / ".github" / "project-governance.json"
    governance_path.write_text(_governance(None), encoding="utf-8")
    (repository / "application.txt").write_text("identical\n", encoding="utf-8")
    parent = _commit(repository, "parent")
    governance_path.write_text(_governance(BRANCH), encoding="utf-8")
    head = _commit(repository, "start")
    return {
        "root": repository,
        "git": ci.GitRepository(repository),
        "parent": parent,
        "head": head,
    }


def _artifact(attestation: dict[str, Any]) -> tuple[bytes, str]:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            ci.START_ARTIFACT_FILE,
            json.dumps(attestation, sort_keys=True).encode("utf-8"),
        )
    archive = output.getvalue()
    return archive, "sha256:" + hashlib.sha256(archive).hexdigest()


class StartAPI:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.parent = fixture["parent"]
        self.head = fixture["head"]
        self.rules = _ruleset()
        self.app = {"id": APP_ID, "slug": APP_SLUG}
        self.bot = {"id": BOT_ID, "login": BOT_LOGIN, "type": "Bot"}
        self.commit = {
            "sha": self.head,
            "author": deepcopy(self.bot),
            "commit": {"verification": {"verified": True, "reason": "valid"}},
        }
        self.refs: dict[str, list[str]] = {
            BRANCH: [self.head, self.head],
            "main": [self.parent, self.parent],
        }
        self.lifecycle_runs = [
            {
                "id": LIFECYCLE_RUN_ID,
                "run_attempt": 1,
                "workflow_id": 340565782,
                "path": ci.COORDINATION_WORKFLOW_PATH,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": self.parent,
                "status": "completed",
                "conclusion": "success",
                "created_at": (NOW - timedelta(minutes=15)).isoformat(),
                "updated_at": (NOW - timedelta(minutes=10)).isoformat(),
                "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
            }
        ]
        self.parent_runs = [
            {
                "id": PARENT_RUN_ID,
                "run_attempt": 2,
                "workflow_id": ci.APPROVED_WORKFLOW_ID,
                "path": ci.APPROVED_WORKFLOW_PATH,
                "event": "push",
                "head_branch": "main",
                "head_sha": self.parent,
                "status": "completed",
                "conclusion": "success",
                "created_at": (NOW - timedelta(minutes=40)).isoformat(),
                "updated_at": (NOW - timedelta(minutes=20)).isoformat(),
                "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
            }
        ]
        self.start_runs = [
            {
                "id": START_RUN_ID,
                "run_attempt": 1,
                "workflow_id": ci.APPROVED_WORKFLOW_ID,
                "path": ci.APPROVED_WORKFLOW_PATH,
                "event": "push",
                "head_branch": BRANCH,
                "head_sha": self.head,
                "status": "in_progress",
                "conclusion": None,
                "actor": deepcopy(self.bot),
                "triggering_actor": deepcopy(self.bot),
                "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
            }
        ]
        self.jobs = [
            {
                "name": name,
                "status": "completed",
                "conclusion": "success",
                "run_id": PARENT_RUN_ID,
                "run_attempt": 2,
                "head_sha": self.parent,
            }
            for name in sorted(ci.REQUIRED_SOURCE_JOBS)
        ]
        self.attestation = coordination.build_start_attestation(
            result={
                "branch": BRANCH,
                "head_sha": self.head,
                "base_main_sha": self.parent,
            },
            ruleset=self.rules,
            expected_app_id=APP_ID,
            app_slug=APP_SLUG,
            repository=REPOSITORY,
            repository_id=REPOSITORY_ID,
            lifecycle_run_id=LIFECYCLE_RUN_ID,
            lifecycle_run_attempt=1,
        )
        self.archive, self.digest = _artifact(self.attestation)

    def ref_sha(self, ref_name: str) -> str:
        values = self.refs[ref_name]
        return values.pop(0) if len(values) > 1 else values[0]

    def workflow_definition(self, path: str) -> dict[str, Any]:
        assert path == ci.COORDINATION_WORKFLOW_PATH
        return {"id": 340565782, "path": path, "state": "active"}

    def workflow_runs(
        self, source_sha: str, event: str | None = "push"
    ) -> list[dict[str, Any]]:
        if source_sha == self.parent and event == "workflow_dispatch":
            return deepcopy(self.lifecycle_runs)
        if source_sha == self.parent and event == "push":
            return deepcopy(self.parent_runs)
        if source_sha == self.head and event == "push":
            return deepcopy(self.start_runs)
        return []

    def run_artifacts(self, run_id: int) -> list[dict[str, Any]]:
        assert run_id == LIFECYCLE_RUN_ID
        return [
            {
                "id": 601,
                "name": f"coordination-start-{LIFECYCLE_RUN_ID}-1",
                "expired": False,
                "digest": self.digest,
                "workflow_run": {
                    "id": LIFECYCLE_RUN_ID,
                    "repository_id": REPOSITORY_ID,
                    "head_repository_id": REPOSITORY_ID,
                    "head_branch": "main",
                    "head_sha": self.parent,
                },
            }
        ]

    def artifact_archive(self, artifact_id: int) -> bytes:
        assert artifact_id == 601
        return self.archive

    def run_attempt_jobs(self, run_id: int, attempt: int) -> list[dict[str, Any]]:
        assert (run_id, attempt) == (PARENT_RUN_ID, 2)
        return deepcopy(self.jobs)

    def github_app(self, slug: str) -> dict[str, Any]:
        assert slug == APP_SLUG
        return deepcopy(self.app)

    def user(self, login: str) -> dict[str, Any]:
        assert login == BOT_LOGIN
        return deepcopy(self.bot)

    def repository_commit(self, commit: str) -> dict[str, Any]:
        assert commit == self.head
        return deepcopy(self.commit)

    def ruleset(self, ruleset_id: int) -> dict[str, Any]:
        assert ruleset_id == RULESET_ID
        return {
            key: deepcopy(value)
            for key, value in self.rules.items()
            if key != "bypass_actors"
        }


class GitOverride:
    def __init__(self, delegate: Any, **overrides: Any) -> None:
        self.delegate = delegate
        self.overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name not in self.overrides:
            return getattr(self.delegate, name)
        override = self.overrides[name]
        return override if callable(override) else lambda *args: override


def _event(fixture: dict[str, Any], **changes: Any) -> Any:
    values = {
        "event_name": "push",
        "before_sha": ci.ZERO_SHA,
        "current_sha": fixture["head"],
        "ref": f"refs/heads/{BRANCH}",
        "forced": False,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
    }
    values.update(changes)
    return ci.CIEvent(**values)


def _classify(
    fixture: dict[str, Any],
    *,
    api: Any | None = None,
    git: Any | None = None,
    branch: str = BRANCH,
    event_changes: dict[str, Any] | None = None,
) -> Any:
    governance = governance_module.ProjectGovernance(1, "main", branch)
    return ci.classify_ci_mode(
        event=_event(fixture, **(event_changes or {})),
        git=git or fixture["git"],
        api=api or StartAPI(fixture),
        governance=governance,
        now=NOW,
    )


def test_exact_canonical_start_uses_lightweight_mode_and_gate(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    result = _classify(fixture)

    assert result.ci_mode == "coordination-start"
    assert result.comparison_base == fixture["parent"]
    assert result.source_run_id == str(PARENT_RUN_ID)
    gate_arguments = type(
        "Arguments",
        (),
        {
            "mode": "coordination-start",
            "classifier_result": "success",
            "lint_result": "skipped",
            "test_result": "skipped",
            "build_result": "skipped",
            "full_attestation_result": "skipped",
            "equivalent_result": "skipped",
            "docs_result": "skipped",
            "coordination_start_result": "success",
        },
    )()
    importlib.import_module("validate_ci_gate").validate_gate(gate_arguments)


def test_artifact_redirect_never_forwards_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = "https://artifact-storage.invalid/signed-download"
    headers = Message()
    headers["Location"] = location
    observed: list[Any] = []

    class Opener:
        def open(self, request: Any, timeout: float) -> Any:
            observed.append(("api", request, timeout))
            raise HTTPError(request.full_url, 302, "Found", headers, None)

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *arguments: object) -> None:
            return None

        def read(self) -> bytes:
            return b"archive"

    def unsigned_open(request: Any, timeout: float) -> Response:
        observed.append(("artifact", request, timeout))
        return Response()

    monkeypatch.setattr(ci, "build_opener", lambda handler: Opener())
    monkeypatch.setattr(ci, "urlopen", unsigned_open)
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository=REPOSITORY,
        token="secret-fixture-token",
    )

    assert api.artifact_archive(601) == b"archive"
    api_request = observed[0][1]
    artifact_request = observed[1][1]
    assert api_request.get_header("Authorization") == "Bearer secret-fixture-token"
    assert artifact_request.full_url == location
    assert artifact_request.get_header("Authorization") is None


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong-origin",
        "wrong-parent",
        "extra-parent",
        "main-advanced",
        "extra-file",
        "mode-drift",
        "parent-governance",
        "start-governance",
        "remote-ref-drift",
        "missing-lifecycle-artifact",
        "stale-lifecycle-evidence",
        "ambiguous-lifecycle-artifact",
        "missing-parent-full",
        "stale-parent-full",
        "ambiguous-parent-full",
        "missing-parent-job",
        "workflow-revision",
        "ruleset-unavailable",
        "ruleset-weakened",
    ),
)
def test_start_uncertainty_falls_back_to_full(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    api = StartAPI(fixture)
    git: Any = fixture["git"]
    if mutation == "wrong-origin":
        api.start_runs[0]["actor"]["id"] = BOT_ID + 1
    elif mutation == "wrong-parent":
        git = GitOverride(git, commit_object_parents=("f" * 40,))
    elif mutation == "extra-parent":
        git = GitOverride(git, commit_object_parents=(fixture["parent"], "f" * 40))
    elif mutation == "main-advanced":
        api.refs["main"] = ["f" * 40]
    elif mutation in {"extra-file", "mode-drift"}:
        original = git.tree_entries

        def changed_entries(commit: str) -> dict[str, tuple[str, str, str]]:
            entries = original(commit)
            if commit == fixture["head"]:
                if mutation == "extra-file":
                    entries["unexpected.txt"] = ("100644", "blob", "f" * 40)
                else:
                    _, kind, sha = entries["application.txt"]
                    entries["application.txt"] = ("120000", kind, sha)
            return entries

        git = GitOverride(git, tree_entries=changed_entries)
    elif mutation in {"parent-governance", "start-governance"}:
        original_blob = git.blob_bytes

        def governance_bytes(commit: str, path: str) -> bytes:
            if mutation == "parent-governance" and commit == fixture["parent"]:
                return _governance(BRANCH).encode()
            if mutation == "start-governance" and commit == fixture["head"]:
                return _governance("integration/wrong-ab12cd34").encode()
            return original_blob(commit, path)

        git = GitOverride(git, blob_bytes=governance_bytes)
    elif mutation == "remote-ref-drift":
        api.refs[BRANCH] = [fixture["head"], "f" * 40]
    elif mutation == "missing-lifecycle-artifact":
        api.run_artifacts = lambda run_id: (_ for _ in ()).throw(
            ci.ClassificationFailure("lifecycle artifact unavailable")
        )
    elif mutation == "stale-lifecycle-evidence":
        api.lifecycle_runs[0]["updated_at"] = (NOW - timedelta(hours=73)).isoformat()
    elif mutation == "ambiguous-lifecycle-artifact":
        original_artifacts = api.run_artifacts
        api.run_artifacts = lambda run_id: original_artifacts(run_id) * 2
    elif mutation == "missing-parent-full":
        api.parent_runs = []
    elif mutation == "stale-parent-full":
        api.parent_runs[0]["updated_at"] = (NOW - timedelta(hours=73)).isoformat()
    elif mutation == "ambiguous-parent-full":
        api.parent_runs.append(deepcopy(api.parent_runs[0]))
    elif mutation == "missing-parent-job":
        api.jobs = [job for job in api.jobs if job["name"] != "CI Gate"]
    elif mutation == "workflow-revision":
        original_blob_sha = git.blob_sha
        git = GitOverride(
            git,
            blob_sha=lambda commit, path: (
                "f" * 40
                if commit == fixture["head"]
                else original_blob_sha(commit, path)
            ),
        )
    elif mutation == "ruleset-unavailable":
        api.ruleset = lambda ruleset_id: (_ for _ in ()).throw(
            ci.ClassificationFailure("ruleset unavailable")
        )
    elif mutation == "ruleset-weakened":
        api.rules["rules"] = api.rules["rules"][:-1]

    result = _classify(fixture, api=api, git=git)

    assert result.ci_mode == "full"
    assert result.reason.startswith("coordination Start validation failed closed:")


@pytest.mark.parametrize(
    ("branch", "event_changes"),
    (
        ("integration/not-generated", {"ref": "refs/heads/integration/not-generated"}),
        (BRANCH, {"before_sha": "1" * 40}),
        (BRANCH, {"event_name": "pull_request"}),
        (BRANCH, {"forced": True}),
    ),
)
def test_noncanonical_start_event_falls_back_to_full(
    tmp_path: Path,
    branch: str,
    event_changes: dict[str, Any],
) -> None:
    fixture = _fixture(tmp_path)

    result = _classify(
        fixture,
        branch=branch,
        event_changes=event_changes,
    )

    assert result.ci_mode == "full"
