from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
PLAYWRIGHT_CONFIG = REPOSITORY_ROOT / "frontend" / "playwright.config.ts"
FAMILIES = ("chromium", "firefox", "webkit")


def _workflow() -> dict:
    return yaml.load(
        TEST_WORKFLOW.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step["name"] == name)


def _configured_projects() -> tuple[str, ...]:
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    return tuple(re.findall(r"^\s+name: '([^']+)',?$", config, flags=re.MULTILINE))


def test_browser_families_partition_configured_projects_exactly() -> None:
    configured = set(_configured_projects())
    selected = {family: {family, f"{family}-admin"} for family in FAMILIES}

    assert "readiness" in configured
    assert "setup" in configured
    assert set().union(*selected.values()) == configured - {"readiness", "setup"}
    assert all(
        selected[left].isdisjoint(selected[right])
        for index, left in enumerate(FAMILIES)
        for right in FAMILIES[index + 1 :]
    )

    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    project_starts = {
        match.group(1): match.start()
        for match in re.finditer(r"^\s+name: '([^']+)',?$", config, flags=re.MULTILINE)
    }
    ordered_projects = list(_configured_projects())
    dependency_contract = {
        "setup": "dependencies: ['readiness']",
        **{family: "dependencies: ['readiness']" for family in FAMILIES},
        **{f"{family}-admin": "dependencies: ['setup']" for family in FAMILIES},
    }
    for project, dependency in dependency_contract.items():
        start = project_starts[project]
        project_index = ordered_projects.index(project)
        end = (
            project_starts[ordered_projects[project_index + 1]]
            if project_index + 1 < len(ordered_projects)
            else len(config)
        )
        assert dependency in config[start:end]


def test_workflow_runs_three_isolated_browser_family_jobs() -> None:
    workflow = _workflow()
    family = workflow["jobs"]["frontend-e2e-family"]
    selection = _step(family, "List selected frontend E2E cases")["run"]
    execution = _step(family, "Run frontend E2E tests")["run"]

    assert family["name"] == "frontend-e2e-${{ matrix.family }}"
    assert family["runs-on"] == "ubuntu-latest"
    assert family["needs"] == ["backend", "frontend-unit"]
    assert family["strategy"] == {
        "fail-fast": "false",
        "matrix": {"family": list(FAMILIES)},
    }
    assert '--project="$E2E_FAMILY"' in selection
    assert '--project="${E2E_FAMILY}-admin"' in selection
    assert '--project="$E2E_FAMILY"' in execution
    assert '--project="${E2E_FAMILY}-admin"' in execution
    assert "--reporter=dot,blob" in execution
    assert "--no-deps" not in selection
    assert "--no-deps" not in execution


def test_playwright_image_pull_retries_are_bounded_and_fail_closed() -> None:
    workflow = _workflow()
    family = workflow["jobs"]["frontend-e2e-family"]
    image_pull = _step(family, "Pull Playwright image")["run"]

    assert "max_attempts=3" in image_pull
    assert 'for attempt in $(seq 1 "$max_attempts")' in image_pull
    assert 'docker pull "$PLAYWRIGHT_IMAGE"' in image_pull
    assert 'sleep "$delay_seconds"' in image_pull
    assert 'exit "$pull_status"' in image_pull
    assert "|| true" not in image_pull


def test_playwright_image_pull_retry_control_flow(tmp_path: Path) -> None:
    workflow = _workflow()
    family = workflow["jobs"]["frontend-e2e-family"]
    image_pull = _step(family, "Pull Playwright image")["run"]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
count=0
if [[ -f "$COUNTER_FILE" ]]; then
  count="$(cat "$COUNTER_FILE")"
fi
count=$((count + 1))
printf '%s' "$count" > "$COUNTER_FILE"
if [[ "$count" -ge "$SUCCEED_ON" ]]; then
  exit 0
fi
exit 42
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    sleep = fake_bin / "sleep"
    sleep.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$1" >> "$SLEEP_FILE"
""",
        encoding="utf-8",
    )
    sleep.chmod(0o755)

    for succeed_on, expected_status in ((3, 0), (99, 42)):
        case = tmp_path / str(succeed_on)
        case.mkdir()
        counter = case / "counter"
        sleeps = case / "sleeps"
        env = {
            **os.environ,
            "COUNTER_FILE": str(counter),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "PLAYWRIGHT_IMAGE": "mcr.example.invalid/playwright:v1.2.3-noble",
            "SLEEP_FILE": str(sleeps),
            "SUCCEED_ON": str(succeed_on),
        }

        result = subprocess.run(
            ["bash"],
            input=image_pull,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

        assert result.returncode == expected_status
        assert counter.read_text(encoding="utf-8") == "3"
        assert sleeps.read_text(encoding="utf-8").splitlines() == ["10", "20"]


def test_e2e_teardown_skips_only_when_docker_env_was_never_prepared() -> None:
    workflow = _workflow()
    family = workflow["jobs"]["frontend-e2e-family"]
    teardown = _step(family, "Tear down")

    assert teardown["if"] == "always()"
    assert "if [[ ! -f docker/.env ]]" in teardown["run"]
    assert "docker compose" in teardown["run"]
    assert "down --volumes --remove-orphans" in teardown["run"]
    assert "|| true" not in teardown["run"]


def test_e2e_teardown_guard_control_flow(tmp_path: Path) -> None:
    workflow = _workflow()
    family = workflow["jobs"]["frontend-e2e-family"]
    teardown = _step(family, "Tear down")["run"]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_calls = tmp_path / "docker-calls"
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$DOCKER_CALLS"
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = {
        **os.environ,
        "DOCKER_CALLS": str(docker_calls),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    skipped = subprocess.run(
        ["bash"],
        cwd=tmp_path,
        env=env,
        input=teardown,
        text=True,
        capture_output=True,
        check=False,
    )
    assert skipped.returncode == 0
    assert not docker_calls.exists()

    docker_env = tmp_path / "docker" / ".env"
    docker_env.parent.mkdir()
    docker_env.touch()
    cleaned = subprocess.run(
        ["bash"],
        cwd=tmp_path,
        env=env,
        input=teardown,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cleaned.returncode == 0
    assert docker_calls.read_text(encoding="utf-8").strip() == (
        "compose --env-file docker/.env -f docker/docker-compose.dev.yml "
        "down --volumes --remove-orphans"
    )


def test_blob_artifacts_are_unique_and_aggregate_fails_closed() -> None:
    workflow = _workflow()
    family = workflow["jobs"]["frontend-e2e-family"]
    aggregate = workflow["jobs"]["frontend-e2e"]
    blob_upload = _step(family, "Upload Playwright blob report")

    assert blob_upload["if"] == "always()"
    assert blob_upload["with"] == {
        "name": "frontend-e2e-blob-${{ matrix.family }}",
        "path": "frontend/blob-report/report-${{ matrix.family }}.zip",
        "if-no-files-found": "error",
    }
    assert aggregate["name"] == "frontend-e2e"
    assert aggregate["if"] == "${{ always() && inputs.run_checks }}"
    assert aggregate["needs"] == ["frontend-e2e-family"]

    downloads = {
        step["with"]["name"]
        for step in aggregate["steps"]
        if step.get("uses") == "actions/download-artifact@v8"
    }
    assert downloads == {f"frontend-e2e-blob-{family}" for family in FAMILIES}

    artifact_check = _step(aggregate, "Verify complete browser-family artifacts")
    for family_name in FAMILIES:
        assert f"blob-report/report-{family_name}.zip" in artifact_check["run"]
    assert "find blob-report -maxdepth 1" in artifact_check["run"]

    merge = _step(aggregate, "Merge Playwright reports")
    assert merge["run"] == (
        "pnpm exec playwright merge-reports --reporter=html blob-report"
    )
    final_upload = _step(aggregate, "Upload Playwright HTML report")
    assert final_upload["with"]["name"] == "frontend-e2e-report"
    assert final_upload["with"]["if-no-files-found"] == "error"

    result_check = _step(aggregate, "Verify browser-family results")
    assert result_check["if"] == "always()"
    assert result_check["env"]["FAMILY_RESULT"] == (
        "${{ needs.frontend-e2e-family.result }}"
    )
    assert result_check["run"] == 'test "$FAMILY_RESULT" = success'
