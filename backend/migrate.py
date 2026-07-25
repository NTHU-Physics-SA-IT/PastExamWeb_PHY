#!/usr/bin/env python3
"""Fail-closed database migration command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from alembic import command

from app.db.migration_safety import (
    MigrationReport,
    alembic_config,
    inspect_database,
    redact_text,
    safe_error,
)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    subcommands = cli.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser("create")
    create.add_argument("message")

    upgrade = subcommands.add_parser("upgrade")
    upgrade.add_argument("--json", action="store_true")

    downgrade = subcommands.add_parser("downgrade")
    downgrade.add_argument("revision")

    subcommands.add_parser("current")
    subcommands.add_parser("history")

    preflight = subcommands.add_parser("preflight")
    preflight.add_argument("--json", action="store_true")

    reconcile = subcommands.add_parser("reconcile")
    reconcile.add_argument(
        "--check",
        action="store_true",
        required=True,
        help="Run a read-only head-schema assessment.",
    )
    reconcile.add_argument("--json", action="store_true")
    return cli


def print_report(report: MigrationReport, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str))
        return

    empty = (
        str(report.database_empty).upper()
        if report.database_empty is not None
        else "UNKNOWN"
    )
    print("Migration safety report")
    print(f"Database connection: {'OK' if report.database_connected else 'FAILED'}")
    print(f"Database name: {report.database_name or 'UNKNOWN'}")
    print(f"Database empty: {empty}")
    print(
        "Alembic ledger: "
        f"{'PRESENT' if report.alembic_version_exists else 'MISSING'}"
    )
    print(f"Alembic revisions: {report.alembic_versions}")
    print(f"Current revision known: {'YES' if report.current_revision_known else 'NO'}")
    print(f"Repository heads: {report.repository_heads}")
    print(f"Multiple repository heads: {'YES' if report.multiple_heads else 'NO'}")
    print(
        "Head schema candidate: "
        f"{report.schema_candidate_revision or 'NONE'}"
    )
    for check in report.schema_checks:
        print(
            f"Schema [{check.name}]: "
            f"{'PASS' if check.passed else 'FAIL'} - {redact_text(check.message)}"
        )
    print(f"Schema matches head: {'YES' if report.schema_matches_head else 'NO'}")
    print(f"Upgrade allowed: {'YES' if report.upgrade_allowed else 'NO'}")
    for warning in report.warnings:
        print(f"WARNING: {redact_text(warning)}")
    for error in report.errors:
        print(f"ERROR: {redact_text(error)}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = alembic_config()
    try:
        if args.command == "create":
            command.revision(config, message=args.message, autogenerate=True)
        elif args.command == "upgrade":
            report = inspect_database()
            print_report(report, json_output=args.json)
            if not report.upgrade_allowed:
                return 2
            command.upgrade(config, "head")
        elif args.command == "downgrade":
            command.downgrade(config, args.revision)
        elif args.command == "current":
            command.current(config, verbose=True)
        elif args.command == "history":
            command.history(config, verbose=True)
        elif args.command in {"preflight", "reconcile"}:
            report = inspect_database()
            print_report(report, json_output=args.json)
            # A missing ledger remains a failure even when the schema has a
            # structural head candidate. This command never stamps or repairs.
            return 0 if report.upgrade_allowed else 2
    except Exception as exc:
        print(f"Migration command failed: {safe_error(exc)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
