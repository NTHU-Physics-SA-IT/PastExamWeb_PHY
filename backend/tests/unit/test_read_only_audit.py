from __future__ import annotations

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest

import audit
from app.db.audit.models import (
    AuditMode,
    AuditRequest,
    AuditStatus,
)
from app.db.audit.registry import (
    ELIGIBILITY_AUDIT_ID,
    get_audit_adapter,
)
from app.db.audit.runner import (
    AuditExecutionError,
    build_transaction_sql,
    parse_process_output,
    run_with_command,
    validate_adapter_sql,
)

EXPECTED_LEDGER = "f5e1d8c3a7b2"


def request(mode: AuditMode = AuditMode.ISOLATED_TEST) -> AuditRequest:
    return AuditRequest(
        audit_id=ELIGIBILITY_AUDIT_ID,
        audit_version=1,
        mode=mode,
        expected_ledger=EXPECTED_LEDGER,
        repository_revision="a" * 40,
    )


def completed_output(
    *,
    status: str = "complete",
    include_rollback: bool = True,
    include_sentinel: bool = True,
) -> str:
    meta = {
        "read_only": True,
        "identity_ok": True,
        "ledger_row_count": 1,
        "actual_ledger": EXPECTED_LEDGER,
        "ledger_ok": True,
        "schema_ok": True,
        "enum_count": 5,
        "enum_match": True,
    }
    result = {
        "status": status,
        "error_code": None,
        "aggregates": {
            "total": 0,
            "automatic_true": 0,
            "automatic_false": 0,
            "unsupported": 0,
            "unclassified": 0,
            "overlap": 0,
            "bucket_sum": 0,
            "difference": 0,
        },
        "combinations": [],
        "mutual_exclusivity": True,
        "conservation": True,
    }
    lines = [
        "BEGIN",
        "__PASTEXAM_AUDIT_META__" + json.dumps(meta),
        "__PASTEXAM_AUDIT_RESULT__" + json.dumps(result),
    ]
    if include_rollback:
        lines.append("ROLLBACK")
    if include_sentinel:
        lines.append("__PASTEXAM_AUDIT_ROLLBACK_COMPLETE__")
    return "\n".join(lines)


def test_cli_has_no_raw_sql_surface() -> None:
    with pytest.raises(SystemExit):
        audit.parser().parse_args(
            [
                "run",
                "--audit",
                ELIGIBILITY_AUDIT_ID,
                "--mode",
                AuditMode.ISOLATED_TEST.value,
                "--expected-ledger",
                EXPECTED_LEDGER,
                "--sql",
                "select 1",
            ]
        )


def test_registry_is_sealed_and_versioned() -> None:
    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 1)

    assert adapter.accepted_source_revisions == frozenset(
        {
            "a4c7e9d2f6b1",
            "a7c3e9f1b5d2",
            "f5e1d8c3a7b2",
        }
    )
    assert len(adapter.approved_aggregate_labels) == 8
    with pytest.raises(KeyError):
        get_audit_adapter("unknown-audit", 1)


def test_previous_status_audit_is_revision_bounded_and_course_marker_read_only() -> (
    None
):
    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 2)

    assert adapter.accepted_source_revisions == frozenset(
        {
            "f5e1d8c3a7b2",
            "d8f2a6c1b4e7",
        }
    )
    assert "valid_course_marker" in adapter.approved_aggregate_labels
    assert (
        "valid_course_marker_with_previous_status" in adapter.approved_aggregate_labels
    )
    assert "to_jsonb(submission)->>'previous_status'" in adapter.summary_sql
    assert "UPDATE ARCHIVE_SUBMISSIONS" not in adapter.summary_sql.upper()


def test_one_to_one_audit_is_revision_bounded_and_aggregate_only() -> None:
    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 3)

    assert adapter.accepted_source_revisions == frozenset(
        {
            "d8f2a6c1b4e7",
            "6f3a9c2d8e41",
            "9f1c2a7e4b63",
            "b7e3d9a1c5f2",
        }
    )
    for label in (
        "created_archive_id_null",
        "created_archive_id_non_null",
        "distinct_created_archive_ids",
        "max_created_archive_cardinality",
        "dangling_created_archive_links",
        "created_archive_link_checksum",
        "submission_state_checksum",
    ):
        assert label in adapter.approved_aggregate_labels
    assert "GROUP BY created_archive_id" in adapter.summary_sql
    assert "LEFT JOIN archives" in adapter.summary_sql
    assert "UPDATE ARCHIVE_SUBMISSIONS" not in adapter.summary_sql.upper()


def test_bilingual_head_audit_is_new_version_and_preserves_lifecycle_classifier() -> (
    None
):
    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 4)

    assert adapter.accepted_source_revisions == frozenset(
        {
            "c2a8e4f6b9d1",
            "d4b7e2a9c6f1",
        }
    )
    previous = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 3)
    assert adapter.summary_sql == previous.summary_sql
    assert adapter.combinations_sql == previous.combinations_sql
    assert "UPDATE ARCHIVE_SUBMISSIONS" not in adapter.summary_sql.upper()


def test_bilingual_head_continuity_requires_all_nullable_english_columns() -> None:
    bilingual_request = AuditRequest(
        audit_id=ELIGIBILITY_AUDIT_ID,
        audit_version=4,
        mode=AuditMode.PERSISTENT_LOCAL,
        expected_ledger="d4b7e2a9c6f1",
        repository_revision="a" * 40,
    )
    sql = build_transaction_sql(
        bilingual_request,
        get_audit_adapter(ELIGIBILITY_AUDIT_ID, 4),
    )

    for column in (
        "name_en",
        "label_en",
        "requested_course_name_en",
        "requested_category_name_en",
        "requested_category_label_en",
    ):
        assert column in sql
    assert "is_nullable = 'YES'" in sql
    assert "data_type = 'character varying'" in sql


def test_cli_defaults_to_current_bilingual_audit_version() -> None:
    arguments = audit.parser().parse_args(
        [
            "run",
            "--audit",
            ELIGIBILITY_AUDIT_ID,
            "--mode",
            AuditMode.PERSISTENT_LOCAL.value,
        ]
    )

    assert arguments.version == 4


def test_transaction_is_noninteractive_read_only_and_explicitly_rolled_back() -> None:
    sql = build_transaction_sql(request(), get_audit_adapter(ELIGIBILITY_AUDIT_ID, 1))

    assert "BEGIN TRANSACTION" in sql
    assert "REPEATABLE READ" in sql
    assert "READ ONLY" in sql
    assert "statement_timeout" in sql
    assert "lock_timeout" in sql
    assert "idle_in_transaction_session_timeout" in sql
    assert "enumlabel::text" in sql
    assert "ROLLBACK;" in sql
    assert "__PASTEXAM_AUDIT_ROLLBACK_COMPLETE__" in sql
    assert "\\quit" not in sql


def test_adapter_sql_rejects_writes_and_unsafe_database_operations() -> None:
    for statement in (
        "UPDATE archive_submissions SET owner_id = NULL",
        "CREATE TEMP TABLE unsafe(id integer)",
        "SELECT pg_advisory_lock(1)",
        "SELECT * FROM archive_submissions FOR UPDATE",
    ):
        with pytest.raises(ValueError, match="read-only"):
            validate_adapter_sql(statement)


def test_complete_output_requires_process_success_rollback_and_sentinel() -> None:
    parsed = parse_process_output(
        request(),
        CompletedProcess(
            args=["psql"], returncode=0, stdout=completed_output(), stderr=""
        ),
    )

    assert parsed.status is AuditStatus.COMPLETE
    assert parsed.explicit_rollback is True
    assert parsed.completion_sentinel is True

    for output in (
        completed_output(include_rollback=False),
        completed_output(include_sentinel=False),
    ):
        parsed = parse_process_output(
            request(),
            CompletedProcess(args=["psql"], returncode=0, stdout=output, stderr=""),
        )
        assert parsed.status is AuditStatus.INCOMPLETE_TRANSPORT
        assert parsed.explicit_rollback is ("ROLLBACK" in output.splitlines())


def test_sql_error_is_audit_error_and_never_complete() -> None:
    parsed = parse_process_output(
        request(),
        CompletedProcess(
            args=["psql"],
            returncode=3,
            stdout="BEGIN\n",
            stderr="ERROR: statement failed",
        ),
    )

    assert parsed.status is AuditStatus.AUDIT_ERROR
    assert parsed.explicit_rollback is False
    assert parsed.error_code == "psql_error"


def test_output_schema_rejects_unknown_labels_and_unsafe_fields() -> None:
    output = completed_output().replace(
        '"difference": 0',
        '"difference": 0, "row_id": 123',
    )
    with pytest.raises(AuditExecutionError, match="result_schema_invalid"):
        parse_process_output(
            request(),
            CompletedProcess(args=["psql"], returncode=0, stdout=output, stderr=""),
        )


def test_output_schema_normalizes_non_object_marker_payload() -> None:
    output = "\n".join(
        "__PASTEXAM_AUDIT_RESULT__[]"
        if line.startswith("__PASTEXAM_AUDIT_RESULT__")
        else line
        for line in completed_output().splitlines()
    )

    with pytest.raises(AuditExecutionError, match="result_schema_invalid"):
        parse_process_output(
            request(),
            CompletedProcess(args=["psql"], returncode=0, stdout=output, stderr=""),
        )


def test_output_schema_rejects_unregistered_combination_flags() -> None:
    output = completed_output().replace(
        '"combinations": []',
        '"combinations": [{"flags": ["invented_flag"], "count": 1}]',
    )
    with pytest.raises(AuditExecutionError, match="unknown combination label"):
        parse_process_output(
            request(),
            CompletedProcess(args=["psql"], returncode=0, stdout=output, stderr=""),
        )


def test_transport_timeout_is_audit_error_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def timeout(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutExpired(cmd=["psql"], timeout=30)

    monkeypatch.setattr("subprocess.run", timeout)
    with pytest.raises(AuditExecutionError, match="transport_failed"):
        run_with_command(request(), command=["psql"], sql="SELECT 1")
    assert calls == 1


def test_enum_continuity_is_text_typed_and_exact() -> None:
    sql = build_transaction_sql(
        request(),
        get_audit_adapter(ELIGIBILITY_AUDIT_ID, 1),
    )

    assert "array_agg(e.enumlabel::text ORDER BY e.enumsortorder)" in sql
    assert "'PENDING'" in sql
    assert "'TAKEDOWN'" in sql
    assert "enum_count = 5" in sql


@pytest.mark.parametrize(
    ("mode", "identity_fragment"),
    [
        (AuditMode.ISOLATED_TEST, "pastexam_test"),
        (AuditMode.PERSISTENT_LOCAL, "archive_db"),
        (AuditMode.PRODUCTION_AGGREGATE_ONLY, "current_database()"),
    ],
)
def test_each_mode_has_a_separate_identity_gate(
    mode: AuditMode,
    identity_fragment: str,
) -> None:
    sql = build_transaction_sql(
        request(mode),
        get_audit_adapter(ELIGIBILITY_AUDIT_ID, 1),
    )
    assert identity_fragment in sql


def test_persistent_local_identity_uses_container_and_database_not_owner_role() -> None:
    sql = build_transaction_sql(
        request(AuditMode.PERSISTENT_LOCAL),
        get_audit_adapter(ELIGIBILITY_AUDIT_ID, 1),
    )

    assert "current_database() = 'archive_db'" in sql
    assert "pg_get_userbyid(database.datdba) = current_user" not in sql


def test_human_summary_is_derived_without_another_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = parse_process_output(
        request(),
        CompletedProcess(
            args=["psql"], returncode=0, stdout=completed_output(), stderr=""
        ),
    )
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("summary must not execute another query")

    monkeypatch.setattr("subprocess.run", forbidden)
    summary = parsed.to_human_summary()

    assert "complete" in summary
    assert called is False


def test_production_mode_refuses_without_attempting_a_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("production connection attempted")

    monkeypatch.setattr("subprocess.run", forbidden)
    exit_code = audit.main(
        [
            "run",
            "--audit",
            ELIGIBILITY_AUDIT_ID,
            "--mode",
            AuditMode.PRODUCTION_AGGREGATE_ONLY.value,
            "--expected-ledger",
            EXPECTED_LEDGER,
            "--repository-revision",
            "a" * 40,
            "--output",
            "json",
        ]
    )

    assert exit_code == 2
    assert called is False


def test_fake_transport_receives_one_complete_stdin_stream(tmp_path: Path) -> None:
    capture = tmp_path / "stdin.sql"
    fake_psql = tmp_path / "fake_psql.py"
    fake_psql.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        f"Path({str(capture)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n"
        f"print({completed_output()!r})\n",
        encoding="utf-8",
    )

    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 1)
    sql = build_transaction_sql(request(), adapter)
    result = audit.run_with_command_for_test(
        request(),
        command=[sys.executable, str(fake_psql)],
        sql=sql,
    )

    assert result.status is AuditStatus.COMPLETE
    assert capture.read_text(encoding="utf-8") == sql
