"""Non-interactive transport and fail-closed parsing for sealed audits."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

from pydantic import ValidationError

from app.core.config import SQLALCHEMY_DATABASE_URL
from app.db.audit.models import (
    AuditMode,
    AuditRequest,
    AuditResult,
    AuditStatus,
    ContinuityResult,
    FlagCombination,
)
from app.db.audit.registry import AuditAdapter, get_audit_adapter
from app.db.migration_safety import redact_text
from app.db.test_database_guard import validate_test_database_target

META_MARKER = "__PASTEXAM_AUDIT_META__"
RESULT_MARKER = "__PASTEXAM_AUDIT_RESULT__"
ROLLBACK_SENTINEL = "__PASTEXAM_AUDIT_ROLLBACK_COMPLETE__"
MAX_OUTPUT_BYTES = 64 * 1024
MAX_COMBINATIONS = 20
BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = BACKEND_ROOT.parent


class AuditExecutionError(RuntimeError):
    """A bounded audit could not produce a safe, validated result."""


_FORBIDDEN_SQL = re.compile(
    r"""
    \b(
        insert|update|delete|merge|truncate|alter|create|drop|
        grant|revoke|copy|vacuum|analyze|reindex|call|do|lock
    )\b
    |
    \bfor\s+(update|share|no\s+key\s+update|key\s+share)\b
    |
    \bpg_(try_)?advisory_(xact_)?lock\b
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def validate_adapter_sql(sql: str) -> None:
    if _FORBIDDEN_SQL.search(sql):
        raise ValueError("sealed audit SQL must remain read-only")
    if re.search(r"\btemporary?\b", sql, flags=re.IGNORECASE):
        raise ValueError("sealed audit SQL must remain read-only")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _identity_expression(request: AuditRequest) -> str:
    expected_database = request.expected_database
    expected_role = request.expected_role
    if request.mode is AuditMode.ISOLATED_TEST:
        database_check = (
            f"current_database() = {_sql_literal(expected_database)}"
            if expected_database
            else "current_database() LIKE 'pastexam_test\\_%' ESCAPE '\\'"
        )
        role_check = (
            f"current_user = {_sql_literal(expected_role)}"
            if expected_role
            else "current_user LIKE 'pastexam_test\\_%' ESCAPE '\\'"
        )
        privilege_check = (
            "NOT role.rolsuper "
            "AND NOT role.rolcreatedb "
            "AND NOT role.rolcreaterole "
            "AND pg_get_userbyid(database.datdba) = current_user"
        )
    elif request.mode is AuditMode.PERSISTENT_LOCAL:
        database_check = (
            f"current_database() = {_sql_literal(expected_database or 'archive_db')}"
        )
        role_check = (
            f"current_user = {_sql_literal(expected_role)}" if expected_role else "TRUE"
        )
        privilege_check = "TRUE"
    else:
        database_check = (
            f"current_database() = {_sql_literal(expected_database)}"
            if expected_database
            else "current_database() NOT LIKE 'pastexam_test\\_%' ESCAPE '\\'"
        )
        role_check = (
            f"current_user = {_sql_literal(expected_role)}" if expected_role else "TRUE"
        )
        privilege_check = "TRUE"
    return f"({database_check}) AND ({role_check}) AND ({privilege_check})"


def _continuity_cte(request: AuditRequest) -> str:
    expected = _sql_literal(request.expected_ledger)
    expects_owner_delete_column = request.expected_ledger in {
        "f5e1d8c3a7b2",
        "d8f2a6c1b4e7",
        "6f3a9c2d8e41",
        "9f1c2a7e4b63",
        "b7e3d9a1c5f2",
    }
    owner_delete_column_condition = (
        """
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'archive_submissions'
              AND column_name = 'owner_self_delete_consumed'
              AND data_type = 'boolean'
              AND is_nullable = 'NO'
              AND lower(regexp_replace(column_default, '[(): ]', '', 'g'))
                  IN ('false', 'false::boolean')
        )
        """
        if expects_owner_delete_column
        else """
        NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'archive_submissions'
              AND column_name = 'owner_self_delete_consumed'
        )
        """
    )
    expects_previous_status_column = request.expected_ledger in {
        "d8f2a6c1b4e7",
        "6f3a9c2d8e41",
        "9f1c2a7e4b63",
        "b7e3d9a1c5f2",
    }
    previous_status_column_condition = (
        """
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'archive_submissions'
              AND column_name = 'previous_status'
              AND udt_name = 'submissionstatus'
              AND is_nullable = 'YES'
        )
        """
        if expects_previous_status_column
        else """
        NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'archive_submissions'
              AND column_name = 'previous_status'
        )
        """
    )
    return f"""
WITH identity AS (
    SELECT
        ({_identity_expression(request)}) AS identity_ok
    FROM pg_database AS database
    JOIN pg_roles AS role ON role.rolname = current_user
    WHERE database.datname = current_database()
),
ledger AS (
    SELECT
        count(*)::integer AS ledger_row_count,
        min(version_num) AS actual_ledger
    FROM alembic_version
),
required_columns AS (
    SELECT count(*)::integer = 10 AS required_columns_ok
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'archive_submissions'
      AND column_name IN (
        'requester_id',
        'owner_id',
        'status',
        'deleted_at',
        'deleted_by_id',
        'delete_reason',
        'lifecycle_reason',
        'restored_at',
        'restored_by_id',
        'created_archive_id'
      )
),
schema_state AS (
    SELECT
        to_regclass('public.archive_submissions') IS NOT NULL
        AND to_regclass('public.users') IS NOT NULL
        AND to_regclass('public.alembic_version') IS NOT NULL
        AND required_columns.required_columns_ok
        AND ({owner_delete_column_condition})
        AND ({previous_status_column_condition}) AS schema_ok
    FROM required_columns
),
enum_state AS (
    SELECT
        count(*)::integer AS enum_count,
        array_agg(e.enumlabel::text ORDER BY e.enumsortorder)
            = ARRAY[
                'PENDING',
                'APPROVED',
                'REJECTED',
                'DELETED',
                'TAKEDOWN'
              ]::text[] AS enum_match
    FROM pg_type AS t
    JOIN pg_namespace AS namespace ON namespace.oid = t.typnamespace
    JOIN pg_enum AS e ON e.enumtypid = t.oid
    WHERE namespace.nspname = 'public'
      AND t.typname = 'submissionstatus'
),
continuity AS (
    SELECT
        current_setting('transaction_read_only') = 'on' AS read_only,
        identity.identity_ok,
        ledger.ledger_row_count,
        ledger.actual_ledger,
        (
            ledger.ledger_row_count = 1
            AND ledger.actual_ledger = {expected}
        ) AS ledger_ok,
        schema_state.schema_ok,
        enum_state.enum_count,
        enum_state.enum_match
    FROM identity, ledger, schema_state, enum_state
)
"""


def _meta_select(request: AuditRequest) -> str:
    return (
        _continuity_cte(request)
        + f"""
SELECT
    '{META_MARKER}' || json_build_object(
        'read_only', read_only,
        'identity_ok', identity_ok,
        'ledger_row_count', ledger_row_count,
        'actual_ledger', actual_ledger,
        'ledger_ok', ledger_ok,
        'schema_ok', schema_ok,
        'enum_count', enum_count,
        'enum_match', enum_match
    )::text
FROM continuity
"""
    )


def _gate_select(request: AuditRequest) -> str:
    return (
        _continuity_cte(request)
        + """
SELECT (
    read_only
    AND identity_ok
    AND ledger_ok
    AND schema_ok
    AND enum_count = 5
    AND enum_match
) AS gate_ok
FROM continuity
"""
    )


def _result_select(adapter: AuditAdapter) -> str:
    return f"""
WITH summary AS (
{adapter.summary_sql}
),
combinations AS (
{adapter.combinations_sql}
),
result AS (
    SELECT
        CASE
            WHEN summary.unsupported = 0
             AND summary.unclassified = 0
             AND summary.overlap = 0
             AND summary.difference = 0
            THEN 'complete'
            ELSE 'data_blocked'
        END AS status,
        to_jsonb(summary) AS aggregates,
        summary.overlap = 0 AS mutual_exclusivity,
        summary.difference = 0 AS conservation,
        COALESCE(
            (
                SELECT json_agg(
                    json_build_object('flags', flags, 'count', count)
                    ORDER BY flags
                )
                FROM combinations
            ),
            '[]'::json
        ) AS combinations
    FROM summary
)
SELECT
    '{RESULT_MARKER}' || json_build_object(
        'status', status,
        'error_code', NULL,
        'aggregates', aggregates,
        'combinations', combinations,
        'mutual_exclusivity', mutual_exclusivity,
        'conservation', conservation
    )::text
FROM result
"""


def build_transaction_sql(request: AuditRequest, adapter: AuditAdapter) -> str:
    if request.expected_ledger not in adapter.accepted_source_revisions:
        raise AuditExecutionError("expected_ledger_not_supported")
    validate_adapter_sql(adapter.summary_sql)
    validate_adapter_sql(adapter.combinations_sql)
    return f"""\\set ON_ERROR_STOP on
\\pset tuples_only on
\\pset format unaligned
\\pset pager off
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '20s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '30s';
{_meta_select(request)};
{_gate_select(request)}
\\gset audit_
\\if :audit_gate_ok
{_result_select(adapter)};
\\else
SELECT '{RESULT_MARKER}' || json_build_object(
    'status', 'audit_error',
    'error_code', 'continuity_gate_failed',
    'aggregates', NULL,
    'combinations', '[]'::json,
    'mutual_exclusivity', NULL,
    'conservation', NULL
)::text;
\\endif
ROLLBACK;
\\echo {ROLLBACK_SENTINEL}
"""


def _empty_result(
    request: AuditRequest,
    *,
    status: AuditStatus,
    error_code: str,
    explicit_rollback: bool = False,
    completion_sentinel: bool = False,
) -> AuditResult:
    return AuditResult(
        audit_id=request.audit_id,
        audit_version=request.audit_version,
        mode=request.mode,
        expected_ledger=request.expected_ledger,
        repository_revision=request.repository_revision,
        status=status,
        error_code=error_code,
        continuity=None,
        aggregates=None,
        combinations=[],
        mutual_exclusivity=None,
        conservation=None,
        explicit_rollback=explicit_rollback,
        completion_sentinel=completion_sentinel,
    )


def _marked_json(output: str, marker: str) -> dict[str, Any] | None:
    matches = [
        line[len(marker) :] for line in output.splitlines() if line.startswith(marker)
    ]
    if len(matches) != 1:
        return None
    value = json.loads(matches[0])
    if not isinstance(value, dict):
        raise ValueError("marker payload must be an object")
    return value


def parse_process_output(
    request: AuditRequest,
    process: CompletedProcess[str],
) -> AuditResult:
    output = process.stdout or ""
    explicit_rollback = "ROLLBACK" in output.splitlines()
    completion_sentinel = ROLLBACK_SENTINEL in output.splitlines()
    if process.returncode != 0:
        return _empty_result(
            request,
            status=AuditStatus.AUDIT_ERROR,
            error_code="psql_error",
            explicit_rollback=explicit_rollback,
            completion_sentinel=completion_sentinel,
        )
    if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise AuditExecutionError("result_schema_invalid: output too large")
    try:
        meta = _marked_json(output, META_MARKER)
        payload = _marked_json(output, RESULT_MARKER)
        if meta is None or payload is None:
            return _empty_result(
                request,
                status=AuditStatus.INCOMPLETE_TRANSPORT,
                error_code="required_marker_missing",
                explicit_rollback=explicit_rollback,
                completion_sentinel=completion_sentinel,
            )
        continuity = ContinuityResult.model_validate(meta)
        aggregates_payload = payload.pop("aggregates", None)
        combinations_payload = payload.pop("combinations", [])
        adapter = get_audit_adapter(request.audit_id, request.audit_version)
        result = AuditResult(
            audit_id=request.audit_id,
            audit_version=request.audit_version,
            mode=request.mode,
            expected_ledger=request.expected_ledger,
            repository_revision=request.repository_revision,
            continuity=continuity,
            aggregates=(
                adapter.aggregate_model.model_validate(aggregates_payload)
                if aggregates_payload is not None
                else None
            ),
            combinations=[
                FlagCombination.model_validate(item) for item in combinations_payload
            ],
            explicit_rollback=explicit_rollback,
            completion_sentinel=completion_sentinel,
            **payload,
        )
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        raise AuditExecutionError("result_schema_invalid") from exc

    if not explicit_rollback or not completion_sentinel:
        return result.model_copy(
            update={
                "status": AuditStatus.INCOMPLETE_TRANSPORT,
                "error_code": "explicit_rollback_not_confirmed",
            }
        )
    approved_flags = {
        flag for combination in result.combinations for flag in combination.flags
    }
    if len(result.combinations) > MAX_COMBINATIONS:
        raise AuditExecutionError("result_schema_invalid: too many combinations")
    if result.status is AuditStatus.COMPLETE and (
        result.aggregates is None
        or result.continuity is None
        or not all(
            (
                result.continuity.read_only,
                result.continuity.identity_ok,
                result.continuity.ledger_ok,
                result.continuity.schema_ok,
                result.continuity.enum_match,
                result.mutual_exclusivity,
                result.conservation,
            )
        )
    ):
        raise AuditExecutionError("result_schema_invalid: unsafe complete result")
    if approved_flags and not all(
        re.fullmatch(r"[a-z][a-z0-9_]{0,63}", flag) for flag in approved_flags
    ):
        raise AuditExecutionError("result_schema_invalid: unsafe combination label")
    if not approved_flags.issubset(adapter.approved_combination_flags):
        raise AuditExecutionError("result_schema_invalid: unknown combination label")
    return result


def run_with_command(
    request: AuditRequest,
    *,
    command: Sequence[str],
    sql: str,
    environment: dict[str, str] | None = None,
) -> AuditResult:
    try:
        process = subprocess.run(
            list(command),
            input=sql,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditExecutionError(
            f"transport_failed: {redact_text(exc.__class__.__name__)}"
        ) from exc
    return parse_process_output(request, process)


def _inspect_container(
    name: str,
    *,
    project: str,
    service: str,
) -> None:
    format_value = (
        '{{.Name}}|{{index .Config.Labels "com.docker.compose.project"}}'
        '|{{index .Config.Labels "com.docker.compose.service"}}'
        "|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}"
    )
    process = subprocess.run(
        ["docker", "inspect", "--format", format_value, name],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    expected = f"/{name}|{project}|{service}|running|healthy"
    if process.returncode != 0 or process.stdout.strip() != expected:
        raise AuditExecutionError("container_identity_failed")


def _isolated_command(request: AuditRequest) -> tuple[list[str], dict[str, str]]:
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    target = validate_test_database_target(
        test_database_url=test_database_url,
        runtime_database_url=SQLALCHEMY_DATABASE_URL,
        isolation_confirmed=os.environ.get("PASTEXAM_TEST_DATABASE_ISOLATED"),
        allowed_hosts=os.environ.get(
            "TEST_DATABASE_ALLOWED_HOSTS",
            "127.0.0.1,localhost,db",
        ).split(","),
    )
    if request.expected_database not in {None, target.database_name}:
        raise AuditExecutionError("isolated_database_identity_mismatch")
    if request.expected_role not in {None, target.user_name}:
        raise AuditExecutionError("isolated_role_identity_mismatch")

    container = os.environ.get("PASTEXAM_AUDIT_TEST_CONTAINER")
    if container:
        if not re.fullmatch(r"[a-f0-9]{12,64}", container):
            raise AuditExecutionError("isolated_container_identity_invalid")
    elif target.host_name == "db":
        container = "pastexam-dev-postgres"
        _inspect_container(container, project="pastexam-dev", service="db")

    environment = os.environ.copy()
    if target.url.password:
        environment["PGPASSWORD"] = target.url.password
    if container:
        command = [
            "docker",
            "exec",
            "-i",
            "-e",
            "PGPASSWORD",
            container,
            "psql",
            "-X",
            "--no-psqlrc",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            target.user_name,
            "-d",
            target.database_name,
        ]
    else:
        command = [
            "psql",
            "-X",
            "--no-psqlrc",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            target.host_name,
            "-p",
            str(target.url.port or 5432),
            "-U",
            target.user_name,
            "-d",
            target.database_name,
        ]
    return command, environment


def _persistent_local_command() -> tuple[list[str], dict[str, str] | None]:
    _inspect_container(
        "pastexam-dev-postgres",
        project="pastexam-dev",
        service="db",
    )
    return (
        [
            "docker",
            "exec",
            "-i",
            "pastexam-dev-postgres",
            "sh",
            "-lc",
            (
                "exec psql -X --no-psqlrc -v ON_ERROR_STOP=1 "
                '-U "$POSTGRES_USER" -d "$POSTGRES_DB"'
            ),
        ],
        None,
    )


def _production_command(
    request: AuditRequest,
) -> tuple[list[str], dict[str, str] | None]:
    if not request.production_authorized:
        raise AuditExecutionError("production_mode_requires_explicit_authorization")
    _inspect_container("pastexam-postgres", project="pastexam", service="db")
    return (
        [
            "docker",
            "exec",
            "-i",
            "pastexam-postgres",
            "sh",
            "-lc",
            (
                "exec psql -X --no-psqlrc -v ON_ERROR_STOP=1 "
                '-U "$POSTGRES_USER" -d "$POSTGRES_DB"'
            ),
        ],
        None,
    )


def execute_audit(request: AuditRequest, adapter: AuditAdapter) -> AuditResult:
    sql = build_transaction_sql(request, adapter)
    if request.mode is AuditMode.ISOLATED_TEST:
        command, environment = _isolated_command(request)
    elif request.mode is AuditMode.PERSISTENT_LOCAL:
        command, environment = _persistent_local_command()
    else:
        command, environment = _production_command(request)
    return run_with_command(
        request,
        command=command,
        sql=sql,
        environment=environment,
    )
