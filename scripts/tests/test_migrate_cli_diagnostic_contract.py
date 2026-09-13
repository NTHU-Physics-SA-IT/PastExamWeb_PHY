from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATE = REPOSITORY_ROOT / "backend" / "migrate.py"


def test_diagnose_head_seals_import_time_configuration_failure() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DB_PORT": "not-an-integer",
            "DB_PASSWORD": "private-test-password-must-not-leak",
        }
    )

    process = subprocess.run(
        [sys.executable, str(MIGRATE), "diagnose-head", "--json"],
        cwd=MIGRATE.parent,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert process.returncode == 2
    assert process.stderr == ""
    assert len(process.stdout.strip().splitlines()) == 1
    assert json.loads(process.stdout) == {
        "schema_version": 1,
        "kind": "migration-class-zero-probe",
        "probe_outcome": "failed",
        "failure_code": "migrator_initialization_failed",
        "report": None,
    }
    assert "private-test-password-must-not-leak" not in process.stdout
