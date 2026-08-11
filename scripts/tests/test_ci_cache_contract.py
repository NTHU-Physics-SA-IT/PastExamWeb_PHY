from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LINT_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "lint.yml"
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def _yaml(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _step(workflow: dict, job: str, name: str) -> dict:
    return next(step for step in workflow["jobs"][job]["steps"] if step["name"] == name)


def test_frontend_jobs_key_pnpm_cache_from_frontend_lockfile() -> None:
    lint = _yaml(LINT_WORKFLOW)
    test = _yaml(TEST_WORKFLOW)

    for workflow, job in (
        (lint, "frontend"),
        (test, "frontend-unit"),
        (test, "frontend-e2e"),
    ):
        setup_node = _step(workflow, job, "Setup Node.js")
        assert setup_node["with"]["cache"] == "pnpm"
        assert setup_node["with"]["cache-dependency-path"] == "frontend/pnpm-lock.yaml"


def test_release_cache_remains_root_scoped() -> None:
    release = _yaml(RELEASE_WORKFLOW)
    setup_node = _step(release, "release", "Setup Node.js")
    install = _step(release, "release", "Install dependencies")

    assert setup_node["with"]["cache"] == "pnpm"
    assert "cache-dependency-path" not in setup_node["with"]
    assert "working-directory" not in install
    assert (REPOSITORY_ROOT / "pnpm-lock.yaml").is_file()


def test_rejected_dev_image_cache_and_prebuild_are_absent() -> None:
    test = _yaml(TEST_WORKFLOW)
    workflow_text = TEST_WORKFLOW.read_text(encoding="utf-8")

    for job in ("backend", "frontend-e2e"):
        step_names = {step["name"] for step in test["jobs"][job]["steps"]}
        assert "Set up Docker Buildx" not in step_names
        assert "Build and load backend development image" not in step_names

    e2e_step_names = {step["name"] for step in test["jobs"]["frontend-e2e"]["steps"]}
    stack_start = _step(test, "frontend-e2e", "Start application stack")
    normalized_start = " ".join(stack_start["run"].split())

    assert "backend-dev-ci" not in workflow_text
    assert "docker/build-push-action" not in workflow_text
    assert "Build frontend development image" not in e2e_step_names
    assert normalized_start.endswith("up -d")
    assert "--no-build" not in normalized_start
