# Validation policy

Status: Active

Source of truth for: Risk-proportional local verification, retry limits, and CI completion

Applies to: All repository changes and completion reports

Related documents:
- [Local development environment](local-environment.md)
- [Code organization](code-organization.md)
- [Migration safety](../migration-safety.md)
- [Production deployment](../production-deployment.md)

## Verification principles

Validation is targeted first, proportional to risk, and expanded only when
evidence justifies it. Decide what a check can prove before running it. Stop
when the relevant checks pass and residual risk is acceptably low.

Documentation-only changes do not require application builds, browser
automation, Docker, or database tests. A small UI change does not automatically
authorize backend coverage, multi-browser E2E, image builds, or migration
integration.

## Static preflight

Before choosing runtime checks:

1. inspect `git status` and the diff scope;
2. identify changed contracts and consumers;
3. check syntax, formatting, lint, imports, types, and paths only where relevant;
4. confirm that generated files, secrets, and unrelated changes are absent;
5. assign a risk level and a finite verification budget.

## Risk levels

This policy elaborates the repository-wide levels in `AGENTS.md`; it does not
define a second scale.

| Level | Typical scope | Expected verification |
| --- | --- | --- |
| Level 1 — localized/low risk | Documentation, isolated styles, local UI copy, focused helper | Diff plus the narrowest static or unit-level check |
| Level 2 — behavioral/cross-layer | Shared frontend component, API contract, service behavior, authorization | Affected tests and relevant lint/type/build checks |
| Level 3 — high risk/release | Lifecycle, persistent data, migration, storage, authentication infrastructure, deployment | Focused safety tests first, then justified integration, build, Docker, migration, or E2E checks |

## Targeted command matrix

Run commands from the indicated package directory. Replace examples with the
smallest changed path or test node.

| Target | One-shot command | Use |
| --- | --- | --- |
| Frontend file lint | `pnpm exec eslint src/path/File.vue` | Changed Vue/JS/TS files |
| Frontend Vitest file | `pnpm exec vitest run src/path/file.test.js` | Focused frontend behavior |
| Frontend Vitest test name | `pnpm exec vitest run src/path/file.test.js -t "test name"` | One affected behavior |
| Playwright spec/project | `pnpm exec playwright test e2e/spec.ts --project=chromium` | A justified browser scenario |
| Frontend production build | `pnpm build` | Bundling, shared configuration, or release-sensitive frontend changes |
| Backend path lint | `uv run ruff check app/path.py tests/path.py` | Changed Python paths |
| Backend pytest file | `uv run pytest tests/path.py` | Focused backend behavior |
| Backend pytest node | `uv run pytest tests/path.py::test_name` | One affected behavior |

`pnpm test` starts Vitest watch mode. Agents performing a one-shot check must
use `pnpm exec vitest run ...` or the repository's non-watch coverage command
when the broader scope is justified.

Backend tests, including files named `unit`, are subject to the global guard in
`backend/tests/conftest.py`. Do not claim that the complete backend unit suite
is database-free. Tests must use an explicitly isolated database URL, approved
test identity markers, and a target distinct from runtime data.

### Current CI implementation

The workflows under `.github/workflows/` run scope detection, frontend and
backend lint, backend tests, frontend unit coverage, browser E2E, image builds,
and deployment gates according to the branch and changed paths. CI may
legitimately run more than the minimum local checks.

## Verification budget

Before running checks, record:

- the directly relevant checks;
- the maximum browser scenarios and projects;
- whether Docker is necessary;
- whether a production build is necessary;
- checks explicitly excluded as disproportionate or unsafe.

Browser or screenshot validation normally has at most two attempts per
scenario: the initial attempt and one targeted retry after a concrete change.

## Failure classification

Classify a failure before acting:

- current-change defect;
- existing failure;
- infrastructure failure;
- flaky test;
- missing environment;
- product-decision conflict;
- unavailable tool.

The classification determines whether to correct the change, perform one
bounded retry, stop for a decision, or report the limitation.

## Retry and stop rules

- Do not rerun an unchanged command without a new hypothesis or modification.
- A failed check receives at most one evidence-based correction and retry at
  the same scope before reassessment.
- Stop browser work after the initial attempt and one targeted retry for the
  same scenario.
- Stop when required services, credentials, or isolated data are unavailable;
  do not compensate by running a broader suite.
- Do not run full backend coverage, three-browser E2E, Docker image builds, or
  migration integration for an ordinary small frontend task.
- Do not create an unexplained second Compose project for verification.
- Never skip a test, delete it, or weaken an assertion merely to obtain a green
  result.

## CI completion policy

When the task requires a CI result, a queued or in-progress run is not a final
result. Prefer a blocking, low-frequency wait:

```bash
gh run watch <run-id> --exit-status
```

After a failure, read the failed log and classify it. A failed-job rerun is
allowed once only when there is concrete transient or flaky evidence. If the
same signature fails again, move to targeted diagnosis. Stop for user direction
when resolution requires broader scope, workflow policy, product decisions,
permissions, secrets, or destructive operations.

## Verification reporting

Report checks under:

- **Passed**
- **Failed**
- **Skipped**
- **Unavailable**
- **Not applicable**

For each material check, state what it proved and what it did not prove. Never
claim build, test, migration, browser, or deployment success without evidence.

## Test evidence

- `frontend/package.json` defines the current frontend scripts.
- `frontend/playwright.config.js` defines browser projects, retries, and
  artifacts.
- `backend/pyproject.toml` defines backend test and lint dependencies.
- `backend/tests/conftest.py` implements the isolated-database guard.
- `.github/workflows/main.yml`, `lint.yml`, `test.yml`, and `build.yml` define
  the current CI gates.

## Required follow-up

Update command examples when package scripts or CI entry points change. Do not
add a broader default merely because one task required a higher risk level.
