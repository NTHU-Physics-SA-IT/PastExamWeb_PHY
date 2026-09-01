import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_production_env_keys.py"
PRODUCTION_ENV_EXAMPLES = (
    REPOSITORY_ROOT / "backend" / ".env.production.runtime.example",
    REPOSITORY_ROOT / "backend" / ".env.production.migrator.example",
)


def run_validator(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *(str(path) for path in paths)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_production_examples_exclude_default_admin_password() -> None:
    result = run_validator(*PRODUCTION_ENV_EXAMPLES)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "declaration",
    (
        "DEFAULT_ADMIN_PASSWORD=synthetic-test-only",
        "  DEFAULT_ADMIN_PASSWORD = synthetic-test-only",
        "export DEFAULT_ADMIN_PASSWORD=synthetic-test-only",
    ),
)
def test_forbidden_key_is_rejected_without_printing_value(
    tmp_path: Path, declaration: str
) -> None:
    environment_file = tmp_path / "production.env"
    environment_file.write_text(f"{declaration}\n", encoding="utf-8")

    result = run_validator(environment_file)

    assert result.returncode == 1
    assert "DEFAULT_ADMIN_PASSWORD" in result.stdout
    assert "synthetic-test-only" not in result.stdout
    assert result.stderr == ""


def test_near_match_is_not_rejected(tmp_path: Path) -> None:
    environment_file = tmp_path / "production.env"
    environment_file.write_text(
        "NOT_DEFAULT_ADMIN_PASSWORD=synthetic-test-only\n", encoding="utf-8"
    )

    result = run_validator(environment_file)

    assert result.returncode == 0
    assert result.stdout == ""


def test_dev_compose_scopes_bootstrap_password_to_explicit_service() -> None:
    compose = yaml.safe_load(
        (REPOSITORY_ROOT / "docker" / "docker-compose.dev.yml").read_text(
            encoding="utf-8"
        )
    )

    for service_name in ("backend", "migrate"):
        environment = compose["services"][service_name]["environment"]
        assert "DEFAULT_ADMIN_PASSWORD" not in environment
        assert "BOOTSTRAP_ADMIN_PASSWORD" not in environment

    bootstrap = compose["services"]["bootstrap"]
    assert bootstrap["profiles"] == ["bootstrap"]
    assert bootstrap["environment"]["ALLOW_DATABASE_BOOTSTRAP"] == "true"
    assert "BOOTSTRAP_ADMIN_PASSWORD" in bootstrap["environment"]
    assert "DEFAULT_ADMIN_PASSWORD" not in bootstrap["environment"]


def test_ci_seeds_through_explicit_bootstrap_service() -> None:
    workflow = yaml.load(
        (REPOSITORY_ROOT / ".github" / "workflows" / "test.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )
    seed_step = next(
        step
        for step in workflow["jobs"]["backend"]["steps"]
        if step["name"] == "Seed database"
    )

    command = seed_step["run"]
    assert "--profile bootstrap" in command
    assert "run --rm --no-deps" in command
    assert "bootstrap uv run python -m app.scripts.seed_db" in command
    assert "-e ALLOW_DATABASE_BOOTSTRAP" not in command
