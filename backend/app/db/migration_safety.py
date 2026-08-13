"""Read-only, fail-closed Alembic preflight and schema inspection."""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    CheckConstraint,
    Index,
    MetaData,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import URL

from app.core.config import settings
from app.db.schema_manifests import (
    HEAD_SCHEMA_REVISION,
    ManifestSpec,
    get_manifest_spec,
    reviewed_manifest_revisions,
)
from app.models import models as models_module
from app.utils.exception_logging import redacted_exc_info

logger = logging.getLogger(__name__)

LEDGER_TABLE = "alembic_version"
MIGRATION_LOCK_CLASS_ID = 1_438_970_421
CANONICAL_CATEGORY_NAME_INDEX = "uq_course_category_configs_normalized_name"
CANONICAL_CATEGORY_KEY_INDEX = "uq_course_category_configs_normalized_key"
CANONICAL_CATEGORY_LEGACY_CHECK = "ck_course_category_configs_no_legacy_key"
ARCHIVE_SUBMISSION_PREVIOUS_STATUS_CHECKS = {
    "ck_archive_submissions_previous_status_not_deleted",
    "ck_archive_submissions_active_previous_status_null",
}
ARCHIVE_SUBMISSION_CREATED_ARCHIVE_UNIQUE = "uq_archive_submissions_created_archive_id"
USER_OAUTH_IDENTITY_UNIQUE = "uq_users_oauth_provider_sub"
IDENTIFIER_TEXT_CAST = re.compile(
    r"\bcast\(\s*(?P<identifier>[a-z_]\w*(?:\.[a-z_]\w*)?)"
    r"\s+as\s+text\s*\)"
)


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
    reviewed_manifest_revisions: list[str] = field(default_factory=list)
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


def alembic_config(url: URL | str | None = None) -> Config:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    configured_url = url or database_url()
    if isinstance(configured_url, str):
        rendered_url = configured_url
    else:
        rendered_url = configured_url.render_as_string(hide_password=False)
    config.set_main_option(
        "sqlalchemy.url",
        rendered_url.replace("+asyncpg", "").replace("%", "%%"),
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


@contextmanager
def migration_advisory_lock(engine: Engine):
    """Hold a database-scoped PostgreSQL advisory lock for one migration run."""
    with engine.connect() as connection:
        database_name, database_oid = connection.execute(
            text(
                "SELECT current_database(), oid::integer "
                "FROM pg_database WHERE datname = current_database()"
            )
        ).one()
        acquired = bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(:class_id, :database_oid)"),
                {
                    "class_id": MIGRATION_LOCK_CLASS_ID,
                    "database_oid": database_oid,
                },
            )
        )
        if not acquired:
            raise RuntimeError(
                "Another migration process holds the advisory lock for "
                f"database {database_name!r}"
            )
        try:
            yield database_name
        finally:
            released = bool(
                connection.scalar(
                    text("SELECT pg_advisory_unlock(:class_id, :database_oid)"),
                    {
                        "class_id": MIGRATION_LOCK_CLASS_ID,
                        "database_oid": database_oid,
                    },
                )
            )
            if not released:
                raise RuntimeError("Migration advisory lock could not be released")


def revision_graph(
    config: Config | None = None,
) -> tuple[ScriptDirectory, list[str]]:
    script = ScriptDirectory.from_config(config or alembic_config())
    return script, sorted(script.get_heads())


def is_revision_ancestor(
    script: ScriptDirectory,
    *,
    revision: str,
    head: str,
) -> bool:
    return revision in {
        item.revision for item in script.walk_revisions(base="base", head=head)
    }


def head_metadata() -> MetaData:
    """Copy the SQLModel contract used by the reviewed head manifest."""
    metadata = MetaData()
    for table in models_module.SQLModel.metadata.sorted_tables:
        table.to_metadata(metadata)
    return metadata


def _metadata_for_variant(variant: str) -> MetaData:
    metadata = head_metadata()
    if variant == "head":
        return metadata
    if variant not in {
        "pre_nthu_student_id",
        "pre_user_oauth_identity_unique",
        "pre_archive_submission_one_to_one",
        "pre_archive_submission_previous_status",
        "pre_owner_self_delete_eligibility",
        "pre_archive_reports",
        "pre_metadata_alignment",
        "pre_category_canonicalization",
    }:
        raise ValueError(f"Unknown schema metadata variant: {variant}")

    users = metadata.tables["users"]
    users._columns.remove(users.c.student_id)
    if variant == "pre_nthu_student_id":
        return metadata

    for constraint in list(users.constraints):
        if (
            isinstance(constraint, UniqueConstraint)
            and constraint.name == "uq_users_oauth_provider_sub"
        ):
            users.constraints.remove(constraint)
    if variant == "pre_user_oauth_identity_unique":
        return metadata

    archive_submissions = metadata.tables["archive_submissions"]
    for constraint in list(archive_submissions.constraints):
        if (
            isinstance(constraint, UniqueConstraint)
            and constraint.name == ARCHIVE_SUBMISSION_CREATED_ARCHIVE_UNIQUE
        ):
            archive_submissions.constraints.remove(constraint)
    if variant == "pre_archive_submission_one_to_one":
        return metadata

    for constraint in list(archive_submissions.constraints):
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name in ARCHIVE_SUBMISSION_PREVIOUS_STATUS_CHECKS
        ):
            archive_submissions.constraints.remove(constraint)
    archive_submissions._columns.remove(archive_submissions.c.previous_status)
    if variant == "pre_archive_submission_previous_status":
        return metadata

    archive_submissions._columns.remove(
        archive_submissions.c.owner_self_delete_consumed
    )
    if variant == "pre_owner_self_delete_eligibility":
        return metadata

    metadata.remove(metadata.tables["archive_reports"])
    if variant == "pre_archive_reports":
        return metadata

    # e3b7c1d9f5a2 adds these indexes and drops the no-longer-referenced enum.
    for table_name in ("courses", "course_submissions", "archive_submissions"):
        table = metadata.tables[table_name]
        for index in list(table.indexes):
            if tuple(index.columns.keys()) == ("category",):
                table.indexes.remove(index)

    if variant == "pre_metadata_alignment":
        return metadata

    # c9e4f1a7b2d6 introduced only these category integrity constraints.
    category_config = metadata.tables["course_category_configs"]
    for index in list(category_config.indexes):
        if index.name in {
            CANONICAL_CATEGORY_NAME_INDEX,
            CANONICAL_CATEGORY_KEY_INDEX,
        }:
            category_config.indexes.remove(index)
    for constraint in list(category_config.constraints):
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == CANONICAL_CATEGORY_LEGACY_CHECK
        ):
            category_config.constraints.remove(constraint)
    return metadata


def _retained_enums(spec: ManifestSpec) -> dict[str, set[str]]:
    return {enum_name: set(values) for enum_name, values in spec.retained_enums}


def metadata_for_revision(revision: str) -> MetaData | None:
    """Return model-derived metadata for a reviewed revision, when applicable."""
    spec = get_manifest_spec(revision)
    if spec is None or spec.metadata_variant is None:
        return None
    return _metadata_for_variant(spec.metadata_variant)


def _load_snapshot_manifest(spec: ManifestSpec) -> dict[str, Any]:
    path = spec.snapshot_path
    if path is None:
        raise ValueError(f"Revision {spec.revision} has no snapshot manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("manifest_version") != 1:
        raise ValueError(f"Unsupported schema manifest version for {spec.revision}")
    if payload.get("revision") != spec.revision:
        raise ValueError(f"Schema manifest revision mismatch for {spec.revision}")
    return payload["schema"]


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
    normalized = " ".join(str(value).replace('"', "").lower().split())
    normalized = normalized.replace("::character varying", "")
    normalized = normalized.replace("::text[]", "")
    normalized = normalized.replace("::text", "")
    # PostgreSQL reflects a redundant CAST(identifier AS TEXT) as
    # identifier::text. Only canonicalize casts of a bare identifier so
    # operators, literals, functions, and boolean structure remain visible.
    normalized = IDENTIFIER_TEXT_CAST.sub(r"\g<identifier>", normalized)
    normalized = re.sub(r"\(\(([^()]*)\)\)", r"(\1)", normalized)
    normalized = re.sub(r"^\((.*)\)$", r"\1", normalized)
    normalized = re.sub(
        r"^\(([\w.]+)\)(?=\s*(?:=|<>|in|not))",
        r"\1",
        normalized,
    )

    # PostgreSQL reflects IN/NOT IN checks as = ANY / <> ALL array
    # expressions. Canonicalize both forms without changing their meaning.
    any_match = re.fullmatch(
        r"(?P<column>[\w().]+) = any \(array\[(?P<values>.*)\]\)",
        normalized,
    )
    if any_match:
        normalized = f"{any_match.group('column')} in ({any_match.group('values')})"
    all_match = re.fullmatch(
        r"(?P<column>[\w().]+) <> all \(array\[(?P<values>.*)\]\)",
        normalized,
    )
    if all_match:
        normalized = f"{all_match.group('column')} not in ({all_match.group('values')})"
    return normalized


def _normalize_index_expression(value: Any) -> str | None:
    normalized = _normalize_predicate(value)
    if normalized is None:
        return None
    return normalized.replace("::character varying", "").replace("::text", "")


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
    column_names = tuple(index.columns.keys())
    elements = column_names or tuple(
        _normalize_index_expression(expression) for expression in index.expressions
    )
    return (
        elements,
        bool(index.unique),
        _normalize_predicate(predicate),
    )


def _actual_index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    dialect_options = index.get("dialect_options") or {}
    column_names = index.get("column_names") or []
    expressions = index.get("expressions") or []
    elements = tuple(
        column_name
        if column_name is not None
        else _normalize_index_expression(
            expressions[position] if position < len(expressions) else None
        )
        for position, column_name in enumerate(column_names)
    )
    return (
        elements,
        bool(index.get("unique")),
        _normalize_predicate(dialect_options.get("postgresql_where")),
    )


def capture_live_schema(connection: Connection) -> dict[str, Any]:
    """Capture the normalized public-schema contract for a reviewed manifest."""
    inspector = inspect(connection)
    table_names = sorted(
        set(inspector.get_table_names(schema="public")) - {LEDGER_TABLE}
    )
    tables: dict[str, Any] = {}
    for table_name in table_names:
        columns = {
            column["name"]: {
                "type": _normalize_type(column["type"], connection.dialect),
                "nullable": bool(column["nullable"]),
                "server_default": _normalize_default(column.get("default")),
            }
            for column in inspector.get_columns(table_name, schema="public")
        }
        primary_key = sorted(
            (inspector.get_pk_constraint(table_name, schema="public") or {}).get(
                "constrained_columns"
            )
            or []
        )
        foreign_keys = sorted(
            [
                {
                    "columns": list(item.get("constrained_columns") or []),
                    "referred_table": item.get("referred_table"),
                    "referred_columns": list(item.get("referred_columns") or []),
                    "ondelete": str(
                        (item.get("options") or {}).get("ondelete") or ""
                    ).upper(),
                }
                for item in inspector.get_foreign_keys(
                    table_name,
                    schema="public",
                )
            ],
            key=lambda item: json.dumps(item, sort_keys=True),
        )
        unique_constraints = sorted(
            [
                sorted(item.get("column_names") or [])
                for item in inspector.get_unique_constraints(
                    table_name,
                    schema="public",
                )
            ]
        )
        check_constraints = sorted(
            filter(
                None,
                (
                    _normalize_predicate(item.get("sqltext"))
                    for item in inspector.get_check_constraints(
                        table_name,
                        schema="public",
                    )
                ),
            )
        )
        indexes = sorted(
            [
                {
                    "signature": [
                        list(_actual_index_signature(item)[0]),
                        _actual_index_signature(item)[1],
                        _actual_index_signature(item)[2],
                    ],
                    "name": item.get("name"),
                }
                for item in inspector.get_indexes(
                    table_name,
                    schema="public",
                )
                if not item.get("duplicates_constraint")
            ],
            key=lambda item: json.dumps(item, sort_keys=True),
        )
        tables[table_name] = {
            "columns": columns,
            "primary_key": primary_key,
            "foreign_keys": foreign_keys,
            "unique_constraints": unique_constraints,
            "check_constraints": check_constraints,
            "indexes": indexes,
        }

    enums = {
        item["name"]: sorted(item["labels"])
        for item in inspector.get_enums(schema="public")
    }
    return {
        "tables": tables,
        "enums": dict(sorted(enums.items())),
    }


def _snapshot_check(name: str, expected: Any, actual: Any) -> CheckResult:
    passed = expected == actual
    return CheckResult(
        name=name,
        passed=passed,
        message="OK" if passed else "schema manifest mismatch",
        details={} if passed else {"expected": expected, "actual": actual},
    )


def compare_snapshot_schema(
    connection: Connection,
    expected: dict[str, Any],
) -> list[CheckResult]:
    """Compare a live database with a committed snapshot manifest."""
    actual = capture_live_schema(connection)
    expected_tables = expected.get("tables", {})
    actual_tables = actual.get("tables", {})
    checks = [
        _snapshot_check(
            "tables",
            sorted(expected_tables),
            sorted(actual_tables),
        )
    ]
    for table_name in sorted(set(expected_tables) & set(actual_tables)):
        for feature in (
            "columns",
            "primary_key",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
            "indexes",
        ):
            checks.append(
                _snapshot_check(
                    f"{table_name}.{feature}",
                    expected_tables[table_name].get(feature),
                    actual_tables[table_name].get(feature),
                )
            )
    checks.append(
        _snapshot_check(
            "enum.types",
            sorted(expected.get("enums", {})),
            sorted(actual.get("enums", {})),
        )
    )
    for enum_name in sorted(
        set(expected.get("enums", {})) & set(actual.get("enums", {}))
    ):
        checks.append(
            _snapshot_check(
                f"enum.{enum_name}.values",
                expected["enums"][enum_name],
                actual["enums"][enum_name],
            )
        )
    return checks


def compare_head_schema(
    connection: Connection,
    metadata: MetaData | None = None,
    *,
    retained_enums: dict[str, set[str]] | None = None,
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
        expected_named_critical = {
            (
                constraint.name,
                tuple(constraint.columns.keys()),
            )
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
            and constraint.name
            in {
                ARCHIVE_SUBMISSION_CREATED_ARCHIVE_UNIQUE,
                USER_OAUTH_IDENTITY_UNIQUE,
            }
        }
        if expected_named_critical:
            critical_names = {name for name, _ in expected_named_critical}
            actual_named_critical = {
                (
                    item.get("name"),
                    tuple(item.get("column_names") or []),
                )
                for item in inspector.get_unique_constraints(
                    table_name,
                    schema="public",
                )
                if item.get("name") in critical_names
            }
            checks.append(
                _set_check(
                    f"{table_name}.named_critical_unique_constraints",
                    expected_named_critical,
                    actual_named_critical,
                )
            )

        expected_checks = {
            _normalize_predicate(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        actual_checks = {
            _normalize_predicate(item.get("sqltext"))
            for item in inspector.get_check_constraints(table_name, schema="public")
        }
        checks.append(
            _set_check(
                f"{table_name}.check_constraints", expected_checks, actual_checks
            )
        )

        expected_indexes = {_expected_index_signature(index) for index in table.indexes}
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
    expected_enums.update(retained_enums or {})
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
    report.reviewed_manifest_revisions = list(reviewed_manifest_revisions())
    script, heads = revision_graph()
    report.repository_heads = heads
    report.multiple_heads = len(heads) != 1
    if report.multiple_heads:
        report.errors.append(
            f"Repository must have exactly one head; found {len(heads)}"
        )
    elif heads[0] != HEAD_SCHEMA_REVISION or get_manifest_spec(heads[0]) is None:
        report.errors.append(
            f"Repository head has no reviewed schema manifest: {heads[0]}"
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
                report.errors.append("Alembic ledger must contain exactly one revision")

            ledger_missing = (
                not report.alembic_version_exists or not report.alembic_versions
            )
            manifest_spec: ManifestSpec | None = None
            if report.database_empty and ledger_missing and not report.errors:
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
                manifest_spec = get_manifest_spec(report.current_revision)
                if manifest_spec is None:
                    report.errors.append(
                        "Known revision has no reviewed schema manifest: "
                        f"{report.current_revision}"
                    )
                elif report.current_revision != heads[0] and not is_revision_ancestor(
                    script,
                    revision=report.current_revision,
                    head=heads[0],
                ):
                    report.errors.append(
                        "Database revision is not an ancestor of repository head"
                    )

            should_compare = (
                compare_schema
                and not report.database_empty
                and len(heads) == 1
                and (
                    ledger_missing
                    or (len(report.alembic_versions) == 1 and manifest_spec is not None)
                )
            )
            if should_compare:
                comparison_spec = manifest_spec
                if ledger_missing:
                    comparison_spec = get_manifest_spec(heads[0])
                if comparison_spec is None:
                    report.errors.append(
                        "No reviewed schema manifest is available for comparison"
                    )
                elif comparison_spec.snapshot_file is not None:
                    report.schema_checks = compare_snapshot_schema(
                        connection,
                        _load_snapshot_manifest(comparison_spec),
                    )
                elif comparison_spec.metadata_variant is not None:
                    report.schema_checks = compare_head_schema(
                        connection,
                        metadata=_metadata_for_variant(
                            comparison_spec.metadata_variant
                        ),
                        retained_enums=_retained_enums(comparison_spec),
                    )
                if report.schema_matches_head:
                    report.schema_candidate_revision = comparison_spec.revision

            report.upgrade_allowed = bool(
                not report.errors
                and len(report.alembic_versions) == 1
                and report.current_revision_known
                and (
                    (report.current_revision == heads[0] and report.schema_matches_head)
                    or (
                        report.current_revision != heads[0]
                        and manifest_spec is not None
                        and report.schema_matches_head
                    )
                )
            )
            if report.upgrade_allowed and report.current_revision != heads[0]:
                report.warnings.append(
                    "Database has a validated forward migration path to head"
                )
            if (
                len(report.alembic_versions) == 1
                and report.current_revision == heads[0]
                and not report.schema_matches_head
            ):
                report.errors.append(
                    "Database ledger is at repository head but schema drift was found"
                )
            if (
                len(report.alembic_versions) == 1
                and report.current_revision != heads[0]
                and manifest_spec is not None
                and not report.schema_matches_head
            ):
                report.errors.append(
                    "Database source schema does not match its reviewed manifest"
                )
            if ledger_missing and report.schema_matches_head:
                report.warnings.append(
                    "Schema structurally matches repository head, but data-migration "
                    "history cannot be proven. No stamp or repair is available."
                )
    except Exception as exc:
        logger.error(
            "Database inspection failed closed",
            exc_info=redacted_exc_info(exc),
        )
        report.errors.append(f"Database inspection failed: {safe_error(exc)}")
    finally:
        if owned_engine:
            engine.dispose()
    return report
