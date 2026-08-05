# Backend runtime recovery

Status: Active

Source of truth for: Read-only backend runtime classification, controlled
restart eligibility, and final clean-start acceptance

Applies to: The canonical local bind-mounted FastAPI backend

Related documents:
- [Local development environment](local-environment.md)
- [Validation policy](validation.md)
- [Feature development workflow](feature-development-workflow.md)

## Read-only diagnosis

Run the repository checker with exact container IDs and every relevant changed
backend source file:

```bash
python3 scripts/check-backend-runtime.py \
  --backend-container-id <exact-backend-id> \
  --postgres-container-id <exact-postgres-id> \
  --source-file backend/app/path.py \
  --output json
```

The checker compares Git, host, and bind-mounted source; inspects the existing
Uvicorn/WatchFiles supervisor, application child, listener, Docker health,
direct and proxy health; and verifies the exact PostgreSQL identity and sealed
baseline. It is read-only and does not import application modules, start the
application, run migrations, signal a process, or perform container lifecycle.

Its classifications and exit codes are:

| Classification | Exit |
| --- | ---: |
| `healthy` | 0 |
| `source_mismatch` | 10 |
| `current_code_startup_failure` | 11 |
| `reload_only_failure` | 12 |
| `healthcheck_only_failure` | 13 |
| `postgres_environment_incident` | 14 |
| `inconclusive` | 15 |

An invalid invocation exits 2. Missing or contradictory evidence is
`inconclusive`, not a guessed diagnosis.

## Controlled restart eligibility

A restart requires a separately authorized operational task. Before that task
may restart anything, prove all of the following:

- the exact backend container identity;
- the exact PostgreSQL identity is healthy and unchanged;
- the expected branch and clean HEAD;
- host, container, and HEAD source equality;
- no-write syntax checks and explicitly selected safe narrow imports;
- the reload supervisor exists but its application child does not;
- bounded logs show a transient reload-child failure;
- no deterministic current-code startup failure, OOM, restart loop, hang, or
  database incident; and
- the sealed baseline is complete with explicit rollback.

Only the following exact action may then be authorized:

```text
docker restart <verified-exact-backend-container-id>
```

The operation is limited to one restart. Do not resolve by service name, use
Compose, recreate the container, operate PostgreSQL or dependencies, or send a
second signal or restart.

## Restart and clean-start acceptance

Use a bounded wait and require:

- unchanged backend ID, running and healthy;
- one live application child started after the restart;
- the expected application listener;
- no terminal startup traceback or restart loop;
- the configured internal `/health` probe succeeds;
- canonical Nginx `/api/health` succeeds;
- current bind-mounted source still matches HEAD;
- unchanged PostgreSQL ID, health, and restart count;
- unchanged Alembic head and sealed aggregate checksums; and
- explicit rollback remains true.

Every affected backend implementation batch requires one final clean-start
acceptance after its final local commits. Hot reload is development feedback,
not final runtime authority. If the task does not explicitly authorize a
restart, stop and request that authority. If the one restart fails, do not try
again; classify the result as corrective implementation or further operational
diagnosis.

Stage 5A does not introduce a permanent no-reload validation backend. That
environment separation remains a Stage 6 concern.
