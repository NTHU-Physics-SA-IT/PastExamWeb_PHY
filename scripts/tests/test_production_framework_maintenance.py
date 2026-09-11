from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "production-framework-maintenance.py"
VALIDATOR = ROOT / "scripts" / "validate-production-framework-installation.py"
WRAPPER = ROOT / "scripts" / "pastexam-framework-maintenance-ssh-wrapper.sh"
BOOTSTRAP = ROOT / "scripts" / "bootstrap-production-framework-maintenance-channel.sh"
INSTALLER = ROOT / "scripts" / "install-production-activation-framework.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "install-production-framework.yml"
SHA = "a" * 40


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _evidence(validator) -> dict:
    return {
        "schema_version": 1,
        "source_sha": SHA,
        "outcome": "installed",
        "installed_files": [
            {"id": component, "sha256": "b" * 64, "uid": 0, "gid": 0, "mode": mode}
            for component, mode in validator.COMPONENTS
        ],
    }


def test_install_helper_derives_release_and_returns_fixed_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _load(HELPER, "framework_maintenance_install")
    release = tmp_path / "releases" / SHA
    release.mkdir(parents=True)
    files = ["scripts/install-production-activation-framework.sh"] + [
        source for _, source, _, _ in helper.COMPONENTS
    ]
    for relative in files:
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"reviewed {relative}\n", encoding="utf-8")
        path.chmod(0o700 if relative.endswith((".py", ".sh")) else 0o600)
    (release / ".release-source-sha").write_text(f"{SHA}\n", encoding="utf-8")
    manifest_lines = []
    for relative in files:
        digest = hashlib.sha256((release / relative).read_bytes()).hexdigest()
        manifest_lines.append(f"{digest}  {relative}")
    (release / ".release-files.sha256").write_text(
        "\n".join(manifest_lines) + "\n", encoding="utf-8"
    )

    def fake_run(command, **kwargs):
        assert command == [
            str(release / "scripts/install-production-activation-framework.sh"),
            str(release),
            SHA,
        ]
        assert kwargs["capture_output"] is True
        for _, source, target, mode in helper.COMPONENTS:
            destination = tmp_path / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((release / source).read_bytes())
            destination.chmod(int(mode, 8))
        return subprocess.CompletedProcess(command, 0, "ignored", "ignored")

    monkeypatch.setenv("PASTEXAM_FRAMEWORK_MAINTENANCE_TEST_MODE", "1")
    monkeypatch.setenv("PASTEXAM_FRAMEWORK_MAINTENANCE_TEST_ROOT", str(tmp_path))
    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    evidence = helper.install(SHA)

    assert set(evidence) == {"schema_version", "source_sha", "outcome", "installed_files"}
    assert evidence["source_sha"] == SHA
    assert evidence["outcome"] == "installed"
    assert [item["id"] for item in evidence["installed_files"]] == [
        item[0] for item in helper.COMPONENTS
    ]
    assert all(set(item) == {"id", "sha256", "uid", "gid", "mode"} for item in evidence["installed_files"])


def test_install_helper_cli_rejects_extra_or_malformed_arguments() -> None:
    for arguments in ([], [SHA, "extra"], ["A" * 40], ["a" * 39], [f"{SHA};id"]):
        process = subprocess.run(
            [sys.executable, str(HELPER), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
        assert process.returncode == 2
        assert process.stdout == ""
        assert "failed closed" in process.stderr


def test_install_helper_rejects_test_override_under_root_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _load(HELPER, "framework_maintenance_test_override")
    monkeypatch.setenv("PASTEXAM_FRAMEWORK_MAINTENANCE_TEST_MODE", "1")
    monkeypatch.setenv("PASTEXAM_FRAMEWORK_MAINTENANCE_TEST_ROOT", str(tmp_path))
    monkeypatch.setattr(helper.os, "geteuid", lambda: 0)
    with pytest.raises(helper.MaintenanceError):
        helper._roots()


def test_maintenance_wrapper_allows_only_install_sha(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "sudo.json"
    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\nopen(os.environ['LOG'],'w').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    environment = os.environ.copy()
    environment.update({"PATH": f"{fake_bin}:{environment['PATH']}", "LOG": str(log)})

    environment["SSH_ORIGINAL_COMMAND"] = f"install {SHA}"
    accepted = subprocess.run(["/bin/bash", str(WRAPPER)], env=environment, check=False)
    assert accepted.returncode == 0
    assert json.loads(log.read_text(encoding="utf-8")) == [
        "-n",
        "/usr/local/libexec/pastexam-production-framework-maintenance",
        SHA,
    ]

    for command in (
        "",
        "install",
        f"install {SHA} extra",
        f"install {'A' * 40}",
        f"install {SHA};id",
        f"install {SHA}\nid",
        f"status {SHA}",
        "bash",
    ):
        log.unlink(missing_ok=True)
        environment["SSH_ORIGINAL_COMMAND"] = command
        rejected = subprocess.run(
            ["/bin/bash", str(WRAPPER)], env=environment, capture_output=True, check=False
        )
        assert rejected.returncode == 2
        assert not log.exists()


def test_evidence_validator_is_exact_and_fail_closed(tmp_path: Path) -> None:
    validator = _load(VALIDATOR, "framework_maintenance_validator")
    valid = _evidence(validator)
    assert validator.validate(valid, SHA) == valid

    invalid_documents = [
        {**valid, "raw_stderr": "secret"},
        {**valid, "source_sha": "c" * 40},
        {**valid, "schema_version": True},
        {**valid, "outcome": "partial"},
        {**valid, "installed_files": valid["installed_files"][:-1]},
        {
            **valid,
            "installed_files": [
                {**valid["installed_files"][0], "id": "/usr/local/secret"},
                *valid["installed_files"][1:],
            ],
        },
        {
            **valid,
            "installed_files": [
                {**valid["installed_files"][0], "mode": "0777"},
                *valid["installed_files"][1:],
            ],
        },
        {
            **valid,
            "installed_files": [
                {**valid["installed_files"][0], "id": ["not", "hashable"]},
                *valid["installed_files"][1:],
            ],
        },
    ]
    for document in invalid_documents:
        with pytest.raises(validator.EvidenceError):
            validator.validate(document, SHA)

    raw = tmp_path / "raw.json"
    output = tmp_path / "validated.json"
    raw.write_text(json.dumps(valid), encoding="utf-8")
    process = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--input",
            str(raw),
            "--output",
            str(output),
            "--expected-sha",
            SHA,
        ],
        check=False,
    )
    assert process.returncode == 0
    assert json.loads(output.read_text(encoding="utf-8")) == valid
    assert output.stat().st_mode & 0o777 == 0o600


def test_workflow_is_manual_protected_exact_main_install_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    document = yaml.safe_load(source)
    trigger = document.get("on", document.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert set(trigger["workflow_dispatch"]["inputs"]) == {"target_sha"}
    assert document["concurrency"]["group"] == "production-activation"
    install_job = document["jobs"]["install"]
    assert install_job["environment"] == "production"
    assert "validate_production_deploy_authority.py" in source
    assert "validate_candidate_source_run.py" in source
    assert "validate_activation_authority.py" in source
    assert '"install $TARGET_SHA"' in source
    assert "validate-production-framework-installation.py" in source
    assert "PRODUCTION_FRAMEWORK_MAINTENANCE_SSH_PRIVATE_KEY" in source
    for forbidden in (
        "docker compose up",
        "docker compose down",
        "docker compose run",
        "docker compose pull",
        "migrate.py upgrade",
        "alembic upgrade",
        '"preflight $TARGET_SHA',
        '"start $TARGET_SHA',
        "rollback-start",
    ):
        assert forbidden not in source


def test_bootstrap_and_installer_grant_only_digest_bound_maintenance() -> None:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    assert '[ "$#" -eq 1 ]' in bootstrap
    assert 'release_root="/opt/pastexam-releases/$source_sha"' in bootstrap
    assert "pastexam-framework-maintenance-authorized-key.pub" in bootstrap
    assert 'restrict,command="%s"' in bootstrap
    assert '--shell "$wrapper"' in bootstrap
    assert '[ "$(id -nG "$account")" = "$account" ]' in bootstrap
    assert "sha256:%s %s *" in bootstrap
    assert "NOPASSWD: ALL" not in bootstrap
    assert "NOPASSWD: ALL" not in installer
    assert "pastexam-production-framework-maintenance" in installer
    assert "maintenance_digest" in installer
    for source in (bootstrap, installer, HELPER.read_text(encoding="utf-8")):
        for forbidden in (
            "docker compose up",
            "docker compose down",
            "docker compose run",
            "docker compose pull",
            "docker restart",
            "systemctl restart",
            "migrate.py upgrade",
            "alembic upgrade",
        ):
            assert forbidden not in source
