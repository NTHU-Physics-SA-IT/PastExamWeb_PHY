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

The production Compose contract reads host-specific configuration outside the
release checkout:

- `/etc/pastexam/compose.prod.env` for Compose interpolation;
- `/etc/pastexam/docker-compose.edge.yml` for the reviewed host-specific nginx
  host-port bindings;
- `/opt/pastexam-config/backend.env` for the restricted runtime role; and
- `/opt/pastexam-config/migrator.env` for the one-shot migration role.

All four files must be root-owned deployment inputs with mode `0600`.
Secrets are neither copied into an immutable release nor printed. Runtime and
migrator credentials must be different.

`docker/.env.production.example` documents the non-secret Compose variable
contract. A release is rendered explicitly with the production definition and
the external environment file:

```bash
docker compose \
  --env-file /etc/pastexam/compose.prod.env \
  --file docker/docker-compose.prod.yml \
  --file /etc/pastexam/docker-compose.edge.yml \
  config
```

The base production definition deliberately exposes nginx port `8080` only to
the Compose network and does not publish a host port. The external edge
override is the reviewed authority for every host binding. The tracked
`docker/docker-compose.prod-edge.example.yml` demonstrates a loopback-only
`127.0.0.1:8080:8080` topology for a separately managed host edge proxy; it is
not authority for a production host and must not be copied over an existing
contract without reconciling current ingress.

The repository nginx configuration is HTTP-only and listens on container port
`8080`. TLS/HTTPS must terminate in a separately managed host proxy or load
balancer before traffic reaches that listener. If a host instead terminates
TLS inside `pastexam-nginx`, the current repository contract is insufficient:
activation must remain blocked until the required listeners, certificates,
and mappings are represented in a reviewed repository change. Do not infer
`80`, `443`, or `8443` from a container snapshot.

Before backup, activation renders the combined Compose configuration without
printing it and derives the PostgreSQL container, database and role plus the
MinIO container and bucket from that rendered contract. These values are
passed to the backup tools through isolated explicit environments. Arbitrary
inherited shell values are not backup authority, and runtime/migrator
credential files remain separate.

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

1. immutable `release_sha` agreement across `release-manifest.env`,
   `.release-source-sha`, and the release directory name;
2. combined base/edge Compose rendering and backup-identity extraction;
3. nginx ingress preservation preflight against the currently published
   `pastexam-nginx` bindings, plus Compose-target/listener consistency;
4. logical PostgreSQL custom-format backup plus validation;
5. read-only MinIO manifest;
6. migration preflight;
7. one-shot safe migration and postflight;
8. backend/frontend/nginx start;
9. internal and external health checks;
10. an activation marker written only after success.

There is no automatic database rollback. Any failure stops the sequence and
does not mark the release activated. Missing or malformed external files,
release-identity disagreement, missing rendered backup inputs, a missing
current nginx container, a target listener mismatch, or any target edge
contract that would drop a current published binding fails before backup,
migration, service recreation, or traffic switching. An intentional ingress
change therefore requires a separately reviewed edge-topology change; it
cannot be smuggled through ordinary activation.

The workflow file exposing this skeleton is manual-only, uses the protected
`production` environment, and also requires a repository-variable gate. It
must not be dispatched until production revision discovery, role creation,
external configuration, backup destinations, and approval rules have been
reviewed in a separately authorized production change.

## Production schema comparison contract

Production schema readiness is a three-way comparison:

1. the actual production `alembic_version` ledger and targeted schema
   fingerprint;
2. the migration head expected by the exact deployed backend commit, resolved
   from that commit's migration graph; and
3. the current development head, used only to describe a future upgrade path.

Production first compares with the deployed release. A production ledger that
differs from development is not by itself drift. A migration revision is not a
Git commit ID, and the deployed graph must be read from the deployed commit
tree. Classification constants needed by a later aggregate audit must be
compared between the deployed and current versions. Only after the deployed
head, one-row ledger, targeted schema and enum shape, and applicable constants
are reconciled may a separately authorized aggregate-only production audit
run.

Use these readiness descriptions:

- `matches deployed release`: ledger and targeted schema match the deployed
  backend expectation;
- `reviewed older state`: the state is a reviewed ancestor and no newer app is
  claimed to be running;
- `behind deployed app`: ledger/schema are older than the deployed backend
  expectation;
- `schema ahead of ledger` or `schema behind ledger`: the fingerprint and
  ledger disagree in that direction;
- `ahead of deployed app`: production schema is newer than the deployed
  backend expectation; and
- `untracked/divergent`: the state is absent from or incompatible with the
  reviewed deployed graph.

Development-head difference is reported separately and never substitutes for
the deployed-release comparison.

## Backup and restore

`scripts/postgres-logical-backup.sh` produces a custom-format `pg_dump`,
metadata, and SHA-256 file in an absolute directory outside the repository.
It records the database identity, PostgreSQL version, explicit immutable
application release SHA, and the single Alembic revision, and validates the
archive with `pg_restore --list`. The release SHA is verified from candidate
metadata by activation and passed explicitly; backup never requires or
reconstructs a `.git` directory inside a git-archive candidate.

`scripts/postgres-logical-restore.sh` restores only to a previously absent
database named `pastexam_restore_*`. It preserves a failed target for
diagnosis, then runs read-only migration preflight. It never overwrites,
stamps, migrates, or switches services.

MinIO backup is intentionally separate. The read-only manifest tool records
object metadata without moving, replacing, or deleting objects. PostgreSQL
restore never triggers MinIO restore or orphan cleanup.
