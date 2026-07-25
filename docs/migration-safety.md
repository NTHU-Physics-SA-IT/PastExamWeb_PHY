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
uv run migrate.py preflight
uv run migrate.py preflight --json
uv run migrate.py upgrade
uv run migrate.py reconcile --check
uv run migrate.py reconcile --check --json
```

All preflight and reconciliation checks are read-only. This repository
provides no stamp or repair command.

`upgrade` is allowed only when:

- the database has no application tables and has no ledger revision; or
- the repository has exactly one head, the database ledger contains exactly
  that known head, and the complete supported head-schema comparison passes.

A known non-head revision is deliberately blocked. The repository does not
store a reviewed schema manifest for every historical revision, so preflight
cannot prove that an older live schema is consistent with its ledger.

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

## Compose and deployment boundaries

The isolated acceptance Compose project has a one-shot `migrate` service. It
runs `python migrate.py upgrade`, and dependent services start only after it
completes successfully. It does not seed data.

The production Compose file, production deployment workflows, backup scripts,
restore scripts, production hosts, and production databases are outside this
change. `PRODUCTION_DEPLOY_ENABLED` must remain unset or false.

## Migration-chain rule

Existing revision files are immutable. Add a new revision for future schema
changes and update the models in the same change. Extend the focused migration
safety scenarios whenever a new PostgreSQL enum, persistent server default,
partial index, or other schema feature changes the head manifest.
