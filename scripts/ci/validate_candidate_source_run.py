"""Resolve authoritative exact-main-SHA Full CI for manual candidate prep."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_SUCCESSFUL_JOBS = {
    "Detect CI mode",
    "Full CI Attestation",
    "CI Gate",
    "Publish production image authority",
    "build / backend",
    "build / frontend",
}


class AuthorityError(RuntimeError):
    """Exact-SHA Full CI authority is missing, stale, or malformed."""


def _request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise AuthorityError("GitHub returned malformed CI authority.")
    return payload


def resolve_authority(
    repository: str, release_sha: str, token: str, api_url: str
) -> tuple[int, int]:
    if not re.fullmatch(r"[0-9a-f]{40}", release_sha):
        raise AuthorityError("Release SHA must be a full lowercase commit SHA.")
    query = urllib.parse.urlencode(
        {
            "event": "push",
            "head_sha": release_sha,
            "status": "completed",
            "per_page": 100,
        }
    )
    runs = _request_json(
        f"{api_url}/repos/{repository}/actions/workflows/main.yml/runs?{query}", token
    ).get("workflow_runs")
    if not isinstance(runs, list):
        raise AuthorityError("GitHub Full CI run list is malformed.")
    matches = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == release_sha
        and run.get("head_branch") == "main"
        and run.get("event") == "push"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]
    if len(matches) != 1:
        raise AuthorityError(
            "Expected exactly one successful exact-main-SHA Full CI run."
        )
    run = matches[0]
    run_id, attempt = run.get("id"), run.get("run_attempt")
    if not isinstance(run_id, int) or not isinstance(attempt, int) or attempt < 1:
        raise AuthorityError("Full CI run identity is malformed.")
    jobs = _request_json(
        f"{api_url}/repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
        token,
    ).get("jobs")
    if not isinstance(jobs, list):
        raise AuthorityError("Full CI job authority is malformed.")
    successful = {
        job.get("name")
        for job in jobs
        if isinstance(job, dict) and job.get("conclusion") == "success"
    }
    missing = REQUIRED_SUCCESSFUL_JOBS - successful
    if missing:
        raise AuthorityError("Exact-SHA run is not authoritative Full CI.")
    return run_id, attempt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise AuthorityError("GITHUB_TOKEN is required.")
    run_id, attempt = resolve_authority(
        args.repository,
        args.release_sha,
        token,
        os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
    )
    with args.output.open("a", encoding="utf-8") as output:
        output.write(f"release_sha={args.release_sha}\n")
        output.write(f"source_ci_run_id={run_id}\n")
        output.write(f"source_ci_run_attempt={attempt}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
