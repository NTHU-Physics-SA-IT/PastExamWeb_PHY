"""Executable contract for ADR-0006 postmerge Full-evidence reuse."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import importlib
from pathlib import Path
import sys
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
CI_SCRIPTS = REPOSITORY_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
ci = importlib.import_module("classify_ci_mode")
project_governance = importlib.import_module("project_governance")

PROJECT_GOVERNANCE = project_governance.load_project_governance(REPOSITORY_ROOT)
assert PROJECT_GOVERNANCE.coordination_branch is not None
COORDINATION_BRANCH = PROJECT_GOVERNANCE.coordination_branch
COORDINATION_REF = PROJECT_GOVERNANCE.coordination_ref

REPOSITORY = "NTHU-Physics-SA-IT/PastExamWeb_PHY"
REPOSITORY_ID = 12345
NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)

# Historical PR #95 supplies real identities for the exact Case-B shape.
C = "7e2368c8d35a52567d49d662702e163756314cb6"
M = "09263e5004a88de2402ef8c6027b68de88b4f64f"
S = "1f659f8192b7d6b39b8fbd8eb3ad4f2896b9549a"
Q = "b76befdda6a73c700e6962ed8fb8a36161775382"
OTHER = "f" * 40
PR_NUMBER = 95
SOURCE_RUN_ID = 9001
PR_RUN_ID = 9002

TCB_WORKFLOW = ".github/workflows/main.yml"
TCB_CLASSIFIER = "scripts/ci/classify_ci_mode.py"
APPLICATION_PATH = "backend/app/main.py"


def _blob(label: str, path: str) -> str:
    return hashlib.sha1(f"{label}:{path}".encode()).hexdigest()


def _full_run(
    *,
    run_id: int,
    event: str,
    attempt: int = 1,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "head_sha": S,
        "head_branch": "sync/case-b-refresh",
        "event": event,
        "status": "completed",
        "conclusion": "success",
        "path": ci.APPROVED_WORKFLOW_PATH,
        "workflow_id": ci.APPROVED_WORKFLOW_ID,
        "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
        "run_attempt": attempt,
        "created_at": (NOW - timedelta(hours=2)).isoformat(),
        "updated_at": (NOW - timedelta(hours=1)).isoformat(),
        # Historical run and check-suite metadata do not retain this association.
        "pull_requests": [],
    }


def _required_jobs(
    *,
    run_id: int,
    attempt: int = 1,
    overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    overrides = overrides or {}
    return [
        {
            "name": name,
            "status": "completed",
            "conclusion": overrides.get(name, "success"),
            "run_id": run_id,
            "run_attempt": attempt,
            "head_sha": S,
        }
        for name in sorted(ci.REQUIRED_SOURCE_JOBS)
    ]


class CaseBGit:
    """Small explicit Git model for C/M/S/Q contract mutations."""

    def __init__(self) -> None:
        self.parents_by_commit: dict[str, tuple[str, ...]] = {
            S: (C, M),
            Q: (C, S),
        }
        self.source_paths: tuple[str, ...] = (
            TCB_WORKFLOW,
            TCB_CLASSIFIER,
            APPLICATION_PATH,
        )
        self.first_parent_commits = 1
        self.source_contains_base = True
        self.equal_source_and_merge_trees = True
        self.empty_source_to_merge_diff = True
        self.blob_overrides: dict[tuple[str, str], str] = {}
        self.path_identity_overrides: dict[tuple[str, str], tuple[str, str, str]] = {}

    def parents(self, commit: str) -> tuple[str, ...]:
        return self.parents_by_commit.get(commit, ())

    def first_parent_count(self, base: str, head: str) -> int:
        assert (base, head) == (C, Q)
        return self.first_parent_commits

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        if (ancestor, descendant) == (C, S):
            return self.source_contains_base
        return (ancestor, descendant) in {(C, Q), (M, S), (M, Q)}

    def trees_are_equal(self, left: str, right: str) -> bool:
        if {left, right} == {Q, S}:
            return self.equal_source_and_merge_trees
        return left == right

    def diff_is_empty(self, left: str, right: str) -> bool:
        if {left, right} == {Q, S}:
            return self.empty_source_to_merge_diff
        return left == right

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        if (base, head) in {(C, S), (C, Q)}:
            return self.source_paths
        if {base, head} == {S, Q}:
            return ()
        return self.source_paths

    def merge_base(self, left: str, right: str) -> str:
        return C

    def tree_sha(self, commit: str) -> str:
        if commit in {S, Q}:
            return _blob("source-tree", "tree")
        return _blob(commit, "tree")

    def blob_sha(self, commit: str, path: str) -> str:
        override = self.blob_overrides.get((commit, path))
        if override is not None:
            return override
        if commit in {M, S, Q} and ci.is_governance_path(path):
            return _blob("trusted-main", path)
        return _blob(commit, path)

    def tracked_paths(self, commit: str) -> tuple[str, ...]:
        return tuple(path for path in self.source_paths if self.blob_sha(commit, path))

    def path_identity(self, commit: str, path: str) -> tuple[str, str, str]:
        if (commit, path) in self.path_identity_overrides:
            return self.path_identity_overrides[(commit, path)]
        blob = self.blob_sha(commit, path)
        if not blob:
            raise ci.ClassificationFailure("fixture path is missing")
        return "100644", "blob", blob


class DualFullAPI:
    """Narrow evidence model; it is deliberately not a fake GitHub server."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.refs = {
            COORDINATION_BRANCH: Q,
            "main": M,
            "sync/case-b-refresh": S,
        }
        self.runs = [
            _full_run(run_id=SOURCE_RUN_ID, event="push"),
            _full_run(run_id=PR_RUN_ID, event="pull_request"),
        ]
        self.jobs_by_run = {
            SOURCE_RUN_ID: _required_jobs(run_id=SOURCE_RUN_ID),
            PR_RUN_ID: _required_jobs(run_id=PR_RUN_ID),
        }
        self.pull_request_payload = {
            "number": PR_NUMBER,
            "state": "closed",
            "merged": True,
            "created_at": (NOW - timedelta(hours=3)).isoformat(),
            "merged_at": (NOW - timedelta(minutes=30)).isoformat(),
            "merge_commit_sha": Q,
            "base": {
                "ref": COORDINATION_BRANCH,
                "sha": C,
                "repo": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
            },
            "head": {
                "ref": "sync/case-b-refresh",
                "sha": S,
                "repo": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
            },
        }
        self.pull_requests_by_commit = {
            Q: [deepcopy(self.pull_request_payload)],
            S: [deepcopy(self.pull_request_payload)],
        }

    def workflow_runs(
        self,
        source_sha: str,
        event: str | None = "push",
    ) -> list[dict[str, Any]]:
        assert source_sha == S
        self.calls.append(("workflow_runs", source_sha, event))
        return deepcopy(
            self.runs
            if event is None
            else [run for run in self.runs if run["event"] == event]
        )

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        self.calls.append(("run_jobs", run_id))
        return deepcopy(self.jobs_by_run[run_id])

    def run_attempt_jobs(
        self,
        run_id: int,
        run_attempt: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(("run_attempt_jobs", run_id, run_attempt))
        return deepcopy(self.jobs_by_run[run_id])

    def ref_sha(self, ref_name: str) -> str:
        self.calls.append(("ref_sha", ref_name))
        return self.refs[ref_name]

    def pull_request(self, number: int) -> dict[str, Any]:
        assert number == PR_NUMBER
        self.calls.append(("pull_request", number))
        return deepcopy(self.pull_request_payload)

    def pull_requests_for_commit(self, commit: str) -> list[dict[str, Any]]:
        """Future postmerge binding for the GitHub commit/PR association API."""

        self.calls.append(("pull_requests_for_commit", commit))
        return deepcopy(self.pull_requests_by_commit.get(commit, []))


class NoProvenanceAPI:
    def __getattr__(self, name: str) -> Any:
        def unexpected_call(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(f"generic Full path invoked provenance API: {name}")

        return unexpected_call


def _push_event(**changes: Any) -> Any:
    values = {
        "event_name": "push",
        "before_sha": C,
        "current_sha": Q,
        "ref": COORDINATION_REF,
        "forced": False,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
    }
    values.update(changes)
    return ci.CIEvent(**values)


def _classify(
    *,
    git: CaseBGit | None = None,
    api: Any | None = None,
    event_changes: dict[str, Any] | None = None,
) -> Any:
    return ci.classify_ci_mode(
        event=_push_event(**(event_changes or {})),
        git=git or CaseBGit(),
        api=api or DualFullAPI(),
        now=NOW,
    )


def test_exact_case_b_dual_full_postmerge_contract_uses_equivalent() -> None:
    api = DualFullAPI()
    result = _classify(api=api)

    assert result.ci_mode == "equivalent-merge", result.reason
    assert result.source_sha == S
    assert api.calls == [
        ("ref_sha", COORDINATION_BRANCH),
        ("ref_sha", "main"),
        ("pull_requests_for_commit", Q),
        ("pull_requests_for_commit", S),
        ("workflow_runs", S, None),
        ("run_attempt_jobs", SOURCE_RUN_ID, 1),
        ("run_attempt_jobs", PR_RUN_ID, 1),
    ]


def test_later_pr_that_only_contains_historical_commits_is_not_ambiguous() -> None:
    api = DualFullAPI()
    containing_pull_request = deepcopy(api.pull_request_payload)
    containing_pull_request.update(
        {
            "number": 98,
            "state": "open",
            "created_at": (NOW - timedelta(minutes=10)).isoformat(),
            "merged_at": None,
            "merge_commit_sha": OTHER,
        }
    )
    containing_pull_request["base"]["sha"] = OTHER
    containing_pull_request["head"]["sha"] = OTHER
    api.pull_requests_by_commit[Q].append(deepcopy(containing_pull_request))
    api.pull_requests_by_commit[S].append(deepcopy(containing_pull_request))

    assert _classify(api=api).ci_mode == "equivalent-merge"


def test_historical_pr95_git_topology_and_governance_are_eligible() -> None:
    result = ci.classify_ci_mode(
        event=_push_event(),
        git=ci.GitRepository(REPOSITORY_ROOT),
        api=DualFullAPI(),
        now=NOW,
    )

    assert result.ci_mode == "equivalent-merge", result.reason
    assert result.source_sha == S


def test_commit_pull_request_api_accepts_exact_list_response() -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository=REPOSITORY,
        token="fixture-token",
    )
    api._get = lambda url: ([{"number": PR_NUMBER}], "")  # type: ignore[method-assign]

    assert api.pull_requests_for_commit(Q) == [{"number": PR_NUMBER}]


def test_commit_pull_request_api_rejects_off_origin_pagination() -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository=REPOSITORY,
        token="fixture-token",
    )
    api._get = lambda url: (  # type: ignore[method-assign]
        [{"number": PR_NUMBER}],
        '<https://attacker.invalid/page/2>; rel="next"',
    )

    with pytest.raises(ci.ClassificationFailure, match="approved API origin"):
        api.pull_requests_for_commit(Q)


@pytest.mark.parametrize(
    "case",
    (
        "wrong-parent-order",
        "extra-parent",
        "before-mismatch",
        "multiple-first-parent-commits",
        "force-push",
        "base-not-ancestor",
        "tree-mismatch",
        "merge-only-content",
        "coordination-ref-advanced",
    ),
)
def test_postmerge_topology_uncertainty_fails_closed(case: str) -> None:
    git = CaseBGit()
    api = DualFullAPI()
    event_changes: dict[str, Any] = {}

    if case == "wrong-parent-order":
        git.parents_by_commit[Q] = (S, C)
    elif case == "extra-parent":
        git.parents_by_commit[Q] = (C, S, OTHER)
    elif case == "before-mismatch":
        event_changes["before_sha"] = OTHER
    elif case == "multiple-first-parent-commits":
        git.first_parent_commits = 2
    elif case == "force-push":
        event_changes["forced"] = True
    elif case == "base-not-ancestor":
        git.source_contains_base = False
    elif case == "tree-mismatch":
        git.equal_source_and_merge_trees = False
    elif case == "merge-only-content":
        git.empty_source_to_merge_diff = False
    elif case == "coordination-ref-advanced":
        api.refs[COORDINATION_BRANCH] = OTHER

    assert _classify(git=git, api=api, event_changes=event_changes).ci_mode == "full"


@pytest.mark.parametrize(
    "case",
    ("source-not-two-parent", "wrong-main-parent", "current-main-advanced"),
)
def test_case_b_source_or_main_identity_mismatch_fails_closed(case: str) -> None:
    git = CaseBGit()
    api = DualFullAPI()

    if case == "source-not-two-parent":
        git.parents_by_commit[S] = (C,)
    elif case == "wrong-main-parent":
        git.parents_by_commit[S] = (C, OTHER)
    elif case == "current-main-advanced":
        api.refs["main"] = OTHER

    assert _classify(git=git, api=api).ci_mode == "full"


@pytest.mark.parametrize(
    "case",
    (
        "missing",
        "failed",
        "stale",
        "ambiguous",
        "wrong-repository",
        "wrong-workflow",
        "wrong-attempt",
        "required-job-missing",
        "required-job-failed",
        "required-job-duplicated",
    ),
)
def test_source_full_evidence_mismatch_fails_closed(case: str) -> None:
    api = DualFullAPI()
    source = next(run for run in api.runs if run["event"] == "push")

    if case == "missing":
        api.runs.remove(source)
    elif case == "failed":
        source["conclusion"] = "failure"
    elif case == "stale":
        source["updated_at"] = (NOW - timedelta(hours=73)).isoformat()
    elif case == "ambiguous":
        duplicate = deepcopy(source)
        duplicate["id"] = 9011
        api.runs.append(duplicate)
    elif case == "wrong-repository":
        source["repository"] = {"id": 999, "full_name": "other/repository"}
    elif case == "wrong-workflow":
        source["workflow_id"] = 999
    elif case == "wrong-attempt":
        source["run_attempt"] = 0
    elif case == "required-job-missing":
        api.jobs_by_run[SOURCE_RUN_ID].pop()
    elif case == "required-job-failed":
        api.jobs_by_run[SOURCE_RUN_ID][0]["conclusion"] = "failure"
    elif case == "required-job-duplicated":
        api.jobs_by_run[SOURCE_RUN_ID].append(
            deepcopy(api.jobs_by_run[SOURCE_RUN_ID][0])
        )

    assert _classify(api=api).ci_mode == "full"


@pytest.mark.parametrize(
    "case",
    (
        "missing",
        "failed",
        "stale",
        "ambiguous",
        "wrong-repository",
        "wrong-workflow",
        "wrong-base",
        "wrong-head",
        "wrong-pr",
        "pr-association-ambiguous",
        "run-wrong-pr",
        "run-before-pr",
        "run-job-attempt-mismatch",
    ),
)
def test_pr_full_evidence_or_identity_mismatch_fails_closed(case: str) -> None:
    api = DualFullAPI()
    pr_run = next(run for run in api.runs if run["event"] == "pull_request")

    if case == "missing":
        api.runs.remove(pr_run)
    elif case == "failed":
        pr_run["conclusion"] = "failure"
    elif case == "stale":
        pr_run["updated_at"] = (NOW - timedelta(hours=73)).isoformat()
    elif case == "ambiguous":
        duplicate = deepcopy(pr_run)
        duplicate["id"] = 9012
        api.runs.append(duplicate)
    elif case == "wrong-repository":
        pr_run["repository"] = {"id": 999, "full_name": "other/repository"}
    elif case == "wrong-workflow":
        pr_run["path"] = ".github/workflows/other.yml"
    elif case == "wrong-base":
        api.pull_request_payload["base"]["sha"] = OTHER
        api.pull_requests_by_commit[Q][0]["base"]["sha"] = OTHER
    elif case == "wrong-head":
        api.pull_request_payload["head"]["sha"] = OTHER
        api.pull_requests_by_commit[Q][0]["head"]["sha"] = OTHER
    elif case == "wrong-pr":
        api.pull_request_payload["number"] = 96
        api.pull_requests_by_commit[Q][0]["number"] = 96
    elif case == "pr-association-ambiguous":
        second = deepcopy(api.pull_requests_by_commit[Q][0])
        second["number"] = 96
        api.pull_requests_by_commit[Q].append(second)
    elif case == "run-wrong-pr":
        pr_run["pull_requests"] = [{"number": 96}]
    elif case == "run-before-pr":
        pr_run["created_at"] = (NOW - timedelta(hours=4)).isoformat()
    elif case == "run-job-attempt-mismatch":
        pr_run["run_attempt"] = 2
        assert all(job["run_attempt"] == 1 for job in api.jobs_by_run[PR_RUN_ID])

    assert _classify(api=api).ci_mode == "full"


@pytest.mark.parametrize(
    "case",
    ("modified", "added-helper", "deleted", "redirected", "type-changed"),
)
def test_untrusted_governance_or_tcb_content_fails_closed(case: str) -> None:
    git = CaseBGit()

    if case == "modified":
        git.blob_overrides[(S, TCB_CLASSIFIER)] = _blob("candidate", TCB_CLASSIFIER)
    elif case == "added-helper":
        helper = "scripts/ci/candidate_attestation_helper.py"
        git.source_paths += (helper,)
        git.blob_overrides[(M, helper)] = ""
        git.blob_overrides[(S, helper)] = _blob("candidate", helper)
    elif case == "deleted":
        resolver = "scripts/ci/project_governance.py"
        git.source_paths += (resolver,)
        git.blob_overrides[(M, resolver)] = _blob("trusted-main", resolver)
        git.blob_overrides[(S, resolver)] = ""
    elif case == "redirected":
        git.blob_overrides[(S, TCB_WORKFLOW)] = _blob("redirect", TCB_WORKFLOW)
    elif case == "type-changed":
        git.path_identity_overrides[(S, TCB_WORKFLOW)] = (
            "120000",
            "blob",
            _blob("trusted-main", TCB_WORKFLOW),
        )

    assert _classify(git=git).ci_mode == "full"


def test_ordinary_governance_coordination_pr_remains_full() -> None:
    git = CaseBGit()
    git.parents_by_commit[S] = (C,)
    event = ci.CIEvent(
        event_name="pull_request",
        before_sha="",
        current_sha=Q,
        ref=f"refs/pull/{PR_NUMBER}/merge",
        forced=False,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        action="opened",
        pr_number=PR_NUMBER,
        base_ref=COORDINATION_BRANCH,
        base_sha=C,
        head_ref="sync/case-b-refresh",
        head_sha=S,
        head_repository=REPOSITORY,
        head_repository_id=REPOSITORY_ID,
    )

    result = ci.classify_ci_mode(event=event, git=git, api=DualFullAPI(), now=NOW)

    assert result.ci_mode == "full"


@pytest.mark.parametrize(
    ("event", "paths"),
    (
        (
            _push_event(ref="refs/heads/main"),
            (TCB_WORKFLOW,),
        ),
        (
            _push_event(ref="refs/heads/release/v2"),
            (APPLICATION_PATH,),
        ),
        (
            _push_event(ref="refs/heads/production/stable"),
            (APPLICATION_PATH,),
        ),
        (
            _push_event(ref="refs/heads/topic"),
            (APPLICATION_PATH,),
        ),
    ),
)
def test_generic_full_routes_do_not_call_postmerge_provenance_api(
    event: Any,
    paths: tuple[str, ...],
) -> None:
    git = CaseBGit()
    git.source_paths = paths

    result = ci.classify_ci_mode(
        event=event,
        git=git,
        api=NoProvenanceAPI(),
        now=NOW,
    )

    assert result.ci_mode == "full"


def test_ordinary_governance_pr_full_does_not_call_postmerge_api() -> None:
    git = CaseBGit()
    event = ci.CIEvent(
        event_name="pull_request",
        before_sha="",
        current_sha=Q,
        ref=f"refs/pull/{PR_NUMBER}/merge",
        forced=False,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        action="opened",
        pr_number=PR_NUMBER,
        base_ref=COORDINATION_BRANCH,
        base_sha=C,
        head_ref="ordinary-governance-change",
        head_sha=S,
        head_repository=REPOSITORY,
        head_repository_id=REPOSITORY_ID,
    )

    result = ci.classify_ci_mode(
        event=event,
        git=git,
        api=NoProvenanceAPI(),
        now=NOW,
    )

    assert result.ci_mode == "full"


def test_non_candidate_governance_push_does_not_call_postmerge_api() -> None:
    git = CaseBGit()
    git.parents_by_commit[Q] = (C, S, OTHER)

    result = ci.classify_ci_mode(
        event=_push_event(),
        git=git,
        api=NoProvenanceAPI(),
        now=NOW,
    )

    assert result.ci_mode == "full"


def test_main_governance_pr_remains_full_without_postmerge_api() -> None:
    git = CaseBGit()
    event = ci.CIEvent(
        event_name="pull_request",
        before_sha="",
        current_sha=Q,
        ref=f"refs/pull/{PR_NUMBER}/merge",
        forced=False,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        action="opened",
        pr_number=PR_NUMBER,
        base_ref="main",
        base_sha=C,
        head_ref="governance-change",
        head_sha=S,
        head_repository=REPOSITORY,
        head_repository_id=REPOSITORY_ID,
    )

    result = ci.classify_ci_mode(
        event=event,
        git=git,
        api=NoProvenanceAPI(),
        now=NOW,
    )

    assert result.ci_mode == "full"
