from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = REPOSITORY_ROOT / "scripts" / "minio-storage-preflight.sh"


def _bash() -> Path:
    if os.name == "nt":
        path = Path(os.environ["ProgramFiles"]) / "Git" / "bin" / "bash.exe"
        assert path.is_file()
        return path
    return Path("/bin/bash")


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    resolved = path.resolve().as_posix()
    return f"/{resolved[0].lower()}{resolved[2:]}"


def _run(tmp_path: Path, *, stat_ok: bool = True, version: str = "Enabled"):
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        "docker() {\n"
        "if [[ \"$*\" == *'mc stat --json'* ]]; then\n"
        f"  return {0 if stat_ok else 1}\n"
        "fi\n"
        "if [[ \"$*\" == *'mc version info --json'* ]]; then\n"
        f"  printf '%s\\n' '{{\"versioning\":{{\"status\":\"{version}\"}}}}'\n"
        "fi\n"
        "}\n"
        f"python3() {{ '{_bash_path(Path(sys.executable))}' \"$@\"; }}\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "BASH_ENV": _bash_path(bash_env),
            "MINIO_CONTAINER": "synthetic-minio",
            "MINIO_BUCKET_NAME": "synthetic-bucket",
        }
    )
    return subprocess.run(
        [str(_bash()), _bash_path(PREFLIGHT)],
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def test_preflight_passes_for_existing_versioned_bucket(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "preflight passed" in result.stdout


@pytest.mark.parametrize(
    ("stat_ok", "version", "message"),
    [
        (False, "Enabled", "could not verify"),
        (True, "Suspended", "requires bucket versioning"),
        (True, "Unversioned", "requires bucket versioning"),
    ],
)
def test_preflight_fails_closed_without_required_storage_state(
    tmp_path: Path,
    stat_ok: bool,
    version: str,
    message: str,
) -> None:
    result = _run(tmp_path, stat_ok=stat_ok, version=version)
    assert result.returncode == 2
    assert message in result.stderr
