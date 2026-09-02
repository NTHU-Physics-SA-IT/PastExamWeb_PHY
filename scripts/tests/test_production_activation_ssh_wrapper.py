from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "pastexam-activate-ssh-wrapper.sh"
INSTALLER = ROOT / "scripts" / "install-production-activation-framework.sh"
SHA = "a" * 40


def _bash() -> Path:
    if os.name == "nt":
        return Path(os.environ["ProgramFiles"]) / "Git" / "bin" / "bash.exe"
    return Path("/bin/bash")


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    resolved = path.resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if resolved.is_relative_to(temporary_root):
        return f"/tmp/{resolved.relative_to(temporary_root).as_posix()}"
    return f"/{resolved.drive.rstrip(':').lower()}{resolved.as_posix()[2:]}"


def _invoke(
    tmp_path: Path, command: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "sudo.log"
    sudo = fake_bin / "sudo"
    sudo.write_text(
        '#!/usr/bin/env bash\nset -eu\nprintf \'%s\\n\' "$@" >"$FAKE_SUDO_LOG"\n',
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "SSH_ORIGINAL_COMMAND": command,
            "FAKE_SUDO_LOG": _bash_path(log),
            "PATH": f"{_bash_path(fake_bin)}:{environment.get('PATH', '')}",
        }
    )
    process = subprocess.run(
        [str(_bash()), str(WRAPPER)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )
    return process, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.mark.parametrize(
    "command",
    [
        "status",
        f"preflight {SHA} 123 1",
        f"start {SHA} activation-123-1 123 1 456 1",
        "request-status activation-123-1",
        "receipt activation-123-1",
        "resume activation-123-1",
        f"rollback-preflight {SHA} 123 1",
        f"rollback-start {SHA} rollback-123-1 123 1 456 1",
    ],
)
def test_wrapper_allows_only_exact_control_grammar(
    tmp_path: Path, command: str
) -> None:
    process, arguments = _invoke(tmp_path, command)

    assert process.returncode == 0, process.stderr
    assert arguments[:2] == [
        "-n",
        "/usr/local/sbin/pastexam-production-deployment-control",
    ]
    assert arguments[2:] == command.split()


@pytest.mark.parametrize(
    "command",
    [
        "",
        "docker ps",
        "sudo -l",
        "worker activation-123-1",
        "rollback-worker rollback-123-1",
        f"start {SHA};id activation-123-1 123 1 456 1",
        f"start {SHA} activation-123-1 123 1 456 1 extra",
        f"start {'A' * 40} activation-123-1 123 1 456 1",
        f"start {SHA} bad 123 1 456 1",
        f"preflight {SHA} 0 1",
        "request-status activation-123-1;id",
        "bash",
        "sh -c id",
    ],
)
def test_wrapper_rejects_shell_and_unreviewed_authority(
    tmp_path: Path, command: str
) -> None:
    process, arguments = _invoke(tmp_path, command)

    assert process.returncode != 0
    assert arguments == []


def test_installer_uses_root_owned_immutable_sources_and_starts_nothing() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "sha256sum --check --quiet .release-files.sha256" in source
    assert "stat -c '%u' \"$source_root\"" in source
    assert '[ ! -L "$source_path" ]' in source
    assert "8#$source_mode & 8#022" in source
    assert "writable by an unsafe role" in source
    assert "sha256:%s %s *" in source
    assert "visudo -c" in source
    for forbidden in (
        "docker compose up",
        "docker restart",
        "systemctl restart",
        "useradd",
        "usermod",
        "passwd -u",
    ):
        assert forbidden not in source
