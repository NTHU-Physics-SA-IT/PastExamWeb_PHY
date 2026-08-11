from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[2]
BACKUP_SCRIPT = REPOSITORY_ROOT / "scripts" / "postgres-logical-backup.sh"


def test_backup_checksum_supports_macos_and_gnu_coreutils() -> None:
    script = BACKUP_SCRIPT.read_text(encoding="utf-8")

    assert "command -v shasum" in script
    assert 'shasum -a 256 "$dump_path"' in script
    assert "command -v sha256sum" in script
    assert 'sha256sum "$dump_path"' in script
    assert "Neither shasum nor sha256sum is available." in script
