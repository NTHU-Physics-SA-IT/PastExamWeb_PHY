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

Candidate preparation writes only the digest-pinned frontend and backend image
references to the immutable release `compose.prod.env`. Activation layers that
file after the external production Compose environment, so candidate images
are authoritative while host configuration and secrets remain outside the
release. The rendered frontend, backend, and migrator images must exactly match
the checksummed release manifest before backup begins.

The production Compose contract reads host-specific configuration outside the
release checkout:

- `/etc/pastexam/compose.prod.env` for Compose interpolation;
- `/etc/pastexam/docker-compose.edge.yml` for the reviewed host-specific nginx
  host-port and certificate bind mounts;
- `/opt/pastexam-config/backend.env` for the restricted runtime role; and
- `/opt/pastexam-config/migrator.env` for the one-shot migration role.

All four files must be root-owned deployment inputs with mode `0600`. Secrets
are neither copied into an immutable release nor printed. Runtime and migrator
credentials must be different.

The Compose environment names the host-managed Cloudflare Origin certificate
and private-key paths with `PRODUCTION_TLS_CERT_FILE` and
`PRODUCTION_TLS_KEY_FILE`. Both files must exist before activation and must be
root-owned with mode `0600`. Certificate and key contents remain outside Git
and outside every immutable release.

The external Compose environment also sets `PRODUCTION_NGINX_PROXY_IP` to the
nginx address reserved outside the dynamic allocation range of the dedicated
`pastexam-trusted-proxy-network`. That network is an explicit `172.30.0.0/28`
bridge: `172.30.0.1` is its gateway, nginx uses `172.30.0.2`, and dynamic
backend allocation is restricted to `172.30.0.8/29`. Compose passes the same
single nginx address to Uvicorn as `FORWARDED_ALLOW_IPS`; do not replace it
with `*` or a whole network.

Only backend and nginx join the trusted-proxy network. The network-scoped
`backend-trusted` alias forces nginx API, sitemap, and robots traffic across
that bridge, so the backend sees nginx's reserved address as its immediate
peer. Both services remain on `pastexam-network` for their existing application
dependencies; that shared network retains Docker-selected IPAM and must not be
recreated merely to activate this trust boundary. Development supplies the
same backend alias on its existing default network without production IPAM or
Cloudflare trust.

`docker/.env.production.example` documents the Compose variable contract. A
release is rendered explicitly with the production definition, external
configuration, and its later immutable image override:

```bash
docker compose \
  --env-file /etc/pastexam/compose.prod.env \
  --env-file /opt/pastexam-releases/<release-sha>/compose.prod.env \
  --file docker/docker-compose.prod.yml \
  --file /etc/pastexam/docker-compose.edge.yml \
  config
```

The supported DigitalOcean edge terminates Cloudflare Origin TLS inside
`pastexam-nginx` and has this explicit topology:

- host `80` to nginx `8080` (HTTP);
- host `8080` to nginx `8080` (HTTP); and
- host `443` to nginx `8443` (TLS).

Ownership is deliberately split. `proxy/nginx.conf` owns repository-reviewed
application routing, headers, OAuth callback log suppression, and SEO routes.
`proxy/nginx.production-listeners.conf` owns the repository-reviewed `8080`
and `8443 ssl` listener directives, the container certificate paths, and the
official Cloudflare source networks trusted for `CF-Connecting-IP`.
`docker/docker-compose.prod.yml` mounts both immutable files. The external
`/etc/pastexam/docker-compose.edge.yml` owns host-specific published ports and
binds the host-managed certificate material to those exact container paths.
The tracked `docker/docker-compose.prod-edge.example.yml` represents this
topology; its former loopback-only example is not appropriate for this host.

Ordinary development continues to use the same application routing through
`proxy/nginx.development-listeners.conf`, which listens only on `8080` and
does not require production certificates. An edge override must not replace
either repository nginx configuration mount. Activation derives the actual
mounted sources from rendered Compose and requires them to be the immutable
release files, so the configuration checked is exactly the configuration
started by Docker.

This client-IP contract is safe only while public origin ingress remains
Cloudflare-only. Cloudflare CIDR changes must be applied together to the
DigitalOcean Cloud Firewall and the `set_real_ip_from` list before either side
is treated as current. nginx rebuilds both `X-Real-IP` and `X-Forwarded-For`
from its normalized `$remote_addr`; applications must not trust arbitrary
incoming forwarding headers directly. The access log intentionally retains
the immediate peer address rather than adding raw visitor-IP logging.

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
3. rendered nginx config, listener, certificate, and private-key mount
   extraction, followed by external TLS file ownership/mode checks;
4. nginx ingress preservation preflight against the currently published
   `pastexam-nginx` bindings, exact immutable config-mount verification,
   required TLS directives, and Compose-target/listener consistency;
5. logical PostgreSQL custom-format backup plus validation;
6. read-only MinIO manifest;
7. migration preflight;
8. one-shot safe migration and postflight;
9. backend/frontend/nginx start;
10. internal and external health checks;
11. an activation marker written only after success.

There is no automatic database rollback. Any failure stops the sequence and
does not mark the release activated. Missing or malformed external files,
release-identity disagreement, missing rendered backup inputs, a missing
current nginx container, an absent or unsafe TLS file, a missing certificate
mount, an unexpected nginx config mount, an incomplete TLS listener, a target
listener mismatch, or any target edge contract that would drop a current
published binding fails before backup, migration, service recreation, or
traffic switching. An intentional ingress change therefore requires a
separately reviewed edge-topology change; it cannot be smuggled through
ordinary activation.

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
