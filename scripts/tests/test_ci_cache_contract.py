from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LINT_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "lint.yml"
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
DEV_COMPOSE = REPOSITORY_ROOT / "docker" / "docker-compose.dev.yml"


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


def test_backend_dev_image_cache_is_local_and_dedicated() -> None:
    test = _yaml(TEST_WORKFLOW)
    expected = {
        "context": "./backend",
        "file": "./backend/Dockerfile.dev",
        "push": "false",
        "load": "true",
        "tags": "pastexam-backend-dev:latest",
        "cache-from": "type=gha,scope=backend-dev-ci",
        "cache-to": "type=gha,scope=backend-dev-ci,mode=max,ignore-error=true",
    }

    for job in ("backend", "frontend-e2e"):
        buildx = _step(test, job, "Set up Docker Buildx")
        build = _step(test, job, "Build and load backend development image")

        assert buildx["uses"] == "docker/setup-buildx-action@v4"
        assert build["uses"] == "docker/build-push-action@v7"
        assert build["with"] == expected


def test_compose_consumes_loaded_backend_image_without_rebuilding() -> None:
    test = _yaml(TEST_WORKFLOW)
    compose = _yaml(DEV_COMPOSE)
    backend_image = "${BACKEND_IMAGE:-pastexam-backend-dev:latest}"

    for service in ("migrate", "bootstrap", "backend"):
        assert compose["services"][service]["image"] == backend_image

    assert compose["services"]["backend"]["volumes"] == [
        "/app/.venv",
        "../backend:/app",
    ]

    for name in (
        "Run migrations",
        "Seed database",
        "Run backend tests with coverage",
    ):
        run = _step(test, "backend", name)["run"]
        assert "run --rm" in run.replace("\\\n", " ")
        assert "--build" not in run

    frontend_build = _step(test, "frontend-e2e", "Build frontend development image")
    stack_start = _step(test, "frontend-e2e", "Start application stack")
    bootstrap = _step(test, "frontend-e2e", "Bootstrap isolated E2E database")
    assert "build frontend" in frontend_build["run"]
    assert "up --no-build -d" in stack_start["run"]
    assert "run --rm bootstrap" in bootstrap["run"]
    assert "--build" not in bootstrap["run"]
