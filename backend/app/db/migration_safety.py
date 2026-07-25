"""Read-only, fail-closed Alembic preflight and schema inspection."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote, quote_plus

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    DefaultClause,
    Index,
    MetaData,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import URL

from app.core.config import settings
from app.models import models as models_module


LEDGER_TABLE = "alembic_version"
RETAINED_ENUMS = {
    # b6f1e2d9a4c7 converted category columns to varchar but intentionally
    # retained the historical PostgreSQL type.
    "coursecategory": {
        "FRESHMAN",
        "SOPHOMORE",
        "JUNIOR",
        "SENIOR",
        "GRADUATE",
        "INTERDISCIPLINARY",
        "GENERAL",
    },
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationReport:
    database_connected: bool = False
    database_name: str | None = None
    database_empty: bool | None = None
    alembic_version_exists: bool = False
    alembic_versions: list[str] = field(default_factory=list)
    current_revision: str | None = None
    current_revision_known: bool = False
    repository_heads: list[str] = field(default_factory=list)
    multiple_heads: bool = False
    schema_candidate_revision: str | None = None
    schema_checks: list[CheckResult] = field(default_factory=list)
    upgrade_allowed: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def schema_matches_head(self) -> bool:
        return bool(self.schema_checks) and all(
            check.passed for check in self.schema_checks
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_matches_head"] = self.schema_matches_head
        return _redact_payload(payload)


def database_url() -> URL:
    """Build a structured URL so callers never need to format credentials."""
    return URL.create(
        "postgresql+psycopg2",
        username=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
    )


def alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        database_url().render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


def _sensitive_values() -> set[str]:
    raw_url = database_url().render_as_string(hide_password=False)
    return {
        settings.DB_PASSWORD,
        settings.SECRET_KEY,
        settings.OAUTH_CLIENT_SECRET,
        settings.MINIO_ROOT_PASSWORD,
        settings.DEFAULT_ADMIN_PASSWORD,
        quote(settings.DB_PASSWORD, safe=""),
        quote_plus(settings.DB_PASSWORD),
        raw_url,
        raw_url.replace("%", "%%"),
    }


def redact_text(value: Any) -> str:
    message = str(value)
    for secret in sorted(
        (value for value in _sensitive_values() if value), key=len, reverse=True
    ):
        message = message.replace(secret, "[REDACTED]")
    return message


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def safe_error(exc: Exception) -> str:
    """Return an exception summary with configured credentials removed."""
    return redact_text(f"{exc.__class__.__name__}: {exc}")


def revision_graph(
    config: Config | None = None,
) -> tuple[ScriptDirectory, list[str]]:
    script = ScriptDirectory.from_config(config or alembic_config())
    return script, sorted(script.get_heads())


def head_metadata() -> MetaData:
    """Return the explicit head-schema manifest used by reconciliation checks."""
    metadata = MetaData()
    for table in models_module.SQLModel.metadata.sorted_tables:
        table.to_metadata(metadata)

    # This migration was intentionally restored after its application models
    # were reverted. Keep the resulting database contract explicit here.
    system_issue_reports = metadata.tables["system_issue_reports"]
    migration_only_columns = (
        Column("github_issue_state", String(20), nullable=True),
        Column("github_linked_at", DateTime(timezone=True), nullable=True),
        Column(
            "github_sync_status",
            String(20),
            nullable=False,
            server_default="pending",
        ),
        Column("github_sync_error", String(300), nullable=True),
    )
    for column in migration_only_columns:
        system_issue_reports.append_column(column)
    Index(
        "ix_system_issue_reports_github_sync_status",
        system_issue_reports.c.github_sync_status,
    )
    discussion_messages = metadata.tables["archive_discussion_messages"]
    Index(
        "ix_archive_discussion_messages_archive_parent",
        discussion_messages.c.archive_id,
        discussion_messages.c.parent_id,
    )

    # PostgreSQL reflects these predicates in a cast-expanded form. Preserve
    # that canonical database representation in the explicit manifest.
    comment_reports = metadata.tables["comment_reports"]
    for constraint in list(comment_reports.constraints):
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == "ck_comment_reports_status"
        ):
            comment_reports.constraints.remove(constraint)
    CheckConstraint(
        "status::text = ANY "
        "(ARRAY['pending'::character varying, 'upheld'::character varying, "
        "'dismissed'::character varying]::text[])",
        name="ck_comment_reports_status",
        table=comment_reports,
    )
    for index in comment_reports.indexes:
        if index.name == "uq_comment_reports_active_reporter_comment_reason":
            index.dialect_options["postgresql"]["where"] = text(
                "((status)::text = 'pending'::text)"
            )

    # These model indexes were not introduced by the immutable migration chain.
    for table_name in ("courses", "course_submissions", "archive_submissions"):
        table = metadata.tables[table_name]
        for index in list(table.indexes):
            if tuple(index.columns.keys()) == ("category",):
                table.indexes.remove(index)

    # Defaults retained by the migration chain but absent from model metadata.
    defaults = {
        ("archive_submissions", "is_admin_upload"): "false",
        ("comment_reports", "comment_deleted"): "false",
        ("comment_reports", "created_at"): "now()",
        ("comment_reports", "status"): "pending",
        ("comment_reports", "updated_at"): "now()",
        ("course_category_configs", "badge_color"): "blue",
        ("course_category_configs", "created_at"): "now()",
        ("course_category_configs", "icon"): "pi pi-fw pi-book",
        ("course_category_configs", "is_active"): "true",
        ("course_category_configs", "label"): "",
        ("course_category_configs", "order_index"): "0",
        ("course_category_configs", "updated_at"): "now()",
        ("personal_notifications", "created_at"): "now()",
        ("personal_notifications", "metadata"): "'{}'::jsonb",
        ("system_issue_reports", "created_at"): "now()",
        ("system_issue_reports", "github_sync_status"): "pending",
        ("system_issue_reports", "metadata"): "'{}'::jsonb",
        ("system_issue_reports", "status"): "local_only",
        ("system_issue_reports", "updated_at"): "now()",
        ("system_settings", "created_at"): "CURRENT_TIMESTAMP",
        ("system_settings", "updated_at"): "CURRENT_TIMESTAMP",
        ("users", "show_level_title"): "true",
    }
    for (table_name, column_name), value in defaults.items():
        metadata.tables[table_name].c[column_name].server_default = DefaultClause(
            text(value)
        )

    # Match constraints/indexes that exist in the immutable chain.
    category_config = metadata.tables["course_category_configs"]
    UniqueConstraint(category_config.c.key)
    system_settings = metadata.tables["system_settings"]
    for index in list(system_settings.indexes):
        if tuple(index.columns.keys()) == ("key",):
            system_settings.indexes.remove(index)
    UniqueConstraint(system_settings.c.key)
    Index("ix_system_settings_key", system_settings.c.key, unique=False)
    return metadata


def _normalize_type(value: Any, dialect: Any) -> str:
    return " ".join(value.compile(dialect=dialect).upper().split())


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(getattr(value, "arg", value)).strip()
    while raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1].strip()
    raw = raw.replace("::character varying", "").replace("::text", "")
    return raw.strip("'").lower()


def _normalize_predicate(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).replace('"', "").lower().split())


def _set_check(name: str, expected: set[Any], actual: set[Any]) -> CheckResult:
    missing = sorted(expected - actual, key=str)
    unexpected = sorted(actual - expected, key=str)
    passed = not missing and not unexpected
    return CheckResult(
        name=name,
        passed=passed,
        message="OK" if passed else f"missing={missing}; unexpected={unexpected}",
        details={"missing": missing, "unexpected": unexpected},
    )


def _expected_index_signature(index: Index) -> tuple[Any, ...]:
    predicate = index.dialect_options["postgresql"].get("where")
    return (
        tuple(index.columns.keys()),
        bool(index.unique),
        _normalize_predicate(predicate),
    )


def _actual_index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    dialect_options = index.get("dialect_options") or {}
    return (
        tuple(index.get("column_names") or []),
        bool(index.get("unique")),
        _normalize_predicate(dialect_options.get("postgresql_where")),
    )


def compare_head_schema(
    connection: Connection, metadata: MetaData | None = None
) -> list[CheckResult]:
    """Compare all supported public-schema features with the head manifest."""
    metadata = metadata or head_metadata()
    inspector = inspect(connection)
    expected_tables = set(metadata.tables)
    actual_tables = set(inspector.get_table_names(schema="public")) - {LEDGER_TABLE}
    checks = [_set_check("tables", expected_tables, actual_tables)]

    for table_name in sorted(expected_tables & actual_tables):
        table = metadata.tables[table_name]
        actual_columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name, schema="public")
        }
        checks.append(
            _set_check(
                f"{table_name}.columns", set(table.columns.keys()), set(actual_columns)
            )
        )
        for column in table.columns:
            actual = actual_columns.get(column.name)
            if actual is None:
                continue
            expected_type = _normalize_type(column.type, connection.dialect)
            actual_type = _normalize_type(actual["type"], connection.dialect)
            checks.append(
                CheckResult(
                    f"{table_name}.{column.name}.type",
                    expected_type == actual_type,
                    "OK"
                    if expected_type == actual_type
                    else f"expected {expected_type}, found {actual_type}",
                )
            )
            expected_nullable = bool(column.nullable)
            actual_nullable = bool(actual["nullable"])
            checks.append(
                CheckResult(
                    f"{table_name}.{column.name}.nullability",
                    expected_nullable == actual_nullable,
                    "OK"
                    if expected_nullable == actual_nullable
                    else (
                        f"expected nullable={expected_nullable}, "
                        f"found {actual_nullable}"
                    ),
                )
            )
            expected_default = _normalize_default(column.server_default)
            actual_default = _normalize_default(actual.get("default"))
            serial_default = bool(
                column.primary_key
                and column.autoincrement in (True, "auto")
                and actual_default
                and actual_default.startswith("nextval(")
            )
            default_ok = expected_default == actual_default or (
                expected_default is None and serial_default
            )
            checks.append(
                CheckResult(
                    f"{table_name}.{column.name}.server_default",
                    default_ok,
                    "OK"
                    if default_ok
                    else f"expected {expected_default!r}, found {actual_default!r}",
                )
            )

        expected_pk = set(table.primary_key.columns.keys())
        actual_pk = set(
            (inspector.get_pk_constraint(table_name, schema="public") or {}).get(
                "constrained_columns"
            )
            or []
        )
        checks.append(_set_check(f"{table_name}.primary_key", expected_pk, actual_pk))

        expected_fks = {
            (
                tuple(element.parent.name for element in constraint.elements),
                tuple(element.target_fullname for element in constraint.elements),
                (constraint.ondelete or "").upper(),
            )
            for constraint in table.foreign_key_constraints
        }
        actual_fks = {
            (
                tuple(fk.get("constrained_columns") or []),
                tuple(
                    f"{fk.get('referred_table')}.{column}"
                    for column in (fk.get("referred_columns") or [])
                ),
                str((fk.get("options") or {}).get("ondelete") or "").upper(),
            )
            for fk in inspector.get_foreign_keys(table_name, schema="public")
        }
        checks.append(
            _set_check(f"{table_name}.foreign_keys", expected_fks, actual_fks)
        )

        expected_unique = {
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        actual_unique = {
            tuple(item.get("column_names") or [])
            for item in inspector.get_unique_constraints(table_name, schema="public")
        }
        checks.append(
            _set_check(
                f"{table_name}.unique_constraints", expected_unique, actual_unique
            )
        )

        expected_checks = {
            _normalize_predicate(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        actual_checks = {
            _normalize_predicate(item.get("sqltext"))
            for item in inspector.get_check_constraints(
                table_name, schema="public"
            )
        }
        checks.append(
            _set_check(
                f"{table_name}.check_constraints", expected_checks, actual_checks
            )
        )

        expected_indexes = {
            _expected_index_signature(index) for index in table.indexes
        }
        actual_indexes = {
            _actual_index_signature(index)
            for index in inspector.get_indexes(table_name, schema="public")
            if not index.get("duplicates_constraint")
        }
        checks.append(
            _set_check(f"{table_name}.indexes", expected_indexes, actual_indexes)
        )

    expected_enums: dict[str, set[str]] = {}
    for table in metadata.tables.values():
        for column in table.columns:
            enum_values = getattr(column.type, "enums", None)
            enum_name = getattr(column.type, "name", None)
            if enum_values and enum_name:
                expected_enums[enum_name] = set(enum_values)
    expected_enums.update(RETAINED_ENUMS)
    actual_enums = {
        item["name"]: set(item["labels"])
        for item in inspector.get_enums(schema="public")
    }
    checks.append(_set_check("enum.types", set(expected_enums), set(actual_enums)))
    for enum_name, values in expected_enums.items():
        checks.append(
            _set_check(
                f"enum.{enum_name}.values", values, actual_enums.get(enum_name, set())
            )
        )
    return checks


def inspect_database(
    engine: Engine | None = None, *, compare_schema: bool = True
) -> MigrationReport:
    """Inspect without changing schema, data, or the Alembic ledger."""
    report = MigrationReport()
    script, heads = revision_graph()
    report.repository_heads = heads
    report.multiple_heads = len(heads) != 1
    if report.multiple_heads:
        report.errors.append(
            f"Repository must have exactly one head; found {len(heads)}"
        )

    owned_engine = engine is None
    engine = engine or create_engine(database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            report.database_connected = True
            report.database_name = connection.scalar(text("SELECT current_database()"))
            inspector = inspect(connection)
            public_tables = set(inspector.get_table_names(schema="public"))
            report.database_empty = not bool(public_tables - {LEDGER_TABLE})
            report.alembic_version_exists = LEDGER_TABLE in public_tables
            if report.alembic_version_exists:
                report.alembic_versions = list(
                    connection.scalars(
                        text(
                            "SELECT version_num FROM alembic_version "
                            "ORDER BY version_num"
                        )
                    )
                )

            if len(report.alembic_versions) == 1:
                report.current_revision = report.alembic_versions[0]
                report.current_revision_known = (
                    script.get_revision(report.current_revision) is not None
                )
            elif len(report.alembic_versions) > 1:
                report.errors.append(
                    "Alembic ledger must contain exactly one revision"
                )

            ledger_missing = (
                not report.alembic_version_exists or not report.alembic_versions
            )
            if (
                report.database_empty
                and ledger_missing
                and not report.multiple_heads
            ):
                report.upgrade_allowed = True
                return report

            if ledger_missing:
                report.errors.append(
                    "Non-empty database has no Alembic ledger; upgrade is blocked"
                )
            elif not report.current_revision_known:
                report.errors.append(
                    "Database revision does not exist in this repository"
                )
            elif len(report.alembic_versions) == 1 and heads:
                if report.current_revision != heads[0]:
                    report.errors.append(
                        "Known non-head revisions require a separately reviewed "
                        "schema manifest; automatic upgrade is blocked"
                    )

            should_compare = (
                compare_schema
                and not report.database_empty
                and len(heads) == 1
                and (
                    ledger_missing
                    or (
                        len(report.alembic_versions) == 1
                        and report.current_revision == heads[0]
                    )
                )
            )
            if should_compare:
                report.schema_checks = compare_head_schema(connection)
                if report.schema_matches_head:
                    report.schema_candidate_revision = heads[0]

            report.upgrade_allowed = bool(
                not report.errors
                and len(report.alembic_versions) == 1
                and report.current_revision == heads[0]
                and report.current_revision_known
                and report.schema_matches_head
            )
            if (
                len(report.alembic_versions) == 1
                and report.current_revision == heads[0]
                and not report.schema_matches_head
            ):
                report.errors.append(
                    "Database ledger is at repository head but schema drift was found"
                )
            if ledger_missing and report.schema_matches_head:
                report.warnings.append(
                    "Schema structurally matches repository head, but data-migration "
                    "history cannot be proven. No stamp or repair is available."
                )
    except Exception as exc:
        report.errors.append(f"Database inspection failed: {safe_error(exc)}")
    finally:
        if owned_engine:
            engine.dispose()
    return report
