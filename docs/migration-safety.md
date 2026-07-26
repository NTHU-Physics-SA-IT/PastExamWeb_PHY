# Alembic migration safety

`alembic_version` is a migration ledger, not a description of the live
schema. If a non-empty database loses that ledger, a direct
`alembic upgrade head` may replay the chain from `base` and collide with
existing objects. Stamping `head` based on table names is also unsafe because
columns, constraints, indexes, enum values, defaults, or data migrations may
still be missing.

## Safe commands

Run from `backend/`:

```bash
uv run python migrate.py preflight
uv run python migrate.py preflight --json
uv run python migrate.py upgrade
uv run python migrate.py reconcile --check
uv run python migrate.py reconcile --check --json
```

All preflight and reconciliation checks are read-only. Production-style
upgrades must use this CLI rather than invoking Alembic directly. The CLI
holds a PostgreSQL advisory lock across preflight, upgrade, and postflight,
and verifies that every phase targets the same database. A concurrent
migration fails without entering Alembic. This repository provides no stamp
or repair command.

`upgrade` is allowed only when:

- the database is truly empty and has no ledger revision;
- the repository has exactly one head, the database ledger contains exactly
  that head, and the complete head-schema comparison passes; or
- the database is at an explicitly reviewed forward-migration source revision
  and its complete revision-specific schema manifest passes.

Known ancestors without a reviewed manifest, unknown revisions, multiple
ledger rows, multiple repository heads, a non-empty database without a
ledger, source drift, and head drift all fail closed. A migration or
postflight error exits non-zero.

Reviewed manifests currently cover:

- `c4d8e2f1a6b9`: the July 12 recovery dump schema, captured from the
  read-only restored database;
- `a4c7e9d2f6b1`: the reviewed pre-canonicalization test baseline;
- `c9e4f1a7b2d6`: the canonical-category schema before metadata alignment;
- `e3b7c1d9f5a2`: the current SQLModel/head contract.

These are not claims about a live production revision. An unrecognized
production revision must remain blocked until a separately authorized,
read-only inspection produces a reviewed manifest.

## What is compared

The head assessment compares:

- tables and columns;
- PostgreSQL data types and nullability;
- primary keys and foreign keys, including delete behavior;
- unique and check constraints;
- indexes, including uniqueness and partial-index predicates;
- server defaults;
- PostgreSQL enum types and values;
- the database ledger revision and repository heads.

Any missing, unexpected, ambiguous, or unsupported structure fails closed.
Errors and JSON reports omit database URLs and redact configured passwords.

## Missing ledger

For a non-empty database without `alembic_version`,
`reconcile --check` may report a structural head candidate only when every
schema check matches. The command still exits non-zero because schema equality
cannot prove that historical data migrations ran. It never creates a ledger,
stamps a revision, changes data, or upgrades the schema.

Recovery requires a separately reviewed procedure and verified backup outside
this automation. Do not add `stamp`, repair logic, or reconciliation to a
container startup command.

## Startup, bootstrap, and Compose boundaries

Normal backend startup calls only the read-only readiness check. It never
runs Alembic, `create_all`, seed synchronization, bootstrap, or stamp. Missing
or drifting schema makes the process fail fast.

Fresh isolated development/test databases may be seeded only with the
explicit bootstrap command:

```bash
ALLOW_DATABASE_BOOTSTRAP=true \
uv run python -m app.scripts.seed_db \
  --confirm-database-name archive_db_dev_example
```

The database name must use an approved dev/test prefix, migration and
postflight must already pass, and the first run permits only the six
migration-created canonical categories with otherwise empty application
tables. A durable marker makes later explicit runs idempotent.

Acceptance, clean-development, and production Compose definitions use a
one-shot `migrate` service running `python migrate.py upgrade`. Backend
startup depends on `service_completed_successfully`; the migrate service has
no seed command, fixed container name, or restart loop.

Destructive tests additionally require an explicit `TEST_DATABASE_URL`, an
isolation marker, approved host/database/role prefixes, a database owned by
the connected non-superuser test role, and a target distinct from runtime
configuration. They never fall back to `DATABASE_URL` or `archive_db`.

## Migration-chain rule

Existing revision files are immutable. Add a new revision for future schema
changes and update the models in the same change. Extend the focused migration
safety scenarios whenever a new PostgreSQL enum, persistent server default,
partial index, or other schema feature changes the head manifest.
