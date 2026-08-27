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

For local PostgreSQL-backed tests, use
`scripts/run-isolated-backend-tests.py` with exact canonical PostgreSQL and
backend container IDs. The runner creates one direct-`docker run` PostgreSQL
15 container with loopback-only port exposure and tmpfs data, applies current
migrations, passes only an argument vector to `python -m pytest`, and removes
its exact generated resource on success, failure, or interruption. It must
prove canonical identity, restart counts, and the sealed baseline before and
after the run. Do not substitute Compose, a permanent test service, or a
canonical database.

When the subject source is a clean external Git worktree, pass
`--canonical-authority-root` with the absolute path of the clean registered
`main` worktree that owns `pastexam-dev`. The runner continues to derive its
migration graph, Python environment path, migrations, and pytest targets from
the subject checkout. Only canonical pre/post `schema-status` uses the
authority checkout's unchanged `scripts/dev-compose.sh`, so its Compose
working-directory guard and ignored environment remain authoritative. An
unrelated repository, copied or unregistered checkout, non-`main` worktree,
dirty authority checkout, ambiguous path, or missing wrapper fails closed.

On a schema-changing branch, the canonical persistent ledger may remain at a
reviewed ancestor while the ephemeral database migrates to the repository
head. Pass that baseline explicitly with
`--canonical-expected-ledger <revision>`. The runner accepts it only when the
revision has a reviewed manifest, is an Alembic ancestor of the single current
head, and is supported by the sealed audit. This option affects only canonical
pre/post snapshots: the ephemeral target is always the non-overridable current
repository head, and exact canonical snapshot equality remains mandatory.

### Current CI implementation

The workflows under `.github/workflows/` run scope detection, frontend and
backend lint, backend tests, frontend unit coverage, browser E2E, image builds,
and deployment gates according to the branch and changed paths. CI may
legitimately run more than the minimum local checks.

Normal independent development starts from fresh `main`; coordination is used
only when the task or milestone explicitly requires the optional coordination
branch defined by canonical project governance. `main` pull requests use Full
CI by default, except when the centralized classifier conclusively identifies
every changed path as docs-only. Main pushes always use Full CI. Governance-path
source pushes and pull requests to the exact configured coordination branch use
Full. Protected Case-B Source, pull-request, and final postmerge workflows also
use Full; ordinary protected coordination receives no Equivalent eligibility.
All uncertainty retains the fail-closed Full fallback.

Protected coordination has one narrow `coordination-start` mode for the exact
App-created bootstrap commit. It requires independent machine proof of the
current-main parent, governance-only tree identity, trusted protected-main
lifecycle artifact, lifecycle-App origin, unchanged exact integration ruleset,
and fresh exact-parent Full evidence. Every uncertainty falls back to Full.
Active integration pull requests and feature pushes, Case-B reconciliation and
postmerge, return, closeout, and stale or invalid authority remain Full-only or
blocked.
Ordinary main does not run or require a coordination-specific App gate. See
[ADR-0013](../decisions/0013-simplified-protected-coordination.md) and the
[operator runbook](../runbooks/coordination.md).

The stable `integration/**` workflow family only starts workflow evaluation. It
does not approve a base or grant Equivalent eligibility; the classifier and PR
base policy resolve the exact configured coordination branch at runtime.

Once an immutable main candidate and its pull request are genuinely ready, push
the exact candidate and promptly open the ready pull request to `main` rather
than waiting merely for candidate Source CI to finish. Candidate Source and PR
workflows are independent evidence and may overlap when selected; all exact
results required by the repository must still be terminal successful before
merge. Source success is an evidence requirement for merge, not a prerequisite
for opening an otherwise ready pull request. The main pull request uses Full CI
unless its entire change is conclusively docs-only. Follow the detailed
[pull request rules](../../CONTRIBUTING.md#pull-requests) and the narrower
[ADR-0014 protected Case-B Full policy](../decisions/0014-protected-coordination-case-b-full-policy.md)
where applicable. ADR-0006 remains historical evidence for the older shared-
governance model.
After an authorized main merge, semantic-release is callable only from the
successful exact-main-SHA CI run after `CI Gate`; it remains version authority
but does not enable or perform production deployment. Branch-authority transfer
and production governance require separate post-main decisions.

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

A workflow rerun request becomes an accepted logical retry only after GitHub
accepts the request and the run's `run_attempt` increments. A transport-level
502, 503, or 504 with an unchanged attempt is an unavailable control-plane
operation, not new CI evidence. Before any separately authorized resubmission,
re-read the run attempt to avoid creating duplicate retries. A future
repository-owned rerun helper may use only a small bounded transport retry with
backoff and this attempt recheck; task-specific retry limits remain authority.

## Verification reporting

Report checks under:

- **Passed**
- **Failed**
- **Skipped by instruction**
- **Unavailable**
- **Not applicable**

For each material check, state what it proved and what it did not prove. Never
claim build, test, migration, browser, or deployment success without evidence.
`Failed` is an executed check that found a defect. `Skipped by instruction`
records an explicit scope restriction. `Unavailable` records a missing safe
environment, permission, or dependency and does not cancel a requirement.
`Not applicable` means there is no causal relationship to the task. A required
item in any state other than `Passed` keeps its completion layer non-green.

For the bounded database audit runner, `complete` additionally requires the
expected environment, ledger, targeted schema and enum gates; a single
non-interactive input stream; a confirmed read-only transaction; an explicit
`ROLLBACK`; the completion sentinel; approved aggregate-only output; and
mutual-exclusivity and conservation checks. A timeout, lock wait, SQL/type
error, truncated transport, missing rollback/sentinel, unknown output label, or
partial result is an audit error or incomplete transport, never successful
evidence. The runner performs no implicit retry.

## Backend runtime evidence

Keep three evidence layers distinct:

- Repository evidence proves source, focused tests, and exact-SHA CI.
- Environment evidence proves the current bind-mounted source, process child,
  listener, direct/proxy health, PostgreSQL identity, and sealed baseline.
- Merge evidence proves the integration merge commit and its own CI.

Use `scripts/check-backend-runtime.py` for read-only source/runtime/service/data
classification. An affected backend implementation batch requires one final
clean-start acceptance after its final local commits. Restart is never implied
by running the checker and requires the explicit authority and one-restart
limit in [Backend runtime recovery](backend-runtime-recovery.md).

## Test evidence

- `frontend/package.json` defines the current frontend scripts.
- `frontend/playwright.config.ts` defines browser projects, retries, and
  artifacts.
- `backend/pyproject.toml` defines backend test and lint dependencies.
- `backend/tests/conftest.py` implements the isolated-database guard.
- `.github/workflows/main.yml`, `lint.yml`, `test.yml`, and `build.yml` define
  the current CI gates.

## Required follow-up

Update command examples when package scripts or CI entry points change. Do not
add a broader default merely because one task required a higher risk level.
