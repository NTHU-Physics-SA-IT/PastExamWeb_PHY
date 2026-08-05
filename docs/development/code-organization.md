# Code organization

Status: Active

Source of truth for: Code ownership boundaries and project-pattern consistency

Applies to: Frontend, backend, API, storage, and test changes

Related documents:
- [UI guidelines](../ui/guidelines.md)
- [Domain contracts](../domain/README.md)
- [Validation policy](validation.md)
- [Migration safety](../migration-safety.md)

## Current repository organization

### Frontend

- `frontend/src/views/` owns route-level screens and currently contains some
  large feature coordinators such as `Archive.vue` and `Admin.vue`.
- `frontend/src/components/` owns reusable presentation and interaction
  components; `frontend/src/components/admin/` holds admin-specific components.
- `frontend/src/composables/` owns reusable Vue stateful behavior.
- `frontend/src/utils/` owns shared formatting, normalization, storage,
  authentication, and preference helpers.
- `frontend/src/api/` and `frontend/src/api/services/` own HTTP/WebSocket client
  setup and endpoint wrappers.
- `frontend/src/constants/` owns shared static mappings and options.
- `frontend/src/router/` owns route definitions and route guards.
- A small amount of shared module-level state exists in modules such as the API
  client and global toast utilities; it is not a general-purpose store layer.

### Backend

- `backend/app/api/services/` contains FastAPI routers and many endpoint
  implementations.
- `backend/app/services/` and selected helpers under
  `backend/app/api/services/` contain reusable domain/application operations.
- `backend/app/models/models.py` contains most SQLModel table models, request
  schemas, and response schemas.
- `backend/app/utils/` contains authentication and other cross-cutting helpers.
- `backend/app/db/` owns sessions, startup/schema checks, and migration safety.
- `backend/alembic/` owns the migration graph.
- MinIO operations are performed through storage helpers used by archive and
  lifecycle services.
- `backend/tests/api/`, `backend/tests/unit/`, and
  `backend/tests/integration/` contain API behavior, focused logic, and
  database/migration tests.

### Current implementation

There is no repository layer. Models and schemas are concentrated in one large
module. Some endpoint functions perform querying, authorization, business
rules, side effects, and commits together. Transaction ownership is not yet
consistent: some operations commit in the route, while multi-step archive
operations can commit at more than one point.

These are current facts, not a requirement to preserve the structure forever.

## Pattern consistency

- Search for the same or adjacent responsibility before adding code.
- Do not introduce a second formatter, normalizer, status map, permission rule,
  lifecycle resolver, notification builder, visibility rule, breakpoint, or
  API error mapper when an established implementation can be extended safely.
- Before adding an abstraction, explain why the closest existing abstraction
  cannot be extended without changing unrelated behavior.
- Before changing a shared abstraction, identify its known consumers and their
  contract assumptions.
- If parallel implementations are discovered outside the requested outcome,
  record the risk; do not turn a focused change into an unrequested repository-
  wide consolidation.

## Frontend responsibility

The frontend owns presentation, route behavior, client-side interaction state,
and recoverable loading, empty, error, timeout, and permission-denied views. It
may hide unavailable controls for usability, but it cannot be the only
authorization or business-invariant boundary.

Endpoint wrappers and the shared API client own transport concerns. Domain
status meaning comes from [Domain contracts](../domain/README.md), while
presentation rules come from [UI guidelines](../ui/guidelines.md).

## Backend responsibility

### Intended direction

- Routers map requests, dependencies, and responses.
- Application/domain services own business operations and transaction
  orchestration.
- Shared helpers expose their side effects and do not commit unexpectedly.
- The backend enforces authorization and invariants regardless of frontend UI.
- A repository layer is introduced only if it solves a demonstrated ownership
  problem; it is not required for architectural symmetry.

### Known gap

The current router/service modules do not consistently follow this separation.
For example, archive review, trash, report, and course modules include inline
permission checks and direct commits alongside business logic. Consolidation
requires characterization tests and must not be performed opportunistically.

## Transaction ownership

One complete business operation should have one visible transaction owner.
Helpers must document whether they only mutate/flush or whether they commit.
Callers must not assume PostgreSQL and MinIO share an atomic transaction.

Archive upload, review, deletion, restore, report, notification, and object
cleanup behavior is governed by
[Notifications and side effects](../domain/notifications-and-side-effects.md).

## Contract maintenance

- When responsibility moves but observable behavior remains unchanged, update
  this document if the ownership map changes.
- When entity relationships, states, authorization, visibility, notifications,
  or side effects change, update the affected `docs/domain/` contract and
  focused tests in the same change.
- When persisted schema or migration behavior changes, update
  [Migration safety](../migration-safety.md) and any affected Domain contract.
- Do not promote observed behavior to an intended invariant when code, tests,
  and product decisions disagree.

## Test evidence

Current responsibility boundaries are exercised by API tests under
`backend/tests/api/`, Vitest unit and component evidence under
`frontend/tests/unit/`, Playwright browser and journey evidence under
`frontend/tests/e2e/`, and migration tests under
`backend/tests/integration/`. The required test levels are selected through
the [Feature development workflow](feature-development-workflow.md) and
[Validation policy](validation.md); this location map does not require every
frontend change to add both unit and E2E coverage. Those tests are evidence for
behavior, not proof that transaction ownership is already consolidated.

## Required follow-up

Future lifecycle consolidation should first add focused characterization tests,
then move one vertical operation at a time behind an explicit transaction and
authorization boundary.
