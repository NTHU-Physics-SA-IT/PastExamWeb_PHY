from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTIVATE = ROOT / ".github" / "workflows" / "activate-production.yml"
ROLLBACK = ROOT / ".github" / "workflows" / "rollback-production.yml"
AUTHORITY = ROOT / "scripts" / "ci" / "validate_activation_authority.py"
MERGER_BOUND = ROOT / "scripts" / "ci" / "validate_merger_bound_deploy.py"
INSTALLER = ROOT / "scripts" / "install-production-activation-framework.sh"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
CLASSIFIER = ROOT / "scripts" / "ci" / "classify_ci_mode.py"
EXPECTED_SECRETS = {
    "PRODUCTION_ACTIVATION_HOST",
    "PRODUCTION_ACTIVATION_KNOWN_HOSTS",
    "PRODUCTION_ACTIVATION_SSH_PRIVATE_KEY",
    "PRODUCTION_ACTIVATION_USER",
}


def _load_authority():
    sys.path.insert(0, str(AUTHORITY.parent))
    try:
        spec = importlib.util.spec_from_file_location("activation_authority", AUTHORITY)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _load_classifier():
    sys.path.insert(0, str(CLASSIFIER.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "stageb_ci_classifier", CLASSIFIER
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize(
    ("workflow", "expected_permissions"),
    [
        (
            ACTIVATE,
            {"actions": "read", "contents": "read", "pull-requests": "read"},
        ),
        (ROLLBACK, {"actions": "read", "contents": "read"}),
    ],
)
def test_production_workflows_are_manual_protected_and_non_cancelling(
    workflow: Path, expected_permissions: dict[str, str]
) -> None:
    source = workflow.read_text(encoding="utf-8")
    document = yaml.safe_load(source)
    trigger = document.get("on", document.get(True))

    assert set(trigger) == {"workflow_dispatch"}
    assert document["permissions"] == expected_permissions
    assert document["concurrency"] == {
        "group": "production-activation",
        "cancel-in-progress": False,
    }
    assert "environment: production" in source
    assert "secrets: inherit" not in source
    assert "pull_request" not in trigger
    assert (
        set(re.findall(r"secrets\.(PRODUCTION_ACTIVATION_[A-Z_]+)", source))
        == EXPECTED_SECRETS
    )


def test_activation_workflow_enforces_exact_main_twice_and_starts_once() -> None:
    source = ACTIVATE.read_text(encoding="utf-8")

    assert source.count("git rev-parse origin/main") >= 2
    assert source.count('"start $TARGET_SHA') == 1
    assert "request-status $request_id" in source
    assert "resume $request_id" in source
    assert "poll_count % 6" in source
    assert "production-deployment-receipt" in source
    assert "vars.PRODUCTION_DEPLOY_ENABLED" not in source
    assert source.rfind("git fetch --no-tags origin main") > source.find(
        '"preflight $TARGET_SHA'
    )
    assert source.rfind("git fetch --no-tags origin main") < source.find(
        '"start $TARGET_SHA'
    )


def test_activation_revalidates_merger_bound_authority_before_production_ssh() -> None:
    source = ACTIVATE.read_text(encoding="utf-8")
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    authority_steps = workflow["jobs"]["authority"]["steps"]
    activate_steps = workflow["jobs"]["activate"]["steps"]

    assert MERGER_BOUND.is_file()
    assert source.count("validate_merger_bound_deploy.py") == 2
    assert "--actor \"$ORIGINAL_ACTOR\"" in source
    assert "--triggering-actor \"$TRIGGERING_ACTOR\"" in source
    assert "--target-sha \"$TARGET_SHA\"" in source
    assert "--token" not in source

    first_gate = next(
        index
        for index, step in enumerate(authority_steps)
        if "validate_merger_bound_deploy.py" in step.get("run", "")
    )
    exact_main_lock = next(
        index
        for index, step in enumerate(authority_steps)
        if step["name"] == "Require workflow source and target to be exact current main"
    )
    assert first_gate == exact_main_lock + 1

    second_gate = next(
        index
        for index, step in enumerate(activate_steps)
        if "validate_merger_bound_deploy.py" in step.get("run", "")
    )
    relock = next(
        index
        for index, step in enumerate(activate_steps)
        if step["name"] == "Re-lock current main and Main Full after approval"
    )
    ssh_setup = next(
        index
        for index, step in enumerate(activate_steps)
        if step["name"] == "Configure restricted production SSH identity"
    )
    assert relock < second_gate < ssh_setup
    for steps, gate in ((authority_steps, first_gate), (activate_steps, second_gate)):
        env = steps[gate]["env"]
        assert env["GITHUB_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
        assert env["ORIGINAL_ACTOR"] == "${{ github.actor }}"
        assert env["TRIGGERING_ACTOR"] == "${{ github.triggering_actor }}"


def test_rollback_is_separate_explicit_and_never_automatic() -> None:
    activation = ACTIVATE.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")

    assert "rollback-start" not in activation
    assert rollback.count('"rollback-start $TARGET_SHA') == 1
    assert "rollback-preflight" in rollback
    assert "finalization-retry-required" in rollback
    assert '"resume $request_id"' in rollback
    assert "poll_count % 6" in rollback
    assert rollback.rfind("git fetch --no-tags origin main") > rollback.find(
        '"rollback-preflight $TARGET_SHA'
    )
    assert rollback.rfind("git fetch --no-tags origin main") < rollback.find(
        '"rollback-start $TARGET_SHA'
    )
    assert "alembic downgrade" not in rollback.lower()


def test_stage_b_control_plane_is_always_full_ci_and_its_tests_are_wired() -> None:
    classifier = _load_classifier()
    governed_paths = {
        "scripts/activate-production-release.sh",
        "scripts/install-production-activation-framework.sh",
        "scripts/pastexam-activate-ssh-wrapper.sh",
        "scripts/production-activation-contract.py",
        "scripts/production-deployment-control.py",
    }
    assert all(classifier.is_governance_path(path) for path in governed_paths)

    test_workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
    for test_name in (
        "test_production_activation_contract.py",
        "test_production_activation_ssh_wrapper.py",
        "test_merger_bound_deploy_authority.py",
        "test_production_activation_workflow_contract.py",
        "test_production_deployment_control.py",
    ):
        assert test_name in test_workflow


def test_host_installer_grants_only_digest_bound_controller_authority() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "sha256:%s %s *" in source
    assert "/usr/local/sbin/pastexam-production-deployment-control" in source
    assert "NOPASSWD: ALL" not in source
    assert "usermod" not in source
    assert "useradd" not in source
    assert "systemctl restart" not in source
    assert "docker compose up" not in source
    assert "pastexam-nginx-image-override.yml" in source


def _artifacts(tmp_path: Path):
    sha = "a" * 40
    frontend = "sha256:" + "1" * 64
    backend = "sha256:" + "2" * 64
    nginx = "sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903"
    checksum = "3" * 64
    image_authority = tmp_path / "production-image-authority.env"
    image_authority.write_text(
        f"source_sha={sha}\nfrontend_digest={frontend}\nbackend_digest={backend}\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": 1,
        "kind": "production-candidate-preparation",
        "source_sha": sha,
        "workflow_run_id": 10,
        "workflow_run_attempt": 1,
        "source_ci_run_id": 20,
        "source_ci_run_attempt": 1,
        "prepared_at": "2026-09-01T00:00:00Z",
        "image_digests": {"frontend": frontend, "backend": backend, "nginx": nginx},
        "package_sha256": checksum,
        "release_files_sha256": checksum,
        "release_manifest_sha256": "4" * 64,
        "release_id": sha,
        "release_path": f"releases/{sha}",
        "outcome": "verified",
    }
    receipt_path = tmp_path / "candidate-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return sha, receipt_path, image_authority


def test_activation_authority_binds_source_run_receipt_and_images(
    tmp_path: Path,
) -> None:
    module = _load_authority()
    sha, receipt, image_authority = _artifacts(tmp_path)

    result = module.validate_activation_authority(receipt, image_authority, sha, 20, 1)

    assert result["release_sha"] == sha
    assert result["candidate_receipt_sha256"]
    assert result["nginx_digest"] == module.NGINX_DIGEST

    with pytest.raises(module.ActivationAuthorityError, match="Source Full"):
        module.validate_activation_authority(receipt, image_authority, sha, 21, 1)


def test_legacy_two_image_receipt_is_allowed_only_with_exact_rollback_nginx(
    tmp_path: Path,
) -> None:
    module = _load_authority()
    sha, receipt_path, image_authority = _artifacts(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["image_digests"].pop("nginx")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    compose = tmp_path / "legacy-compose.yml"
    compose.write_text(
        "services:\n  nginx:\n    image: nginx:1.29.2\n  backend:\n    image: ignored\n",
        encoding="utf-8",
    )

    result = module.validate_activation_authority(
        receipt_path, image_authority, sha, 20, 1, compose
    )
    assert result["nginx_digest"] == module.NGINX_DIGEST

    with pytest.raises(module.ActivationAuthorityError, match="not supplied"):
        module.validate_activation_authority(receipt_path, image_authority, sha, 20, 1)
