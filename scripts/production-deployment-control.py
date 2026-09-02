#!/usr/bin/env python3
"""Root-owned, fail-closed production deployment state and control plane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{7,79}$")
REVISION_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}$")
ACTIVATION_FAILURE_STAGES = frozenset(
    {
        "startup",
        "helper-authority",
        "external-config",
        "candidate-contract",
        "compose-structure",
        "image-contract",
        "production-values",
        "runtime-compose-config",
        "ingress-contract",
        "persistent-services",
        "postgres-readiness",
        "redis-readiness",
        "minio-preflight",
        "class-zero-before",
        "postgres-backup",
        "minio-manifest",
        "class-zero-after",
        "application-cutover",
        "internal-health",
        "external-health",
        "bounded-observation",
        "activation-marker",
        "engine-evidence",
    }
)
NGINX_DIGEST = "sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903"
CANDIDATE_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "source_sha",
        "workflow_run_id",
        "workflow_run_attempt",
        "source_ci_run_id",
        "source_ci_run_attempt",
        "prepared_at",
        "image_digests",
        "package_sha256",
        "release_files_sha256",
        "release_manifest_sha256",
        "release_id",
        "release_path",
        "outcome",
    }
)
TERMINAL_STATES = frozenset({"ACTIVE", "FAILED", "ROLLED_BACK"})
LEGAL_TRANSITIONS = {
    "PREPARED": frozenset({"ACTIVATING", "ROLLING_BACK", "FAILED"}),
    "ACTIVATING": frozenset({"ACTIVE", "FAILED"}),
    "ROLLING_BACK": frozenset({"ROLLED_BACK", "FAILED"}),
    "ACTIVE": frozenset(),
    "FAILED": frozenset(),
    "ROLLED_BACK": frozenset(),
}
ACTIVE_KEYS = frozenset(
    {
        "schema_version",
        "active_sha",
        "active_release_directory",
        "manifest_sha256",
        "activation_request_id",
        "activation_workflow",
        "activated_at",
        "database_revision",
        "previous_active_sha",
        "receipt_reference",
        "receipt_sha256",
    }
)
REQUEST_CONTRACT_KEYS = frozenset(
    {
        "schema_version",
        "request_id",
        "operation",
        "target_sha",
        "source_ci_run_id",
        "source_ci_run_attempt",
        "workflow_run_id",
        "workflow_run_attempt",
    }
)
REQUEST_STATE_KEYS = REQUEST_CONTRACT_KEYS | {
    "state",
    "phase",
    "previous_active_sha",
    "created_at",
    "updated_at",
    "worker_dispatched",
    "worker_unit",
    "failure",
    "receipt_reference",
    "receipt_sha256",
}


class DeploymentError(RuntimeError):
    """Deployment authority, state, or transition is invalid."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise DeploymentError(f"Cannot checksum {path.name}.") from error
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeploymentError(f"Cannot read valid {label} JSON.") from error
    if not isinstance(payload, dict):
        raise DeploymentError(f"The {label} must be a JSON object.")
    return payload


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.partial-", dir=path.parent
    )
    temporary = Path(temporary_name)
    replaced = False
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if not hasattr(os, "fchmod"):
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        replaced = True
        _fsync_directory(path.parent)
    finally:
        if not replaced:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, encoded)


def read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DeploymentError(
            "Cannot read the current-release environment view."
        ) from error
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key in values or any(c in key for c in "\r\n"):
            raise DeploymentError("Current-release environment view is malformed.")
        values[key] = value
    return values


def read_checksum_file(path: Path, *, expected_name: str) -> str:
    try:
        line = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise DeploymentError(f"Cannot read {path.name}.") from error
    match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
    if match is None or match.group(2) != expected_name:
        raise DeploymentError(f"{path.name} is malformed.")
    return match.group(1)


def verify_release_files(release: Path, checksum_path: Path) -> None:
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DeploymentError(
            "Cannot read release-files checksum authority."
        ) from error
    if not lines:
        raise DeploymentError("Release-files checksum authority is empty.")
    observed: set[str] = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        if match is None:
            raise DeploymentError("Release-files checksum authority is malformed.")
        relative = Path(match.group(2))
        if relative.is_absolute() or ".." in relative.parts:
            raise DeploymentError("Release-files checksum path is unsafe.")
        normalized = relative.as_posix()
        if normalized in observed:
            raise DeploymentError("Release-files checksum path is duplicated.")
        observed.add(normalized)
        target = release / relative
        if not target.is_file() or sha256_file(target) != match.group(1):
            raise DeploymentError("Candidate release file checksum disagrees.")


def _legacy_nginx_authority_is_exact(compose_path: Path) -> bool:
    try:
        lines = compose_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    in_nginx = False
    images: list[str] = []
    for line in lines:
        if re.fullmatch(r"  nginx:\s*", line):
            in_nginx = True
            continue
        if in_nginx and re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", line):
            break
        match = re.fullmatch(r"    image:\s*([^\s#]+)\s*", line)
        if in_nginx and match:
            images.append(match.group(1))
    return images == ["nginx:1.29.2"]


def verify_candidate(
    config: DeploymentConfig,
    target_sha: str,
    request: RequestContract,
    *,
    allow_activated: bool = False,
) -> dict[str, Any]:
    _require_sha(target_sha, label="Target SHA")
    request.validate()
    if request.target_sha != target_sha:
        raise DeploymentError("Candidate target disagrees with the request.")
    release = config.releases_root / target_sha
    if (
        not release.is_dir()
        or release.resolve().parent != config.releases_root.resolve()
    ):
        raise DeploymentError("Exact-SHA candidate directory is unavailable.")
    source_path = release / ".release-source-sha"
    try:
        if source_path.read_text(encoding="utf-8").strip() != target_sha:
            raise DeploymentError("Candidate source SHA disagrees.")
    except OSError as error:
        raise DeploymentError("Candidate source authority is unavailable.") from error

    files_authority = release / ".release-files.sha256"
    verify_release_files(release, files_authority)
    manifest_path = release / "release-manifest.env"
    receipt_path = release / "candidate-receipt.json"
    manifest = read_env_file(manifest_path)
    receipt = _load_json(receipt_path, label="candidate receipt")
    if set(receipt) != CANDIDATE_RECEIPT_KEYS:
        raise DeploymentError("Candidate receipt has an unexpected schema.")
    manifest_checksum = sha256_file(manifest_path)
    receipt_checksum = sha256_file(receipt_path)
    if (
        read_checksum_file(
            release / "candidate-receipt.sha256", expected_name="candidate-receipt.json"
        )
        != receipt_checksum
    ):
        raise DeploymentError("Candidate receipt checksum disagrees.")
    files_checksum = sha256_file(files_authority)
    image_digests = receipt.get("image_digests")
    legacy_rollback = (
        request.operation == "rollback"
        and isinstance(image_digests, dict)
        and set(image_digests) == {"frontend", "backend"}
        and "nginx_image" not in manifest
        and "nginx_image_digest" not in manifest
        and _legacy_nginx_authority_is_exact(release / "docker/docker-compose.prod.yml")
    )
    required_manifest = {
        "release_sha": target_sha,
        "source_ci_run_id": str(request.source_ci_run_id),
        "source_ci_run_attempt": str(request.source_ci_run_attempt),
    }
    if not legacy_rollback:
        required_manifest["nginx_image_digest"] = NGINX_DIGEST
    for key, value in required_manifest.items():
        if manifest.get(key) != value:
            raise DeploymentError(f"Candidate manifest field {key} disagrees.")
    if not isinstance(image_digests, dict) or (
        set(image_digests) != {"frontend", "backend", "nginx"} and not legacy_rollback
    ):
        raise DeploymentError("Candidate image authority is malformed.")
    image_digests = dict(image_digests)
    if legacy_rollback:
        image_digests["nginx"] = NGINX_DIGEST
    for component, digest in image_digests.items():
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            raise DeploymentError(f"Candidate {component} digest is malformed.")
    expected_receipt = {
        "schema_version": 1,
        "kind": "production-candidate-preparation",
        "source_sha": target_sha,
        "source_ci_run_id": request.source_ci_run_id,
        "source_ci_run_attempt": request.source_ci_run_attempt,
        "release_manifest_sha256": manifest_checksum,
        "release_files_sha256": files_checksum,
        "release_id": target_sha,
        "release_path": f"releases/{target_sha}",
        "outcome": "verified",
    }
    for key, value in expected_receipt.items():
        if receipt.get(key) != value:
            raise DeploymentError(f"Candidate receipt field {key} disagrees.")
    if image_digests["nginx"] != NGINX_DIGEST:
        raise DeploymentError("Candidate nginx digest disagrees.")
    for component in ("frontend", "backend", "nginx"):
        if component == "nginx" and legacy_rollback:
            manifest_digest = NGINX_DIGEST
            image = f"nginx:1.29.2@{NGINX_DIGEST}"
        else:
            manifest_digest = manifest.get(f"{component}_image_digest")
            image = manifest.get(f"{component}_image")
        if manifest_digest != image_digests[component] or not isinstance(image, str):
            raise DeploymentError(
                f"Candidate {component} manifest authority disagrees."
            )
        if IMAGE_PATTERN.fullmatch(image) is None or not image.endswith(
            f"@{image_digests[component]}"
        ):
            raise DeploymentError(f"Candidate {component} image is not digest-pinned.")
    activated = release / ".activated"
    if request.operation == "activate" and activated.exists() and not allow_activated:
        raise DeploymentError("A normal activation target is already marked activated.")
    if activated.exists():
        try:
            marker = activated.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise DeploymentError(
                "Candidate activation marker is unreadable."
            ) from error
        if marker != manifest_checksum:
            raise DeploymentError("Candidate activation marker disagrees.")
    return {
        "release_directory": str(release),
        "manifest_sha256": manifest_checksum,
        "candidate_receipt": str(receipt_path),
        "candidate_receipt_sha256": receipt_checksum,
        "image_digests": image_digests,
        "prepared_at": receipt.get("prepared_at"),
    }


def verify_runtime(active: ActiveRecord) -> dict[str, Any]:
    release = Path(active.active_release_directory)
    manifest = read_env_file(release / "release-manifest.env")
    nginx_image = manifest.get("nginx_image")
    legacy_nginx = nginx_image is None
    if legacy_nginx:
        try:
            compose_lines = (
                (release / "docker/docker-compose.prod.yml")
                .read_text(encoding="utf-8")
                .splitlines()
            )
        except OSError as error:
            raise DeploymentError(
                "Legacy active nginx authority is unavailable."
            ) from error
        nginx_section = False
        nginx_images: list[str] = []
        for line in compose_lines:
            if re.fullmatch(r"  nginx:\s*", line):
                nginx_section = True
                continue
            if nginx_section and re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", line):
                break
            match = re.fullmatch(r"    image:\s*([^\s#]+)\s*", line)
            if nginx_section and match:
                nginx_images.append(match.group(1))
        if len(nginx_images) != 1:
            raise DeploymentError("Legacy active nginx authority is ambiguous.")
        nginx_image = nginx_images[0]
    containers = {
        "pastexam-backend": manifest.get("backend_image"),
        "pastexam-frontend": manifest.get("frontend_image"),
        "pastexam-nginx": nginx_image,
    }
    if any(
        not isinstance(image, str)
        or (
            (name != "pastexam-nginx" or not legacy_nginx)
            and IMAGE_PATTERN.fullmatch(image) is None
        )
        for name, image in containers.items()
    ):
        raise DeploymentError("Active runtime image authority is incomplete.")
    process = subprocess.run(
        ["docker", "inspect", *containers],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise DeploymentError("Active runtime inspection failed.")
    try:
        inspected = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise DeploymentError("Active runtime inspection is malformed.") from error
    if not isinstance(inspected, list) or len(inspected) != len(containers):
        raise DeploymentError("Active runtime inspection is incomplete.")
    evidence: dict[str, Any] = {}
    for item in inspected:
        if not isinstance(item, dict):
            raise DeploymentError("Active runtime inspection is malformed.")
        name = str(item.get("Name", "")).removeprefix("/")
        if name not in containers:
            raise DeploymentError("Active runtime container identity is unexpected.")
        config = item.get("Config")
        state = item.get("State")
        if not isinstance(config, dict) or not isinstance(state, dict):
            raise DeploymentError("Active runtime container evidence is incomplete.")
        labels = config.get("Labels")
        health = state.get("Health")
        health_status = health.get("Status") if isinstance(health, dict) else None
        if (
            config.get("Image") != containers[name]
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project.working_dir")
            != active.active_release_directory
            or state.get("Status") != "running"
            or health_status not in (None, "healthy")
        ):
            raise DeploymentError("Active runtime disagrees with the canonical ledger.")
        restart_count = item.get("RestartCount")
        if (
            isinstance(restart_count, bool)
            or not isinstance(restart_count, int)
            or restart_count < 0
        ):
            raise DeploymentError("Active runtime restart evidence is malformed.")
        evidence[name] = {
            "id": str(item.get("Id", ""))[:12],
            "restart_count": restart_count,
            "health": health_status or "not-configured",
        }
    return evidence


def _render_env_file(existing: dict[str, str], active: ActiveRecord) -> bytes:
    values = dict(existing)
    values.update(
        {
            "release_sha": active.active_sha,
            "release_dir": active.active_release_directory,
            "activated_at": active.activated_at,
        }
    )
    required = {"release_sha", "release_dir", "activated_at"}
    if not required.issubset(values):
        raise DeploymentError("Current-release environment view is incomplete.")
    return "".join(f"{key}={value}\n" for key, value in values.items()).encode("utf-8")


def _atomic_symlink(path: Path, target: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    try:
        try:
            os.symlink(target, temporary, target_is_directory=True)
        except OSError as error:
            if os.name != "nt" or getattr(error, "winerror", None) != 1314:
                raise
            process = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(temporary), str(target)],
                text=True,
                capture_output=True,
                check=False,
            )
            if process.returncode != 0:
                raise DeploymentError(
                    "Cannot create the atomic compatibility link."
                ) from error
        try:
            os.replace(temporary, path)
        except PermissionError:
            if os.name != "nt" or not path.exists():
                raise
            os.rmdir(path)
            os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise DeploymentError(f"{label} must be a lowercase 40-character SHA.")
    return value


def _require_digest(value: Any, *, label: str, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise DeploymentError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _require_positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DeploymentError(f"{label} must be a positive integer.")
    return value


def _require_request_id(value: Any) -> str:
    if not isinstance(value, str) or REQUEST_ID_PATTERN.fullmatch(value) is None:
        raise DeploymentError("Request ID is malformed.")
    return value


def _require_revision(value: Any) -> str:
    if not isinstance(value, str) or REVISION_PATTERN.fullmatch(value) is None:
        raise DeploymentError("Database revision is malformed.")
    return value


def _require_timestamp(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise DeploymentError(f"{label} is malformed.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeploymentError(f"{label} is malformed.") from error
    if parsed.tzinfo is None:
        raise DeploymentError(f"{label} must include a timezone.")
    return value


@dataclass(frozen=True)
class DeploymentConfig:
    state_root: Path = Path("/var/lib/pastexam-deployments")
    releases_root: Path = Path("/opt/pastexam-releases")
    active_link: Path = Path("/opt/pastexam-current")
    active_env: Path = Path("/opt/pastexam-current-release.env")
    mutation_lock: Path = Path("/run/lock/pastexam-production-activation.lock")
    engine_path: Path = Path("/usr/local/libexec/pastexam-activate-production-release")
    backup_root: Path = Path("/opt/pastexam-backups")
    systemd_run: str = "systemd-run"
    systemctl: str = "systemctl"
    internal_health_url: str = "http://127.0.0.1:8080/api/health"
    external_health_url: str = "https://physarchive.com/api/health"
    runtime_verification: bool = True

    @property
    def active_ledger(self) -> Path:
        return self.state_root / "active.json"

    @property
    def requests_dir(self) -> Path:
        return self.state_root / "requests"

    @property
    def receipts_dir(self) -> Path:
        return self.state_root / "receipts"


@dataclass(frozen=True)
class ActiveRecord:
    schema_version: int
    active_sha: str
    active_release_directory: str
    manifest_sha256: str
    activation_request_id: str | None
    activation_workflow: dict[str, int] | None
    activated_at: str
    database_revision: str
    previous_active_sha: str | None
    receipt_reference: str | None
    receipt_sha256: str | None

    def validate(self) -> ActiveRecord:
        if self.schema_version != 1:
            raise DeploymentError("Active ledger schema version is unsupported.")
        _require_sha(self.active_sha, label="Active SHA")
        release = Path(self.active_release_directory)
        if not release.is_absolute() or release.name != self.active_sha:
            raise DeploymentError("Active release directory is not exact-SHA-bound.")
        _require_digest(self.manifest_sha256, label="Manifest checksum")
        if self.activation_request_id is not None:
            _require_request_id(self.activation_request_id)
        if self.activation_workflow is not None:
            if set(self.activation_workflow) != {"run_id", "run_attempt"}:
                raise DeploymentError("Activation workflow provenance is malformed.")
            _require_positive_int(self.activation_workflow["run_id"], label="Run ID")
            _require_positive_int(
                self.activation_workflow["run_attempt"], label="Run attempt"
            )
        _require_timestamp(self.activated_at, label="Activation timestamp")
        _require_revision(self.database_revision)
        if self.previous_active_sha is not None:
            _require_sha(self.previous_active_sha, label="Previous active SHA")
        if (self.receipt_reference is None) != (self.receipt_sha256 is None):
            raise DeploymentError("Receipt reference and checksum must be paired.")
        if self.receipt_reference is not None:
            if not Path(self.receipt_reference).is_absolute():
                raise DeploymentError("Receipt reference must be absolute.")
            _require_digest(self.receipt_sha256, label="Receipt checksum")
        return self

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ActiveRecord:
        if set(payload) != ACTIVE_KEYS:
            raise DeploymentError("The active ledger has an unexpected schema.")
        return cls(**payload).validate()


@dataclass(frozen=True)
class RequestContract:
    schema_version: int
    request_id: str
    operation: str
    target_sha: str
    source_ci_run_id: int
    source_ci_run_attempt: int
    workflow_run_id: int
    workflow_run_attempt: int

    def validate(self) -> RequestContract:
        if self.schema_version != 1:
            raise DeploymentError("Request schema version is unsupported.")
        _require_request_id(self.request_id)
        if self.operation not in {"activate", "rollback"}:
            raise DeploymentError("Request operation is unsupported.")
        _require_sha(self.target_sha, label="Target SHA")
        _require_positive_int(self.source_ci_run_id, label="Source CI run ID")
        _require_positive_int(self.source_ci_run_attempt, label="Source CI run attempt")
        _require_positive_int(self.workflow_run_id, label="Workflow run ID")
        _require_positive_int(self.workflow_run_attempt, label="Workflow run attempt")
        return self


_HELD_LOCKS: set[Path] = set()


class MutationLock(AbstractContextManager["MutationLock"]):
    def __init__(self, path: Path):
        self.path = path.resolve(strict=False)
        self._stream: Any = None

    def acquire(self) -> None:
        if self.path in _HELD_LOCKS:
            raise DeploymentError("Another production mutation is active.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                if stream.tell() == 0 and stream.read(1) == b"":
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            stream.close()
            raise DeploymentError("Another production mutation is active.") from error
        _HELD_LOCKS.add(self.path)
        self._stream = stream

    def release(self) -> None:
        if self._stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._stream.seek(0)
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()
            self._stream = None
            _HELD_LOCKS.discard(self.path)

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


class DeploymentStore:
    def __init__(self, config: DeploymentConfig):
        self.config = config

    def initialize(self) -> None:
        for directory in (
            self.config.state_root,
            self.config.requests_dir,
            self.config.receipts_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                directory.chmod(0o700)
            except OSError:
                if os.name != "nt":
                    raise

    def load_active(self) -> ActiveRecord:
        return ActiveRecord.from_dict(
            _load_json(self.config.active_ledger, label="active ledger")
        )

    def _verify_active_artifacts(self, active: ActiveRecord) -> None:
        active.validate()
        release = Path(active.active_release_directory)
        manifest = release / "release-manifest.env"
        marker = release / ".activated"
        if not release.is_dir() or not manifest.is_file() or not marker.is_file():
            raise DeploymentError("Active release evidence is incomplete.")
        if sha256_file(manifest) != active.manifest_sha256:
            raise DeploymentError("Active release manifest checksum disagrees.")
        try:
            marker_value = marker.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise DeploymentError("Cannot read active release marker.") from error
        if marker_value != active.manifest_sha256:
            raise DeploymentError("Active release marker disagrees.")
        if active.receipt_reference is not None:
            receipt = Path(active.receipt_reference)
            if not receipt.is_file() or sha256_file(receipt) != active.receipt_sha256:
                raise DeploymentError("Active deployment receipt disagrees.")

    def _write_compatibility_views(self, active: ActiveRecord) -> None:
        existing = read_env_file(self.config.active_env)
        atomic_write_bytes(self.config.active_env, _render_env_file(existing, active))
        _atomic_symlink(self.config.active_link, Path(active.active_release_directory))

    def verify_active_views(self, active: ActiveRecord) -> None:
        self._verify_active_artifacts(active)
        try:
            linked = self.config.active_link.resolve(strict=True)
        except OSError as error:
            raise DeploymentError(
                "Active compatibility link is unavailable."
            ) from error
        if linked != Path(active.active_release_directory).resolve(strict=True):
            raise DeploymentError(
                "Active compatibility link disagrees with the ledger."
            )
        values = read_env_file(self.config.active_env)
        if (
            values.get("release_sha") != active.active_sha
            or values.get("release_dir") != active.active_release_directory
        ):
            raise DeploymentError("Active environment view disagrees with the ledger.")

    def seed_active(self, active: ActiveRecord) -> None:
        self.initialize()
        if self.config.active_ledger.exists():
            existing = self.load_active()
            if existing != active:
                raise DeploymentError(
                    "Refusing to overwrite an existing active ledger."
                )
            self._verify_active_artifacts(existing)
            self._write_compatibility_views(existing)
            return
        self._verify_active_artifacts(active)
        atomic_write_json(self.config.active_ledger, asdict(active))
        self._write_compatibility_views(active)

    def _request_path(self, request_id: str) -> Path:
        _require_request_id(request_id)
        return self.config.requests_dir / f"{request_id}.json"

    def load_request(self, request_id: str) -> dict[str, Any]:
        payload = _load_json(self._request_path(request_id), label="deployment request")
        if set(payload) != REQUEST_STATE_KEYS:
            raise DeploymentError("Deployment request has an unexpected schema.")
        self._validate_request_payload(payload)
        return payload

    @staticmethod
    def _contract_payload(request: RequestContract) -> dict[str, Any]:
        request.validate()
        return asdict(request)

    @staticmethod
    def _validate_request_payload(payload: dict[str, Any]) -> None:
        contract = RequestContract(
            **{key: payload[key] for key in REQUEST_CONTRACT_KEYS}
        ).validate()
        if payload["state"] not in LEGAL_TRANSITIONS:
            raise DeploymentError("Deployment request state is unsupported.")
        if not isinstance(payload["phase"], str) or not payload["phase"]:
            raise DeploymentError("Deployment request phase is malformed.")
        _require_sha(payload["previous_active_sha"], label="Previous active SHA")
        _require_timestamp(payload["created_at"], label="Created timestamp")
        _require_timestamp(payload["updated_at"], label="Updated timestamp")
        if not isinstance(payload["worker_dispatched"], bool):
            raise DeploymentError("Worker dispatch state is malformed.")
        expected_unit = f"pastexam-deployment-{contract.request_id}.service"
        if payload["worker_unit"] != expected_unit:
            raise DeploymentError("Worker unit identity is malformed.")
        failure = payload["failure"]
        if failure is not None and (
            not isinstance(failure, dict)
            or set(failure) != {"code", "message"}
            or not all(
                isinstance(failure[key], str) and failure[key] for key in failure
            )
        ):
            raise DeploymentError("Deployment request failure is malformed.")
        if (payload["receipt_reference"] is None) != (
            payload["receipt_sha256"] is None
        ):
            raise DeploymentError("Deployment request receipt evidence is incomplete.")
        if payload["receipt_sha256"] is not None:
            _require_digest(payload["receipt_sha256"], label="Receipt checksum")

    def prepare_request(
        self, request: RequestContract, *, previous_active_sha: str
    ) -> tuple[dict[str, Any], bool]:
        self.initialize()
        contract = self._contract_payload(request)
        _require_sha(previous_active_sha, label="Previous active SHA")
        path = self._request_path(request.request_id)
        if path.exists():
            existing = self.load_request(request.request_id)
            observed_contract = {key: existing[key] for key in REQUEST_CONTRACT_KEYS}
            if (
                observed_contract != contract
                or existing["previous_active_sha"] != previous_active_sha
            ):
                raise DeploymentError(
                    "Request ID was reused with different immutable input."
                )
            return existing, False
        now = utc_now()
        payload = {
            **contract,
            "state": "PREPARED",
            "phase": "prepared",
            "previous_active_sha": previous_active_sha,
            "created_at": now,
            "updated_at": now,
            "worker_dispatched": False,
            "worker_unit": f"pastexam-deployment-{request.request_id}.service",
            "failure": None,
            "receipt_reference": None,
            "receipt_sha256": None,
        }
        self._validate_request_payload(payload)
        atomic_write_json(path, payload)
        return payload, True

    def _write_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_request_payload(payload)
        atomic_write_json(self._request_path(payload["request_id"]), payload)
        return payload

    def mark_worker_dispatched(self, request_id: str) -> dict[str, Any]:
        payload = self.load_request(request_id)
        if payload["state"] in TERMINAL_STATES:
            return payload
        payload["worker_dispatched"] = True
        payload["updated_at"] = utc_now()
        return self._write_request(payload)

    def mark_recoverable(
        self, request_id: str, *, phase: str, code: str, message: str
    ) -> dict[str, Any]:
        payload = self.load_request(request_id)
        if payload["state"] not in {"ACTIVATING", "ROLLING_BACK"}:
            raise DeploymentError("Only an in-progress request can be recoverable.")
        payload.update(
            {
                "phase": phase,
                "updated_at": utc_now(),
                "failure": {"code": code, "message": message},
            }
        )
        return self._write_request(payload)

    def transition(
        self,
        request_id: str,
        new_state: str,
        *,
        phase: str,
        failure: dict[str, str] | None = None,
        receipt_reference: str | None = None,
        receipt_sha256: str | None = None,
    ) -> dict[str, Any]:
        payload = self.load_request(request_id)
        current = payload["state"]
        if new_state not in LEGAL_TRANSITIONS[current]:
            raise DeploymentError(
                f"Illegal request transition: {current} -> {new_state}."
            )
        if new_state == "FAILED" and failure is None:
            raise DeploymentError(
                "Failed transition requires sanitized failure evidence."
            )
        if new_state != "FAILED" and failure is not None:
            raise DeploymentError("Failure evidence is valid only for FAILED state.")
        if (receipt_reference is None) != (receipt_sha256 is None):
            raise DeploymentError("Receipt evidence must be complete.")
        payload.update(
            {
                "state": new_state,
                "phase": phase,
                "updated_at": utc_now(),
                "failure": failure,
                "receipt_reference": receipt_reference,
                "receipt_sha256": receipt_sha256,
            }
        )
        return self._write_request(payload)

    def finalize_active(self, request_id: str, active: ActiveRecord) -> None:
        request = self.load_request(request_id)
        if request["state"] != "ACTIVATING":
            raise DeploymentError(
                "Only an activating request may finalize active state."
            )
        if request["target_sha"] != active.active_sha:
            raise DeploymentError("Active record target disagrees with the request.")
        self._verify_active_artifacts(active)
        atomic_write_json(self.config.active_ledger, asdict(active.validate()))
        self._write_compatibility_views(active)
        self.transition(
            request_id,
            "ACTIVE",
            phase="finalized",
            receipt_reference=active.receipt_reference,
            receipt_sha256=active.receipt_sha256,
        )

    def finalize_rollback(self, request_id: str, active: ActiveRecord) -> None:
        request = self.load_request(request_id)
        if request["state"] != "ROLLING_BACK":
            raise DeploymentError(
                "Only a rolling-back request may finalize active state."
            )
        if request["target_sha"] != active.active_sha:
            raise DeploymentError("Rollback active target disagrees with the request.")
        self._verify_active_artifacts(active)
        atomic_write_json(self.config.active_ledger, asdict(active.validate()))
        self._write_compatibility_views(active)
        self.transition(
            request_id,
            "ROLLED_BACK",
            phase="finalized",
            receipt_reference=active.receipt_reference,
            receipt_sha256=active.receipt_sha256,
        )

    def reconcile_committed_finalization(
        self, request_id: str, active: ActiveRecord, *, rollback: bool
    ) -> dict[str, Any]:
        request = self.load_request(request_id)
        expected_state = "ROLLING_BACK" if rollback else "ACTIVATING"
        if request["state"] != expected_state:
            raise DeploymentError("Committed finalization request state disagrees.")
        if (
            active.active_sha != request["target_sha"]
            or active.previous_active_sha != request["previous_active_sha"]
            or active.activation_request_id != request_id
        ):
            raise DeploymentError("Committed finalization authority disagrees.")
        self._verify_active_artifacts(active)
        self._write_compatibility_views(active)
        return self.transition(
            request_id,
            "ROLLED_BACK" if rollback else "ACTIVE",
            phase="finalized-recovery",
            receipt_reference=active.receipt_reference,
            receipt_sha256=active.receipt_sha256,
        )


class DeploymentController:
    def __init__(
        self,
        config: DeploymentConfig,
        *,
        dispatch_worker: Callable[..., None] | None = None,
    ):
        self.config = config
        self.store = DeploymentStore(config)
        self.dispatch_worker = dispatch_worker or self._systemd_dispatch

    def _verify_runtime(self, active: ActiveRecord) -> dict[str, Any]:
        if not self.config.runtime_verification:
            return {}
        return verify_runtime(active)

    def status(self) -> dict[str, Any]:
        active = self.store.load_active()
        self.store.verify_active_views(active)
        runtime = self._verify_runtime(active)
        return {"schema_version": 1, "active": asdict(active), "runtime": runtime}

    def _systemd_dispatch(self, request_id: str, *, rollback: bool = False) -> None:
        unit = f"pastexam-deployment-{request_id}"
        command = [
            self.config.systemd_run,
            "--unit",
            unit,
            "--collect",
            "--no-block",
            "--property=Type=oneshot",
            "--property=Restart=no",
            str(Path(__file__).resolve()),
            "rollback-worker" if rollback else "worker",
            request_id,
        ]
        process = subprocess.run(command, text=True, capture_output=True, check=False)
        if process.returncode != 0:
            raise DeploymentError("The host deployment worker could not be dispatched.")

    def _worker_is_active(self, request_id: str) -> bool:
        unit = f"pastexam-deployment-{request_id}.service"
        process = subprocess.run(
            [self.config.systemctl, "is-active", "--quiet", unit],
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode == 0:
            return True
        if process.returncode in {3, 4}:
            return False
        raise DeploymentError("The host deployment worker state is unavailable.")

    def start(
        self,
        request: RequestContract,
        *,
        candidate_verifier: Callable[[str, RequestContract], dict[str, Any]]
        | None = None,
    ) -> dict[str, Any]:
        request.validate()
        if request.operation != "activate":
            raise DeploymentError("Normal start requires an activation request.")
        active = self.store.load_active()
        self.store.verify_active_views(active)
        self._verify_runtime(active)
        if request.target_sha == active.active_sha:
            verifier = candidate_verifier or (
                lambda target, contract: verify_candidate(
                    self.config, target, contract, allow_activated=True
                )
            )
        else:
            verifier = candidate_verifier or self.preflight
        verifier(request.target_sha, request)
        prepared, created = self.store.prepare_request(
            request, previous_active_sha=active.active_sha
        )
        if not created:
            return prepared
        if request.target_sha == active.active_sha:
            self.store.transition(
                request.request_id, "ACTIVATING", phase="already-active"
            )
            result = self.store.transition(
                request.request_id,
                "ACTIVE",
                phase="ALREADY_ACTIVE",
                receipt_reference=active.receipt_reference,
                receipt_sha256=active.receipt_sha256,
            )
            return result
        try:
            self.dispatch_worker(request.request_id)
        except DeploymentError as error:
            self.store.transition(
                request.request_id,
                "FAILED",
                phase="dispatch",
                failure={"code": "worker-dispatch-failed", "message": str(error)},
            )
            raise
        return self.store.mark_worker_dispatched(request.request_id)

    def preflight(self, target_sha: str, request: RequestContract) -> dict[str, Any]:
        active = self.store.load_active()
        self.store.verify_active_views(active)
        self._verify_runtime(active)
        candidate = verify_candidate(
            self.config,
            target_sha,
            request,
            allow_activated=request.operation == "rollback",
        )
        environment = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PRODUCTION_DEPLOY_ENABLED": "true",
            "ACTIVATION_CONFIRMATION": "activate-reviewed-production-release",
            "ACTIVATION_PREFLIGHT_ONLY": "true",
            "RELEASE_DIRECTORY": candidate["release_directory"],
            "RELEASE_MANIFEST": str(
                Path(candidate["release_directory"]) / "release-manifest.env"
            ),
            "RELEASE_MANIFEST_SHA256": candidate["manifest_sha256"],
            "INTERNAL_HEALTH_URL": self.config.internal_health_url,
            "EXTERNAL_HEALTH_URL": self.config.external_health_url,
        }
        process = subprocess.run(
            [str(self.config.engine_path)],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        if process.returncode != 0:
            raise DeploymentError("Production activation preflight failed closed.")
        return candidate

    def rollback_start(self, request: RequestContract) -> dict[str, Any]:
        request.validate()
        if request.operation != "rollback":
            raise DeploymentError("Rollback start requires a rollback request.")
        active = self.store.load_active()
        self.store.verify_active_views(active)
        if active.previous_active_sha != request.target_sha:
            raise DeploymentError(
                "Rollback target is not the canonical previous active SHA."
            )
        self.preflight(request.target_sha, request)
        prepared, created = self.store.prepare_request(
            request, previous_active_sha=active.active_sha
        )
        if not created:
            return prepared
        try:
            self.dispatch_worker(request.request_id, rollback=True)
        except DeploymentError as error:
            self.store.transition(
                request.request_id,
                "FAILED",
                phase="dispatch",
                failure={"code": "worker-dispatch-failed", "message": str(error)},
            )
            raise
        return self.store.mark_worker_dispatched(request.request_id)

    def resume(self, request_id: str) -> dict[str, Any]:
        request = self.store.load_request(request_id)
        if request["state"] in TERMINAL_STATES:
            return request
        active = self.store.load_active()
        safe_finalization_recovery = (
            request["phase"] == "finalization-retry-required"
            or active.active_sha == request["target_sha"]
        )
        if not safe_finalization_recovery or self._worker_is_active(request_id):
            return request
        rollback = request["operation"] == "rollback"
        try:
            self.dispatch_worker(request_id, rollback=rollback)
        except DeploymentError as error:
            self.store.mark_recoverable(
                request_id,
                phase="finalization-retry-required",
                code="worker-redispatch-failed",
                message=str(error),
            )
            raise
        return self.store.mark_worker_dispatched(request_id)

    def _engine_evidence_path(self, request_id: str) -> Path:
        _require_request_id(request_id)
        return self.config.requests_dir / f"{request_id}.engine.json"

    def _engine_failure_evidence_path(self, request_id: str) -> Path:
        _require_request_id(request_id)
        return self.config.requests_dir / f"{request_id}.failure.json"

    def _load_engine_failure_evidence(
        self, request: dict[str, Any], *, expected_exit_code: int
    ) -> dict[str, Any] | None:
        path = self._engine_failure_evidence_path(request["request_id"])
        try:
            if not path.is_file() or path.is_symlink():
                return None
            payload = _load_json(path, label="engine failure evidence")
            if set(payload) != {
                "schema_version",
                "request_id",
                "target_sha",
                "stage",
                "exit_code",
                "observed_at",
            }:
                return None
            if (
                payload["schema_version"] != 1
                or payload["request_id"] != request["request_id"]
                or payload["target_sha"] != request["target_sha"]
                or payload["stage"] not in ACTIVATION_FAILURE_STAGES
                or isinstance(payload["exit_code"], bool)
                or not isinstance(payload["exit_code"], int)
                or payload["exit_code"] != expected_exit_code
                or not 1 <= payload["exit_code"] <= 255
            ):
                return None
            _require_timestamp(
                payload["observed_at"], label="Engine failure observed timestamp"
            )
        except (DeploymentError, OSError, TypeError):
            return None
        return payload

    def _invoke_engine(
        self, request: dict[str, Any], candidate: dict[str, Any]
    ) -> None:
        evidence = self._engine_evidence_path(request["request_id"])
        failure_evidence = self._engine_failure_evidence_path(request["request_id"])
        if failure_evidence.exists():
            raise DeploymentError("The production activation engine failed closed.")
        environment = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PRODUCTION_DEPLOY_ENABLED": "true",
            "ACTIVATION_CONFIRMATION": "activate-reviewed-production-release",
            "RELEASE_DIRECTORY": candidate["release_directory"],
            "RELEASE_MANIFEST": str(
                Path(candidate["release_directory"]) / "release-manifest.env"
            ),
            "RELEASE_MANIFEST_SHA256": candidate["manifest_sha256"],
            "PRODUCTION_BACKUP_DIRECTORY": str(self.config.backup_root),
            "ACTIVATION_EVIDENCE_PATH": str(evidence),
            "ACTIVATION_FAILURE_EVIDENCE_PATH": str(failure_evidence),
            "ACTIVATION_REQUEST_ID": request["request_id"],
            "ACTIVATION_TARGET_SHA": request["target_sha"],
            "INTERNAL_HEALTH_URL": self.config.internal_health_url,
            "EXTERNAL_HEALTH_URL": self.config.external_health_url,
        }
        process = subprocess.run(
            [str(self.config.engine_path)],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        if process.returncode != 0:
            failure = self._load_engine_failure_evidence(
                request, expected_exit_code=process.returncode
            )
            if failure is not None:
                raise DeploymentError(
                    "The production activation engine failed closed at stage "
                    f"'{failure['stage']}' with exit code {failure['exit_code']}."
                )
            raise DeploymentError("The production activation engine failed closed.")
        if failure_evidence.exists():
            raise DeploymentError("The production activation engine failed closed.")

    def _load_engine_evidence(
        self, request: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]:
        payload = _load_json(
            self._engine_evidence_path(request["request_id"]), label="engine evidence"
        )
        expected_keys = {
            "schema_version",
            "target_sha",
            "started_at",
            "completed_at",
            "database_revision_before",
            "database_revision_after",
            "postgres_backup_metadata",
            "postgres_backup_checksum",
            "minio_manifest",
            "observation_snapshots",
            "critical_error_count",
            "health_outcome",
            "restart_stability",
        }
        if set(payload) != expected_keys or payload.get("schema_version") != 1:
            raise DeploymentError("Engine evidence has an unexpected schema.")
        if payload.get("target_sha") != request["target_sha"]:
            raise DeploymentError("Engine evidence target disagrees.")
        _require_timestamp(payload.get("started_at"), label="Engine start timestamp")
        _require_timestamp(
            payload.get("completed_at"), label="Engine completion timestamp"
        )
        before = _require_revision(payload.get("database_revision_before"))
        after = _require_revision(payload.get("database_revision_after"))
        if before != after:
            raise DeploymentError("Engine database revision changed during activation.")
        if (
            payload.get("health_outcome") != "green"
            or payload.get("restart_stability") != "stable"
            or payload.get("critical_error_count") != 0
        ):
            raise DeploymentError("Engine health evidence is not green and stable.")
        _require_positive_int(
            payload.get("observation_snapshots"), label="Observation snapshots"
        )
        for key in (
            "postgres_backup_metadata",
            "postgres_backup_checksum",
            "minio_manifest",
        ):
            path = Path(str(payload.get(key)))
            if not path.is_absolute() or not path.is_file():
                raise DeploymentError("Engine backup evidence is unavailable.")
        marker = Path(candidate["release_directory"]) / ".activated"
        if not marker.is_file():
            raise DeploymentError(
                "Activation engine did not publish its completion marker."
            )
        return payload

    def _write_receipt(
        self,
        request: dict[str, Any],
        active: ActiveRecord,
        candidate: dict[str, Any],
        evidence: dict[str, Any],
    ) -> tuple[Path, str]:
        receipt_path = self.config.receipts_dir / f"{request['request_id']}.json"
        rollback = request["operation"] == "rollback"
        receipt = {
            "schema_version": 1,
            "kind": "production-rollback" if rollback else "production-activation",
            "request_id": request["request_id"],
            "target_sha": request["target_sha"],
            "previous_active_sha": active.active_sha,
            "source_ci_run_id": request["source_ci_run_id"],
            "source_ci_run_attempt": request["source_ci_run_attempt"],
            "activation_workflow_run_id": request["workflow_run_id"],
            "activation_workflow_run_attempt": request["workflow_run_attempt"],
            "github_environment": "production",
            "candidate_receipt_sha256": candidate["candidate_receipt_sha256"],
            "release_manifest_sha256": candidate["manifest_sha256"],
            "image_digests": candidate["image_digests"],
            "started_at": evidence["started_at"],
            "completed_at": evidence["completed_at"],
            "database_revision_before": evidence["database_revision_before"],
            "database_revision_after": evidence["database_revision_after"],
            "migration_risk_class": 0,
            "postgres_backup_metadata": evidence["postgres_backup_metadata"],
            "postgres_backup_checksum": evidence["postgres_backup_checksum"],
            "minio_manifest": evidence["minio_manifest"],
            "health_outcome": evidence["health_outcome"],
            "observation_snapshots": evidence["observation_snapshots"],
            "critical_error_count": evidence["critical_error_count"],
            "restart_stability": evidence["restart_stability"],
            "resulting_active_sha": request["target_sha"],
            "rollback_from_sha": active.active_sha if rollback else None,
            "rollback_to_sha": request["target_sha"] if rollback else None,
            "outcome": "rolled-back" if rollback else "active",
        }
        atomic_write_json(receipt_path, receipt)
        return receipt_path, sha256_file(receipt_path)

    def worker(self, request_id: str) -> dict[str, Any]:
        return self._run_worker(request_id, rollback=False)

    def rollback_worker(self, request_id: str) -> dict[str, Any]:
        return self._run_worker(request_id, rollback=True)

    def _run_worker(self, request_id: str, *, rollback: bool) -> dict[str, Any]:
        with MutationLock(self.config.mutation_lock):
            request = self.store.load_request(request_id)
            if request["state"] in TERMINAL_STATES:
                return request
            expected_operation = "rollback" if rollback else "activate"
            if request["operation"] != expected_operation:
                raise DeploymentError(
                    "Worker operation disagrees with its fixed entrypoint."
                )
            active = self.store.load_active()
            if active.active_sha == request["target_sha"]:
                self._verify_runtime(active)
                return self.store.reconcile_committed_finalization(
                    request_id, active, rollback=rollback
                )
            self.store.verify_active_views(active)
            self._verify_runtime(active)
            if active.active_sha != request["previous_active_sha"]:
                raise DeploymentError(
                    "Active production changed after request preparation."
                )
            if rollback and active.previous_active_sha != request["target_sha"]:
                raise DeploymentError("Rollback target is no longer canonical.")
            contract = RequestContract(
                **{key: request[key] for key in REQUEST_CONTRACT_KEYS}
            )
            candidate = verify_candidate(
                self.config,
                request["target_sha"],
                contract,
                allow_activated=rollback or request["state"] == "ACTIVATING",
            )
            if request["state"] == "PREPARED":
                request = self.store.transition(
                    request_id,
                    "ROLLING_BACK" if rollback else "ACTIVATING",
                    phase="rollback-engine" if rollback else "engine",
                )
            evidence_path = self._engine_evidence_path(request_id)
            marker = Path(candidate["release_directory"]) / ".activated"
            finalization_started = False
            try:
                if not (evidence_path.is_file() and marker.is_file()):
                    if evidence_path.exists() or (marker.exists() and not rollback):
                        raise DeploymentError(
                            "Activation completion evidence is partial."
                        )
                    self._invoke_engine(request, candidate)
                evidence = self._load_engine_evidence(request, candidate)
                if evidence["database_revision_before"] != active.database_revision:
                    raise DeploymentError(
                        "Canonical ledger database revision disagrees."
                    )
                finalization_started = True
                receipt_path, receipt_digest = self._write_receipt(
                    request, active, candidate, evidence
                )
                new_active = ActiveRecord(
                    schema_version=1,
                    active_sha=request["target_sha"],
                    active_release_directory=candidate["release_directory"],
                    manifest_sha256=candidate["manifest_sha256"],
                    activation_request_id=request_id,
                    activation_workflow={
                        "run_id": request["workflow_run_id"],
                        "run_attempt": request["workflow_run_attempt"],
                    },
                    activated_at=evidence["completed_at"],
                    database_revision=evidence["database_revision_after"],
                    previous_active_sha=active.active_sha,
                    receipt_reference=str(receipt_path),
                    receipt_sha256=receipt_digest,
                )
                if rollback:
                    self.store.finalize_rollback(request_id, new_active)
                else:
                    self.store.finalize_active(request_id, new_active)
                return self.store.load_request(request_id)
            except DeploymentError as error:
                current = self.store.load_request(request_id)
                if (
                    finalization_started
                    and evidence_path.is_file()
                    and marker.is_file()
                ):
                    self.store.mark_recoverable(
                        request_id,
                        phase="finalization-retry-required",
                        code="finalization-failed",
                        message=str(error),
                    )
                elif current["state"] in {"ACTIVATING", "ROLLING_BACK"}:
                    self.store.transition(
                        request_id,
                        "FAILED",
                        phase="rollback" if rollback else "activation",
                        failure={
                            "code": "rollback-failed"
                            if rollback
                            else "activation-failed",
                            "message": str(error),
                        },
                    )
                raise


def _default_config() -> DeploymentConfig:
    if os.environ.get("PASTEXAM_DEPLOYMENT_TEST_MODE") == "1":
        root = Path(os.environ["PASTEXAM_DEPLOYMENT_TEST_ROOT"]).resolve()
        return DeploymentConfig(
            state_root=root / "state",
            releases_root=root / "releases",
            active_link=root / "pastexam-current",
            active_env=root / "pastexam-current-release.env",
            mutation_lock=root / "activation.lock",
            engine_path=root / "engine",
            backup_root=root / "backups",
            internal_health_url="http://127.0.0.1/api/health",
            external_health_url="https://example.invalid/api/health",
        )
    return DeploymentConfig()


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("target_sha")
    preflight.add_argument("source_ci_run_id", type=int)
    preflight.add_argument("source_ci_run_attempt", type=int)
    start = subparsers.add_parser("start")
    start.add_argument("target_sha")
    start.add_argument("request_id")
    start.add_argument("source_ci_run_id", type=int)
    start.add_argument("source_ci_run_attempt", type=int)
    start.add_argument("workflow_run_id", type=int)
    start.add_argument("workflow_run_attempt", type=int)
    request_status = subparsers.add_parser("request-status")
    request_status.add_argument("request_id")
    receipt = subparsers.add_parser("receipt")
    receipt.add_argument("request_id")
    resume = subparsers.add_parser("resume")
    resume.add_argument("request_id")
    rollback_preflight = subparsers.add_parser("rollback-preflight")
    rollback_preflight.add_argument("target_sha")
    rollback_preflight.add_argument("source_ci_run_id", type=int)
    rollback_preflight.add_argument("source_ci_run_attempt", type=int)
    rollback_start = subparsers.add_parser("rollback-start")
    rollback_start.add_argument("target_sha")
    rollback_start.add_argument("request_id")
    rollback_start.add_argument("source_ci_run_id", type=int)
    rollback_start.add_argument("source_ci_run_attempt", type=int)
    rollback_start.add_argument("workflow_run_id", type=int)
    rollback_start.add_argument("workflow_run_attempt", type=int)
    worker = subparsers.add_parser("worker")
    worker.add_argument("request_id")
    rollback_worker = subparsers.add_parser("rollback-worker")
    rollback_worker.add_argument("request_id")
    seed = subparsers.add_parser("seed-active")
    seed.add_argument("active_sha")
    seed.add_argument("manifest_sha256")
    seed.add_argument("activated_at")
    seed.add_argument("database_revision")
    return parser


def _request_from_args(
    args: argparse.Namespace, *, operation: str = "activate"
) -> RequestContract:
    return RequestContract(
        schema_version=1,
        request_id=getattr(args, "request_id", "preflight-only"),
        operation=operation,
        target_sha=args.target_sha,
        source_ci_run_id=args.source_ci_run_id,
        source_ci_run_attempt=args.source_ci_run_attempt,
        workflow_run_id=getattr(args, "workflow_run_id", 1),
        workflow_run_attempt=getattr(args, "workflow_run_attempt", 1),
    ).validate()


def main() -> int:
    args = _parser().parse_args()
    config = _default_config()
    store = DeploymentStore(config)
    controller = DeploymentController(config)
    try:
        if args.command == "status":
            _print_json(controller.status())
        elif args.command == "preflight":
            request = _request_from_args(args)
            active = store.load_active()
            candidate = controller.preflight(request.target_sha, request)
            _print_json(
                {
                    "schema_version": 1,
                    "outcome": "eligible",
                    "target_sha": request.target_sha,
                    "current_active_sha": active.active_sha,
                    "manifest_sha256": candidate["manifest_sha256"],
                    "candidate_receipt_sha256": candidate["candidate_receipt_sha256"],
                }
            )
        elif args.command == "start":
            _print_json(controller.start(_request_from_args(args)))
        elif args.command == "rollback-preflight":
            request = _request_from_args(args, operation="rollback")
            active = store.load_active()
            if active.previous_active_sha != request.target_sha:
                raise DeploymentError("Rollback target is not canonical.")
            candidate = controller.preflight(request.target_sha, request)
            _print_json(
                {
                    "schema_version": 1,
                    "outcome": "rollback-eligible",
                    "target_sha": request.target_sha,
                    "current_active_sha": active.active_sha,
                    "database_revision": active.database_revision,
                    "manifest_sha256": candidate["manifest_sha256"],
                    "candidate_receipt_sha256": candidate["candidate_receipt_sha256"],
                }
            )
        elif args.command == "rollback-start":
            _print_json(
                controller.rollback_start(
                    _request_from_args(args, operation="rollback")
                )
            )
        elif args.command == "request-status":
            _print_json(store.load_request(args.request_id))
        elif args.command == "receipt":
            request = store.load_request(args.request_id)
            if (
                request["state"] not in TERMINAL_STATES
                or request["receipt_reference"] is None
            ):
                raise DeploymentError("Deployment receipt is not available.")
            receipt_path = Path(request["receipt_reference"])
            if sha256_file(receipt_path) != request["receipt_sha256"]:
                raise DeploymentError("Deployment receipt checksum disagrees.")
            _print_json(_load_json(receipt_path, label="deployment receipt"))
        elif args.command == "resume":
            _print_json(controller.resume(args.request_id))
        elif args.command == "worker":
            _print_json(controller.worker(args.request_id))
        elif args.command == "rollback-worker":
            _print_json(controller.rollback_worker(args.request_id))
        else:
            active = ActiveRecord(
                schema_version=1,
                active_sha=_require_sha(args.active_sha, label="Active SHA"),
                active_release_directory=str(config.releases_root / args.active_sha),
                manifest_sha256=_require_digest(
                    args.manifest_sha256, label="Manifest checksum"
                ),
                activation_request_id=None,
                activation_workflow=None,
                activated_at=_require_timestamp(
                    args.activated_at, label="Activation timestamp"
                ),
                database_revision=_require_revision(args.database_revision),
                previous_active_sha=None,
                receipt_reference=None,
                receipt_sha256=None,
            )
            with MutationLock(config.mutation_lock):
                store.seed_active(active)
            _print_json(
                {
                    "schema_version": 1,
                    "outcome": "seeded",
                    "active_sha": active.active_sha,
                }
            )
    except DeploymentError as error:
        print(f"Production deployment control failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
