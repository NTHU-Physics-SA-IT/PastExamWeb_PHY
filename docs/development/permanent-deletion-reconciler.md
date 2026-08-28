# Permanent-deletion reconciler

Status: Active

Source of truth for: Running the dedicated Stage 5F-E reconciler process

Related documents:

- [Permanent deletion](../domain/permanent-deletion.md)
- [Local environment](local-environment.md)
- [Production deployment](../production-deployment.md)

## Safety boundary

The process handles only existing PostgreSQL permanent-deletion operations. It
does not scan Trash rows or MinIO, fabricate work, reset retry budgets,
force-complete, or process `MANUAL_REVIEW` or `COMPLETED` destructively. The
existing process-one saga remains the sole claim, lease, exact-Version-ID,
retry, verification, and finalization authority.

The worker is not registered with FastAPI startup and no tracked Compose service
starts it by default. Repository implementation does not authorize running it
against the canonical local database or production. Production activation,
configuration, supervision, deployment, and rollback require a separate
Owner-authorized operations task.

## Entrypoint

Run one bounded pass from the backend environment:

```bash
python -m app.maintenance.permanent_deletion_reconciler --once
```

Run the long-lived process explicitly:

```bash
python -m app.maintenance.permanent_deletion_reconciler \
  --poll-interval-seconds 30 \
  --operation-batch-limit 25 \
  --purge-batch-limit 25
```

All values are validated as positive and bounded. A pass first processes its
deterministically ordered due-operation batch and then independently purges a
bounded batch of `COMPLETED` minimal-audit ledgers whose existing 180-day
deadline is due. It sleeps only between passes. SIGINT or SIGTERM prevents a
new pass after the current pass reaches a safe boundary; crashes recover through
the existing PostgreSQL lease expiry rather than a force-release.

Logs contain aggregate counts and sanitized exception classes only. They do not
emit credentials, object keys, Version IDs, or user descriptive data.
