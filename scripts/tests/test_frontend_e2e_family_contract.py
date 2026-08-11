from __future__ import annotations

from pathlib import Path
import re

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

    assert "setup" in configured
    assert set().union(*selected.values()) == configured - {"setup"}
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
    for family in FAMILIES:
        project = f"{family}-admin"
        start = project_starts[project]
        project_index = ordered_projects.index(project)
        end = (
            project_starts[ordered_projects[project_index + 1]]
            if project_index + 1 < len(ordered_projects)
            else len(config)
        )
        assert "dependencies: ['setup']" in config[start:end]


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
