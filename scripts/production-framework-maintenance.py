#!/usr/bin/env python3
"""Install the exact immutable production framework and emit fixed evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
MAINTENANCE_USER = "pastexam-framework-maintenance"

COMPONENTS = (
    ("deployment-controller", "scripts/production-deployment-control.py", "usr/local/sbin/pastexam-production-deployment-control", "0755"),
    ("activation-wrapper", "scripts/pastexam-activate-ssh-wrapper.sh", "usr/local/sbin/pastexam-activate-ssh-wrapper", "0755"),
    ("activation-engine", "scripts/activate-production-release.sh", "usr/local/libexec/pastexam-activate-production-release", "0700"),
    ("activation-contract", "scripts/production-activation-contract.py", "usr/local/libexec/pastexam-production-activation-contract.py", "0700"),
    ("postgres-backup", "scripts/postgres-logical-backup.sh", "usr/local/libexec/pastexam-postgres-logical-backup", "0700"),
    ("minio-preflight", "scripts/minio-storage-preflight.sh", "usr/local/libexec/pastexam-minio-storage-preflight", "0700"),
    ("minio-manifest", "scripts/minio-readonly-manifest.sh", "usr/local/libexec/pastexam-minio-readonly-manifest", "0700"),
    ("nginx-override", "docker/docker-compose.nginx-immutable.yml", "usr/local/libexec/pastexam-nginx-image-override.yml", "0600"),
    ("maintenance-wrapper", "scripts/pastexam-framework-maintenance-ssh-wrapper.sh", "usr/local/sbin/pastexam-framework-maintenance-ssh-wrapper", "0755"),
    ("maintenance-helper", "scripts/production-framework-maintenance.py", "usr/local/libexec/pastexam-production-framework-maintenance", "0700"),
)


class MaintenanceError(RuntimeError):
    """The fixed maintenance operation failed closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _roots() -> tuple[Path, Path, int, int]:
    if os.environ.get("PASTEXAM_FRAMEWORK_MAINTENANCE_TEST_MODE") == "1":
        if os.geteuid() == 0 or os.environ.get("SUDO_USER"):
            raise MaintenanceError("Production maintenance test authority is invalid.")
        root = Path(os.environ["PASTEXAM_FRAMEWORK_MAINTENANCE_TEST_ROOT"]).resolve()
        return root / "releases", root, os.getuid(), os.getgid()
    if os.geteuid() != 0 or os.environ.get("SUDO_USER") != MAINTENANCE_USER:
        raise MaintenanceError("Production maintenance authority is invalid.")
    return Path("/opt/pastexam-releases"), Path("/"), 0, 0


def _regular_safe(
    path: Path, *, owner_uid: int, owner_gid: int, mode: str | None = None
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise MaintenanceError("Required maintenance authority is unavailable.") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise MaintenanceError("Required maintenance authority is not a regular file.")
    if metadata.st_uid != owner_uid or metadata.st_gid != owner_gid:
        raise MaintenanceError("Required maintenance authority has an unsafe owner.")
    observed_mode = stat.S_IMODE(metadata.st_mode)
    if observed_mode & 0o022:
        raise MaintenanceError("Required maintenance authority has an unsafe mode.")
    if mode is not None and observed_mode != int(mode, 8):
        raise MaintenanceError("Installed maintenance authority has an unexpected mode.")
    return metadata


def _release(
    releases_root: Path, source_sha: str, owner_uid: int, owner_gid: int
) -> Path:
    if SHA.fullmatch(source_sha) is None:
        raise MaintenanceError("Source SHA is malformed.")
    release = releases_root / source_sha
    try:
        metadata = release.lstat()
        resolved = release.resolve(strict=True)
    except OSError as error:
        raise MaintenanceError("Immutable release is unavailable.") from error
    if release.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise MaintenanceError("Immutable release is not a regular directory.")
    if (
        resolved != release
        or metadata.st_uid != owner_uid
        or metadata.st_gid != owner_gid
    ):
        raise MaintenanceError("Immutable release authority is invalid.")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise MaintenanceError("Immutable release mode is unsafe.")
    marker = release / ".release-source-sha"
    _regular_safe(marker, owner_uid=owner_uid, owner_gid=owner_gid)
    if marker.read_text(encoding="utf-8").strip() != source_sha:
        raise MaintenanceError("Immutable release SHA disagrees.")
    return release


def _verify_manifest(release: Path, owner_uid: int, owner_gid: int) -> None:
    manifest = release / ".release-files.sha256"
    _regular_safe(manifest, owner_uid=owner_uid, owner_gid=owner_gid)
    seen: set[str] = set()
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise MaintenanceError("Release checksum manifest is unreadable.") from error
    if not lines:
        raise MaintenanceError("Release checksum manifest is empty.")
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\x00\r\n]+)", line)
        if match is None:
            raise MaintenanceError("Release checksum manifest is malformed.")
        expected, relative = match.groups()
        candidate = Path(relative)
        if candidate.is_absolute() or relative in seen or ".." in candidate.parts:
            raise MaintenanceError("Release checksum path is invalid.")
        seen.add(relative)
        path = release / candidate
        _regular_safe(path, owner_uid=owner_uid, owner_gid=owner_gid)
        if _sha256(path) != expected:
            raise MaintenanceError("Release checksum verification failed.")


def _target(root: Path, relative: str) -> Path:
    return root / relative if root != Path("/") else Path("/") / relative


def install(source_sha: str) -> dict[str, Any]:
    releases_root, target_root, owner_uid, owner_gid = _roots()
    release = _release(releases_root, source_sha, owner_uid, owner_gid)
    _verify_manifest(release, owner_uid, owner_gid)
    installer = release / "scripts/install-production-activation-framework.sh"
    _regular_safe(installer, owner_uid=owner_uid, owner_gid=owner_gid)
    for _, source_relative, _, _ in COMPONENTS:
        _regular_safe(
            release / source_relative,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
    environment = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
    }
    if target_root != Path("/"):
        environment.update(
            {
                "PASTEXAM_FRAMEWORK_INSTALL_TEST_MODE": "1",
                "PASTEXAM_FRAMEWORK_INSTALL_TEST_ROOT": str(target_root),
            }
        )
    result = subprocess.run(
        [str(installer), str(release), source_sha],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise MaintenanceError("Reviewed framework installer failed.")
    installed_files = []
    for component_id, source_relative, target_relative, expected_mode in COMPONENTS:
        source = release / source_relative
        target = _target(target_root, target_relative)
        metadata = _regular_safe(
            target,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            mode=expected_mode,
        )
        digest = _sha256(target)
        if digest != _sha256(source):
            raise MaintenanceError("Installed framework digest disagrees.")
        installed_files.append(
            {
                "id": component_id,
                "sha256": digest,
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "mode": expected_mode,
            }
        )
    return {
        "schema_version": 1,
        "source_sha": source_sha,
        "outcome": "installed",
        "installed_files": installed_files,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("Production framework maintenance failed closed.", file=sys.stderr)
        return 2
    try:
        print(json.dumps(install(sys.argv[1]), sort_keys=True, separators=(",", ":")))
    except (MaintenanceError, OSError, UnicodeError, KeyError, subprocess.SubprocessError):
        print("Production framework maintenance failed closed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
