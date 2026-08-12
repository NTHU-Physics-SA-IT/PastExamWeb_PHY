from __future__ import annotations

from pathlib import Path
import re

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
PLAYWRIGHT_CONFIG = REPOSITORY_ROOT / "frontend" / "playwright.config.ts"
VITE_WARMUP = REPOSITORY_ROOT / "frontend" / "scripts" / "settle-vite-route.mjs"
ARCHIVE_E2E_SPEC = (
    REPOSITORY_ROOT / "frontend" / "tests" / "e2e" / "admin" / "archive.spec.ts"
)
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


def test_each_family_settles_archive_vite_before_playwright() -> None:
    workflow = _workflow()
    family = workflow["jobs"]["frontend-e2e-family"]
    step_names = [step["name"] for step in family["steps"]]
    warmup = _step(family, "Settle Archive Vite dependencies")
    execution = _step(family, "Run frontend E2E tests")

    assert step_names.index("Wait for API readiness") < step_names.index(
        "Settle Archive Vite dependencies"
    )
    assert step_names.index("Settle Archive Vite dependencies") < step_names.index(
        "Run frontend E2E tests"
    )
    assert warmup["env"] == {
        "E2E_FAMILY": "${{ matrix.family }}",
        "PLAYWRIGHT_IMAGE": "${{ steps.playwright-image.outputs.image }}",
    }
    assert "--network pastexam-dev-network" in warmup["run"]
    assert "-e E2E_FAMILY" in warmup["run"]
    assert "-e PLAYWRIGHT_BASE_URL=http://nginx:8080" in warmup["run"]
    assert '"$PLAYWRIGHT_IMAGE"' in warmup["run"]
    assert "node scripts/settle-vite-route.mjs" in warmup["run"]
    assert "sleep" not in warmup["run"]
    assert "--network pastexam-dev-network" in execution["run"]

    warmup_source = VITE_WARMUP.read_text(encoding="utf-8")
    assert "QUIET_WINDOW_MS = 10_000" in warmup_source
    assert "PHASE_TIMEOUT_MS = 45_000" in warmup_source
    assert "[vite] connected." in warmup_source
    assert "isNavigationRequest()" in warmup_source
    assert "stable-generation-verification" in warmup_source
    assert "page.reload" in warmup_source

    watched_test = ARCHIVE_E2E_SPEC.read_text(encoding="utf-8").split(
        "keeps Archive edit state for approved 404 and 409 move conflicts", maxsplit=1
    )[1]
    assert "page.reload" not in watched_test
    assert "archiveDocumentRequestCount" not in watched_test
    assert "requestCountBeforeMissingMove" in watched_test
    assert "requestCountBeforeLifecycleConflict" in watched_test


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
