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

Automatic candidate preparation is governed only by
`AUTO_PREPARE_PRODUCTION_CANDIDATE`; activation authority remains separate.
Candidate preparation never runs `docker compose pull`, `docker compose up`,
or a traffic switch. See the
[candidate preparation runbook](runbooks/production-candidate-preparation.md)
for the fixed-command, capacity, receipt, and retention contracts.

## Production configuration boundary

Candidate preparation writes only the digest-pinned frontend and backend image
references to the immutable release `compose.prod.env`. Activation layers that
file after the external production Compose environment, so candidate images
are authoritative while host configuration and secrets remain outside the
release. The rendered frontend, backend, and migrator images must exactly match
the checksummed release manifest before backup begins.

The base production Compose definition also pins nginx 1.29.2 by registry
digest. Candidate manifests and receipts record that digest alongside the two
application image digests, and activation requires all three rendered images to
match. A mutable nginx tag is not valid candidate authority.

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

The backend runtime uses only `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` for a
child access key under the dedicated non-root application identity. The
backend environment must not contain `MINIO_ROOT_USER` or
`MINIO_ROOT_PASSWORD`; those names remain valid only for the MinIO server's
separate infrastructure configuration. Bucket-wide orphan maintenance receives
explicit operator credentials outside normal backend runtime. See the
[MinIO application identity runbook](runbooks/minio-application-identity.md).

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

The first GitHub-driven activation framework supports only migration Class 0:
the production database must already be at the exact single repository head
and pass the complete schema comparison. `migrate.py require-head --json` is a
read-only, advisory-lock-protected gate. Any non-zero delta fails before backup
or application mutation; this framework never runs `migrate.py upgrade`.

The production Compose definition has no bootstrap profile or `seed_db.py`
command, and backend startup performs only its read-only schema readiness
check. `DEFAULT_ADMIN_PASSWORD` is forbidden in the production runtime and
migrator environment contracts. A key-name-only source validator rejects it
in both committed production environment templates before Compose rendering;
the validator never emits or resolves a value. The explicit dev/test bootstrap
instead owns `BOOTSTRAP_ADMIN_PASSWORD`, which normal API and migrator settings
do not load.

An older active release may still require the legacy key in its root-owned
host configuration. Leave that physical key in place until a compatible
release is deployed and verified, then remove only that key through a separate
human-controlled cleanup. Enforcement against the actual external host files
must be coordinated with that cleanup; committed-template validation does not
claim the deployed legacy file is already clean. Category display metadata and
custom categories remain managed data; deployment does not synchronize them
to application defaults.

The root-owned activation engine remains fail-closed unless all of the
following are supplied by the reviewed controller:

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
5. read-only verification that the existing PostgreSQL, Redis, and MinIO
   containers are already running, followed by functional PostgreSQL readiness,
   Redis PING, and MinIO authority probes; migration probes use
   `docker compose run --no-deps` so preflight cannot start a missing service;
6. read-only verification that the application bucket exists and versioning is
   `Enabled`;
7. logical PostgreSQL custom-format backup plus validation;
8. read-only MinIO manifest;
9. exact-head, zero-delta migration verification before and after backup;
10. exact backend/frontend/nginx start with dependency traversal disabled;
11. immediate internal and external health checks;
12. three bounded observation snapshots covering health, Redis, storage, and
    restart-count stability; and
13. activation evidence and a marker written only after success.

The storage preflight never creates a bucket or changes versioning. Production
activation is blocked until a separately authorized operational gate enables
versioning on the existing bucket.

The MinIO service healthcheck's `mc ready local` command proves only service
readiness. Activation does not trust that container-local alias for
authenticated bucket authority. The storage preflight creates a unique,
root-only temporary `mc` configuration inside the MinIO container, derives a
distinct loopback alias from the server's operator environment, performs only
the bucket and versioning reads, and removes the temporary configuration on
exit. MinIO operator credentials never enter backend runtime configuration.

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

## GitHub activation and durable state

`.github/workflows/activate-production.yml` is manual `workflow_dispatch`
only. Before approval it binds the requested exact current-main SHA to one
authoritative successful Main Full run, immutable image authority, and the
candidate receipt. The mutation-capable job uses the protected `production`
Environment and exactly its four activation SSH secrets. After approval it
rechecks current main and the same Main Full authority before contacting the
restricted host identity. Workflow concurrency never cancels an in-progress
production mutation.

The host controller stores canonical active authority at
`/var/lib/pastexam-deployments/active.json`, durable request state under
`requests/`, and checksummed receipts under `receipts/`. It verifies the
ledger, running images, Compose working directory, release evidence,
`/opt/pastexam-current`, and `/opt/pastexam-current-release.env` before a
mutation. After the engine, health, observation, and receipt gates succeed, the
controller commits the canonical ledger first and then atomically updates both
compatibility views. If the process stops between those writes, the next
worker invocation verifies the committed ledger, runtime, marker, and receipt,
repairs only the compatibility views, and completes the original request
without rerunning backup or activation. A repeated identical request is a
status lookup; conflicting reuse is rejected. A systemd-owned worker continues
after SSH/runner disconnect, and a receipt-finalization retry uses existing
engine evidence without rerunning backup or activation. During polling, the
workflow periodically asks the controller to resume; the controller dispatches
only when the original worker is inactive and either the target ledger is
already committed or the request is explicitly in the finalization-retry
phase.

Rollback is a separate manual protected workflow. It accepts only the
canonical previous exact SHA, requires the database revision to remain
unchanged, performs no Alembic downgrade, and never runs automatically in
response to a generic assertion failure.

`PRODUCTION_DEPLOY_ENABLED=false` remains the repository governance setting;
it does not expose or authorize the host controller. Actual authority is the
protected Environment plus the forced-command, digest-bound host entrypoint.
Do not dispatch either production workflow until a separate first-deployment
gate explicitly authorizes it.

## Upload and PDF request boundary

Production nginx limits ordinary `/api/` requests to `1M`. The exact
`POST /api/archives/upload` route has a `21M` transport allowance so multipart
overhead can carry the backend's authoritative 20 MiB PDF limit; `/minio/`
retains its separate `100M` object-serving contract. The exact upload location
must preserve the same trusted-client forwarding, authorization, CORS, and
backend routing directives as the generic API location.

The backend stages an upload with a hard byte cap before parsing and uses the
pinned pikepdf/qpdf stack in a bounded helper process. Validation rejects
encrypted, recovery-dependent, over-limit, embedded-file, form/XFA,
JavaScript, launch-action, additional-action, and file-attachment documents.
Production Linux constrains parser address space and serializes parsing across
Uvicorn workers. Each worker admits at most one helper; with the production
four-worker command there can be at most four helper processes (a 1 GiB sum of
hard address-space ceilings), while the container-wide advisory lock permits
only one helper to import pikepdf and parse at a time. Waiting helpers remain
before the parser import. Deployment validation must continue to build the
production backend image and run nginx syntax checks for both development and
production configurations. Historical orphan cleanup remains a separate,
operator-controlled operation and is never triggered by this request path.

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
