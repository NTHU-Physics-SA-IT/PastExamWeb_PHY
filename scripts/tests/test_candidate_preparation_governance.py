import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / ".github" / "workflows" / "main.yml"
PREPARE = ROOT / ".github" / "workflows" / "deploy.yml"
MANUAL = ROOT / ".github" / "workflows" / "prepare-production-candidate.yml"
ACTIVATE = ROOT / ".github" / "workflows" / "activate-production.yml"
HOST_COMMAND = ROOT / "scripts" / "prepare-production-candidate.sh"
INSTALLER = ROOT / "scripts" / "install-production-activation-framework.sh"
PACKAGER = ROOT / "scripts" / "package-production-candidate.sh"
RUNBOOK = ROOT / "docs" / "runbooks" / "production-candidate-preparation.md"
RECEIPT_MODULE = ROOT / "scripts" / "ci" / "validate_candidate_receipt.py"
SOURCE_MODULE = ROOT / "scripts" / "ci" / "validate_candidate_source_run.py"
WORKFLOWS = ROOT / ".github" / "workflows"
LEGACY_SSH_WORKFLOW = WORKFLOWS / "test-digitalocean-ssh.yml"
LEGACY_DO_SECRETS = (
    "DO_HOST",
    "DO_KNOWN_HOSTS",
    "DO_SSH_PRIVATE_KEY",
    "DO_USER",
)
FRAMEWORK_SOURCE_AUTHORITIES = (
    "scripts/production-deployment-control.py",
    "scripts/pastexam-activate-ssh-wrapper.sh",
    "scripts/activate-production-release.sh",
    "scripts/production-activation-contract.py",
    "scripts/postgres-logical-backup.sh",
    "scripts/minio-storage-preflight.sh",
    "scripts/minio-readonly-manifest.sh",
    "docker/docker-compose.nginx-immutable.yml",
)
EXECUTABLE_FRAMEWORK_SOURCES = frozenset(
    path
    for path in FRAMEWORK_SOURCE_AUTHORITIES
    if path != "scripts/production-activation-contract.py"
    and path != "docker/docker-compose.nginx-immutable.yml"
)


def _yaml(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_authorities(path: Path) -> tuple[str, ...]:
    match = re.search(
        r"(?ms)^source_authorities=\(\n(?P<body>.*?)^\)$",
        path.read_text(encoding="utf-8"),
    )
    assert match is not None
    return tuple(line.strip() for line in match.group("body").splitlines())


def test_automatic_candidate_control_and_explicit_secrets() -> None:
    job = _yaml(MAIN)["jobs"]["prepare_production_candidate"]
    assert "vars.AUTO_PREPARE_PRODUCTION_CANDIDATE == 'true'" in job["if"]
    assert "github.event_name == 'push'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert "PRODUCTION_DEPLOY_ENABLED" not in job["if"]
    assert job["uses"] == "./.github/workflows/deploy.yml"
    assert set(job["secrets"]) == {
        "candidate_ssh_private_key",
        "candidate_known_hosts",
        "candidate_host",
        "candidate_user",
    }
    assert job["secrets"] != "inherit"


def test_candidate_workflow_has_candidate_only_boundary() -> None:
    source = PREPARE.read_text(encoding="utf-8")
    workflow = _yaml(PREPARE)
    job = workflow["jobs"]["prepare"]
    steps = job["steps"]
    names = [step["name"] for step in steps]
    assert set(workflow["on"]) == {"workflow_call"}
    assert job["environment"] == "production-candidate"
    activation_jobs = _yaml(ACTIVATE)["jobs"]
    assert activation_jobs["authority"].get("environment") is None
    assert activation_jobs["activate"]["environment"] == "production"
    assert names.index("Fail-closed host capacity preflight") < names.index(
        "Upload through fixed candidate entrypoint"
    )
    assert "/usr/local/sbin/pastexam-prepare-candidate preflight" in source
    assert "/usr/local/sbin/pastexam-prepare-candidate upload" in source
    assert "/usr/local/sbin/pastexam-prepare-candidate prepare" in source
    assert "/usr/local/sbin/pastexam-prepare-candidate cleanup" in source
    assert "bash -s" not in source
    assert "scp " not in source
    assert "secrets: inherit" not in source
    assert "PRODUCTION_DEPLOY_ENABLED" not in source
    assert "activate-production-release" not in source


def test_candidate_receipt_validation_receives_immutable_nginx_authority() -> None:
    steps = _yaml(PREPARE)["jobs"]["prepare"]["steps"]
    validation_step = next(
        step for step in steps if step["name"] == "Prepare and verify immutable candidate"
    )
    nginx_digest = validation_step["env"]["NGINX_IMAGE_DIGEST"]

    assert nginx_digest.startswith("sha256:")
    assert len(nginx_digest) == len("sha256:") + 64
    assert '--nginx-digest "$NGINX_IMAGE_DIGEST"' in validation_step["run"]


def test_legacy_generic_ssh_and_broad_secret_inheritance_are_absent() -> None:
    assert not LEGACY_SSH_WORKFLOW.exists()
    for workflow_path in WORKFLOWS.glob("*.y*ml"):
        source = workflow_path.read_text(encoding="utf-8")
        assert "secrets: inherit" not in source
        for secret_name in LEGACY_DO_SECRETS:
            assert secret_name not in source


def test_activation_workflow_keeps_mutation_behind_production_environment() -> None:
    source = ACTIVATE.read_text(encoding="utf-8")
    assert "environment: production" in source
    assert "workflow_dispatch:" in source
    assert "pastexam-production-deployment-control" not in source
    assert "pastexam-activate-production-release" not in source
    assert "docker compose" not in source
    assert "ssh " in source
    assert " start " in source


def test_candidate_source_has_no_active_service_or_data_mutation() -> None:
    source = (
        PREPARE.read_text(encoding="utf-8") + HOST_COMMAND.read_text(encoding="utf-8")
    ).lower()
    forbidden = (
        "docker compose up",
        "docker compose down",
        "docker compose restart",
        "docker compose pull",
        "alembic upgrade",
        "set_bucket_versioning",
        ".activated",
        "current-release",
        "production_backend_env",
        "mc admin",
        "mc rm",
        "redis-cli",
        "psql ",
    )
    for token in forbidden:
        assert token not in source
    assert "docker compose" in source
    assert "config --quiet" in source


def test_retention_is_governance_only() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    host_source = HOST_COMMAND.read_text(encoding="utf-8")
    for invariant in (
        "active release",
        "previous known-good rollback release",
        "pinned audit/evidence release",
        "newest ten unactivated candidates",
    ):
        assert invariant in runbook
    assert "never an automatic candidate job" in runbook
    assert 'find "$releases_root"' not in host_source
    assert 'rm -rf -- "$release_root"' not in host_source


def test_manual_and_automatic_paths_converge() -> None:
    main_job = _yaml(MAIN)["jobs"]["prepare_production_candidate"]
    manual = _yaml(MANUAL)
    manual_job = manual["jobs"]["prepare"]
    assert main_job["uses"] == manual_job["uses"] == "./.github/workflows/deploy.yml"
    assert set(manual["on"]) == {"workflow_dispatch"}
    authority_run = "\n".join(
        step.get("run", "") for step in manual["jobs"]["authority"]["steps"]
    )
    assert "git merge-base --is-ancestor" in authority_run
    assert 'test "$WORKFLOW_REF" = "refs/heads/main"' in authority_run
    assert 'test "$(git rev-parse origin/main)" = "$WORKFLOW_SHA"' in authority_run
    assert "validate_candidate_source_run.py" in authority_run
    assert "imagetools inspect" in authority_run
    manual_source = MANUAL.read_text(encoding="utf-8")
    assert "production-image-authority-${{ inputs.release_sha }}" in manual_source
    assert 'test "$observed" = "$expected"' in manual_source


def test_host_command_is_fixed_and_fail_closed() -> None:
    source = HOST_COMMAND.read_text(encoding="utf-8")
    assert "minimum_available_bytes=$((10 * 1024 * 1024 * 1024))" in source
    assert "minimum_available_percent=20" in source
    assert "minimum_available_inodes=100000" in source
    assert "minimum_inode_percent=10" in source
    assert "maximum_archive_bytes=$((256 * 1024 * 1024))" in source
    assert "Filesystem capacity metrics are unavailable." in source
    assert "Candidate disk capacity is below the fail-closed threshold." in source
    assert "Candidate inode capacity is below the fail-closed threshold." in source
    assert "releases_root=/opt/pastexam-releases" in source
    assert 'archive="/tmp/pastexam-$release_sha-$run_id.tar.gz"' in source
    assert "RELEASES_ROOT:-" not in source
    assert "PRODUCTION_COMPOSE_ENV_FILE:-" not in source
    assert "flock -n 9" in source
    assert "Another candidate preparation is active." in source
    assert "pathlib.PurePosixPath" in source
    assert "member.issym()" in source
    assert "member.islnk()" in source


def test_candidate_and_installer_share_framework_source_mode_contract() -> None:
    assert _source_authorities(HOST_COMMAND) == FRAMEWORK_SOURCE_AUTHORITIES
    assert _source_authorities(INSTALLER) == FRAMEWORK_SOURCE_AUTHORITIES
    source = HOST_COMMAND.read_text(encoding="utf-8")
    assert source.count("verify_framework_source_authorities") >= 2
    assert "stat -c '%u' \"$candidate_root\"" in source
    assert "has an unexpected owner" in source
    assert "8#$source_mode & 8#022" in source
    assert "-c tar.umask=0022 archive" in PACKAGER.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="candidate packaging is Linux-only")
def test_candidate_package_normalizes_git_archive_modes(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    package = scripts / PACKAGER.name
    package.write_text(PACKAGER.read_text(encoding="utf-8"), encoding="utf-8")
    package.chmod(0o755)
    for relative in FRAMEWORK_SOURCE_AUTHORITIES:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture for {relative}\n", encoding="utf-8")
        path.chmod(0o775 if relative in EXECUTABLE_FRAMEWORK_SOURCES else 0o664)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Candidate Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True
    )
    sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()

    unsafe_archive = tmp_path / "unsafe.tar"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "tar.umask=0002",
            "archive",
            "--format=tar",
            f"--output={unsafe_archive}",
            sha,
        ],
        check=True,
    )
    with tarfile.open(unsafe_archive) as bundle:
        for relative in FRAMEWORK_SOURCE_AUTHORITIES:
            expected = (
                0o775 if relative in EXECUTABLE_FRAMEWORK_SOURCES else 0o664
            )
            assert bundle.getmember(relative).mode == expected

    candidate = tmp_path / "candidate.tar.gz"
    result = subprocess.run(
        ["bash", str(package)],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ
        | {"RELEASE_SHA": sha, "OUTPUT_ARCHIVE": str(candidate)},
    )
    assert result.returncode == 0, result.stderr
    with tarfile.open(candidate, "r:gz") as bundle:
        for relative in FRAMEWORK_SOURCE_AUTHORITIES:
            expected = (
                0o755 if relative in EXECUTABLE_FRAMEWORK_SOURCES else 0o644
            )
            assert bundle.getmember(relative).mode == expected
        manifest = bundle.extractfile(".release-files.sha256")
        assert manifest is not None
        for line in manifest.read().decode().splitlines():
            checksum, separator, relative = line.partition("  ")
            assert separator
            assert hashlib.sha256((repository / relative).read_bytes()).hexdigest() == (
                checksum
            )


@pytest.mark.skipif(os.name == "nt", reason="host command is Linux-only")
@pytest.mark.parametrize(
    ("disk_line", "inode_line", "expected"),
    [
        (
            "fake 20000000 5000000 15000000 25% /",
            "fake 1000000 100000 900000 10% /",
            None,
        ),
        (
            "fake 20000000 19999000 1000 99% /",
            "fake 1000000 100000 900000 10% /",
            "disk capacity",
        ),
        (
            "fake 100000000 85000000 15000000 85% /",
            "fake 1000000 100000 900000 10% /",
            "disk capacity",
        ),
        (
            "fake 20000000 5000000 15000000 25% /",
            "fake 1000000 900001 99999 90% /",
            "inode capacity",
        ),
        (
            "fake 20000000 5000000 15000000 25% /",
            "fake 2000000 1850000 150000 93% /",
            "inode capacity",
        ),
        ("malformed", "malformed", "unavailable"),
    ],
)
def test_host_capacity_preflight_is_fail_closed(
    tmp_path: Path, disk_line: str, inode_line: str, expected: str | None
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_df = fake_bin / "df"
    fake_df.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "-Pk" ]; then
  printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n%s\\n' "$DISK_LINE"
else
  printf 'Filesystem Inodes IUsed IFree IUse%% Mounted on\\n%s\\n' "$INODE_LINE"
fi
""",
        encoding="utf-8",
    )
    fake_df.chmod(0o755)
    env = os.environ | {
        "DISK_LINE": disk_line,
        "INODE_LINE": inode_line,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "PASTEXAM_CANDIDATE_TEST_MODE": "1",
        "PASTEXAM_CANDIDATE_TEST_RELEASES_ROOT": str(tmp_path),
        "PASTEXAM_CANDIDATE_TEST_COMPOSE_ENV": str(tmp_path / "compose.env"),
    }
    result = subprocess.run(
        ["bash", str(HOST_COMMAND), "preflight"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    if expected is None:
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["outcome"] == "capacity-verified"
        assert payload["available_bytes"] == 15000000 * 1024
    else:
        assert result.returncode != 0
        assert expected in result.stderr.lower()


@pytest.mark.skipif(os.name == "nt", reason="host command is Linux-only")
def test_host_command_prepares_receipt_and_reuses_only_exact_candidate(
    tmp_path: Path,
) -> None:
    sha = "1" * 40
    digest = "sha256:" + "2" * 64
    source = tmp_path / "source"
    compose = source / "docker" / "docker-compose.prod.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services: {}\n", encoding="utf-8")
    for relative in FRAMEWORK_SOURCE_AUTHORITIES:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture for {relative}\n", encoding="utf-8")
        path.chmod(0o755 if relative in EXECUTABLE_FRAMEWORK_SOURCES else 0o644)
    tracked = sorted(
        path for path in source.rglob("*") if path.is_file()
    )
    files_manifest = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
        f"{path.relative_to(source).as_posix()}\n"
        for path in tracked
    )
    (source / ".release-source-sha").write_text(sha + "\n", encoding="utf-8")
    (source / ".release-files.sha256").write_text(files_manifest, encoding="utf-8")
    archive = tmp_path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for path in source.rglob("*"):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(source).as_posix())
    package_checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    files_checksum = hashlib.sha256(files_manifest.encode()).hexdigest()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_df = fake_bin / "df"
    fake_df.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "-Pk" ]; then
  echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'
  echo 'fake 20000000 5000000 15000000 25% /'
else
  echo 'Filesystem Inodes IUsed IFree IUse% Mounted on'
  echo 'fake 1000000 100000 900000 10% /'
fi
""",
        encoding="utf-8",
    )
    fake_df.chmod(0o755)
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env python3
import pathlib, sys
args = sys.argv[1:]
if "--images" in args:
    env_files = [args[index + 1] for index, value in enumerate(args) if value == "--env-file"]
    values = pathlib.Path(env_files[-1]).read_text(encoding="utf-8").splitlines()
    for line in values:
        if line.startswith(("FRONTEND_IMAGE=", "BACKEND_IMAGE=")):
            print(line.split("=", 1)[1])
    print("nginx:1.29.2@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903")
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    compose_env = tmp_path / "compose.env"
    compose_env.write_text("SAFE_TEST_ONLY=1\n", encoding="utf-8")
    releases = tmp_path / "releases"
    releases.mkdir()
    env = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "PASTEXAM_CANDIDATE_TEST_MODE": "1",
        "PASTEXAM_CANDIDATE_TEST_RELEASES_ROOT": str(releases),
        "PASTEXAM_CANDIDATE_TEST_COMPOSE_ENV": str(compose_env),
    }

    def prepare(
        run_id: int, *, expect_success: bool = True
    ) -> dict | subprocess.CompletedProcess[str]:
        upload = Path(f"/tmp/pastexam-{sha}-{run_id}.tar.gz")
        try:
            uploaded = subprocess.run(
                [
                    "bash",
                    str(HOST_COMMAND),
                    "upload",
                    sha,
                    str(run_id),
                    package_checksum,
                ],
                input=archive.read_bytes(),
                check=False,
                capture_output=True,
                env=env,
            )
            assert uploaded.returncode == 0, uploaded.stderr.decode()
            assert json.loads(uploaded.stdout)["outcome"] == "upload-verified"
            result = subprocess.run(
                [
                    "bash",
                    str(HOST_COMMAND),
                    "prepare",
                    sha,
                    str(run_id),
                    "1",
                    "42",
                    "1",
                    digest,
                    digest,
                    package_checksum,
                    files_checksum,
                ],
                check=False,
                capture_output=True,
                env=env,
                text=True,
            )
            if expect_success:
                assert result.returncode == 0, result.stderr
                return json.loads(result.stdout)
            return result
        finally:
            upload.unlink(missing_ok=True)

    first = prepare(100)
    second = prepare(101)
    assert first == second
    assert first["outcome"] == "verified"
    assert first["release_path"] == f"releases/{sha}"
    candidate = releases / sha
    assert (candidate / "candidate-receipt.sha256").is_file()
    assert not (candidate / ".activated").exists()
    for relative in FRAMEWORK_SOURCE_AUTHORITIES:
        mode = stat.S_IMODE((candidate / relative).stat().st_mode)
        assert mode & 0o022 == 0
        assert bool(mode & 0o111) == (relative in EXECUTABLE_FRAMEWORK_SOURCES)

    unsafe = candidate / FRAMEWORK_SOURCE_AUTHORITIES[0]
    unsafe.chmod(stat.S_IMODE(unsafe.stat().st_mode) | stat.S_IWGRP)
    group_writable = prepare(102, expect_success=False)
    assert isinstance(group_writable, subprocess.CompletedProcess)
    assert group_writable.returncode != 0
    assert "writable by an unsafe role" in group_writable.stderr

    unsafe.chmod((stat.S_IMODE(unsafe.stat().st_mode) & ~stat.S_IWGRP) | stat.S_IWOTH)
    world_writable = prepare(103, expect_success=False)
    assert isinstance(world_writable, subprocess.CompletedProcess)
    assert world_writable.returncode != 0
    assert "writable by an unsafe role" in world_writable.stderr

    unsafe.chmod(stat.S_IMODE(unsafe.stat().st_mode) & ~stat.S_IWOTH)
    original = unsafe.read_bytes()
    sibling = unsafe.with_name(unsafe.name + ".fixture")
    sibling.write_bytes(original)
    unsafe.unlink()
    unsafe.symlink_to(sibling.name)
    symlinked = prepare(104, expect_success=False)
    assert isinstance(symlinked, subprocess.CompletedProcess)
    assert symlinked.returncode != 0
    assert "not a regular file" in symlinked.stderr


def _receipt() -> tuple[dict, dict[str, str]]:
    sha = "a" * 40
    digest = "sha256:" + "b" * 64
    checksum = "c" * 64
    expected = {
        "release_sha": sha,
        "frontend_digest": digest,
        "backend_digest": digest,
        "nginx_digest": "sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903",
        "source_archive_sha256": checksum,
        "release_files_sha256": checksum,
    }
    receipt = {
        "schema_version": 1,
        "kind": "production-candidate-preparation",
        "source_sha": sha,
        "workflow_run_id": 1,
        "workflow_run_attempt": 1,
        "source_ci_run_id": 2,
        "source_ci_run_attempt": 1,
        "prepared_at": "2026-08-31T00:00:00Z",
        "image_digests": {
            "frontend": digest,
            "backend": digest,
            "nginx": expected["nginx_digest"],
        },
        "package_sha256": checksum,
        "release_files_sha256": checksum,
        "release_manifest_sha256": checksum,
        "release_id": sha,
        "release_path": f"releases/{sha}",
        "outcome": "verified",
    }
    return receipt, expected


def test_candidate_receipt_is_exact_and_secret_free() -> None:
    module = _load(RECEIPT_MODULE, "candidate_receipt")
    receipt, expected = _receipt()
    module.validate_receipt(receipt, expected)
    assert not ({"secret", "token", "access_key", "host", "user"} & set(receipt))
    receipt["release_path"] = "/opt/pastexam-releases/" + expected["release_sha"]
    with pytest.raises(module.ReceiptError):
        module.validate_receipt(receipt, expected)


def test_manual_authority_requires_one_exact_full_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load(SOURCE_MODULE, "candidate_source")
    sha = "d" * 40
    responses = iter(
        [
            {
                "workflow_runs": [
                    {
                        "id": 42,
                        "run_attempt": 2,
                        "head_sha": sha,
                        "head_branch": "main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
            {
                "jobs": [
                    {"name": name, "conclusion": "success"}
                    for name in module.REQUIRED_SUCCESSFUL_JOBS
                ]
            },
        ]
    )
    monkeypatch.setattr(module, "_request_json", lambda _url, _token: next(responses))
    assert module.resolve_authority("owner/repo", sha, "token", "https://api") == (
        42,
        2,
    )


def test_manual_authority_rejects_non_full_run(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load(SOURCE_MODULE, "candidate_source_missing")
    sha = "e" * 40
    responses = iter(
        [
            {
                "workflow_runs": [
                    {
                        "id": 7,
                        "run_attempt": 1,
                        "head_sha": sha,
                        "head_branch": "main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
            {"jobs": [{"name": "CI Gate", "conclusion": "success"}]},
        ]
    )
    monkeypatch.setattr(module, "_request_json", lambda _url, _token: next(responses))
    with pytest.raises(module.AuthorityError):
        module.resolve_authority("owner/repo", sha, "token", "https://api")
