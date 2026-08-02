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
uv run python audit.py run \
  --audit archive-submission-self-delete-eligibility \
  --mode isolated-test
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

- `c4d8e2f1a6b9`: a reviewed legacy schema captured from an isolated,
  read-only restore;
- `a4c7e9d2f6b1`: the reviewed pre-canonicalization test baseline;
- `c9e4f1a7b2d6`: the canonical-category schema before metadata alignment;
- `e3b7c1d9f5a2`: the reviewed schema before the archive-report workflow;
- `a7c3e9f1b5d2`: the reviewed schema before persisted ArchiveSubmission
  owner-self-delete eligibility;
- `f5e1d8c3a7b2`: the reviewed schema before typed ArchiveSubmission previous
  status; and
- `d8f2a6c1b4e7`: the current repository head and SQLModel metadata contract.

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

The six canonical category keys are identity anchors, not immutable display
content. Category `name`, `label`, `icon`, `badge_color`, ordering, active
state, and trash/restore metadata remain database-managed. Custom rows are
also database-managed and do not need to be added to application constants.
The missing-row default for `math-department` is `戳戳數學系` with label
`數學`.

Category migrations only convert the documented legacy keys and their key
references. They preserve administrator metadata and submission snapshot
fields. Ambiguous canonical/legacy rows or normalized-name collisions abort
the transaction; migrations never choose a row by ID or delete a conflicting
row automatically.

The ArchiveSubmission owner-self-delete eligibility migration classifies the
reviewed source rows before adding its non-null boolean. Historical owner
self-deletes, active restored rows with cleared deletion provenance, and
currently identifiable administrator-deleted rows are conservatively
backfilled as consumed. Metadata-consistent historical system/cascade rows
using the tracked linked-Archive permanent-deletion format are also
conservatively backfilled as consumed; future system/cascade deletion preserves
the existing value and remains application-milestone work. Clean active rows
are not consumed. Unknown actor/reason combinations, mismatched system
metadata, ownership or lifecycle contradictions, overlapping buckets,
unclassified rows, and conservation failures abort the PostgreSQL transaction.
The migration does not infer one submission's value from a shared Archive and
does not modify Archive, ownership, review, delete, or restore metadata.

On the first bootstrap, one missing canonical key or any extra custom category
is evidence that the database is not the expected clean initialized target,
so bootstrap fails without creating an administrator or marker. After the
marker exists, missing canonical keys are recreated from defaults, while
existing and custom rows are left unchanged. Legacy keys and same-name
different-key conflicts still fail closed.

The default administrator password is applied only while creating the named
default account or restoring it from soft deletion. Restoration intentionally
resets the password and is therefore a sensitive dev/test operation. A normal
account retains its password and email. A renamed account still holding the
configured default email causes an explicit conflict error; if both configured
identity fields were changed, bootstrap can create a separate default account.

Development and production Compose definitions use a
one-shot `migrate` service running `python migrate.py upgrade`. Backend
startup depends on `service_completed_successfully`; the migrate service has
no seed command, fixed container name, or restart loop.

Destructive tests additionally require an explicit `TEST_DATABASE_URL`, an
isolation marker, approved host/database/role prefixes, a database owned by
the connected non-superuser test role, and a target distinct from runtime
configuration. They never fall back to `DATABASE_URL` or `archive_db`.

## Bounded read-only aggregate audits

`backend/audit.py` is the sealed audit entry point. It accepts only registered
audit IDs and versions; callers cannot provide SQL, table names, output fields,
retry behavior, or free-form predicates. A versioned adapter owns historical
constants and aggregate predicates independently of application services, and
focused parity tests keep a migration-specific adapter aligned with its
reviewed migration classifier. Adding a classifier requires a new registered
version and synthetic PostgreSQL evidence.

Every execution sends one complete input stream to non-interactive `psql` and
uses `ON_ERROR_STOP`, `REPEATABLE READ READ ONLY`, statement/lock/idle
timeouts, environment identity checks, a one-row ledger check, targeted schema
and enum continuity (including `pg_enum.enumlabel::text`), aggregate-only
classification, mutual-exclusivity and conservation checks, explicit
`ROLLBACK`, and a final completion sentinel. It creates no server file,
temporary object, lock, function, or persistent state and never emits row IDs,
PII, raw free-text reasons, or timestamps.

The strict machine-readable result distinguishes `complete`, `data_blocked`,
`audit_error`, and `incomplete_transport`. Human output is derived from the
same validated object and does not query again. Unknown fields, more than the
bounded combination count, an unexpected revision/environment/enum, a write
token, a timeout, a psql error, missing rollback, or truncated transport fails
closed. There is no implicit retry or repair operation.

Modes remain separate:

- isolated test mode reuses the destructive-test identity guard;
- persistent-local mode requires the exact healthy `pastexam-dev` PostgreSQL
  container and never migrates or repairs it; and
- production aggregate-only mode requires both task-level authorization and
  the explicit CLI production gate, plus the exact production container
  identity. Merely selecting the mode is not production authority.

This runner is not a SQL shell, migration wrapper, schema reconciliation
replacement, data remediation tool, production repair tool, or generic
database console.

For the persistent local stack, invoke the same sealed adapter through
`scripts/dev-compose.sh schema-status`. `backend-resume` runs that compatibility
gate before starting an existing paused backend; it never creates a container
or performs an upgrade. `backend-pause` and `backend-resume` are deliberate
schema-branch controls, not general restart shortcuts.

## Migration-chain rule

Published or deployed revision files are immutable. Add a new revision for
future schema changes and update the models in the same change. An unpublished
revision isolated to an unmerged development branch may be corrected before
release only after history and tag checks prove it has not shipped. Extend the
focused migration safety scenarios whenever a new PostgreSQL enum, persistent
server default, partial index, or other schema feature changes the head
manifest.
