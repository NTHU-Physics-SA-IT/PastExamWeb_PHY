# Contributing

## Before you start

Use these sources instead of duplicating their rules here:

- [Repository Agent and automation rules](AGENTS.md)
- [Documentation index and authority map](docs/README.md)
- [Local development environment](docs/development/local-environment.md)
- [Validation policy](docs/development/validation.md)

## Branches and commits

- Develop features and fixes on a branch other than `main`.
- Keep each commit focused on one purpose and avoid unrelated changes.
- Use a concise Conventional Commit message that describes the outcome.
- Preserve existing work and inspect the exact staged diff before committing.

## Pull requests

Not every local or exploratory change must become a pull request. When opening
a formal pull request, target `main`; the `Validate PR base branch` workflow
rejects other bases, and there is no `dev` integration branch.

Before merge, the pushed final commit must reach a terminal successful CI
result for the checks selected by the repository workflows. A pull request
description should state:

- the purpose and scope of the change;
- verification performed;
- checks not run and why;
- Domain impact;
- migration impact; and
- remaining risk.

## Domain and documentation changes

Changes to entity relationships, states, authorization, public visibility,
notifications, transactions, or storage side effects must update the affected
[Domain contract](docs/domain/README.md) and focused tests in the same change.
A behavior-preserving internal refactor does not require rewriting the
contract, but its existing contract tests must remain green.

If code, tests, and Domain documents conflict, report the conflict rather than
choosing one as the intended behavior.

## Validation

Start with targeted, risk-proportional checks and wait for required CI to reach
a terminal state. The command matrix, retry budget, stop rules, and reporting
categories are defined in the [validation policy](docs/development/validation.md).

## Migrations

Persisted model or schema changes require a safe Alembic migration. Never
rewrite an applied revision. Follow [migration safety](docs/migration-safety.md)
for generation, review, preflight, upgrade, and recovery boundaries.

## Production candidates

Push CI may build images for validation, but image publication is limited to
`main`. Production candidate preparation also requires its repository gate and
the protected `production` environment. A prepared candidate is immutable and
does not activate production or switch traffic automatically.

Candidate evidence must be reviewed before a separately approved activation.
Follow [production deployment safety](docs/production-deployment.md) for the
release gate, backup, configuration, activation, and rollback boundaries.
