from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path
import sys
from typing import Any

import pytest


CI_SCRIPTS = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
ci = importlib.import_module("classify_ci_mode")
gate = importlib.import_module("validate_ci_gate")

RUN_ATTEMPT = 2
RUN_SHA = "a" * 40
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
    run_attempt: Any = RUN_ATTEMPT,
    head_sha: Any = RUN_SHA,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
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
        run_attempt=RUN_ATTEMPT,
        sha=RUN_SHA,
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


@pytest.mark.parametrize("observed_attempt", (None, 0, 1, "2"))
def test_missing_malformed_or_other_attempt_fails(observed_attempt: Any) -> None:
    mismatched = _successful_snapshot()
    mismatched[0]["run_attempt"] = observed_attempt

    with pytest.raises(RuntimeError, match="attempt mismatch"):
        _poll([mismatched, _successful_snapshot()])


def test_other_sha_fails_without_cross_run_substitution() -> None:
    mismatched = _successful_snapshot()
    mismatched[0]["head_sha"] = "b" * 40

    with pytest.raises(RuntimeError, match="SHA mismatch"):
        _poll([mismatched, _successful_snapshot()])


@pytest.mark.parametrize("run_attempt", (None, 0, -1, True, "2"))
def test_expected_run_attempt_must_be_positive_integer(run_attempt: Any) -> None:
    with pytest.raises(RuntimeError, match="run attempt"):
        gate._require_unique_successes(
            load_jobs=_successful_snapshot,
            required_names=REQUIRED_JOBS,
            run_attempt=run_attempt,
            sha=RUN_SHA,
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
            run_attempt=RUN_ATTEMPT,
            sha=RUN_SHA,
            max_observations=5,
            poll_interval_seconds=0.0,
            sleeper=sleeps.append,
        )

    assert calls == 1
    assert sleeps == []


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
