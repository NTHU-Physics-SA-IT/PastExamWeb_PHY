# PastExamWeb_PHY API

## Overview

The backend is a FastAPI application using SQLModel and asynchronous SQLAlchemy
access to PostgreSQL. Redis supports runtime features, MinIO stores archive
objects, and Alembic manages schema migrations. Uvicorn serves the application.
Exact dependency versions are defined by `pyproject.toml` and `uv.lock`.

## Application layout

- `app/main.py`: FastAPI application creation, router registration, health
  endpoint, and startup readiness.
- `app/api/`: top-level API router wiring.
- `app/api/services/`: FastAPI routers and many endpoint implementations.
- `app/services/`: reusable application and Domain operations.
- `app/models/`: SQLModel tables, request schemas, and response schemas.
- `app/utils/`: authentication, storage, and other cross-cutting helpers.
- `app/db/`: sessions, startup checks, test guards, and migration safety.
- `alembic/`: migration environment and revision graph.
- `tests/`: API, unit, database, utility, and migration/integration tests.

There is currently no repository layer. Routes, authorization, business rules,
side effects, and commits are still mixed in parts of the application. This is
a documented current limitation, not a reason to invent a new layer during an
unrelated change. Follow [Code organization](../docs/development/code-organization.md)
for the intended responsibility direction.

## Running locally

From the repository root, start the canonical complete local stack with:

```bash
scripts/dev-compose.sh start
```

For focused backend development, the API can be started from `backend/`:

```bash
uv sync --locked
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Standalone startup still requires valid environment configuration and
available PostgreSQL, Redis, and MinIO services. See the
[local development environment](../docs/development/local-environment.md)
instead of creating a second Compose setup.

## Validation

From `backend/`, the minimal tooling entry points are:

```bash
uv run ruff check app tests
uv run pytest tests/path.py
```

Replace the pytest path with the smallest relevant file or test node. Backend
tests are subject to the isolated test database guard in `tests/conftest.py`;
even files named `unit` must not be assumed to be database-free.

Use the [validation policy](../docs/development/validation.md) for targeted
commands, database isolation requirements, retry limits, and CI completion.

## Database migrations

Schema changes use Alembic and must add a reviewed migration without rewriting
an applied revision. Migration generation, preflight, upgrade, bootstrap, and
recovery rules are maintained only in
[Migration safety](../docs/migration-safety.md).

## Domain contracts

API and service behavior must follow the
[Domain contracts](../docs/domain/README.md). Behavior changes require focused
tests and corresponding contract updates. The backend is the final enforcement
boundary for authorization and state transitions.

## Production

Production candidate, backup, configuration, activation, and rollback
procedures are defined in
[Production deployment safety](../docs/production-deployment.md). They are not
development commands.

## Related documentation

- [Documentation index](../docs/README.md)
- [Local development environment](../docs/development/local-environment.md)
- [Code organization](../docs/development/code-organization.md)
- [Validation policy](../docs/development/validation.md)
- [Domain contracts](../docs/domain/README.md)
- [Migration safety](../docs/migration-safety.md)
- [Production deployment safety](../docs/production-deployment.md)
