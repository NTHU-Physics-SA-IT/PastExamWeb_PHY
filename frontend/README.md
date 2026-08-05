# PastExamWeb_PHY frontend

## Overview

The frontend is a Vue application built with Vite. It uses PrimeVue and
PrimeFlex for UI foundations, Vue Router for navigation, Axios for HTTP,
Tailwind CSS integration, and Vitest and Playwright for tests. Exact dependency
versions are defined by `package.json` and `pnpm-lock.yaml`.

## Source layout

- `src/views/`: route-level screens and feature coordinators.
- `src/components/`: reusable presentation and interaction components.
- `src/components/admin/`: admin-specific components.
- `src/composables/`: reusable stateful Vue behavior.
- `src/utils/`: shared formatting, preferences, authentication, and other
  helpers.
- `src/api/services/`: endpoint wrappers built on the shared API client.
- `src/constants/`: shared static mappings and options.
- `src/router/`: routes and navigation guards.
- `tests/unit/`: Vitest component and utility tests.
- `tests/e2e/`: Playwright setup, fixtures, and browser scenarios.

See [Code organization](../docs/development/code-organization.md) for current
ownership boundaries and intended direction.

## Running the frontend

From the repository root, the canonical complete local environment is:

```bash
scripts/dev-compose.sh start
```

For frontend-only development, install the locked dependencies and start Vite
from `frontend/`:

```bash
pnpm install --frozen-lockfile
pnpm dev
```

This standalone server does not prepare the backend, PostgreSQL, Redis, or
MinIO. Use the [local development environment](../docs/development/local-environment.md)
for the complete stack and environment boundaries.

## Validation

The commonly used package scripts are:

- `pnpm lint`: lint frontend source and tests.
- `pnpm test`: start Vitest in watch mode.
- `pnpm test:coverage`: run the frontend unit suite once with coverage.
- `pnpm test:e2e`: run Playwright; this depends on a prepared full environment.
- `pnpm build`: produce the frontend build.

Use the targeted one-shot Vitest and Playwright forms in the
[validation policy](../docs/development/validation.md) instead of starting a
broader or watch-mode check unnecessarily.

## UI and Domain contracts

Follow the [UI guidelines](../docs/ui/guidelines.md) for presentation,
responsive behavior, themes, and user-visible labels. Domain meanings and
allowed actions come from the [Domain contracts](../docs/domain/README.md);
frontend status copy must not redefine them.

Hiding or disabling a control improves usability but is not an authorization
boundary. The backend must enforce permissions and state transitions.

## Related documentation

- [Documentation index](../docs/README.md)
- [Local development environment](../docs/development/local-environment.md)
- [Code organization](../docs/development/code-organization.md)
- [Validation policy](../docs/development/validation.md)
- [UI guidelines](../docs/ui/guidelines.md)
- [Domain contracts](../docs/domain/README.md)
