#!/usr/bin/env python3
"""Fail-closed database migration command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

try:
    from sqlalchemy import create_engine

    from alembic import command
    from app.db.migration_safety import (
        MigrationAdvisoryLockReleaseError,
        MigrationAdvisoryLockUnavailableError,
        MigrationReport,
        alembic_config,
        database_url,
        inspect_database,
        migration_advisory_lock,
        redact_text,
        safe_error,
    )
except Exception:  # noqa: BLE001 - diagnostic mode must classify import/config failure.
    MIGRATOR_INITIALIZATION_FAILED = True
else:
    MIGRATOR_INITIALIZATION_FAILED = False

DIAGNOSTIC_SCHEMA_VERSION = 1
DIAGNOSTIC_KIND = "migration-class-zero-probe"


class DatabaseIdentityMismatchError(RuntimeError):
    """The inspection target differs from the advisory-lock target."""


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

    require_head = subcommands.add_parser("require-head")
    require_head.add_argument("--json", action="store_true")

    diagnose_head = subcommands.add_parser("diagnose-head")
    diagnose_head.add_argument("--json", action="store_true", required=True)

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
        f"Alembic ledger: {'PRESENT' if report.alembic_version_exists else 'MISSING'}"
    )
    print(f"Alembic revisions: {report.alembic_versions}")
    print(f"Current revision known: {'YES' if report.current_revision_known else 'NO'}")
    print(f"Repository heads: {report.repository_heads}")
    print(f"Reviewed manifests: {report.reviewed_manifest_revisions}")
    print(f"Multiple repository heads: {'YES' if report.multiple_heads else 'NO'}")
    print(f"Head schema candidate: {report.schema_candidate_revision or 'NONE'}")
    passed_checks = sum(check.passed for check in report.schema_checks)
    print(f"Schema checks: {passed_checks}/{len(report.schema_checks)} passed")
    for check in (item for item in report.schema_checks if not item.passed):
        print(f"Schema [{check.name}]: FAIL - {redact_text(check.message)}")
    print(f"Schema matches head: {'YES' if report.schema_matches_head else 'NO'}")
    print(f"Upgrade allowed: {'YES' if report.upgrade_allowed else 'NO'}")
    for warning in report.warnings:
        print(f"WARNING: {redact_text(warning)}")
    for error in report.errors:
        print(f"ERROR: {redact_text(error)}")


def class_zero_eligible(report: MigrationReport) -> bool:
    """Return the single authoritative Class-0 eligibility decision."""
    return bool(
        report.upgrade_allowed
        and not report.multiple_heads
        and len(report.repository_heads) == 1
        and report.current_revision == report.repository_heads[0]
        and report.current_revision_known
        and report.schema_matches_head
    )


def _diagnostic_envelope(
    *,
    outcome: str,
    failure_code: str | None,
    report: MigrationReport | None,
) -> dict[str, object]:
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "kind": DIAGNOSTIC_KIND,
        "probe_outcome": outcome,
        "failure_code": failure_code,
        "report": report.to_dict() if report is not None else None,
    }


def _emit_diagnostic_envelope(
    *, outcome: str, failure_code: str | None, report: MigrationReport | None
) -> bool:
    encoded = True
    try:
        serialized = json.dumps(
            _diagnostic_envelope(
                outcome=outcome,
                failure_code=failure_code,
                report=report,
            ),
            sort_keys=True,
            default=str,
        )
    except Exception:  # noqa: BLE001 - emit a fixed safe envelope if encoding fails.
        encoded = False
        serialized = json.dumps(
            _diagnostic_envelope(
                outcome="failed",
                failure_code="diagnostic_envelope_failed",
                report=None,
            ),
            sort_keys=True,
        )
    print(serialized)
    return encoded


def diagnose_head() -> int:
    """Run the read-only Class-0 probe and always emit one safe envelope."""
    if MIGRATOR_INITIALIZATION_FAILED:
        _emit_diagnostic_envelope(
            outcome="failed",
            failure_code="migrator_initialization_failed",
            report=None,
        )
        return 2
    report: MigrationReport | None = None
    engine = None
    stage = "migrator_initialization"
    outcome = "failed"
    failure_code: str | None = None
    exit_code = 2
    try:
        engine = create_engine(database_url(), pool_pre_ping=True)
        stage = "database_or_lock_setup"
        with migration_advisory_lock(engine) as locked_database:
            stage = "database_inspection"
            report = inspect_database(engine)
            stage = "database_identity"
            if report.database_name != locked_database:
                raise DatabaseIdentityMismatchError
            outcome = "eligible" if class_zero_eligible(report) else "ineligible"
            exit_code = 0 if outcome == "eligible" else 2
            stage = "advisory_lock_release"
    except MigrationAdvisoryLockUnavailableError:
        failure_code = "advisory_lock_unavailable"
    except MigrationAdvisoryLockReleaseError:
        failure_code = "advisory_lock_release_failed"
    except DatabaseIdentityMismatchError:
        failure_code = "database_identity_mismatch"
        report = None
    except Exception:  # noqa: BLE001 - map only the trusted stage, never exception text.
        failure_code = {
            "migrator_initialization": "migrator_initialization_failed",
            "database_or_lock_setup": "database_or_lock_setup_failed",
            "database_inspection": "database_inspection_failed",
            "database_identity": "database_inspection_failed",
            "advisory_lock_release": "advisory_lock_release_failed",
        }[stage]
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001 - cleanup failure must remain fail-closed.
                outcome = "failed"
                failure_code = "migrator_cleanup_failed"
                report = None
                exit_code = 2
    if failure_code is not None:
        outcome = "failed"
        exit_code = 2
    emitted = _emit_diagnostic_envelope(
        outcome=outcome,
        failure_code=failure_code,
        report=report,
    )
    return exit_code if emitted else 2


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "diagnose-head":
        return diagnose_head()
    if MIGRATOR_INITIALIZATION_FAILED:
        print(
            "Migration command failed: migrator initialization failed", file=sys.stderr
        )
        return 2
    config = alembic_config()
    try:
        if args.command == "create":
            command.revision(config, message=args.message, autogenerate=True)
        elif args.command == "upgrade":
            engine = create_engine(database_url(), pool_pre_ping=True)
            try:
                with migration_advisory_lock(engine) as locked_database:
                    report = inspect_database(engine)
                    print_report(report, json_output=args.json)
                    if report.database_name != locked_database:
                        raise RuntimeError(
                            "Migration lock and preflight targeted different databases"
                        )
                    if not report.upgrade_allowed:
                        return 2
                    if report.current_revision not in report.repository_heads:
                        command.upgrade(config, "head")
                    upgraded = inspect_database(engine)
                    if (
                        upgraded.database_name != locked_database
                        or not upgraded.upgrade_allowed
                        or upgraded.current_revision not in upgraded.repository_heads
                        or not upgraded.schema_matches_head
                    ):
                        print(
                            "Migration completed but post-upgrade schema "
                            "validation failed",
                            file=sys.stderr,
                        )
                        return 2
            finally:
                engine.dispose()
        elif args.command == "downgrade":
            command.downgrade(config, args.revision)
        elif args.command == "current":
            command.current(config, verbose=True)
        elif args.command == "history":
            command.history(config, verbose=True)
        elif args.command == "require-head":
            engine = create_engine(database_url(), pool_pre_ping=True)
            try:
                with migration_advisory_lock(engine) as locked_database:
                    report = inspect_database(engine)
                    print_report(report, json_output=args.json)
                    if report.database_name != locked_database:
                        raise RuntimeError(
                            "Migration lock and head check targeted different databases"
                        )
                    if not class_zero_eligible(report):
                        print(
                            "Production Class 0 requires the database to match the exact repository head",
                            file=sys.stderr,
                        )
                        return 2
            finally:
                engine.dispose()
        elif args.command in {"preflight", "reconcile"}:
            report = inspect_database()
            print_report(report, json_output=args.json)
            # A missing ledger remains a failure even when the schema has a
            # structural head candidate. This command never stamps or repairs.
            return 0 if report.upgrade_allowed else 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary must fail closed.
        print(f"Migration command failed: {safe_error(exc)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
