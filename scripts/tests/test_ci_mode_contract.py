from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
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
    ) -> None:
        self.source_sha = source_sha
        self.target_sha = target_sha
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
        assert ref_name == "target"
        return self.target_sha


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
        equivalent_allowlist=frozenset({"refs/heads/target"}),
        now=NOW,
    )


def test_classifier_defines_only_three_modes_and_empty_live_allowlist() -> None:
    assert ci.CI_MODES == frozenset({"full", "equivalent-merge", "docs-only"})
    assert ci.LIVE_EQUIVALENT_TARGET_REFS == frozenset()


@pytest.mark.parametrize(
    ("ref", "paths", "expected"),
    (
        ("refs/heads/topic", ("backend/app/main.py",), "full"),
        ("refs/heads/topic", ("docs/guide.md", "README.md"), "docs-only"),
        ("refs/heads/main", ("docs/guide.md",), "full"),
        ("refs/heads/main", ("backend/app/main.py",), "full"),
        ("refs/heads/feat/exam-report-system", ("docs/guide.md",), "full"),
        ("refs/heads/release/v1", ("docs/guide.md",), "full"),
        ("refs/heads/production/stable", ("docs/guide.md",), "full"),
        ("refs/heads/hotfix/production/db", ("docs/guide.md",), "full"),
        ("refs/heads/topic", (".github/workflows/main.yml",), "full"),
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
    result = ci.classify_ci_mode(event=event, git=ScopeGit(paths))

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


def test_valid_two_parent_equivalent_merge_is_eligible(tmp_path: Path) -> None:
    fixture = _equivalent_repository(tmp_path)

    result = _classify_equivalent(fixture)

    assert result.ci_mode == "equivalent-merge"
    assert result.source_sha == fixture["source"]
    assert result.source_run_id == "9001"
    assert result.source_tree == fixture["git"].tree_sha(fixture["source"])


def test_rollout_disabled_keeps_valid_equivalent_fixture_full(tmp_path: Path) -> None:
    fixture = _equivalent_repository(tmp_path)

    result = ci.classify_ci_mode(
        event=_event(fixture),
        git=fixture["git"],
        api=FakeAPI(source_sha=fixture["source"], target_sha=fixture["merge"]),
        now=NOW,
    )

    assert result.ci_mode == "full"


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
        ({}, {"test / backend": "failure"}),
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


@pytest.mark.parametrize(
    (
        "mode",
        "full_attestation",
        "equivalent",
        "docs",
    ),
    (
        ("full", "success", "skipped", "skipped"),
        ("equivalent-merge", "skipped", "success", "skipped"),
        ("docs-only", "skipped", "skipped", "success"),
    ),
)
def test_ci_gate_accepts_only_the_mode_specific_dependency_shape(
    mode: str,
    full_attestation: str,
    equivalent: str,
    docs: str,
) -> None:
    arguments = type(
        "Arguments",
        (),
        {
            "mode": mode,
            "classifier_result": "success",
            "lint_result": "success",
            "test_result": "success",
            "build_result": "success",
            "full_attestation_result": full_attestation,
            "equivalent_result": equivalent,
            "docs_result": docs,
        },
    )()

    gate.validate_gate(arguments)


def test_ci_gate_rejects_illegal_mode_or_dependency_result() -> None:
    arguments = type(
        "Arguments",
        (),
        {
            "mode": "full",
            "classifier_result": "success",
            "lint_result": "success",
            "test_result": "success",
            "build_result": "success",
            "full_attestation_result": "skipped",
            "equivalent_result": "skipped",
            "docs_result": "skipped",
        },
    )()
    with pytest.raises(RuntimeError):
        gate.validate_gate(arguments)
    arguments.mode = "unknown"
    with pytest.raises(RuntimeError):
        gate.validate_gate(arguments)


def test_full_attestation_checks_each_required_execution_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _equivalent_repository(tmp_path)

    class CurrentRunAPI:
        def __init__(self, **arguments: Any) -> None:
            pass

        def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
            assert run_id == 77
            return [
                {"name": name, "conclusion": "success"}
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
            "sha": fixture["merge"],
            "repository_root": fixture["root"],
            "github_output": output,
        },
    )()

    gate.attest_full_ci(arguments)

    evidence = output.read_text(encoding="utf-8")
    assert "mode=full" in evidence
    assert f"sha={fixture['merge']}" in evidence
    assert "workflow_revision=" in evidence


def test_full_attestation_rejects_a_skipped_required_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _equivalent_repository(tmp_path)

    class CurrentRunAPI:
        def __init__(self, **arguments: Any) -> None:
            pass

        def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
            return [
                {
                    "name": name,
                    "conclusion": (
                        "skipped" if name == "test / backend" else "success"
                    ),
                }
                for name in gate.REQUIRED_EXECUTION_JOBS
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
            "sha": fixture["merge"],
            "repository_root": fixture["root"],
            "github_output": None,
        },
    )()

    with pytest.raises(RuntimeError):
        gate.attest_full_ci(arguments)


def test_workflow_contracts_and_check_branch_remain_stable() -> None:
    workflow = MAIN_WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(workflow, Loader=yaml.BaseLoader)
    pr_workflow = PR_WORKFLOW.read_bytes()
    git_blob = f"blob {len(pr_workflow)}\0".encode() + pr_workflow

    assert parsed["on"]["push"]["branches-ignore"] == ["analytics-assets"]
    assert "merge_group" not in parsed["on"]
    assert parsed["permissions"]["actions"] == "read"
    assert parsed["jobs"]["ci_mode"]["name"] == "Detect CI mode"
    assert parsed["jobs"]["full_attestation"]["name"] == "Full CI Attestation"
    assert parsed["jobs"]["ci_gate"]["name"] == "CI Gate"
    assert parsed["jobs"]["ci_gate"]["if"] == "${{ always() }}"
    assert "needs.ci_mode.outputs.ci_mode == 'full'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "needs.ci_gate.result == 'success'" in workflow
    assert "CI Gate" not in PR_WORKFLOW.read_text(encoding="utf-8")
    assert (
        hashlib.sha1(git_blob).hexdigest() == "3de5e768e262493c1e766d206e21ae44e347fd23"
    )
