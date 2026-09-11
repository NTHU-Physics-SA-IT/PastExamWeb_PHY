"""upgrade NTHU identity profile semantics

Revision ID: c3f8a1d6e9b2
Revises: a5f7c9d2e4b6
Create Date: 2026-09-10 00:00:00.000000
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3f8a1d6e9b2"
down_revision: str | Sequence[str] | None = "a5f7c9d2e4b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "users"
EMAIL_INDEX = "ix_users_email"
NAME_INDEX = "ix_users_name"
LOCAL_NAME_INDEX = "uq_users_local_name"
OAUTH_IDENTITY_CONSTRAINT = "uq_users_oauth_provider_sub"
IN_SCHOOL_COLUMN = "nthu_inschool"
LOCAL_NAME_PREDICATE = "is_local IS TRUE"
LOCK_SQL = "LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"

_INDEX_STATE_SQL = sa.text(
    """
    SELECT index_state.indisunique AS is_unique,
           array_agg(attribute.attname ORDER BY key_column.ordinality) AS columns,
           pg_get_expr(index_state.indpred, index_state.indrelid) AS predicate
    FROM pg_class AS table_relation
    JOIN pg_namespace AS namespace
      ON namespace.oid = table_relation.relnamespace
    JOIN pg_index AS index_state
      ON index_state.indrelid = table_relation.oid
    JOIN pg_class AS index_relation
      ON index_relation.oid = index_state.indexrelid
    JOIN LATERAL unnest(index_state.indkey)
      WITH ORDINALITY AS key_column(attnum, ordinality)
      ON TRUE
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = table_relation.oid
     AND attribute.attnum = key_column.attnum
    WHERE namespace.nspname = 'public'
      AND table_relation.relname = :table_name
      AND index_relation.relname = :index_name
    GROUP BY index_state.indisunique, index_state.indpred, index_state.indrelid
    """
)


def _normalized_predicate(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.lower().replace("::boolean", "")
    return re.sub(r'[\s()"]+', "", normalized)


def _require_ledger(connection: sa.Connection, expected: str) -> None:
    versions = list(
        connection.execute(
            sa.text("SELECT version_num FROM alembic_version ORDER BY version_num")
        ).scalars()
    )
    if versions != [expected]:
        raise RuntimeError(
            f"NTHU identity profile migration requires {expected}; found {versions!r}"
        )


def _index_state(
    connection: sa.Connection,
    index_name: str,
) -> tuple[bool, tuple[str, ...], str] | None:
    row = (
        connection.execute(
            _INDEX_STATE_SQL,
            {"table_name": TABLE_NAME, "index_name": index_name},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return (
        bool(row["is_unique"]),
        tuple(row["columns"]),
        _normalized_predicate(row["predicate"]),
    )


def _require_oauth_identity_constraint(connection: sa.Connection) -> None:
    constraints = sa.inspect(connection).get_unique_constraints(
        TABLE_NAME,
        schema="public",
    )
    matching = [
        item for item in constraints if item.get("name") == OAUTH_IDENTITY_CONSTRAINT
    ]
    if len(matching) != 1 or tuple(matching[0].get("column_names") or ()) != (
        "oauth_provider",
        "oauth_sub",
    ):
        raise RuntimeError("NTHU OAuth provider identity constraint is not reviewed")


def _require_columns(connection: sa.Connection, *, upgraded: bool) -> None:
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }
    expected = {
        "email": (sa.String, False),
        "name": (sa.String, False),
        "is_local": (sa.Boolean, False),
        "deleted_at": (sa.DateTime, True),
    }
    for name, (column_type, nullable) in expected.items():
        column = columns.get(name)
        if (
            column is None
            or not isinstance(column["type"], column_type)
            or column["nullable"] is not nullable
        ):
            raise RuntimeError(f"users.{name} source column is not reviewed")

    in_school = columns.get(IN_SCHOOL_COLUMN)
    if upgraded:
        if (
            in_school is None
            or not isinstance(in_school["type"], sa.Boolean)
            or in_school["nullable"] is not True
            or in_school.get("default") is not None
        ):
            raise RuntimeError(
                "users.nthu_inschool does not match the reviewed contract"
            )
    elif in_school is not None:
        raise RuntimeError(
            "NTHU identity profile source already has users.nthu_inschool"
        )


def _require_index(
    connection: sa.Connection,
    index_name: str,
    *,
    unique: bool,
    columns: tuple[str, ...],
    predicate: str = "",
) -> None:
    state = _index_state(connection, index_name)
    expected = (unique, columns, _normalized_predicate(predicate))
    if state != expected:
        raise RuntimeError(
            f"User index {index_name!r} is not reviewed: expected {expected!r}, "
            f"found {state!r}"
        )


def _require_source_schema(connection: sa.Connection) -> None:
    _require_columns(connection, upgraded=False)
    _require_index(connection, EMAIL_INDEX, unique=True, columns=("email",))
    _require_index(connection, NAME_INDEX, unique=True, columns=("name",))
    if _index_state(connection, LOCAL_NAME_INDEX) is not None:
        raise RuntimeError("Local username index already exists")
    _require_oauth_identity_constraint(connection)


def _require_upgraded_schema(connection: sa.Connection) -> None:
    _require_columns(connection, upgraded=True)
    _require_index(connection, EMAIL_INDEX, unique=False, columns=("email",))
    _require_index(connection, NAME_INDEX, unique=False, columns=("name",))
    _require_index(
        connection,
        LOCAL_NAME_INDEX,
        unique=True,
        columns=("name",),
        predicate=LOCAL_NAME_PREDICATE,
    )
    _require_oauth_identity_constraint(connection)


def _duplicate_summary(
    connection: sa.Connection, column_name: str
) -> tuple[int, int, int]:
    row = connection.execute(
        sa.text(
            f"""
            SELECT count(*)::integer AS duplicate_groups,
                   COALESCE(sum(cardinality), 0)::integer AS affected_rows,
                   COALESCE(max(cardinality), 0)::integer AS max_cardinality
            FROM (
                SELECT count(*)::integer AS cardinality
                FROM users
                GROUP BY {column_name}
                HAVING count(*) > 1
            ) AS duplicates
            """
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2])


def _require_downgrade_data(connection: sa.Connection) -> None:
    email = _duplicate_summary(connection, "email")
    name = _duplicate_summary(connection, "name")
    if email[0] or name[0]:
        raise RuntimeError(
            "NTHU identity profile downgrade cannot restore global uniqueness: "
            f"email_duplicate_groups={email[0]}, email_affected_rows={email[1]}, "
            f"email_max_cardinality={email[2]}, name_duplicate_groups={name[0]}, "
            f"name_affected_rows={name[1]}, name_max_cardinality={name[2]}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("NTHU identity profile migration requires PostgreSQL")

    _require_ledger(connection, down_revision)
    connection.execute(sa.text(LOCK_SQL))
    _require_source_schema(connection)

    op.add_column(TABLE_NAME, sa.Column(IN_SCHOOL_COLUMN, sa.Boolean(), nullable=True))
    op.create_index(
        LOCAL_NAME_INDEX,
        TABLE_NAME,
        ["name"],
        unique=True,
        postgresql_where=sa.text(LOCAL_NAME_PREDICATE),
    )
    op.drop_index(NAME_INDEX, table_name=TABLE_NAME)
    op.create_index(NAME_INDEX, TABLE_NAME, ["name"], unique=False)
    op.drop_index(EMAIL_INDEX, table_name=TABLE_NAME)
    op.create_index(EMAIL_INDEX, TABLE_NAME, ["email"], unique=False)

    _require_upgraded_schema(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("NTHU identity profile migration requires PostgreSQL")

    _require_ledger(connection, revision)
    connection.execute(sa.text(LOCK_SQL))
    _require_upgraded_schema(connection)
    _require_downgrade_data(connection)

    op.drop_index(EMAIL_INDEX, table_name=TABLE_NAME)
    op.create_index(EMAIL_INDEX, TABLE_NAME, ["email"], unique=True)
    op.drop_index(NAME_INDEX, table_name=TABLE_NAME)
    op.create_index(NAME_INDEX, TABLE_NAME, ["name"], unique=True)
    op.drop_index(LOCAL_NAME_INDEX, table_name=TABLE_NAME)
    op.drop_column(TABLE_NAME, IN_SCHOOL_COLUMN)

    _require_source_schema(connection)
