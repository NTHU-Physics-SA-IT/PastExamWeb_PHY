# Feature development workflow

Status: Active

Source of truth for: Feature and behavior-change planning, implementation, and
test-design workflow

Applies to: New features, product-behavior changes, Domain bug fixes,
cross-layer changes, and high-risk lifecycle, storage, or notification changes

Related documents:
- [Repository working agreement](../../AGENTS.md)
- [Code organization](code-organization.md)
- [Validation policy](validation.md)
- [UI guidelines](../ui/guidelines.md)
- [Domain contracts](../domain/README.md)
- [Migration safety](../migration-safety.md)
- [Production deployment safety](../production-deployment.md)
- [Contributor merge strategy](../../CONTRIBUTING.md#merge-strategy)

## Authority boundary

This document owns the procedure for planning and implementing feature and
behavior work. It is not a product specification, validation command matrix,
UI design system, migration manual, production runbook, or Skill metadata
source.

Concrete product behavior belongs in the affected Domain contracts. Code
ownership belongs in [Code organization](code-organization.md), validation
scope and retries belong in [Validation policy](validation.md), presentation
decisions belong in [UI guidelines](../ui/guidelines.md), and migration and
production operations belong in their dedicated safety documents. The
repository working agreement remains the mandatory Agent constraint.

## Task classification

Classify scope before planning checks or changing application code. Bug fixes
and refactors add the safeguards below to the applicable scope class.

### Class 0: Non-behavioral

Examples include a typo, link, formatting change, document reorganization, or
a very small presentation correction already shown not to change behavior.

- Confirm that behavior and Domain impact are absent.
- Keep the diff and verification minimal.
- A Feature contract is not required.

Uncertain behavior, security, lifecycle, persistence, or cross-layer impact
cannot be classified as Class 0.

### Class 1: Localized behavior

Examples include one-page interaction, localized UI behavior, a small
adjustment to an existing API, or a bounded bug fix.

- Record a concise statement of the intended behavior and exclusions.
- Search the nearest similar implementation.
- Use a focused impact and test matrix.
- Apply bounded, risk-proportional verification.

### Class 2: Feature, cross-layer, or Domain

Examples include a new feature or API; a new state, transition, permission,
notification, or visibility rule; trash, restore, or permanent-delete
behavior; PostgreSQL, MinIO, Redis, WebSocket, transaction, or migration side
effects; and multi-layer frontend/backend work.

Before application changes, complete:

1. the Feature contract;
2. the product-decision gate;
3. the existing-implementation search;
4. the impact map;
5. responsibility placement;
6. the test matrix; and
7. implementation slices with a red-green and verification plan.

### Bug fix

- Identify the canonical source of expected behavior before treating observed
  code as correct.
- Establish the smallest focused failing evidence before application changes.
- Prefer an automated failing test when it can faithfully and stably reproduce
  the contract deviation. Confirm that it fails because of that deviation,
  rather than an environment, fixture, selector, or stale-bundle problem.
- Make the smallest repair and add justified neighboring regressions.
- Do not write an observed bug back into a Domain contract as the intended
  behavior.

A Domain or cross-layer bug fix also uses the Class 2 pre-implementation gate.

#### Browser or platform-specific failing evidence

A precise, reproducible browser or manual scenario may serve as red evidence
only when all of these conditions are met:

1. the problem depends on a browser, operating system, device, font, rendering
   engine, or real layout environment;
2. the existing unit, component, Playwright, or WebKit coverage cannot
   faithfully and stably reproduce it;
3. the plan states the concrete reason automation cannot represent the
   failure;
4. the scenario has exact, repeatable reproduction conditions;
5. the test matrix marks the automated case `Not applicable` or `Deferred with
   reason`; and
6. manual evidence is not replacing a reasonably automatable backend or Domain
   contract test.

Record the reproduction context needed for another person or Agent to repeat
the failure:

- browser and version;
- operating system and device context;
- CSS viewport, device pixel ratio, and browser zoom;
- font scale and font-loading state;
- theme and relevant UI state;
- route and commit or bundle identity;
- reproduction steps;
- expected and actual results;
- at least one appropriate screenshot, recording, or computed-style capture;
  and
- a neighboring browser or desktop comparison.

The evidence does not need a separate screenshot for every recorded field, but
it must be sufficient to reproduce the failure. After the repair, add or update
the nearest stable automated regression when one can faithfully protect the
same behavior. If the problem still cannot be automated, rerun the same browser
scenario as completion evidence and execute the feasible neighboring automated
regressions.

Do not create source-string assertions, CSS-text-presence assertions,
always-true assertions, or placeholder tests unrelated to the observed visual
failure. Manual evidence is not a general reason to omit test design.

When they can reasonably be represented by an automated test, authorization,
state transitions, public-visibility queries, database persistence,
transaction or rollback behavior, notification or deduplication,
concurrency, trash or restore, storage-call semantics, migration or schema
behavior, and API business-error semantics require focused automated
evidence. A missing required environment is `Unavailable`, not `Not
applicable`; stop or prepare the safe environment instead of substituting
manual evidence.

### Refactor

- State which observable behavior must remain unchanged.
- Protect it with existing tests and any necessary focused characterization
  evidence.
- Do not update a product contract merely because code moved.
- If the work requires a behavior change, stop, resolve any product decision,
  and reclassify the affected work as Class 1 or Class 2.

## Feature contract

Complete this contract before application changes for Class 2 work. Answer
only fields relevant to the feature; write `Not applicable` instead of
inventing behavior.

### Contract fields

- User goal
- Actors
- Permissions
- Preconditions
- Starting states
- Allowed transitions
- Invalid transitions
- Same-target retry or idempotency
- Data mutations
- Data that must not change
- Notifications
- Public visibility
- Trash, restore, and permanent-delete effects
- Storage or external side effects
- Audit or statistics effects
- Failure and rollback semantics
- Concurrency behavior
- User-visible errors
- Compatibility or migration concerns

The resolved product answers must be recorded in the affected Domain
contract, not preserved only in this planning artifact.

## Product-decision gate

Stop and ask the user when any of these are genuinely unresolved:

- permission or public-visibility scope;
- legal state transitions;
- notifications, side effects, or deduplication;
- deletion, retention, restoration, or permanent-delete meaning;
- multiple reasonable user-visible or product outcomes;
- API business semantics that affect users;
- a migration that changes the meaning of existing data;
- an irreversible, production, or destructive choice; or
- conflict between canonical documents.

Do not block on file placement, reuse of an established helper or fixture,
test naming, an internal detail that cannot change product behavior, a choice
already answered uniquely by canonical documentation, or selection of a
bounded validation command. Gather genuinely blocking product questions and
ask them together rather than interrupting for each small detail.

## Existing implementation search

Before application changes, search as applicable for the closest:

- route, service or use case, policy or helper, and model constraint;
- status mapping, authorization rule, notification builder, visibility rule,
  error mapper, and transaction owner;
- frontend API client and component pattern; and
- fixture and focused test.

Record:

- the existing canonical implementation;
- whether it will be reused or extended and why;
- the parallel implementation that must be avoided; and
- the responsibility owner.

Similarity is evidence for reuse analysis, not permission to copy another
implementation.

## Impact map

Mark every layer as `Modify`, `Verify only`, or `Not affected`, with a short
reason. Include neighboring behavior that must be verified even when its files
will not change.

| Layer | Modify | Verify only | Not affected |
| --- | --- | --- | --- |
| Frontend view/component | | | |
| Frontend API client | | | |
| Backend route | | | |
| Service/use case | | | |
| Policy/helper | | | |
| Model/schema | | | |
| Database/migration | | | |
| Authorization | | | |
| Notifications | | | |
| Public visibility | | | |
| Trash/restore | | | |
| Storage | | | |
| Statistics/audit | | | |
| WebSocket/cache | | | |

## Responsibility placement

Use [Code organization](code-organization.md) to assign one canonical owner
for each cross-layer rule:

- a route owns HTTP input/output mapping and dependencies;
- a service or use case owns a complete operation, transaction orchestration,
  and side effects;
- a policy or helper owns reusable state, permission, or decision logic;
- a model or schema owns data shape and necessary constraints; and
- the frontend owns presentation and interaction, not Domain authority.

The backend must reject illegal operations independently; hiding a frontend
control does not replace a server guard. Do not create parallel status,
permission, notification, or visibility logic.

If current responsibility is dispersed and cannot be extended safely for the
requested outcome, record a follow-up refactor. Do not turn a feature slice
into an opportunistic architecture-wide consolidation.

## Test matrix

Evaluate each row and mark it `Required`, `Existing coverage`, `Add`,
`Not required`, `Not applicable`, or `Deferred with reason`. A row may use
more than one mark when, for example, existing evidence needs one added case.

| Behavior | Status and evidence |
| --- | --- |
| Happy path | |
| Authorization | |
| Validation | |
| Invalid state | |
| Same-target retry | |
| Failure/rollback | |
| Notification/side effects | |
| Public visibility | |
| Concurrency | |
| Neighbor regressions | |
| Frontend rendering/actions | |
| Migration/backfill | |
| E2E critical path | |

Choose only the test levels that can prove the affected contract:

- Unit tests fit pure policies, predicates, mappings, and aggregations.
- Backend API or service tests fit authorization, persisted state,
  transactions, notifications, audit, trash, visibility, and concurrency.
- Frontend unit or component tests fit rendering, action availability, error
  display, and data identity or grouping.
- E2E fits a high-value complete user journey or integration not provable at a
  lower level.
- Migration tests are required only when schema or existing-data contracts
  change.

Not every change needs every level or a new test at a level with adequate
existing coverage. Select commands and escalation rules from
[Validation policy](validation.md); do not reproduce its command matrix here.

## Red-green implementation

For new behavior or a bug fix:

1. Establish the smallest focused failing evidence.
2. Prefer and run a stable automated failing test.
3. When the limited browser or platform-specific fallback applies, record the
   reproducible scenario instead.
4. Confirm that the red evidence has the expected cause.
5. Make the smallest application implementation.
6. Make the focused automated test pass or confirm that the reproduced failure
   is resolved.
7. Run neighboring regressions.
8. Add the other required matrix cases.
9. Finish with risk-proportional verification.

Red evidence may be a temporary local state; it does not require a failing
commit or remote push. Do not complete work with a known failing test or a
long-lived `xfail` or skip, weaken an assertion for a green result, change
application code while the red cause is unknown, or combine unrelated Domain
gaps in one repair.

## Implementation slices

Each slice must have one purpose, independent verification, explicit files,
focused tests, a stop condition, and a suggested commit message.

A useful order is:

1. contract and test evidence;
2. backend policy and API;
3. side effects and transactions;
4. frontend behavior; and
5. critical E2E or migration evidence.

Adapt or omit slices that do not fit the actual change. Do not mechanically
create every slice or bundle a large architectural refactor into feature work.

## Documentation maintenance

- Domain-impacting work updates the affected Domain contract and focused tests
  in the same change, without overstating what the tests prove.
- A behavior-preserving refactor does not rewrite the product contract and
  keeps necessary contract tests green.
- Pure UI presentation follows the UI guidelines and does not force unrelated
  Domain edits.
- If code, tests, and canonical documents conflict, stop rather than selecting
  one as the intended product behavior.

## Bounded verification

Follow [Validation policy](validation.md). Start with changed-file static
checks and focused tests, then run related module or neighboring regressions.
Escalate to a build, E2E, migration, or other higher-cost check only when the
risk and impact map justify it.

Wait for required CI to reach a terminal state. Retries are finite and need a
new hypothesis or a concrete transient/flaky classification. Do not replace a
missing environment with an unrelated broad suite, create an unexplained
second Compose project, run every suite for a small task, rerun indefinitely,
or skip required merge-commit CI.

## Commit, CI, and merge workflow

Keep implementation commits to one purpose and verify the exact staged scope.
Do not preserve the red phase as a failing commit. Push only with explicit
authorization, select branch CI by the final head SHA, and wait for its
terminal result.

Merge strategy and merge readiness are owned by
[CONTRIBUTING.md](../../CONTRIBUTING.md#merge-strategy). When a milestone uses
`--no-ff`, its new merge commit needs its own pushed, exact-SHA successful CI
run; source-branch CI is not a substitute.

## Completion gate

Before reporting a behavior change complete, confirm as applicable:

- the Feature contract is answered or marked `Not applicable`;
- product decisions are resolved;
- existing implementation and responsibility owners were identified;
- the impact map and test matrix are complete;
- affected Domain documents are synchronized;
- every committed test is green and neighboring regressions pass;
- application, migration, and storage risks are classified;
- commits have a single purpose;
- branch CI succeeds; and
- milestone merge and merge-commit CI follow `CONTRIBUTING.md`.

Use the completion report in `AGENTS.md`; do not create a second report
template here.
