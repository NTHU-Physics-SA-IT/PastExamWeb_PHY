from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest


CI_SCRIPTS = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
ci = importlib.import_module("classify_ci_mode")
gate = importlib.import_module("validate_ci_gate")

RUN_ID = 77
RUN_ATTEMPT = 2
EXECUTION_HEAD_SHA = "a" * 40
ATTESTED_SHA = "b" * 40
BASE_SHA = "c" * 40
REQUIRED_JOBS = frozenset({"Detect CI mode", "build / frontend"})


def test_default_polling_bound_is_small_and_deterministic() -> None:
    assert gate.FULL_ATTESTATION_MAX_OBSERVATIONS == 5
    assert gate.FULL_ATTESTATION_POLL_INTERVAL_SECONDS == 2.0
    assert (
        gate.FULL_ATTESTATION_MAX_OBSERVATIONS - 1
    ) * gate.FULL_ATTESTATION_POLL_INTERVAL_SECONDS <= 10


def _job(
    name: str,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: Any = RUN_ID,
    run_attempt: Any = RUN_ATTEMPT,
    head_sha: Any = EXECUTION_HEAD_SHA,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
    }


def _successful_snapshot() -> list[dict[str, Any]]:
    return [_job(name) for name in sorted(REQUIRED_JOBS)]


def _poll(
    snapshots: list[list[dict[str, Any]]],
    *,
    max_observations: int | None = None,
) -> tuple[int, list[float]]:
    observations = [deepcopy(snapshot) for snapshot in snapshots]
    calls = 0
    sleeps: list[float] = []

    def load_jobs() -> list[dict[str, Any]]:
        nonlocal calls
        index = min(calls, len(observations) - 1)
        calls += 1
        return deepcopy(observations[index])

    gate._require_unique_successes(
        load_jobs=load_jobs,
        required_names=REQUIRED_JOBS,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        execution_head_sha=EXECUTION_HEAD_SHA,
        max_observations=max_observations or len(observations),
        poll_interval_seconds=0.0,
        sleeper=sleeps.append,
    )
    return calls, sleeps


def test_immediate_success_passes_without_polling() -> None:
    calls, sleeps = _poll([_successful_snapshot()])

    assert calls == 1
    assert sleeps == []


def test_historical_frontend_visibility_lag_polls_to_success() -> None:
    initial = [
        job for job in _successful_snapshot() if job["name"] != "build / frontend"
    ]

    calls, sleeps = _poll([initial, _successful_snapshot()])

    assert calls == 2
    assert sleeps == [0.0]


def test_nonterminal_null_conclusion_polls_to_success() -> None:
    initial = _successful_snapshot()
    classifier = next(job for job in initial if job["name"] == "Detect CI mode")
    classifier.update(status="in_progress", conclusion=None)

    calls, sleeps = _poll([initial, _successful_snapshot()])

    assert calls == 2
    assert sleeps == [0.0]


def test_successive_required_job_visibility_waits_for_complete_snapshot() -> None:
    first = [_job("Detect CI mode", status="queued", conclusion=None)]
    second = [_job("Detect CI mode")]

    calls, sleeps = _poll([first, second, _successful_snapshot()])

    assert calls == 3
    assert sleeps == [0.0, 0.0]


def test_terminal_failure_fails_immediately_without_polling() -> None:
    failed = _successful_snapshot()
    frontend = next(job for job in failed if job["name"] == "build / frontend")
    frontend["conclusion"] = "failure"

    with pytest.raises(RuntimeError, match="terminal non-success.*failure"):
        _poll([failed, _successful_snapshot()])


@pytest.mark.parametrize("conclusion", ("cancelled", "timed_out"))
def test_terminal_cancelled_or_timed_out_fails(conclusion: str) -> None:
    failed = _successful_snapshot()
    frontend = next(job for job in failed if job["name"] == "build / frontend")
    frontend["conclusion"] = conclusion

    with pytest.raises(RuntimeError, match=f"terminal non-success.*{conclusion}"):
        _poll([failed, _successful_snapshot()])


def test_missing_job_after_poll_bound_fails_with_diagnostics() -> None:
    missing = [
        job for job in _successful_snapshot() if job["name"] != "build / frontend"
    ]

    with pytest.raises(RuntimeError, match=r"observation 3/3.*missing"):
        _poll([missing], max_observations=3)


def test_nonterminal_job_after_poll_bound_fails_with_diagnostics() -> None:
    nonterminal = _successful_snapshot()
    classifier = next(job for job in nonterminal if job["name"] == "Detect CI mode")
    classifier.update(status="in_progress", conclusion=None)

    with pytest.raises(RuntimeError, match=r"observation 3/3.*nonterminal"):
        _poll([nonterminal], max_observations=3)


def test_duplicate_required_job_identity_fails_immediately() -> None:
    duplicate = _successful_snapshot()
    duplicate.append(_job("Detect CI mode"))

    with pytest.raises(RuntimeError, match=r"ambiguous.*Detect CI mode.*2 entries"):
        _poll([duplicate, _successful_snapshot()])


@pytest.mark.parametrize("observed_run_id", (None, 0, 76, "77"))
def test_missing_malformed_or_other_run_id_fails(observed_run_id: Any) -> None:
    mismatched = _successful_snapshot()
    mismatched[0]["run_id"] = observed_run_id

    with pytest.raises(RuntimeError, match="run ID mismatch"):
        _poll([mismatched, _successful_snapshot()])


@pytest.mark.parametrize("observed_attempt", (None, 0, 1, "2"))
def test_missing_malformed_or_other_attempt_fails(observed_attempt: Any) -> None:
    mismatched = _successful_snapshot()
    mismatched[0]["run_attempt"] = observed_attempt

    with pytest.raises(RuntimeError, match="attempt mismatch"):
        _poll([mismatched, _successful_snapshot()])


def test_other_execution_head_sha_fails_without_substitution() -> None:
    mismatched = _successful_snapshot()
    mismatched[0]["head_sha"] = "b" * 40

    with pytest.raises(RuntimeError, match="execution-head SHA mismatch"):
        _poll([mismatched, _successful_snapshot()])


@pytest.mark.parametrize("run_attempt", (None, 0, -1, True, "2"))
def test_expected_run_attempt_must_be_positive_integer(run_attempt: Any) -> None:
    with pytest.raises(RuntimeError, match="run attempt"):
        gate._require_unique_successes(
            load_jobs=_successful_snapshot,
            required_names=REQUIRED_JOBS,
            run_id=RUN_ID,
            run_attempt=run_attempt,
            execution_head_sha=EXECUTION_HEAD_SHA,
            max_observations=1,
            poll_interval_seconds=0.0,
            sleeper=lambda _: None,
        )


@pytest.mark.parametrize("run_id", (None, 0, -1, True, "77"))
def test_expected_run_id_must_be_positive_integer(run_id: Any) -> None:
    with pytest.raises(RuntimeError, match="run ID"):
        gate._require_unique_successes(
            load_jobs=_successful_snapshot,
            required_names=REQUIRED_JOBS,
            run_id=run_id,
            run_attempt=RUN_ATTEMPT,
            execution_head_sha=EXECUTION_HEAD_SHA,
            max_observations=1,
            poll_interval_seconds=0.0,
            sleeper=lambda _: None,
        )


def test_transport_failure_is_not_polled() -> None:
    calls = 0
    sleeps: list[float] = []

    def unavailable() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        raise ci.ClassificationFailure("GitHub API evidence unavailable")

    with pytest.raises(ci.ClassificationFailure, match="unavailable"):
        gate._require_unique_successes(
            load_jobs=unavailable,
            required_names=REQUIRED_JOBS,
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            execution_head_sha=EXECUTION_HEAD_SHA,
            max_observations=5,
            poll_interval_seconds=0.0,
            sleeper=sleeps.append,
        )

    assert calls == 1
    assert sleeps == []


def test_workflow_run_uses_exact_run_endpoint() -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository="NTHU-Physics-SA-IT/PastExamWeb_PHY",
        token="fixture-token",
    )
    calls: list[str] = []

    def get(url: str) -> tuple[dict[str, Any], str]:
        calls.append(url)
        return {"id": RUN_ID}, ""

    api._get = get  # type: ignore[method-assign]

    assert api.workflow_run(RUN_ID) == {"id": RUN_ID}
    assert calls == [
        "https://api.github.invalid/repos/NTHU-Physics-SA-IT/"
        "PastExamWeb_PHY/actions/runs/77"
    ]


@pytest.mark.parametrize("run_id", (0, -1, True))
def test_workflow_run_rejects_malformed_identity(run_id: Any) -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository="NTHU-Physics-SA-IT/PastExamWeb_PHY",
        token="fixture-token",
    )

    with pytest.raises(ci.ClassificationFailure, match="malformed"):
        api.workflow_run(run_id)


def test_commit_object_parent_reader_does_not_require_history_walk() -> None:
    git = ci.GitRepository(Path("."))
    calls: list[tuple[str, ...]] = []

    def run(*arguments: str, check: bool = True) -> SimpleNamespace:
        calls.append(arguments)
        return SimpleNamespace(
            stdout=(
                f"tree {'d' * 40}\n"
                f"parent {BASE_SHA}\n"
                f"parent {EXECUTION_HEAD_SHA}\n"
                "author Fixture <fixture@example.invalid> 0 +0000\n\nmessage\n"
            )
        )

    git._run = run  # type: ignore[method-assign]

    assert git.commit_object_parents(ATTESTED_SHA) == (
        BASE_SHA,
        EXECUTION_HEAD_SHA,
    )
    assert calls == [("cat-file", "-p", ATTESTED_SHA)]


def test_attempt_jobs_uses_exact_attempt_endpoint() -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository="NTHU-Physics-SA-IT/PastExamWeb_PHY",
        token="fixture-token",
    )
    calls: list[dict[str, Any]] = []

    def paged_list(**arguments: Any) -> list[dict[str, Any]]:
        calls.append(arguments)
        return []

    api._paged_list = paged_list  # type: ignore[method-assign]

    assert api.run_attempt_jobs(77, 2) == []
    assert calls == [
        {
            "path": (
                "/repos/NTHU-Physics-SA-IT/PastExamWeb_PHY/actions/runs/77/"
                "attempts/2/jobs"
            ),
            "key": "jobs",
            "parameters": {"per_page": "100"},
        }
    ]


@pytest.mark.parametrize(("run_id", "run_attempt"), ((0, 1), (1, 0), (1, -1)))
def test_attempt_jobs_rejects_nonpositive_identity(
    run_id: int,
    run_attempt: int,
) -> None:
    api = ci.GitHubActionsAPI(
        api_url="https://api.github.invalid",
        repository="NTHU-Physics-SA-IT/PastExamWeb_PHY",
        token="fixture-token",
    )

    with pytest.raises(ci.ClassificationFailure, match="malformed"):
        api.run_attempt_jobs(run_id, run_attempt)


class _AttestationAPI:
    def __init__(
        self,
        *,
        event_name: str,
        execution_head_sha: str,
        pull_request: dict[str, Any] | None = None,
        run_overrides: dict[str, Any] | None = None,
        jobs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.run = {
            "id": RUN_ID,
            "run_attempt": RUN_ATTEMPT,
            "event": event_name,
            "head_sha": execution_head_sha,
        }
        self.run.update(run_overrides or {})
        self.jobs = jobs or [
            _job(name, head_sha=execution_head_sha)
            for name in sorted(gate.REQUIRED_EXECUTION_JOBS)
        ]
        self.pull_request_payload = pull_request

    def workflow_run(self, run_id: int) -> dict[str, Any]:
        assert run_id == RUN_ID
        return deepcopy(self.run)

    def run_attempt_jobs(
        self,
        run_id: int,
        run_attempt: int,
    ) -> list[dict[str, Any]]:
        assert run_id == RUN_ID
        assert run_attempt == RUN_ATTEMPT
        return deepcopy(self.jobs)

    def pull_request(self, number: int) -> dict[str, Any]:
        assert number == 68
        assert self.pull_request_payload is not None
        return deepcopy(self.pull_request_payload)


class _AttestationGit:
    def __init__(self, parents: tuple[str, ...]) -> None:
        self.parents = parents
        self.tree_calls: list[str] = []
        self.blob_calls: list[tuple[str, str]] = []

    def commit_object_parents(self, commit: str) -> tuple[str, ...]:
        assert commit == ATTESTED_SHA
        return self.parents

    def tree_sha(self, commit: str) -> str:
        self.tree_calls.append(commit)
        return "d" * 40

    def blob_sha(self, commit: str, path: str) -> str:
        self.blob_calls.append((commit, path))
        return "e" * 40


def _attestation_arguments(
    tmp_path: Path,
    *,
    event_name: str,
    attested_sha: str,
    execution_head_sha: str,
    pr_number: int = 0,
    base_sha: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        mode="full",
        classifier_result="success",
        lint_result="success",
        test_result="success",
        build_result="success",
        api_url="https://api.github.invalid",
        repository="NTHU-Physics-SA-IT/PastExamWeb_PHY",
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        event_name=event_name,
        attested_sha=attested_sha,
        execution_head_sha=execution_head_sha,
        pr_number=pr_number,
        base_sha=base_sha,
        repository_root=tmp_path,
        github_output=tmp_path / "github-output",
    )


def _pull_request_payload() -> dict[str, Any]:
    return {
        "number": 68,
        "state": "open",
        "merge_commit_sha": ATTESTED_SHA,
        "base": {
            "sha": BASE_SHA,
            "repo": {"full_name": "NTHU-Physics-SA-IT/PastExamWeb_PHY"},
        },
        "head": {"sha": EXECUTION_HEAD_SHA},
    }


def _install_attestation_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api: _AttestationAPI,
    git: _AttestationGit,
) -> None:
    monkeypatch.setattr(gate, "GitHubActionsAPI", lambda **_: api)
    monkeypatch.setattr(gate, "GitRepository", lambda _: git)


def test_push_uses_one_attested_and_execution_head_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _AttestationAPI(
        event_name="push",
        execution_head_sha=EXECUTION_HEAD_SHA,
    )
    git = _AttestationGit(())
    _install_attestation_fakes(monkeypatch, api=api, git=git)
    arguments = _attestation_arguments(
        tmp_path,
        event_name="push",
        attested_sha=EXECUTION_HEAD_SHA,
        execution_head_sha=EXECUTION_HEAD_SHA,
    )

    gate.attest_full_ci(arguments)

    evidence = arguments.github_output.read_text(encoding="utf-8")
    assert f"sha={EXECUTION_HEAD_SHA}" in evidence
    assert git.tree_calls == [EXECUTION_HEAD_SHA]
    assert git.blob_calls == [(EXECUTION_HEAD_SHA, ci.APPROVED_WORKFLOW_PATH)]


def test_pull_request_separates_tested_merge_from_execution_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _AttestationAPI(
        event_name="pull_request",
        execution_head_sha=EXECUTION_HEAD_SHA,
        pull_request=_pull_request_payload(),
    )
    git = _AttestationGit((BASE_SHA, EXECUTION_HEAD_SHA))
    _install_attestation_fakes(monkeypatch, api=api, git=git)
    arguments = _attestation_arguments(
        tmp_path,
        event_name="pull_request",
        attested_sha=ATTESTED_SHA,
        execution_head_sha=EXECUTION_HEAD_SHA,
        pr_number=68,
        base_sha=BASE_SHA,
    )

    gate.attest_full_ci(arguments)

    evidence = arguments.github_output.read_text(encoding="utf-8")
    assert f"sha={ATTESTED_SHA}" in evidence
    assert EXECUTION_HEAD_SHA not in evidence
    assert git.tree_calls == [ATTESTED_SHA]
    assert git.blob_calls == [(ATTESTED_SHA, ci.APPROVED_WORKFLOW_PATH)]


def test_workflow_run_execution_head_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _AttestationAPI(
        event_name="push",
        execution_head_sha=EXECUTION_HEAD_SHA,
        run_overrides={"head_sha": "f" * 40},
    )
    _install_attestation_fakes(monkeypatch, api=api, git=_AttestationGit(()))
    arguments = _attestation_arguments(
        tmp_path,
        event_name="push",
        attested_sha=EXECUTION_HEAD_SHA,
        execution_head_sha=EXECUTION_HEAD_SHA,
    )

    with pytest.raises(RuntimeError, match="workflow run execution-head SHA"):
        gate.attest_full_ci(arguments)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"id": RUN_ID + 1}, "workflow run ID mismatch"),
        ({"run_attempt": RUN_ATTEMPT + 1}, "workflow run attempt mismatch"),
        ({"event": "pull_request"}, "workflow run event mismatch"),
    ),
)
def test_workflow_run_identity_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, Any],
    message: str,
) -> None:
    api = _AttestationAPI(
        event_name="push",
        execution_head_sha=EXECUTION_HEAD_SHA,
        run_overrides=overrides,
    )
    _install_attestation_fakes(monkeypatch, api=api, git=_AttestationGit(()))
    arguments = _attestation_arguments(
        tmp_path,
        event_name="push",
        attested_sha=EXECUTION_HEAD_SHA,
        execution_head_sha=EXECUTION_HEAD_SHA,
    )

    with pytest.raises(RuntimeError, match=message):
        gate.attest_full_ci(arguments)


@pytest.mark.parametrize("stale_authority", ("base", "head", "merge"))
def test_stale_pull_request_authority_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_authority: str,
) -> None:
    pull_request = _pull_request_payload()
    if stale_authority == "base":
        pull_request["base"]["sha"] = "f" * 40
    elif stale_authority == "head":
        pull_request["head"]["sha"] = "f" * 40
    else:
        pull_request["merge_commit_sha"] = "f" * 40
    api = _AttestationAPI(
        event_name="pull_request",
        execution_head_sha=EXECUTION_HEAD_SHA,
        pull_request=pull_request,
    )
    _install_attestation_fakes(
        monkeypatch,
        api=api,
        git=_AttestationGit((BASE_SHA, EXECUTION_HEAD_SHA)),
    )
    arguments = _attestation_arguments(
        tmp_path,
        event_name="pull_request",
        attested_sha=ATTESTED_SHA,
        execution_head_sha=EXECUTION_HEAD_SHA,
        pr_number=68,
        base_sha=BASE_SHA,
    )

    with pytest.raises(RuntimeError, match=f"pull request {stale_authority} SHA"):
        gate.attest_full_ci(arguments)


@pytest.mark.parametrize(
    "parents",
    (("f" * 40, EXECUTION_HEAD_SHA), (BASE_SHA, "f" * 40)),
)
def test_pull_request_synthetic_merge_parent_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parents: tuple[str, str],
) -> None:
    api = _AttestationAPI(
        event_name="pull_request",
        execution_head_sha=EXECUTION_HEAD_SHA,
        pull_request=_pull_request_payload(),
    )
    _install_attestation_fakes(
        monkeypatch,
        api=api,
        git=_AttestationGit(parents),
    )
    arguments = _attestation_arguments(
        tmp_path,
        event_name="pull_request",
        attested_sha=ATTESTED_SHA,
        execution_head_sha=EXECUTION_HEAD_SHA,
        pr_number=68,
        base_sha=BASE_SHA,
    )

    with pytest.raises(RuntimeError, match="merge parents do not match"):
        gate.attest_full_ci(arguments)


def test_push_rejects_different_attested_and_execution_head_shas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _AttestationAPI(
        event_name="push",
        execution_head_sha=EXECUTION_HEAD_SHA,
    )
    _install_attestation_fakes(monkeypatch, api=api, git=_AttestationGit(()))
    arguments = _attestation_arguments(
        tmp_path,
        event_name="push",
        attested_sha=ATTESTED_SHA,
        execution_head_sha=EXECUTION_HEAD_SHA,
    )

    with pytest.raises(RuntimeError, match="push attested SHA"):
        gate.attest_full_ci(arguments)


@pytest.mark.parametrize(
    ("event_name", "extra", "expected_pr_number", "expected_base_sha"),
    (
        ("push", [], 0, ""),
        (
            "pull_request",
            ["--pr-number", "68", "--base-sha", BASE_SHA],
            68,
            BASE_SHA,
        ),
    ),
)
def test_full_attestation_parser_keeps_event_aware_sha_roles(
    event_name: str,
    extra: list[str],
    expected_pr_number: int,
    expected_base_sha: str,
) -> None:
    arguments = gate._parser().parse_args(
        [
            "full-attestation",
            "--mode",
            "full",
            "--classifier-result",
            "success",
            "--lint-result",
            "success",
            "--test-result",
            "success",
            "--build-result",
            "success",
            "--api-url",
            "https://api.github.invalid",
            "--repository",
            "NTHU-Physics-SA-IT/PastExamWeb_PHY",
            "--run-id",
            str(RUN_ID),
            "--run-attempt",
            str(RUN_ATTEMPT),
            "--event-name",
            event_name,
            "--attested-sha",
            ATTESTED_SHA if event_name == "pull_request" else EXECUTION_HEAD_SHA,
            "--execution-head-sha",
            EXECUTION_HEAD_SHA,
            *extra,
        ]
    )

    assert arguments.event_name == event_name
    assert arguments.attested_sha == (
        ATTESTED_SHA if event_name == "pull_request" else EXECUTION_HEAD_SHA
    )
    assert arguments.execution_head_sha == EXECUTION_HEAD_SHA
    assert arguments.pr_number == expected_pr_number
    assert arguments.base_sha == expected_base_sha
