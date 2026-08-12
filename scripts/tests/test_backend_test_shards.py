from __future__ import annotations

import configparser
import importlib
import json
from pathlib import Path
import sys

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = REPOSITORY_ROOT / "scripts" / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
shards = importlib.import_module("backend_test_shards")

MANIFEST = CI_SCRIPTS / "backend-test-shards.json"
TEST_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "test.yml"
COVERAGE_CONFIG = REPOSITORY_ROOT / "backend" / ".coveragerc"


def _payload() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _fixture_repository(tmp_path: Path, payload: dict) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    for path in {
        item for shard_paths in payload["shards"].values() for item in shard_paths
    }:
        test_file = repository / "backend" / path
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_fixture():\n    pass\n", encoding="utf-8")
    manifest = repository / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return repository, manifest


def _load_fixture(tmp_path: Path, payload: dict):
    repository, manifest = _fixture_repository(tmp_path, payload)
    return shards.load_manifest(
        repository_root=repository,
        manifest_path=manifest,
    )


def test_canonical_manifest_is_a_complete_exact_two_shard_partition() -> None:
    manifest = shards.load_manifest()
    discovered = {
        path.relative_to(REPOSITORY_ROOT / "backend").as_posix()
        for path in (REPOSITORY_ROOT / "backend" / "tests").rglob("test_*.py")
    }

    assert tuple(manifest.paths_by_shard) == ("a", "b")
    assert set(manifest.all_paths) == discovered
    assert len(manifest.all_paths) == len(set(manifest.all_paths))


def test_duplicate_path_is_rejected(tmp_path: Path) -> None:
    payload = _payload()
    duplicate = payload["shards"]["a"][0]
    payload["shards"]["b"].append(duplicate)
    payload["shards"]["b"].sort()

    with pytest.raises(shards.BackendShardManifestError, match="duplicate"):
        _load_fixture(tmp_path, payload)


def test_missing_assignment_is_rejected(tmp_path: Path) -> None:
    payload = _payload()
    repository, manifest = _fixture_repository(tmp_path, payload)
    payload["shards"]["a"].pop()
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(shards.BackendShardManifestError, match="unassigned"):
        shards.load_manifest(repository_root=repository, manifest_path=manifest)


def test_nonexistent_assignment_is_rejected(tmp_path: Path) -> None:
    payload = _payload()
    payload["shards"]["a"].append("tests/unit/test_nonexistent.py")
    payload["shards"]["a"].sort()
    repository, manifest = _fixture_repository(tmp_path, payload)
    (repository / "backend/tests/unit/test_nonexistent.py").unlink()

    with pytest.raises(shards.BackendShardManifestError, match="nonexistent"):
        shards.load_manifest(repository_root=repository, manifest_path=manifest)


def test_unknown_shard_is_rejected() -> None:
    manifest = shards.load_manifest()

    with pytest.raises(shards.BackendShardManifestError, match="unknown"):
        manifest.paths_for_shard("c")


def test_path_output_preserves_manifest_order_deterministically(
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = "\n".join(_payload()["shards"]["a"]) + "\n"

    assert shards.main(["paths", "--shard", "a"]) == 0
    first = capsys.readouterr().out
    assert shards.main(["paths", "--shard", "a"]) == 0
    second = capsys.readouterr().out

    assert first == second
    assert first == expected


def test_new_unassigned_test_file_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    repository, manifest = _fixture_repository(tmp_path, payload)
    new_test = repository / "backend/tests/unit/test_new_unassigned.py"
    new_test.parent.mkdir(parents=True, exist_ok=True)
    new_test.write_text("def test_new():\n    pass\n", encoding="utf-8")

    with pytest.raises(shards.BackendShardManifestError, match="unassigned"):
        shards.load_manifest(repository_root=repository, manifest_path=manifest)


def test_logging_sensitive_contracts_precede_integration_scenarios() -> None:
    manifest = shards.load_manifest()

    # Alembic scenarios configure logging with disable_existing_loggers. Each
    # independent shard must exercise its caplog contracts before that state.
    for shard, logging_contract in (
        ("a", "tests/unit/test_archive_submission_links.py"),
        ("b", "tests/unit/test_archive_submission_status.py"),
    ):
        paths = manifest.paths_for_shard(shard)
        first_integration = next(
            index
            for index, path in enumerate(paths)
            if path.startswith("tests/integration/")
        )
        assert paths.index(logging_contract) < first_integration


def test_workflow_runs_independent_shards_and_parallel_coverage_combine() -> None:
    workflow = yaml.load(
        TEST_WORKFLOW.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    backend = workflow["jobs"]["backend"]
    coverage = workflow["jobs"]["backend-coverage"]
    e2e = workflow["jobs"]["frontend-e2e-family"]

    assert backend["name"] == "backend-shard-${{ matrix.shard }}"
    assert backend["strategy"] == {
        "fail-fast": "false",
        "matrix": {"shard": ["a", "b"]},
    }
    assert backend["runs-on"] == "ubuntu-latest"
    backend_step_names = {step["name"] for step in backend["steps"]}
    assert {
        "Validate backend shard manifest",
        "Start core services",
        "Verify isolated test database",
        "Run migrations",
        "Seed database",
        "Run backend shard with coverage",
        "Tear down",
    } <= backend_step_names
    assert coverage["name"] == "backend-coverage"
    assert coverage["needs"] == ["backend"]
    assert e2e["needs"] == ["backend", "frontend-unit"]


def test_raw_and_combined_coverage_artifacts_fail_closed() -> None:
    workflow = yaml.load(
        TEST_WORKFLOW.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    backend_steps = workflow["jobs"]["backend"]["steps"]
    upload_raw = next(
        step for step in backend_steps if step["name"] == "Upload raw backend coverage"
    )
    coverage_steps = workflow["jobs"]["backend-coverage"]["steps"]
    final_upload = next(
        step for step in coverage_steps if step["name"] == "Upload backend coverage"
    )

    assert upload_raw["with"]["name"] == "backend-coverage-raw-${{ matrix.shard }}"
    assert upload_raw["with"]["if-no-files-found"] == "error"
    assert upload_raw["with"]["include-hidden-files"] == "true"
    assert final_upload["with"]["name"] == "backend-coverage"
    assert final_upload["with"]["if-no-files-found"] == "error"


def test_combined_coverage_keeps_existing_omissions_and_relative_paths() -> None:
    config = configparser.ConfigParser()
    config.read(COVERAGE_CONFIG)
    run = config["run"]

    assert run.getboolean("relative_files") is True
    assert run["source"].split() == ["app"]
    assert set(run["omit"].split()) == {
        "app/main.py",
        "app/**/__init__.py",
        "app/db/base_class.py",
        "app/db/session.py",
        "app/api/api.py",
        "scripts/*",
        "alembic/*",
        "tests/*",
    }

    workflow = yaml.load(
        TEST_WORKFLOW.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    shard_run = next(
        step["run"]
        for step in workflow["jobs"]["backend"]["steps"]
        if step["name"] == "Run backend shard with coverage"
    )
    combine_run = next(
        step["run"]
        for step in workflow["jobs"]["backend-coverage"]["steps"]
        if step["name"] == "Combine backend coverage"
    )

    assert "--cov-config=.coveragerc" in shard_run
    assert "coverage combine" in combine_run
    assert "coverage report --show-missing" in combine_run
    assert "coverage html" in combine_run
