from __future__ import annotations

import importlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).parents[2]
MAIN_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "main.yml"
PR_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "pr.yml"
CI_SCRIPTS = REPOSITORY_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
ci = importlib.import_module("classify_ci_mode")
gate = importlib.import_module("validate_ci_gate")
project_governance = importlib.import_module("project_governance")

COORDINATION_BRANCH = "integration/current"
COORDINATION_REF = f"refs/heads/{COORDINATION_BRANCH}"
ACTIVE_COORDINATION_GOVERNANCE = project_governance.ProjectGovernance(
    schema_version=1,
    default_development_base="main",
    coordination_branch=COORDINATION_BRANCH,
)

NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
REPOSITORY_ID = 12345
REPOSITORY = "NTHU-Physics-SA-IT/PastExamWeb_PHY"


def _git(repository: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    )
    return process.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _equivalent_repository(tmp_path: Path) -> dict[str, Any]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "CI Fixture")
    _git(repository, "config", "user.email", "ci-fixture@example.invalid")

    workflow = repository / ".github" / "workflows" / "main.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: fixture\n", encoding="utf-8")
    (repository / "application.txt").write_text("base\n", encoding="utf-8")
    base = _commit(repository, "base")
    _git(repository, "update-ref", "refs/remotes/origin/main", base)

    _git(repository, "switch", "-c", "source")
    (repository / "application.txt").write_text("source\n", encoding="utf-8")
    source = _commit(repository, "source")

    _git(repository, "switch", "-c", "target", base)
    _git(repository, "merge", "--no-ff", source, "-m", "equivalent merge")
    merge = _git(repository, "rev-parse", "HEAD")
    return {
        "root": repository,
        "base": base,
        "source": source,
        "merge": merge,
        "git": ci.GitRepository(repository),
    }


def _jobs(*, overrides: dict[str, str] | None = None) -> list[dict[str, Any]]:
    overrides = overrides or {}
    return [
        {"name": name, "conclusion": overrides.get(name, "success")}
        for name in sorted(ci.REQUIRED_SOURCE_JOBS)
    ]


class FakeAPI:
    def __init__(
        self,
        *,
        source_sha: str,
        target_sha: str,
        runs: list[dict[str, Any]] | None = None,
        jobs: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
        target_ref: str = "target",
    ) -> None:
        self.source_sha = source_sha
        self.target_sha = target_sha
        self.target_ref = target_ref
        self.error = error
        self.runs = runs or [
            {
                "id": 9001,
                "head_sha": source_sha,
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "path": ci.APPROVED_WORKFLOW_PATH,
                "workflow_id": ci.APPROVED_WORKFLOW_ID,
                "repository": {"id": REPOSITORY_ID},
                "run_attempt": 1,
                "updated_at": (NOW - timedelta(hours=1)).isoformat(),
            }
        ]
        self.jobs = jobs or _jobs()

    def workflow_runs(self, source_sha: str) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        assert source_sha == self.source_sha
        return deepcopy(self.runs)

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        assert run_id == 9001
        return deepcopy(self.jobs)

    def ref_sha(self, ref_name: str) -> str:
        if self.error:
            raise self.error
        assert ref_name == self.target_ref
        return self.target_sha


class FakePRAPI(FakeAPI):
    def __init__(
        self,
        fixture: dict[str, Any],
        *,
        pull_request_changes: dict[str, Any] | None = None,
        ref_overrides: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(
            source_sha=fixture["source"],
            target_sha=fixture["merge"],
            error=error,
        )
        self.refs = {
            COORDINATION_BRANCH: fixture["base"],
            "source": fixture["source"],
        }
        self.refs.update(ref_overrides or {})
        self.pull_request_payload = {
            "number": 17,
            "state": "open",
            "draft": False,
            "mergeable": True,
            "merge_commit_sha": fixture["merge"],
            "base": {
                "ref": COORDINATION_BRANCH,
                "sha": fixture["base"],
                "repo": {
                    "id": REPOSITORY_ID,
                    "full_name": REPOSITORY,
                },
            },
            "head": {
                "ref": "source",
                "sha": fixture["source"],
                "repo": {
                    "id": REPOSITORY_ID,
                    "full_name": REPOSITORY,
                },
            },
        }
        self.pull_request_payload.update(pull_request_changes or {})

    def ref_sha(self, ref_name: str) -> str:
        if self.error:
            raise self.error
        return self.refs[ref_name]

    def pull_request(self, number: int) -> dict[str, Any]:
        if self.error:
            raise self.error
        assert number == 17
        return deepcopy(self.pull_request_payload)


class GitOverrides:
    def __init__(self, delegate: Any, **overrides: Any) -> None:
        self.delegate = delegate
        self.overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name not in self.overrides:
            return getattr(self.delegate, name)
        value = self.overrides[name]
        if callable(value):
            return value
        return lambda *arguments: value


class ScopeGit:
    def __init__(self, paths: tuple[str, ...], *, fail: bool = False) -> None:
        self.paths = paths
        self.fail = fail

    def merge_base(self, left: str, right: str) -> str:
        if self.fail:
            raise subprocess.CalledProcessError(1, ["git", "merge-base"])
        return "1" * 40

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        return self.paths


def _event(fixture: dict[str, Any], **changes: Any) -> Any:
    values = {
        "event_name": "push",
        "before_sha": fixture["base"],
        "current_sha": fixture["merge"],
        "ref": "refs/heads/target",
        "forced": False,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
    }
    values.update(changes)
    return ci.CIEvent(**values)


def _classify_equivalent(
    fixture: dict[str, Any],
    *,
    event_changes: dict[str, Any] | None = None,
    git: Any | None = None,
    api: Any | None = None,
) -> Any:
    return ci.classify_ci_mode(
        event=_event(fixture, **(event_changes or {})),
        git=git or fixture["git"],
        api=api or FakeAPI(source_sha=fixture["source"], target_sha=fixture["merge"]),
        governance=ACTIVE_COORDINATION_GOVERNANCE,
        equivalent_allowlist=frozenset({"refs/heads/target"}),
        now=NOW,
    )


def _pr_event(fixture: dict[str, Any], **changes: Any) -> Any:
    values = {
        "event_name": "pull_request",
        "before_sha": "",
        "current_sha": fixture["merge"],
        "ref": "refs/pull/17/merge",
        "forced": False,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "action": "synchronize",
        "pr_number": 17,
        "draft": False,
        "base_ref": COORDINATION_BRANCH,
        "base_sha": fixture["base"],
        "head_ref": "source",
        "head_sha": fixture["source"],
        "head_repository": REPOSITORY,
        "head_repository_id": REPOSITORY_ID,
    }
    values.update(changes)
    return ci.CIEvent(**values)


def _classify_pr_equivalent(
    fixture: dict[str, Any],
    *,
    event_changes: dict[str, Any] | None = None,
    git: Any | None = None,
    api: Any | None = None,
) -> Any:
    return ci.classify_ci_mode(
        event=_pr_event(fixture, **(event_changes or {})),
        git=git or fixture["git"],
        api=api or FakePRAPI(fixture),
        governance=ACTIVE_COORDINATION_GOVERNANCE,
        pr_equivalent_allowlist=frozenset({COORDINATION_BRANCH}),
        now=NOW,
    )


def test_classifier_defines_modes_and_resolves_exact_authority() -> None:
    assert ci.CI_MODES == frozenset(
        {"full", "equivalent-merge", "docs-only", "coordination-start"}
    )
    assert COORDINATION_REF == f"refs/heads/{COORDINATION_BRANCH}"
    assert all(token not in COORDINATION_BRANCH for token in ("*", "?", "["))
    source = (CI_SCRIPTS / "classify_ci_mode.py").read_text(encoding="utf-8")
    assert COORDINATION_BRANCH not in source
    assert "load_project_governance" in source


def test_backend_shards_and_combined_coverage_are_required_authority() -> None:
    backend_jobs = {
        "test / backend-shard-a",
        "test / backend-shard-b",
        "test / backend-coverage",
    }

    assert backend_jobs <= ci.REQUIRED_SOURCE_JOBS
    assert backend_jobs <= gate.REQUIRED_EXECUTION_JOBS
    assert "test / backend" not in ci.REQUIRED_SOURCE_JOBS
    assert "test / backend" not in gate.REQUIRED_EXECUTION_JOBS


def test_e2e_families_and_aggregate_are_required_authority() -> None:
    e2e_jobs = {
        "test / frontend-e2e-chromium",
        "test / frontend-e2e-firefox",
        "test / frontend-e2e-webkit",
        "test / frontend-e2e",
    }

    assert e2e_jobs <= ci.REQUIRED_SOURCE_JOBS
    assert e2e_jobs <= gate.REQUIRED_EXECUTION_JOBS


@pytest.mark.parametrize(
    ("ref", "paths", "expected"),
    (
        ("refs/heads/topic", ("backend/app/main.py",), "full"),
        ("refs/heads/topic", ("docs/guide.md", "README.md"), "docs-only"),
        ("refs/heads/topic", (".github/CODEOWNERS",), "docs-only"),
        (
            "refs/heads/topic",
            (".github/CODEOWNERS", "docs/guide.md"),
            "docs-only",
        ),
        (
            "refs/heads/topic",
            (".github/CODEOWNERS", "README.md"),
            "docs-only",
        ),
        (
            "refs/heads/topic",
            (".github/CODEOWNERS", "backend/app/main.py"),
            "full",
        ),
        (
            "refs/heads/topic",
            (".github/CODEOWNERS", ".github/workflows/main.yml"),
            "full",
        ),
        (
            "refs/heads/topic",
            (".github/CODEOWNERS", "scripts/ci/helper.py"),
            "full",
        ),
        ("refs/heads/main", (".github/CODEOWNERS",), "full"),
        ("refs/heads/release/v1", (".github/CODEOWNERS",), "full"),
        ("refs/heads/production/stable", (".github/CODEOWNERS",), "full"),
        (
            "refs/heads/hotfix/production/db",
            (".github/CODEOWNERS",),
            "full",
        ),
        ("refs/heads/main", ("docs/guide.md",), "full"),
        ("refs/heads/main", ("backend/app/main.py",), "full"),
        (COORDINATION_REF, ("docs/guide.md",), "full"),
        ("refs/heads/release/v1", ("docs/guide.md",), "full"),
        ("refs/heads/production/stable", ("docs/guide.md",), "full"),
        ("refs/heads/hotfix/production/db", ("docs/guide.md",), "full"),
        ("refs/heads/topic", (".github/workflows/main.yml",), "full"),
        ("refs/heads/topic", (".github/project-governance.json",), "full"),
        (
            "refs/heads/topic",
            (".github/trusted-activation/claim.json",),
            "full",
        ),
        ("refs/heads/topic", ("scripts/ci/helper.py",), "full"),
        ("refs/heads/topic", ("backend/Dockerfile",), "full"),
        ("refs/heads/topic", ("frontend/pnpm-lock.yaml",), "full"),
        ("refs/heads/topic", ("backend/alembic/versions/x.py",), "full"),
    ),
)
def test_mode_priority(ref: str, paths: tuple[str, ...], expected: str) -> None:
    event = ci.CIEvent(
        event_name="push",
        before_sha="1" * 40,
        current_sha="2" * 40,
        ref=ref,
        forced=False,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
    )
    result = ci.classify_ci_mode(
        event=event,
        git=ScopeGit(paths),
        governance=ACTIVE_COORDINATION_GOVERNANCE,
    )

    assert result.ci_mode == expected


def test_comparison_error_falls_back_to_full() -> None:
    event = ci.CIEvent(
        event_name="push",
        before_sha="1" * 40,
        current_sha="2" * 40,
        ref="refs/heads/topic",
        forced=False,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
    )
    result = ci.classify_ci_mode(
        event=event,
        git=ScopeGit(("docs/guide.md",), fail=True),
    )

    assert result.ci_mode == "full"


def test_comparison_ref_refresh_failure_falls_back_to_full() -> None:
    event = ci.CIEvent(
        event_name="push",
        before_sha="1" * 40,
        current_sha="2" * 40,
        ref="refs/heads/topic",
        forced=False,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        comparison_ref_ready=False,
    )
    result = ci.classify_ci_mode(
        event=event,
        git=ScopeGit(("docs/guide.md",)),
    )

    assert result.ci_mode == "full"


def test_project_governance_resolution_failure_falls_back_to_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_closed() -> None:
        raise project_governance.GovernanceConfigError("missing canonical config")

    monkeypatch.setattr(ci, "load_project_governance", fail_closed)
    event = ci.CIEvent(
        event_name="push",
        before_sha="1" * 40,
        current_sha="2" * 40,
        ref="refs/heads/topic",
        forced=False,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
    )

    result = ci.classify_ci_mode(event=event, git=ScopeGit(("docs/guide.md",)))

    assert result.ci_mode == "full"
    assert result.reason.startswith("project governance failed closed:")


def test_null_governance_grants_no_coordination_or_equivalent_privilege(
    tmp_path: Path,
) -> None:
    fixture = _equivalent_repository(tmp_path)
    null_governance = project_governance.ProjectGovernance(
        schema_version=1,
        default_development_base="main",
        coordination_branch=None,
    )

    pull_request_result = ci.classify_ci_mode(
        event=_pr_event(fixture),
        git=fixture["git"],
        api=FakePRAPI(fixture),
        governance=null_governance,
        now=NOW,
    )
    push_result = ci.classify_ci_mode(
        event=_event(fixture, ref=COORDINATION_REF),
        git=GitOverrides(fixture["git"], changed_paths=("docs/guide.md",)),
        api=FakeAPI(
            source_sha=fixture["source"],
            target_sha=fixture["merge"],
            target_ref=COORDINATION_BRANCH,
        ),
        governance=null_governance,
        now=NOW,
    )

    assert pull_request_result.ci_mode == "full"
    assert pull_request_result.reason == (
        "unapproved pull request base falls back to full CI"
    )
    assert push_result.ci_mode == "docs-only"
    assert push_result.reason == "all changed paths are documentation-only"


def test_simplified_coordination_is_full_only_without_candidate_authority(
    tmp_path: Path,
) -> None:
    fixture = _equivalent_repository(tmp_path)
    result = ci.classify_ci_mode(
        event=_pr_event(fixture),
        git=fixture["git"],
        api=FakePRAPI(fixture),
        governance=ACTIVE_COORDINATION_GOVERNANCE,
        now=NOW,
    )

    assert result.ci_mode == "full"
    assert result.reason == "simplified protected coordination is Full-only"


def test_valid_two_parent_equivalent_merge_is_eligible(tmp_path: Path) -> None:
    fixture = _equivalent_repository(tmp_path)

    result = _classify_equivalent(fixture)

    assert result.ci_mode == "equivalent-merge"
    assert result.source_sha == fixture["source"]
    assert result.source_run_id == "9001"
    assert result.source_tree == fixture["git"].tree_sha(fixture["source"])


def test_non_case_b_coordination_push_remains_full(
    tmp_path: Path,
) -> None:
    fixture = _equivalent_repository(tmp_path)

    result = ci.classify_ci_mode(
        event=_event(
            fixture,
            ref=COORDINATION_REF,
        ),
        git=fixture["git"],
        api=FakeAPI(
            source_sha=fixture["source"],
            target_sha=fixture["merge"],
            target_ref=COORDINATION_BRANCH,
        ),
        governance=ACTIVE_COORDINATION_GOVERNANCE,
        now=NOW,
    )

    assert result.ci_mode == "full"
    assert result.reason == (
        "protected coordination after Start, including Case-B postmerge, is Full-only"
    )


def test_explicit_pr_equivalent_allowlist_cannot_override_full_only(
    tmp_path: Path,
) -> None:
    fixture = _equivalent_repository(tmp_path)

    result = _classify_pr_equivalent(fixture)

    assert result.ci_mode == "full"
    assert result.reason == "simplified protected coordination is Full-only"


def test_live_coordination_pr_is_full_only(
    tmp_path: Path,
) -> None:
    fixture = _equivalent_repository(tmp_path)
    api = FakePRAPI(
        fixture,
        ref_overrides={COORDINATION_BRANCH: fixture["base"]},
    )
    api.pull_request_payload["base"]["ref"] = COORDINATION_BRANCH

    result = ci.classify_ci_mode(
        event=_pr_event(fixture, base_ref=COORDINATION_BRANCH),
        git=fixture["git"],
        api=api,
        governance=ACTIVE_COORDINATION_GOVERNANCE,
        now=NOW,
    )

    assert result.ci_mode == "full"
    assert result.reason == "simplified protected coordination is Full-only"


def test_live_push_governance_merge_falls_back_to_full(
    tmp_path: Path,
) -> None:
    fixture = _equivalent_repository(tmp_path)
    git = GitOverrides(
        fixture["git"],
        changed_paths=("scripts/ci/classify_ci_mode.py",),
    )
    api = FakeAPI(
        source_sha=fixture["source"],
        target_sha=fixture["merge"],
        target_ref=COORDINATION_BRANCH,
    )

    result = ci.classify_ci_mode(
        event=_event(
            fixture,
            ref=COORDINATION_REF,
        ),
        git=git,
        api=api,
        governance=ACTIVE_COORDINATION_GOVERNANCE,
        now=NOW,
    )

    assert result.ci_mode == "full"
    assert result.reason == (
        "protected coordination after Start, including Case-B postmerge, is Full-only"
    )


def test_pr_governance_change_requires_full_before_allowlist(
    tmp_path: Path,
) -> None:
    fixture = _equivalent_repository(tmp_path)
    git = GitOverrides(
        fixture["git"],
        changed_paths=(".github/workflows/main.yml",),
    )

    result = ci.classify_ci_mode(
        event=_pr_event(fixture),
        git=git,
        api=FakePRAPI(fixture),
        governance=ACTIVE_COORDINATION_GOVERNANCE,
        pr_equivalent_allowlist=frozenset({COORDINATION_BRANCH}),
        now=NOW,
    )

    assert result.ci_mode == "full"
    assert result.reason == "simplified protected coordination is Full-only"


@pytest.mark.parametrize(
    "paths",
    (
        ("README.md",),
        ("README.md", "CONTRIBUTING.md", "LICENSE"),
        ("docs/guide.md", "docs/screenshots/example.png"),
        (".github/CODEOWNERS",),
    ),
)
def test_main_pr_lightweight_changes_use_docs_only(
    tmp_path: Path,
    paths: tuple[str, ...],
) -> None:
    fixture = _equivalent_repository(tmp_path)

    result = _classify_pr_equivalent(
        fixture,
        event_changes={
            "base_ref": "main",
            "ref": "refs/pull/17/merge",
        },
        git=GitOverrides(fixture["git"], changed_paths=paths),
    )

    assert result.ci_mode == "docs-only"
    assert result.reason == "all pull request paths are documentation-only"
    assert result.comparison_base == fixture["base"]


@pytest.mark.parametrize(
    "paths",
    (
        ("README.md", "frontend/src/main.ts"),
        ("README.md", "backend/app/main.py"),
        (".github/workflows/main.yml",),
        ("scripts/ci/classify_ci_mode.py",),
        ("frontend/pnpm-lock.yaml",),
        ("backend/alembic/versions/example.py",),
        ("docker/docker-compose.dev.yml",),
        ("notes/guide.md",),
    ),
)
def test_main_pr_non_lightweight_changes_remain_full(
    tmp_path: Path,
    paths: tuple[str, ...],
) -> None:
    fixture = _equivalent_repository(tmp_path)

    result = _classify_pr_equivalent(
        fixture,
        event_changes={
            "base_ref": "main",
            "ref": "refs/pull/17/merge",
        },
        git=GitOverrides(
            fixture["git"],
            changed_paths=paths,
        ),
    )

    assert result.ci_mode == "full"


@pytest.mark.parametrize(
    ("event_changes", "git_overrides"),
    (
        ({"action": "closed"}, {}),
        ({"pr_number": 0}, {}),
        ({"ref": "refs/heads/source"}, {}),
        ({"current_sha": "bad"}, {}),
        ({"base_sha": "bad"}, {}),
        ({"head_sha": "bad"}, {}),
        ({"head_ref": ""}, {}),
        ({"head_repository": ""}, {}),
        ({"head_repository_id": 0}, {}),
        ({}, {"parents": ("1" * 40,)}),
        ({}, {"parents": ("1" * 40, "2" * 40)}),
    ),
)
def test_main_pr_incomplete_identity_fails_closed(
    tmp_path: Path,
    event_changes: dict[str, Any],
    git_overrides: dict[str, Any],
) -> None:
    fixture = _equivalent_repository(tmp_path)
    adjusted = dict(git_overrides)
    if "parents" in adjusted:
        parents = adjusted["parents"]
        adjusted["parents"] = (
            (fixture["base"],) if len(parents) == 1 else (fixture["base"], "2" * 40)
        )

    result = _classify_pr_equivalent(
        fixture,
        event_changes={"base_ref": "main", **event_changes},
        git=GitOverrides(
            fixture["git"],
            changed_paths=("README.md",),
            **adjusted,
        ),
    )

    assert result.ci_mode == "full"
    assert "failed closed" in result.reason


@pytest.mark.parametrize(
    ("event_changes", "git_overrides"),
    (
        ({"action": "closed"}, {}),
        ({"draft": True}, {}),
        ({"pr_number": 0}, {}),
        ({"base_ref": "topic"}, {}),
        ({"ref": "refs/heads/source"}, {}),
        ({"head_repository": "other/repository"}, {}),
        ({"head_repository_id": 999}, {}),
        ({"base_sha": "bad"}, {}),
        ({"head_sha": "bad"}, {}),
        ({}, {"parents": ("1" * 40,)}),
        ({}, {"parents": ("1" * 40, "2" * 40)}),
        ({}, {"parents": ("1" * 40, "2" * 40, "3" * 40)}),
        ({}, {"is_ancestor": False}),
        ({}, {"trees_are_equal": False}),
        ({}, {"diff_is_empty": False}),
        ({}, {"changed_paths": (".github/workflows/main.yml",)}),
    ),
)
def test_pr_candidate_event_topology_and_governance_fail_closed(
    tmp_path: Path,
    event_changes: dict[str, Any],
    git_overrides: dict[str, Any],
) -> None:
    fixture = _equivalent_repository(tmp_path)
    adjusted = dict(git_overrides)
    if "parents" in adjusted:
        parents = adjusted["parents"]
        if len(parents) == 1:
            adjusted["parents"] = (fixture["base"],)
        elif len(parents) == 2:
            adjusted["parents"] = (fixture["base"], "f" * 40)
        else:
            adjusted["parents"] = (
                fixture["base"],
                fixture["source"],
                "3" * 40,
            )

    result = _classify_pr_equivalent(
        fixture,
        event_changes=event_changes,
        git=GitOverrides(fixture["git"], **adjusted),
    )

    assert result.ci_mode == "full"


@pytest.mark.parametrize(
    "pull_request_changes",
    (
        {"state": "closed"},
        {"draft": True},
        {"mergeable": False},
        {"mergeable": None},
        {"merge_commit_sha": "f" * 40},
        {"base": {}},
        {"head": {}},
        {"base": {"ref": "topic", "sha": "1" * 40, "repo": {}}},
        {"head": {"ref": "source", "sha": "2" * 40, "repo": {}}},
    ),
)
def test_pr_api_metadata_mismatch_falls_back(
    tmp_path: Path,
    pull_request_changes: dict[str, Any],
) -> None:
    fixture = _equivalent_repository(tmp_path)
    api = FakePRAPI(fixture, pull_request_changes=pull_request_changes)

    assert _classify_pr_equivalent(fixture, api=api).ci_mode == "full"


def test_pr_base_or_head_advance_falls_back(tmp_path: Path) -> None:
    fixture = _equivalent_repository(tmp_path)
    base_advanced = FakePRAPI(
        fixture,
        ref_overrides={COORDINATION_BRANCH: "f" * 40},
    )
    head_advanced = FakePRAPI(
        fixture,
        ref_overrides={"source": "f" * 40},
    )

    assert _classify_pr_equivalent(fixture, api=base_advanced).ci_mode == "full"
    assert _classify_pr_equivalent(fixture, api=head_advanced).ci_mode == "full"


@pytest.mark.parametrize(
    ("run_change", "job_overrides"),
    (
        ({"conclusion": "failure"}, {}),
        ({"updated_at": (NOW - timedelta(hours=73)).isoformat()}, {}),
        ({}, {"Full CI Attestation": "skipped"}),
        ({}, {"CI Gate": "cancelled"}),
    ),
)
def test_pr_source_attestation_must_be_exact_fresh_and_full(
    tmp_path: Path,
    run_change: dict[str, Any],
    job_overrides: dict[str, str],
) -> None:
    fixture = _equivalent_repository(tmp_path)
    api = FakePRAPI(fixture)
    api.runs[0].update(run_change)
    api.jobs = _jobs(overrides=job_overrides)

    assert _classify_pr_equivalent(fixture, api=api).ci_mode == "full"


@pytest.mark.parametrize(
    "error",
    (
        ci.ClassificationFailure("HTTP 401"),
        ci.ClassificationFailure("HTTP 403"),
        ci.ClassificationFailure("HTTP 404"),
        ci.ClassificationFailure("HTTP 500"),
        ci.ClassificationFailure("rate limit"),
        ci.ClassificationFailure("timeout"),
        ci.ClassificationFailure("malformed JSON"),
    ),
)
def test_pr_api_failures_fall_back(
    tmp_path: Path,
    error: Exception,
) -> None:
    fixture = _equivalent_repository(tmp_path)

    assert (
        _classify_pr_equivalent(
            fixture,
            api=FakePRAPI(fixture, error=error),
        ).ci_mode
        == "full"
    )


@pytest.mark.parametrize(
    ("event_changes", "git_overrides"),
    (
        ({"event_name": "workflow_dispatch"}, {}),
        ({"before_sha": "0" * 40}, {}),
        ({"forced": True}, {}),
        ({"before_sha": "2" * 40}, {}),
        ({}, {"parents": ("1" * 40,)}),
        ({}, {"parents": ("1" * 40, "2" * 40, "3" * 40)}),
        ({}, {"first_parent_count": 2}),
        ({}, {"is_ancestor": False}),
        ({}, {"trees_are_equal": False}),
        ({}, {"diff_is_empty": False}),
        ({}, {"changed_paths": (".github/workflows/main.yml",)}),
    ),
)
def test_topology_tree_and_governance_fail_closed(
    tmp_path: Path,
    event_changes: dict[str, Any],
    git_overrides: dict[str, Any],
) -> None:
    fixture = _equivalent_repository(tmp_path)
    adjusted = dict(git_overrides)
    if "parents" in adjusted:
        parents = adjusted["parents"]
        if len(parents) == 1:
            adjusted["parents"] = (fixture["base"],)
        else:
            adjusted["parents"] = (
                fixture["base"],
                fixture["source"],
                "3" * 40,
            )
    git = GitOverrides(fixture["git"], **adjusted)

    assert (
        _classify_equivalent(
            fixture,
            event_changes=event_changes,
            git=git,
        ).ci_mode
        == "full"
    )


def test_target_advance_falls_back_to_full(tmp_path: Path) -> None:
    fixture = _equivalent_repository(tmp_path)
    api = FakeAPI(source_sha=fixture["source"], target_sha="f" * 40)

    assert _classify_equivalent(fixture, api=api).ci_mode == "full"


@pytest.mark.parametrize(
    "error",
    (
        ci.ClassificationFailure("HTTP 401"),
        ci.ClassificationFailure("HTTP 403"),
        ci.ClassificationFailure("HTTP 404"),
        ci.ClassificationFailure("HTTP 500"),
        ci.ClassificationFailure("rate limit"),
        ci.ClassificationFailure("timeout"),
        ci.ClassificationFailure("malformed JSON"),
        ci.ClassificationFailure("pagination incomplete"),
    ),
)
def test_api_failures_fall_back_to_full(tmp_path: Path, error: Exception) -> None:
    fixture = _equivalent_repository(tmp_path)
    api = FakeAPI(
        source_sha=fixture["source"],
        target_sha=fixture["merge"],
        error=error,
    )

    assert _classify_equivalent(fixture, api=api).ci_mode == "full"


def test_actions_api_rejects_incomplete_pagination() -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository=REPOSITORY,
        token="fixture-token",
    )
    api._get = lambda url: (  # type: ignore[method-assign]
        {"total_count": 2, "workflow_runs": [{"id": 1}]},
        "",
    )

    with pytest.raises(ci.ClassificationFailure, match="incomplete"):
        api.workflow_runs("a" * 40)


def test_actions_api_never_follows_pagination_off_github_origin() -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository=REPOSITORY,
        token="fixture-token",
    )
    api._get = lambda url: (  # type: ignore[method-assign]
        {"total_count": 1, "workflow_runs": [{"id": 1}]},
        '<https://attacker.invalid/page/2>; rel="next"',
    )

    with pytest.raises(ci.ClassificationFailure, match="approved API origin"):
        api.workflow_runs("a" * 40)


def test_actions_api_downloads_exact_job_log() -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository=REPOSITORY,
        token="fixture-token",
    )
    observed: list[str] = []

    def get_bytes(url: str) -> bytes:
        observed.append(url)
        return b"job-log"

    api._get_bytes = get_bytes  # type: ignore[method-assign]

    assert api.job_log(123) == b"job-log"
    assert observed == [
        f"https://api.github.invalid/repos/{REPOSITORY}/actions/jobs/123/logs"
    ]


@pytest.mark.parametrize(
    ("run_change", "job_overrides"),
    (
        ({"head_sha": "f" * 40}, {}),
        ({"event": "workflow_dispatch"}, {}),
        ({"conclusion": "failure"}, {}),
        ({"path": ".github/workflows/other.yml"}, {}),
        ({"workflow_id": 999}, {}),
        ({"repository": {"id": 999}}, {}),
        ({"updated_at": (NOW - timedelta(hours=73)).isoformat()}, {}),
        ({}, {"Full CI Attestation": "skipped"}),
        ({}, {"Full CI Attestation": "neutral"}),
        ({}, {"Full CI Attestation": "cancelled"}),
        ({}, {"test / backend-shard-a": "failure"}),
    ),
)
def test_source_run_mismatch_failure_or_nonfull_mode_falls_back(
    tmp_path: Path,
    run_change: dict[str, Any],
    job_overrides: dict[str, str],
) -> None:
    fixture = _equivalent_repository(tmp_path)
    base_api = FakeAPI(source_sha=fixture["source"], target_sha=fixture["merge"])
    run = deepcopy(base_api.runs[0])
    run.update(run_change)
    api = FakeAPI(
        source_sha=fixture["source"],
        target_sha=fixture["merge"],
        runs=[run],
        jobs=_jobs(overrides=job_overrides),
    )

    assert _classify_equivalent(fixture, api=api).ci_mode == "full"


@pytest.mark.parametrize(
    "job_name",
    (
        "test / backend-shard-a",
        "test / backend-shard-b",
        "test / backend-coverage",
    ),
)
def test_equivalent_requires_each_backend_shard_and_coverage_job(
    tmp_path: Path,
    job_name: str,
) -> None:
    fixture = _equivalent_repository(tmp_path)
    api = FakeAPI(
        source_sha=fixture["source"],
        target_sha=fixture["merge"],
        jobs=_jobs(overrides={job_name: "failure"}),
    )

    assert _classify_equivalent(fixture, api=api).ci_mode == "full"


def test_missing_attestation_and_ambiguous_runs_fall_back(tmp_path: Path) -> None:
    fixture = _equivalent_repository(tmp_path)
    base_api = FakeAPI(source_sha=fixture["source"], target_sha=fixture["merge"])
    missing = [job for job in base_api.jobs if job["name"] != "Full CI Attestation"]
    missing_api = FakeAPI(
        source_sha=fixture["source"],
        target_sha=fixture["merge"],
        jobs=missing,
    )
    ambiguous_api = FakeAPI(
        source_sha=fixture["source"],
        target_sha=fixture["merge"],
        runs=[base_api.runs[0], deepcopy(base_api.runs[0])],
    )

    assert _classify_equivalent(fixture, api=missing_api).ci_mode == "full"
    assert _classify_equivalent(fixture, api=ambiguous_api).ci_mode == "full"


def test_workflow_revision_mismatch_falls_back(tmp_path: Path) -> None:
    fixture = _equivalent_repository(tmp_path)
    git = GitOverrides(
        fixture["git"],
        blob_sha=lambda commit, path: (
            "a" * 40 if commit == fixture["source"] else "b" * 40
        ),
    )

    result = _classify_equivalent(
        fixture,
        git=git,
    )

    assert result.ci_mode == "full"


VALID_GATE_RESULTS = {
    "full": {
        "classifier_result": "success",
        "lint_result": "success",
        "test_result": "success",
        "build_result": "success",
        "full_attestation_result": "success",
        "equivalent_result": "skipped",
        "docs_result": "skipped",
        "coordination_start_result": "skipped",
    },
    "equivalent-merge": {
        "classifier_result": "success",
        "lint_result": "skipped",
        "test_result": "skipped",
        "build_result": "skipped",
        "full_attestation_result": "skipped",
        "equivalent_result": "success",
        "docs_result": "skipped",
        "coordination_start_result": "skipped",
    },
    "docs-only": {
        "classifier_result": "success",
        "lint_result": "skipped",
        "test_result": "skipped",
        "build_result": "skipped",
        "full_attestation_result": "skipped",
        "equivalent_result": "skipped",
        "docs_result": "success",
        "coordination_start_result": "skipped",
    },
    "coordination-start": {
        "classifier_result": "success",
        "lint_result": "skipped",
        "test_result": "skipped",
        "build_result": "skipped",
        "full_attestation_result": "skipped",
        "equivalent_result": "skipped",
        "docs_result": "skipped",
        "coordination_start_result": "success",
    },
}


def _gate_arguments(
    mode: str,
    **overrides: str,
) -> Any:
    values = dict(VALID_GATE_RESULTS.get(mode, VALID_GATE_RESULTS["full"]))
    values.update(overrides)
    return type("Arguments", (), {"mode": mode, **values})()


@pytest.mark.parametrize(
    "mode", ("full", "equivalent-merge", "docs-only", "coordination-start")
)
def test_ci_gate_accepts_exact_mode_result_matrix(mode: str) -> None:
    gate.validate_gate(_gate_arguments(mode))


@pytest.mark.parametrize(
    ("mode", "result_name", "unexpected"),
    (
        ("full", "lint_result", "skipped"),
        ("full", "full_attestation_result", "skipped"),
        ("full", "equivalent_result", "success"),
        ("full", "docs_result", "success"),
        ("equivalent-merge", "lint_result", "success"),
        ("equivalent-merge", "equivalent_result", "skipped"),
        ("equivalent-merge", "equivalent_result", "failure"),
        ("equivalent-merge", "equivalent_result", "cancelled"),
        ("equivalent-merge", "full_attestation_result", "success"),
        ("equivalent-merge", "docs_result", "success"),
        ("docs-only", "lint_result", "success"),
        ("docs-only", "docs_result", "skipped"),
        ("docs-only", "equivalent_result", "success"),
        ("docs-only", "full_attestation_result", "success"),
        ("coordination-start", "coordination_start_result", "failure"),
        ("coordination-start", "coordination_start_result", "cancelled"),
        ("coordination-start", "coordination_start_result", "skipped"),
    ),
)
def test_ci_gate_rejects_mode_result_mismatch(
    mode: str,
    result_name: str,
    unexpected: str,
) -> None:
    with pytest.raises(RuntimeError, match=mode):
        gate.validate_gate(_gate_arguments(mode, **{result_name: unexpected}))


@pytest.mark.parametrize("unexpected", ("cancelled", "failure", "neutral"))
def test_ci_gate_rejects_nonterminal_or_failed_result(unexpected: str) -> None:
    with pytest.raises(RuntimeError, match="lint workflow"):
        gate.validate_gate(_gate_arguments("full", lint_result=unexpected))


def test_ci_gate_rejects_unknown_mode() -> None:
    with pytest.raises(RuntimeError, match="unsupported CI mode"):
        gate.validate_gate(_gate_arguments("unknown"))


def test_ci_gate_rejects_missing_result() -> None:
    arguments = _gate_arguments("full")
    delattr(arguments.__class__, "lint_result")

    with pytest.raises(RuntimeError, match="missing result.*lint workflow"):
        gate.validate_gate(arguments)


def test_ci_gate_rejects_malformed_result() -> None:
    with pytest.raises(RuntimeError, match="classifier"):
        gate.validate_gate(_gate_arguments("full", classifier_result=""))


def test_full_attestation_checks_each_required_execution_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _equivalent_repository(tmp_path)

    class CurrentRunAPI:
        def __init__(self, **arguments: Any) -> None:
            pass

        def workflow_run(self, run_id: int) -> dict[str, Any]:
            assert run_id == 77
            return {
                "id": 77,
                "run_attempt": 2,
                "event": "push",
                "head_sha": fixture["merge"],
            }

        def run_attempt_jobs(
            self,
            run_id: int,
            run_attempt: int,
        ) -> list[dict[str, Any]]:
            assert run_id == 77
            assert run_attempt == 2
            return [
                {
                    "name": name,
                    "status": "completed",
                    "conclusion": "success",
                    "run_id": 77,
                    "run_attempt": 2,
                    "head_sha": fixture["merge"],
                }
                for name in gate.REQUIRED_EXECUTION_JOBS
            ]

    monkeypatch.setattr(gate, "GitHubActionsAPI", CurrentRunAPI)
    output = tmp_path / "github-output"
    arguments = type(
        "Arguments",
        (),
        {
            "mode": "full",
            "classifier_result": "success",
            "lint_result": "success",
            "test_result": "success",
            "build_result": "success",
            "api_url": "https://api.github.invalid",
            "repository": REPOSITORY,
            "run_id": 77,
            "run_attempt": 2,
            "event_name": "push",
            "attested_sha": fixture["merge"],
            "execution_head_sha": fixture["merge"],
            "pr_number": 0,
            "base_ref": "",
            "repository_root": fixture["root"],
            "github_output": output,
        },
    )()

    gate.attest_full_ci(arguments)

    evidence = output.read_text(encoding="utf-8")
    assert "mode=full" in evidence
    assert f"sha={fixture['merge']}" in evidence
    assert "workflow_revision=" in evidence


@pytest.mark.parametrize(
    ("job_name", "evidence_state"),
    tuple(
        (job_name, evidence_state)
        for job_name in (
            "test / backend-shard-a",
            "test / backend-shard-b",
            "test / backend-coverage",
            "test / frontend-e2e-chromium",
            "test / frontend-e2e-firefox",
            "test / frontend-e2e-webkit",
            "test / frontend-e2e",
        )
        for evidence_state in ("missing", "failure")
    ),
)
def test_full_attestation_rejects_missing_or_failed_sharded_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_name: str,
    evidence_state: str,
) -> None:
    fixture = _equivalent_repository(tmp_path)

    class CurrentRunAPI:
        def __init__(self, **arguments: Any) -> None:
            pass

        def workflow_run(self, run_id: int) -> dict[str, Any]:
            return {
                "id": run_id,
                "run_attempt": 2,
                "event": "push",
                "head_sha": fixture["merge"],
            }

        def run_attempt_jobs(
            self,
            run_id: int,
            run_attempt: int,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "name": name,
                    "status": "completed",
                    "conclusion": "failure" if name == job_name else "success",
                    "run_id": run_id,
                    "run_attempt": run_attempt,
                    "head_sha": fixture["merge"],
                }
                for name in gate.REQUIRED_EXECUTION_JOBS
                if not (evidence_state == "missing" and name == job_name)
            ]

    monkeypatch.setattr(gate, "GitHubActionsAPI", CurrentRunAPI)
    arguments = type(
        "Arguments",
        (),
        {
            "mode": "full",
            "classifier_result": "success",
            "lint_result": "success",
            "test_result": "success",
            "build_result": "success",
            "api_url": "https://api.github.invalid",
            "repository": REPOSITORY,
            "run_id": 77,
            "run_attempt": 2,
            "event_name": "push",
            "attested_sha": fixture["merge"],
            "execution_head_sha": fixture["merge"],
            "pr_number": 0,
            "base_ref": "",
            "repository_root": fixture["root"],
            "github_output": None,
        },
    )()

    with pytest.raises(RuntimeError):
        gate.attest_full_ci(arguments)


def test_workflow_contracts_and_check_branch_remain_stable() -> None:
    workflow = MAIN_WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(workflow, Loader=yaml.BaseLoader)
    pr_workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    pr_parsed = yaml.load(pr_workflow, Loader=yaml.BaseLoader)

    assert parsed["on"]["push"]["branches-ignore"] == ["analytics-assets"]
    assert parsed["on"]["pull_request"]["branches"] == [
        "main",
        "integration/**",
    ]
    assert parsed["on"]["pull_request"]["types"] == [
        "opened",
        "reopened",
        "synchronize",
    ]
    assert "paths" not in parsed["on"]["pull_request"]
    assert "paths-ignore" not in parsed["on"]["pull_request"]
    assert "pull_request_target" not in parsed["on"]
    assert "merge_group" not in parsed["on"]
    assert parsed["permissions"]["actions"] == "read"
    assert parsed["jobs"]["ci_mode"]["name"] == "Detect CI mode"
    assert parsed["jobs"]["ci_mode"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pull-requests": "read",
    }
    assert parsed["jobs"]["equivalent_provenance"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pull-requests": "read",
    }
    assert parsed["jobs"]["full_attestation"]["name"] == "Full CI Attestation"
    assert parsed["jobs"]["full_attestation"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pull-requests": "read",
    }
    start_provenance = parsed["jobs"]["coordination_start_provenance"]
    assert start_provenance["name"] == "Coordination Start provenance"
    assert start_provenance["permissions"] == {
        "contents": "read",
        "actions": "read",
    }
    assert "coordination-start" in start_provenance["if"]
    assert "--expect-mode coordination-start" in workflow
    assert "coordination_start_provenance.result" in workflow
    full_attestation = next(
        step
        for step in parsed["jobs"]["full_attestation"]["steps"]
        if step["name"] == "Validate complete full-CI evidence"
    )
    assert full_attestation["env"]["EVENT_BASE_REF"] == (
        "${{ github.event.pull_request.base.ref }}"
    )
    assert "EVENT_BASE_SHA" not in full_attestation["env"]
    assert "--run-attempt '${{ github.run_attempt }}'" in workflow
    assert '--event-name "$EVENT_NAME"' in workflow
    assert '--attested-sha "$ATTESTED_SHA"' in workflow
    assert '--execution-head-sha "$EXECUTION_HEAD_SHA"' in workflow
    assert '--pr-number "$EVENT_PR_NUMBER"' in workflow
    assert '--base-ref "$EVENT_BASE_REF"' in workflow
    assert "${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert parsed["jobs"]["ci_gate"]["name"] == "CI Gate"
    assert parsed["jobs"]["ci_gate"]["if"] == "${{ always() }}"
    assert "needs.ci_mode.outputs.ci_mode == 'full'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "needs.ci_gate.result == 'success'" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "--pr-number" in workflow
    assert "--base-sha" in workflow
    assert "--head-sha" in workflow
    assert "--head-repository-id" in workflow
    docs_revalidation = next(
        step
        for step in parsed["jobs"]["docs_gate"]["steps"]
        if step["name"] == "Revalidate documentation-only scope"
    )
    assert docs_revalidation["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "EVENT_ACTION": "${{ github.event.action }}",
        "EVENT_BEFORE_SHA": "${{ github.event.before }}",
        "EVENT_CURRENT_SHA": "${{ github.sha }}",
        "EVENT_REF": "${{ github.ref }}",
        "EVENT_FORCED": "${{ github.event.forced || false }}",
        "EVENT_REPOSITORY": "${{ github.repository }}",
        "EVENT_REPOSITORY_ID": "${{ github.repository_id }}",
        "EVENT_PR_NUMBER": "${{ github.event.pull_request.number || 0 }}",
        "EVENT_PR_DRAFT": "${{ github.event.pull_request.draft || false }}",
        "EVENT_BASE_REF": "${{ github.event.pull_request.base.ref }}",
        "EVENT_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "EVENT_HEAD_REF": "${{ github.event.pull_request.head.ref }}",
        "EVENT_HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
        "EVENT_HEAD_REPOSITORY": (
            "${{ github.event.pull_request.head.repo.full_name }}"
        ),
        "EVENT_HEAD_REPOSITORY_ID": (
            "${{ github.event.pull_request.head.repo.id || 0 }}"
        ),
    }
    for option in (
        "--action",
        "--pr-number",
        "--draft",
        "--base-ref",
        "--base-sha",
        "--head-ref",
        "--head-sha",
        "--head-repository",
        "--head-repository-id",
    ):
        assert option in docs_revalidation["run"]
    assert "CI Gate" not in pr_workflow
    assert pr_parsed["name"] == "Validate PR base branch"
    assert set(pr_parsed["jobs"]) == {"check-branch"}
    assert pr_parsed["jobs"]["check-branch"]["permissions"] == {"contents": "read"}
    steps = pr_parsed["jobs"]["check-branch"]["steps"]
    assert all(
        step["name"] != "Checkout current protected main authority" for step in steps
    )
    checkout = next(
        step for step in steps if step["name"] == "Checkout immutable pull request base"
    )
    assert checkout["with"] == {
        "fetch-depth": "1",
        "path": "trusted-base",
        "persist-credentials": "false",
        "ref": "${{ github.event.pull_request.base.sha }}",
    }
    head_checkout = next(
        step for step in steps if step["name"] == "Checkout immutable pull request head"
    )
    assert head_checkout["with"] == {
        "fetch-depth": "1",
        "path": "proposed-head",
        "persist-credentials": "false",
        "ref": "${{ github.event.pull_request.head.sha }}",
    }
    assert "scripts/ci/project_governance.py" in pr_workflow
    assert "scripts/ci/trusted_governance_gate.py" not in pr_workflow
    assert "TRUSTED_GOVERNANCE_APP_ID" not in pr_workflow
    assert "TRUSTED_INTEGRATION_RULESET_ID" not in pr_workflow
    assert "TRUSTED_INTEGRATION_RULESET_DIGEST" not in pr_workflow
    assert "gh api --paginate" not in pr_workflow
    assert "protected_coordination_branches" not in pr_workflow
    assert COORDINATION_BRANCH not in pr_workflow
    assert "pull_request_target" not in pr_parsed["on"]
    assert "merge_group" not in pr_parsed["on"]


@pytest.mark.parametrize(
    ("base_branch", "expected_returncode"),
    (
        ("main", 0),
        (COORDINATION_BRANCH, 1),
        (f"{COORDINATION_BRANCH}-near-match", 1),
        ("feat/other", 1),
    ),
)
def test_check_branch_accepts_only_current_repository_bases(
    base_branch: str,
    expected_returncode: int,
) -> None:
    parsed = yaml.load(PR_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    run = next(
        step["run"]
        for step in parsed["jobs"]["check-branch"]["steps"]
        if step["name"] == "Require an approved pull request base"
    )
    process = subprocess.run(
        ["bash", "-c", run],
        env={
            "BASE_BRANCH": base_branch,
            "GH_TOKEN": "test-only",
            "REPOSITORY": "NTHU-Physics-SA-IT/PastExamWeb_PHY",
            "TRUSTED_ROOT": str(REPOSITORY_ROOT),
            "PROPOSED_ROOT": str(REPOSITORY_ROOT),
        },
        text=True,
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )

    assert process.returncode == expected_returncode


def test_check_branch_accepts_exact_branch_local_coordination_base(
    tmp_path: Path,
) -> None:
    parsed = yaml.load(PR_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    run = next(
        step["run"]
        for step in parsed["jobs"]["check-branch"]["steps"]
        if step["name"] == "Require an approved pull request base"
    )
    config = tmp_path / ".github" / "project-governance.json"
    resolver = tmp_path / "scripts" / "ci" / "project_governance.py"
    config.parent.mkdir(parents=True)
    resolver.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_development_base": "main",
                "coordination_branch": COORDINATION_BRANCH,
            }
        ),
        encoding="utf-8",
    )
    resolver.write_text(
        (CI_SCRIPTS / "project_governance.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    exact = subprocess.run(
        ["bash", "-c", run],
        env={
            "BASE_BRANCH": COORDINATION_BRANCH,
            "TRUSTED_ROOT": str(tmp_path),
            "PROPOSED_ROOT": str(tmp_path),
        },
        text=True,
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    near_match = subprocess.run(
        ["bash", "-c", run],
        env={
            "BASE_BRANCH": f"{COORDINATION_BRANCH}-near-match",
            "TRUSTED_ROOT": str(tmp_path),
            "PROPOSED_ROOT": str(tmp_path),
        },
        text=True,
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )

    assert exact.returncode == 0
    assert near_match.returncode == 1


def test_check_branch_bootstrap_accepts_main_and_rejects_incomplete_authority(
    tmp_path: Path,
) -> None:
    parsed = yaml.load(PR_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    run = next(
        step["run"]
        for step in parsed["jobs"]["check-branch"]["steps"]
        if step["name"] == "Require an approved pull request base"
    )
    environment = {
        "BASE_BRANCH": "main",
        "GH_TOKEN": "test-only",
        "REPOSITORY": "NTHU-Physics-SA-IT/PastExamWeb_PHY",
        "TRUSTED_ROOT": str(tmp_path),
        "PROPOSED_ROOT": str(tmp_path),
    }

    bootstrap = subprocess.run(
        ["bash", "-c", run],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    assert bootstrap.returncode == 0

    config = tmp_path / ".github" / "project-governance.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}", encoding="utf-8")
    incomplete = subprocess.run(
        ["bash", "-c", run],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    assert incomplete.returncode == 2
    assert "incomplete" in incomplete.stderr.lower()
