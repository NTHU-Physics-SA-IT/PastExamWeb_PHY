from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
DEV_COMPOSE = REPOSITORY_ROOT / "docker" / "docker-compose.dev.yml"


def _frontend_command() -> str:
    compose = DEV_COMPOSE.read_text(encoding="utf-8")
    frontend = compose.split("\n  frontend:\n", maxsplit=1)[1].split(
        "\n  nginx:\n", maxsplit=1
    )[0]
    match = re.search(r"(?m)^    command: >-\n((?:      .*\n)+)", frontend)
    assert match is not None
    return " ".join(line.strip() for line in match.group(1).splitlines())


def _fake_environment(tmp_path: Path, *, install_exit: int) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pnpm = bin_dir / "pnpm"
    fake_pnpm.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'printf "CI=%s|%s\\n" "${CI-unset}" "$*" >> "$FAKE_PNPM_LOG"\n'
        'if [ "${1:-}" = install ]; then exit "$FAKE_INSTALL_EXIT"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_pnpm.chmod(0o700)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{environment['PATH']}",
            "FAKE_INSTALL_EXIT": str(install_exit),
            "FAKE_PNPM_LOG": str(tmp_path / "pnpm.log"),
        }
    )
    environment.pop("CI", None)
    return environment


def _run_frontend_command(
    tmp_path: Path, *, install_exit: int
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    environment = _fake_environment(tmp_path, install_exit=install_exit)
    process = subprocess.run(
        ["sh", "-c", _frontend_command()],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )
    log = Path(environment["FAKE_PNPM_LOG"]).read_text(
        encoding="utf-8"
    ).splitlines()
    return process, log


def test_frontend_startup_uses_explicit_frozen_noninteractive_install() -> None:
    command = _frontend_command()

    assert command.startswith(
        'sh -c "CI=true pnpm install --frozen-lockfile '
    )
    assert "--store-dir /app/node_modules/.pnpm-store" in command
    assert "&& exec pnpm run dev --host 0.0.0.0 --port 80" in command
    for forbidden in ("--force", "--no-frozen-lockfile", "rm -rf"):
        assert forbidden not in command


def test_frontend_startup_stops_before_vite_when_install_fails(
    tmp_path: Path,
) -> None:
    process, log = _run_frontend_command(tmp_path, install_exit=23)

    assert process.returncode == 23
    assert log == [
        (
            "CI=true|install --frozen-lockfile --store-dir "
            "/app/node_modules/.pnpm-store"
        )
    ]


def test_frontend_startup_scopes_ci_to_install_and_execs_vite(
    tmp_path: Path,
) -> None:
    process, log = _run_frontend_command(tmp_path, install_exit=0)

    assert process.returncode == 0
    assert log == [
        (
            "CI=true|install --frozen-lockfile --store-dir "
            "/app/node_modules/.pnpm-store"
        ),
        "CI=unset|run dev --host 0.0.0.0 --port 80",
    ]
