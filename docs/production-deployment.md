# Production deployment safety

## Immutable candidates

The main build publishes commit-specific frontend and backend tags. Candidate
preparation combines those tags with their registry digests and records them
in a root-only `release-manifest.env` alongside:

- the full release commit SHA;
- the workflow run ID that first created the candidate;
- the source archive SHA-256;
- the tracked-file checksum manifest SHA-256; and
- the UTC creation time.

Rerunning candidate preparation for the same commit validates the existing
manifest, every tracked source file, the immutable image references, and the
rendered Compose images. Matching candidates are reused; mismatches fail
without overwriting either candidate.

The `PRODUCTION_DEPLOY_ENABLED` repository variable must remain unset or false
until candidate evidence has been reviewed. Candidate preparation never runs
`docker compose pull`, `docker compose up`, or a traffic switch.

## Production configuration boundary

The production Compose contract reads secret-bearing configuration outside
the release checkout:

- `/etc/pastexam/compose.prod.env` for Compose interpolation;
- `/opt/pastexam-config/backend.env` for the restricted runtime role; and
- `/opt/pastexam-config/migrator.env` for the one-shot migration role.

All three files must be root-owned deployment inputs with mode `0600`.
Secrets are neither copied into an immutable release nor printed. Runtime and
migrator credentials must be different.

`docker/.env.production.example` documents the non-secret Compose variable
contract. A release is rendered explicitly with the production definition and
the external environment file:

```bash
docker compose \
  --env-file /etc/pastexam/compose.prod.env \
  --file docker/docker-compose.prod.yml \
  config
```

## Migration and activation order

`docker/docker-compose.prod.yml` defines a non-restarting one-shot `migrate`
service with migrator credentials. The backend depends on its successful
completion and therefore cannot start after a failed preflight, migration, or
postflight. Runtime credentials have DML and sequence access but no schema
ownership or DDL privilege.

Production activation runs migrations only. The production Compose definition
has no bootstrap profile or `seed_db.py` command, and backend startup performs
only its read-only schema readiness check. Consequently,
`DEFAULT_ADMIN_PASSWORD` is never consumed to create, restore, or reset an
account during a production update. Category display metadata and custom
categories remain managed data; deployment does not synchronize them to
application defaults.

The activation skeleton is deliberately disabled unless all of the following
are supplied outside Git:

- `PRODUCTION_DEPLOY_ENABLED=true`;
- the exact activation confirmation phrase;
- an immutable release directory and verified manifest checksum;
- external `0600` configuration;
- an external health URL.

It then acquires a host deployment lock and performs:

1. logical PostgreSQL custom-format backup plus validation;
2. read-only MinIO manifest;
3. migration preflight;
4. one-shot safe migration and postflight;
5. backend/frontend/nginx start;
6. internal and external health checks;
7. an activation marker written only after success.

There is no automatic database rollback. Any failure stops the sequence and
does not mark the release activated.

The workflow file exposing this skeleton is manual-only, uses the protected
`production` environment, and also requires a repository-variable gate. It
must not be dispatched until production revision discovery, role creation,
external configuration, backup destinations, and approval rules have been
reviewed in a separately authorized production change.

## Backup and restore

`scripts/postgres-logical-backup.sh` produces a custom-format `pg_dump`,
metadata, and SHA-256 file in an absolute directory outside the repository.
It records the database identity, PostgreSQL version, application commit,
repository head, and the single Alembic revision, and validates the archive
with `pg_restore --list`.

`scripts/postgres-logical-restore.sh` restores only to a previously absent
database named `pastexam_restore_*`. It preserves a failed target for
diagnosis, then runs read-only migration preflight. It never overwrites,
stamps, migrates, or switches services.

MinIO backup is intentionally separate. The read-only manifest tool records
object metadata without moving, replacing, or deleting objects. PostgreSQL
restore never triggers MinIO restore or orphan cleanup.
