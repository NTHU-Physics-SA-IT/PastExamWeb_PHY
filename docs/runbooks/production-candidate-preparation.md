# Production candidate preparation

`PREPARE` is not `ACTIVATE`. Candidate preparation stages and verifies an
immutable, SHA-addressed release; it must not switch traffic, run migrations,
restart services, mutate runtime configuration, or change PostgreSQL, Redis,
MinIO, nginx, Cloudflare, or DigitalOcean networking.

## Governance boundary

Automatic preparation is controlled only by the repository variable
`AUTO_PREPARE_PRODUCTION_CANDIDATE`. Activation remains a separate manual
workflow and may retain its isolated `PRODUCTION_DEPLOY_ENABLED` gate. The
candidate workflow uses the `production-candidate` Environment and four
candidate-only secrets:

`PRODUCTION_DEPLOY_ENABLED=false` remains unchanged during this source rollout;
it is neither a candidate-preparation fallback nor altered by these workflows.

- `PRODUCTION_CANDIDATE_SSH_PRIVATE_KEY`;
- `PRODUCTION_CANDIDATE_KNOWN_HOSTS`;
- `PRODUCTION_CANDIDATE_HOST`; and
- `PRODUCTION_CANDIDATE_USER`.

Do not use `secrets: inherit`. Provision a dedicated candidate SSH principal
whose server-side authorization permits only the root-owned fixed command
`/usr/local/sbin/pastexam-prepare-candidate`. Install the reviewed script from
`scripts/prepare-production-candidate.sh` at that path in a separately
authorized host-governance operation. Do not stream repository shell source to
a privileged interpreter.

The archive is streamed as data to the fixed command's checksum-bound `upload`
subcommand after capacity preflight; the principal does not need general SCP,
SFTP, an interactive shell, or an arbitrary destination. The fixed command
also rejects archive streams larger than 256 MiB.

Configure `production-candidate` for protected `main` only. It needs no routine
human reviewer because it grants preparation—not activation—but it must contain
only the four candidate secrets above and must never contain activation secrets.

Keep `AUTO_PREPARE_PRODUCTION_CANDIDATE` false or absent until the Environment,
candidate-only secrets, fixed host command, and restricted SSH principal have
all been provisioned and read back. This source change does not provision or
enable any of them.

## Fail-closed preparation

Before upload, the fixed command requires the release filesystem to report:

- at least 10 GiB available;
- at least 20 percent available blocks;
- at least 100,000 available inodes; and
- at least 10 percent available inodes.

Missing, zero, or malformed filesystem metrics fail closed. Preparation never
prunes releases. It validates the deterministic package, tracked-file manifest,
source SHA, digest-pinned images, and production Compose rendering, then moves a
run-specific staging directory atomically to `/opt/pastexam-releases/<SHA>`.
The fixed command also holds a host-side nonblocking preparation lock, so the
same immutable namespace cannot be raced by a second caller.
An existing same-SHA candidate is reused only when all immutable inputs and its
receipt still match; conflicting content is never overwritten.

The root-only candidate receipt is also retained as a 90-day GitHub artifact.
It records schema, source SHA, preparation and source-CI run identity, UTC
timestamp, image digests, package/tracked-file/release-manifest checksums, a safe
release identifier, and verified outcome. It contains no host, user, key,
secret, token, object name, or production configuration value.

## Manual exact-SHA preparation

The manual workflow accepts only a full lowercase commit SHA. Before contacting
production it proves the SHA is an ancestor of current `main`, resolves exactly
one successful push Full CI run for that SHA, verifies the Full attestation and
build/gate jobs, and resolves immutable SHA-tagged image manifests. Automatic
and manual preparation call the same reusable workflow.

## Retention invariant

Retention is an explicit operator procedure, never an automatic candidate job.
Preserve the active release, the previous known-good rollback release, every
pinned audit/evidence release, and the newest ten unactivated candidates.
Before any separately authorized deletion, re-read active/rollback/pin
authority, require at least those protected releases, and verify disk/inode
headroom. Failed staging residue is reported by run identity and may be removed
only through the fixed command's exact run-scoped cleanup. Never prune from a
main-push workflow.

## Activation

Activation requires separate explicit authorization and the protected
`production` Environment. It consumes an exact reviewed candidate and its
manifest checksum. Candidate preparation must never create `.activated`, alter
an active pointer, run Compose lifecycle commands, run migrations, write
backups, or mutate storage. Any future change that blurs this boundary requires
a new governance review before auto-preparation can remain enabled.
