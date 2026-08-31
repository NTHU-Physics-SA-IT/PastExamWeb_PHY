from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = REPOSITORY_ROOT / "scripts" / "minio-storage-preflight.sh"
SYNTHETIC_ACCESS_KEY = "synthetic-operator-access"
SYNTHETIC_SECRET_KEY = "synthetic-operator-secret"


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


def _run(
    tmp_path: Path,
    *,
    alias_ok: bool = True,
    stat_ok: bool = True,
    version_query_ok: bool = True,
    version: str = "Enabled",
    signal_stage: str | None = None,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    mc_log = tmp_path / "mc.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_mkdir = fake_bin / "mkdir"
    fake_mkdir.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        'directory="${!#}"\n'
        '/usr/bin/mkdir "$@"\n'
        "if command -v cygpath >/dev/null 2>&1; then\n"
        '  logged_directory="$(cygpath -w "$directory")"\n'
        "else\n"
        '  logged_directory="$directory"\n'
        "fi\n"
        f"printf 'mkdir|%s|directory\\n' \"$logged_directory\" >>'{_bash_path(mc_log)}'\n"
        f"if [[ 'mkdir' == '{signal_stage}' ]]; then kill -TERM \"$PPID\"; fi\n",
        encoding="utf-8",
    )
    fake_mkdir.chmod(0o755)
    fake_mc = fake_bin / "mc"
    fake_mc.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        "[[ \"$1\" == '--config-dir' ]] || exit 91\n"
        'config_directory="$2"\n'
        "if command -v cygpath >/dev/null 2>&1; then\n"
        '  logged_config_directory="$(cygpath -w "$config_directory")"\n'
        "else\n"
        '  logged_config_directory="$config_directory"\n'
        "fi\n"
        "shift 2\n"
        'case "$1 $2" in\n'
        "  'alias set')\n"
        f"    printf 'alias|%s|%s\\n' \"$logged_config_directory\" \"$3\" >>'{_bash_path(mc_log)}'\n"
        f"    if [[ 'alias' == '{signal_stage}' ]]; then kill -TERM \"$PPID\"; fi\n"
        f"    exit {0 if alias_ok else 1}\n"
        "    ;;\n"
        "  'stat --json')\n"
        f"    printf 'stat|%s|%s\\n' \"$logged_config_directory\" \"$3\" >>'{_bash_path(mc_log)}'\n"
        f"    if [[ 'stat' == '{signal_stage}' ]]; then kill -TERM \"$PPID\"; fi\n"
        f"    exit {0 if stat_ok else 1}\n"
        "    ;;\n"
        "  'version info')\n"
        f"    printf 'version|%s|%s\\n' \"$logged_config_directory\" \"$4\" >>'{_bash_path(mc_log)}'\n"
        f"    if [[ 'version' == '{signal_stage}' ]]; then kill -TERM \"$PPID\"; fi\n"
        f"    if [[ {0 if version_query_ok else 1} -ne 0 ]]; then exit 1; fi\n"
        f'    printf \'%s\\n\' \'{{"versioning":{{"status":"{version}"}}}}\'\n'
        "    ;;\n"
        "  *) exit 92 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_mc.chmod(0o755)
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        f"export PATH='{_bash_path(fake_bin)}':\"$PATH\"\n"
        "docker() {\n"
        "  [[ \"$1\" == 'exec' ]] || return 90\n"
        "  shift 2\n"
        f"  MINIO_ROOT_USER='{SYNTHETIC_ACCESS_KEY}' "
        f"MINIO_ROOT_PASSWORD='{SYNTHETIC_SECRET_KEY}' command \"$@\"\n"
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
    result = subprocess.run(
        [str(_bash()), _bash_path(PREFLIGHT)],
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    log_lines = (
        mc_log.read_text(encoding="utf-8").splitlines() if mc_log.exists() else []
    )
    return result, log_lines


def _config_directories(log_lines: list[str]) -> set[Path]:
    return {Path(line.split("|", 2)[1]) for line in log_lines}


def _assert_secret_safe(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout + result.stderr
    assert SYNTHETIC_ACCESS_KEY not in output
    assert SYNTHETIC_SECRET_KEY not in output


def test_preflight_uses_unique_ephemeral_operator_alias_and_cleans_it(
    tmp_path: Path,
) -> None:
    first, first_log = _run(tmp_path / "first")
    second, second_log = _run(tmp_path / "second")

    assert first.returncode == second.returncode == 0
    assert "preflight passed" in first.stdout
    assert [line.split("|", 1)[0] for line in first_log] == [
        "mkdir",
        "alias",
        "stat",
        "version",
    ]
    assert first_log[1].rsplit("|", 1)[1] == "preflight"
    assert all(
        line.rsplit("|", 1)[1].startswith("preflight/") for line in first_log[2:]
    )

    first_directories = _config_directories(first_log)
    second_directories = _config_directories(second_log)
    assert len(first_directories) == len(second_directories) == 1
    assert first_directories.isdisjoint(second_directories)
    assert not any(path.exists() for path in first_directories | second_directories)
    _assert_secret_safe(first)
    _assert_secret_safe(second)


@pytest.mark.parametrize(
    ("alias_ok", "stat_ok", "version_query_ok", "version", "message"),
    [
        (False, True, True, "Enabled", "could not verify"),
        (True, False, True, "Enabled", "could not verify"),
        (True, True, False, "Enabled", "could not verify"),
        (True, True, True, "Disabled", "requires bucket versioning"),
        (True, True, True, "Suspended", "requires bucket versioning"),
        (True, True, True, "Unexpected", "requires bucket versioning"),
    ],
)
def test_preflight_fails_closed_and_cleans_ephemeral_config(
    tmp_path: Path,
    alias_ok: bool,
    stat_ok: bool,
    version_query_ok: bool,
    version: str,
    message: str,
) -> None:
    result, log_lines = _run(
        tmp_path,
        alias_ok=alias_ok,
        stat_ok=stat_ok,
        version_query_ok=version_query_ok,
        version=version,
    )

    assert result.returncode == 2
    assert message in result.stderr
    assert not any(path.exists() for path in _config_directories(log_lines))
    _assert_secret_safe(result)


@pytest.mark.parametrize("signal_stage", ["mkdir", "version"])
def test_preflight_signal_fails_closed_and_cleans_ephemeral_config(
    tmp_path: Path,
    signal_stage: str,
) -> None:
    result, log_lines = _run(tmp_path, signal_stage=signal_stage)

    assert result.returncode == 2
    assert "preflight passed" not in result.stdout
    assert "could not verify" in result.stderr
    assert not any(path.exists() for path in _config_directories(log_lines))
    _assert_secret_safe(result)


def test_preflight_never_uses_or_modifies_persistent_local_alias() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")

    assert 'mc stat --json "local/' not in source
    assert 'mc version info --json "local/' not in source
    assert "--config-dir" in source
    assert 'config_directory="/tmp/pastexam-minio-preflight.$$"' in source
    assert 'mkdir -m 700 -- "$config_directory"' in source
    assert "MINIO_ROOT_USER" in source
    assert "MINIO_ROOT_PASSWORD" in source
    assert "mc version enable" not in source
    assert "mc mb" not in source
