"""Sealed command-line entry point for bounded read-only aggregate audits."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence

from app.db.audit.models import AuditMode, AuditRequest, AuditResult
from app.db.audit.registry import ELIGIBILITY_AUDIT_ID, get_audit_adapter
from app.db.audit.runner import (
    AuditExecutionError,
    execute_audit,
    run_with_command,
)
from app.db.schema_manifests import HEAD_SCHEMA_REVISION


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Run a sealed aggregate-only database audit"
    )
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--audit", required=True, choices=[ELIGIBILITY_AUDIT_ID])
    run.add_argument("--version", type=int, default=1, choices=[1])
    run.add_argument(
        "--mode",
        required=True,
        choices=[mode.value for mode in AuditMode],
    )
    run.add_argument("--expected-ledger", default=HEAD_SCHEMA_REVISION)
    run.add_argument("--repository-revision")
    run.add_argument("--expected-database")
    run.add_argument("--expected-role")
    run.add_argument(
        "--authorize-production-aggregate-only",
        action="store_true",
        help="Required in addition to task-level production authorization",
    )
    run.add_argument("--output", choices=["json", "text"], default="text")
    return root


def _repository_revision(explicit: str | None) -> str:
    if explicit:
        return explicit
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    if process.returncode != 0:
        raise AuditExecutionError("repository_revision_unavailable")
    return process.stdout.strip()


def run_with_command_for_test(
    request: AuditRequest,
    *,
    command: Sequence[str],
    sql: str,
) -> AuditResult:
    return run_with_command(request, command=command, sql=sql)


def _emit(result: AuditResult, output: str) -> None:
    if output == "json":
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    else:
        print(result.to_human_summary())


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        request = AuditRequest(
            audit_id=arguments.audit,
            audit_version=arguments.version,
            mode=AuditMode(arguments.mode),
            expected_ledger=arguments.expected_ledger,
            repository_revision=_repository_revision(arguments.repository_revision),
            expected_database=arguments.expected_database,
            expected_role=arguments.expected_role,
            production_authorized=arguments.authorize_production_aggregate_only,
        )
        adapter = get_audit_adapter(request.audit_id, request.audit_version)
        result = execute_audit(request, adapter)
    except (AuditExecutionError, KeyError, ValueError) as exc:
        print(f"audit_error: {exc}", file=sys.stderr)
        return 2
    _emit(result, arguments.output)
    return 0 if result.status.value in {"complete", "data_blocked"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
