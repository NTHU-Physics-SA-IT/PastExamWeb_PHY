# Local development environment

Status: Active

Source of truth for: Local environment identities, supported modes, and safe Compose use

Applies to: Contributors and Agents running PastExamWeb_PHY outside production

Related documents:
- [Validation policy](validation.md)
- [Migration safety](../migration-safety.md)
- [Production deployment](../production-deployment.md)

## Purpose

This document identifies the supported local stack and its data boundaries. It
does not replace the public quick start in the repository `README.md` or the
operational policies linked above.

## Canonical development stack

### Current implementation

`scripts/dev-compose.sh` is the canonical entry point for the local Compose
stack. It validates the Docker context, the environment file, and the project,
network, volume, database, and bucket identities before it delegates to
`docker/docker-compose.dev.yml`.

The canonical development project name is `pastexam-dev`. The default stack is:

| Service | Compose service | Development role |
| --- | --- | --- |
| Vue/Vite frontend | `frontend` | Serves the application and HMR traffic |
| FastAPI backend | `backend` | Serves `/api` and `/health` |
| PostgreSQL | `db` | Stores application data in the configured development database |
| Redis | `redis` | Supports runtime Redis-backed features |
| MinIO | `minio`, `minio-init` | Stores archive objects and initializes the configured bucket |
| Alembic runner | `migrate` | Runs the guarded migration CLI before backend startup |
| Nginx | `nginx` | Exposes the development site on `127.0.0.1:8080` by default |

An explicit `bootstrap` profile exists for guarded initialization. It is not a
normal startup step.

### Intended invariant

Normal development and feature diagnosis use this named stack unless the task
explicitly requires a separately designed isolated environment.

## Environment modes

| Mode | Current implementation | Data lifetime and boundary |
| --- | --- | --- |
| Development | `scripts/dev-compose.sh` with `docker/docker-compose.dev.yml` | Named local volumes and network; intended to survive ordinary stop/start cycles |
| Test | No independent test Compose file exists | CI derives an ephemeral stack from the development Compose definition and destroys its test volumes afterward |
| Production-like | No separately supported local mode exists | Do not describe an ad hoc Compose project as production-like without an explicit environment contract |
| Production | `docker/docker-compose.prod.yml` plus the production deployment process | External configuration and production data; not a local development mode |

### Known gap

The repository has no standalone test Compose contract. CI isolation therefore
depends on explicit project, database, role, port, volume, and cleanup choices
in the workflows rather than on a dedicated Compose file.

## Environment responsibility matrix

| Environment | Identity guards | Allowed purpose and operations | Forbidden use | Credentials and cleanup | Startup/shutdown owner and evidence |
| --- | --- | --- | --- | --- | --- |
| Isolated test PostgreSQL | Explicit `TEST_DATABASE_URL`; database and role use `pastexam_test_`; approved host; connected non-superuser owns only the test database; target differs from runtime | Red/green fixtures, migration atomicity and downgrade, manifest, classifier, and concurrency evidence | Persistent-history upgrade claims, manual UI, or production distribution claims | Private/CI secret input; only the test lifecycle may reset its schema and clean resources it created | Test fixture/CI owns lifecycle; produces focused PostgreSQL evidence |
| Persistent local development | Project `pastexam-dev`; exact service/container labels; persistent database identity; repository head, ledger, backend health, and bind mount checked together | Aggregate preflight, guarded local upgrade rehearsal, health/proxy smoke, and manual UI | Replacing isolated atomicity tests or representing production | Local secret files are not printed; database, roles, volumes, and user data survive ordinary stop/start | `scripts/dev-compose.sh` and the developer own lifecycle; produces environment and human-verification evidence |
| Acceptance | Explicit controlled acceptance project, database, ports, volumes, and teardown owner | E2E and acceptance behavior in its designed stack | Local data remediation, production audit, or arbitrary migration-rehearsal substitution | Acceptance credentials stay in its workflow; clean only resources created by that run | Acceptance workflow owns startup/shutdown and produces E2E evidence |
| Production | Exact host/container/release identity, deployed-commit graph, actual ledger, targeted schema, and explicit task authorization | Separately authorized aggregate-only audit, deployment migration, backup, activation, and recovery | Red/green experimentation, exploratory row output, local rehearsal replacement, or automatic repair | External root-owned secrets; cleanup/rollback only through the production runbook | Authorized production operations own lifecycle and produce release/audit evidence |

## Schema-changing branch runtime protocol

Before developing or switching a schema-changing branch, record the repository
migration head, persistent-local ledger, backend health, and whether the
backend source is bind-mounted from the working tree. If the repository head
will move ahead of the local ledger, the canonical default is to pause the
existing backend with the guarded development wrapper before exposing the new
tree. Do not leave a fail-fast backend presented as an available site.

During implementation, use isolated PostgreSQL for red/green migration work.
Keep the persistent stack paused or explicitly marked unavailable; do not
repeatedly restart it against a known-incompatible ledger. Once the migration
and branch evidence are green:

1. run a sealed aggregate-only persistent-local preflight;
2. classify every blocker without row identifiers or PII;
3. perform any approved remediation in a separate data task;
4. run the guarded local migration rehearsal;
5. resume the backend only after ledger/schema compatibility passes;
6. verify backend, proxy, public, authentication, and admin boundaries; and
7. record the required manual UI verification.

Switching back to a commit that expects an older schema is blocked until a
separately reviewed compatibility or recovery plan exists. Never automatically
downgrade the persistent-local database. The guarded wrapper reports schema
status and refuses backend resume when repository and ledger compatibility
cannot be proven.

## Canonical Compose use

- Prefer `scripts/dev-compose.sh preflight`, `config`, `start`, `status`,
  `logs`, and `stop` for the normal local stack.
- Do not create a second, vaguely named Compose project merely to bypass a
  fault in the canonical stack.
- An additional Compose environment is allowed only when the task explicitly
  requires isolation and defines its project name, ports, network, volumes,
  database, object-storage bucket, lifecycle, and cleanup policy.
- Treat creation of such an environment as a separate environment task, not as
  an implicit part of an application change.
- Do not copy CI cleanup commands into a local troubleshooting session without
  first proving that every affected resource belongs to an ephemeral test run.

## Data lifetime

The canonical development database, MinIO bucket, Redis state, and named
volumes are persistent local resources. Stopping the stack does not authorize
deleting them.

CI creates an isolated project and uses `down --volumes` for data that it
created for that run. That destructive cleanup is a CI lifecycle guarantee,
not a general local recovery procedure. Never delete an unidentified database,
bucket, volume, or network as a verification shortcut.

## Environment variables

| Variable class | Current source and timing |
| --- | --- |
| Frontend build-time | `frontend/.env.example` documents `VITE_*` values consumed by Vite, including API, site, timezone, and Umami settings |
| Backend runtime | `backend/.env.example` documents database, authentication, MinIO, Redis, and bootstrap settings loaded by the backend |
| Compose interpolation | `docker/.env.example` documents local Compose identities, ports, credentials, database, bucket, network, and volume names; `scripts/dev-compose.sh` defaults to `docker/.env` and supports `PASTEXAM_DEV_COMPOSE_ENV_FILE` |
| Production external configuration | `docker/docker-compose.prod.yml` reads the Compose environment and mounts separate backend runtime and migrator environment files under the production configuration path |

Do not place secrets in documentation, commits, command output, or frontend
build-time variables. A `VITE_*` value is delivered to the browser and is not
a secret.

## Scope boundary

This document does not define:

- Docker recovery or destructive cleanup procedures;
- migration commands or schema-recovery decisions;
- production candidate activation, backup, rollback, or deployment;
- database backup and restore.

Use [Migration safety](../migration-safety.md) and
[Production deployment](../production-deployment.md) for those decisions.

## Test evidence

- `.github/workflows/test.yml` creates and tears down the isolated CI stack.
- `backend/tests/conftest.py` guards destructive backend tests with explicit
  isolated database requirements.
- `scripts/dev-compose.sh` enforces the canonical local identities before
  Compose operations.

## Required follow-up

If the project later introduces a dedicated test Compose definition or a
supported production-like mode, document its complete identity and lifecycle
here before treating it as canonical.
