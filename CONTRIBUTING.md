# Contributing

## Before you start

Use these sources instead of duplicating their rules here:

- [Repository Agent and automation rules](AGENTS.md)
- [Documentation index and authority map](docs/README.md)
- [Decision Record index](docs/decisions/README.md)
- [Collaboration and conflict resolution](docs/development/collaboration-and-conflict-resolution.md)
- [Local development environment](docs/development/local-environment.md)
- [Feature development workflow](docs/development/feature-development-workflow.md)
- [Validation policy](docs/development/validation.md)
- [Protected coordination operator runbook](docs/runbooks/coordination.md)

## Feature and behavior changes

Before adding a feature or changing behavior, classify the scope as Class 0,
Class 1, or Class 2 and use the proportionate process in the
[Feature development workflow](docs/development/feature-development-workflow.md).
Class 2 work completes its Feature contract, impact map, responsibility
placement, and test matrix before application changes.

A bug fix starts with focused failing evidence; a faithful, stable automated
failing test is the default and preferred choice. A browser-only problem that
automation cannot faithfully and stably reproduce may use the canonical
workflow's limited reproducible browser scenario, but manual evidence cannot
replace a reasonably automatable contract test. A refactor must state and
protect the behavior that remains unchanged; if behavior needs to change,
reclassify the work. The canonical workflow contains the detailed conditions,
planning, and implementation procedure, while the merge strategy remains in
this document.

Before modifying established behavior or shared infrastructure, identify
relevant `Accepted` Decision Records by path and conceptual or Domain scope and
preserve their invariants. Intentionally reversing a durable accepted decision
requires explicit task authority, a superseding Decision Record linked in both
directions, and coherent updates to affected operating documents or code.

## Branches and commits

- Fetch current remote refs before choosing a development base.
- Normal independent work starts from fresh `main` unless the task or milestone
  explicitly declares coordinated work.
- `main` publishes ordinary repository-wide authority. A `null` coordination
  branch means only that main does not point to an active coordination target;
  it does not prohibit a separately protected integration branch from carrying
  branch-local coordination authority while main remains null.
- Coordinated work starts from the optional configured coordination branch,
  when one is active, resolved by
  `python3 scripts/ci/project_governance.py coordination-branch`; its existence
  does not make it the universal development base.
- A dormant coordination branch may lag `main`, but it is not a valid base for
  newly declared coordinated work until fresh refs prove that current `main`
  is its ancestor. If it is stale, refresh it in a separately scoped pull
  request through the allowed protected-branch workflow; do not bypass
  protection or rewrite it.
- A configured coordination branch is usable only when its exact ref was
  created by the protected lifecycle path, the integration ruleset remains
  active, branch-local governance names the exact branch, and current `main` is
  its ancestor. Coordination Source and pull-request gates remain Full; only
  an exact final merge may reuse both through ADR-0014. Use the
  [protected coordination runbook](docs/runbooks/coordination.md).
- Keep task branches developer-owned; a visible branch name does not grant
  project authority or make an external, bot, analytics, backup, or recovery
  branch a valid target.
- Keep each commit focused on one purpose and avoid unrelated changes.
- Use a concise Conventional Commit message that describes the outcome.
- Preserve existing work and inspect the exact staged diff before committing.
- Before merge readiness, fetch current refs and integrate the latest intended
  target baseline safely. Do not silently rebase, reset, or retarget shared or
  external work.
- If the target advanced since the branch merge-base, review the relevant
  merged PR context and Accepted Decision Records before integration. Commit
  history alone is insufficient when design intent or invariants are material;
  reconcile semantic conflicts even when Git reports no textual conflict and
  stop on unresolved authority conflicts. Follow the
  [collaboration runbook](docs/development/collaboration-and-conflict-resolution.md).

## Merge strategy

### Milestone branches

Use a merge commit when integrating a completed milestone branch whose stage
boundary should remain visible in project history:

```bash
git merge --no-ff <milestone-branch>
```

Milestone branches include repository governance, Repository Skill migration,
Domain behavior safety nets, Domain contract-conformance fixes,
architectural or lifecycle refactors, and other complete work packages that
need a durable stage boundary.

### Preserve commits

- Do not squash a milestone branch unless the user explicitly requests it.
- Preserve the branch's focused, single-purpose commits.
- Use a clear merge commit message that describes the integrated stage instead
  of accepting a vague default message.

### Small linear branches

Fast-forward integration remains appropriate for a typo, a single documentation
link fix, another very small linear change without milestone significance, or
when the user explicitly does not require the branch boundary to be preserved.
Not every branch requires `--no-ff`.

### Merge readiness

Before merging, confirm that:

- the source branch working tree is clean;
- the source branch is pushed and its CI has completed successfully;
- the destination's local and remote refs agree;
- branch ancestry and the exact differences are understood; and
- there is no unauthorized divergence or unexplained commit.

### Merge commit CI

A `--no-ff` merge creates a new commit. Push the destination branch, locate the
CI run whose head SHA matches that merge commit, and use a blocking watch until
the run reaches a terminal state. The milestone is complete only after that
merge commit's CI succeeds; successful source-branch CI does not replace this
requirement.

### Failure handling

Classify a CI failure before acting. A transient infrastructure failure or
flaky check may receive the finite retry allowed by the
[validation policy](docs/development/validation.md). Stop and report failures
that involve the application, CI policy, Domain behavior, destructive action,
or an undetermined cause. Do not reset, force-push, or rewrite pushed merge
history to conceal a failure.

### Historical note

The earlier governance branch was integrated by fast-forward and its linear
history remains unchanged. Do not reset, rebase, or manufacture a retrospective
merge commit. This milestone merge strategy begins with the Repository Skill
migration milestone.

## Pull requests

Not every local or exploratory change must become a pull request. Normal
independent pull requests may target `main`. A task or milestone that explicitly
requires coordination targets the configured coordination branch instead;
resolve its exact name from canonical project governance rather than historical
prose or visible remote branches.

Before opening or updating a pull request, refresh the intended base and
incorporate it safely. Pull requests to `main` use Full CI by default, except
when the centralized classifier conclusively identifies every changed path as
docs-only. For the configured coordination branch, the Repository classifier
requires Full CI. The simplified lifecycle does not use candidate evidence to
claim Equivalent authority.

For an ordinary independent main-target change, once the final source head,
base freshness, and pull request content are ready, push that head and promptly
open the ready pull request. When Source and PR workflows are both selected,
they run as independent evidence and may overlap. Every exact result required
by the repository must still be terminal successful before merge.

Returning a coordinated milestone to main uses a separately authorized
immutable candidate based on fresh `main`. The final coordination SHA is
true-merged into that candidate. Once its source identity, topology, base
freshness, and pull request content are ready, push the exact candidate and
promptly open its ready pull request to `main`; do not wait merely for candidate
Source CI to finish. Selected Source and PR evidence may run independently and
overlap, but all exact evidence required by the repository must be terminal
successful before merge. Protected Source and pull-request workflows remain
Full. A same-repository normal final merge uses the existing lightweight
Equivalent path only when exact C/H/P/Q state, dual-Full evidence, live refs,
and merged-PR identity all validate; every uncertainty remains Full under
[ADR-0014](docs/decisions/0014-protected-coordination-exact-state-postmerge-reuse.md).

Do not use no-op commits, extra pushes, workflow reruns, pull request
close/reopen actions, or Draft/Ready transitions solely to manufacture overlap.
Lack of overlap caused by natural scheduling is not a policy failure and does
not authorize a rerun. If source identity, base freshness, candidate topology,
semantic conflicts, owner decisions, or other genuine readiness requirements
remain unresolved, the pull request is not ready and must not be opened merely
to chase parallelism. Pull requests targeting `main` never use Equivalent
evidence; governance, CI, configuration, application, mixed, and unknown
changes run Full CI, while only conclusively docs-only changes use the narrow
lightweight path. Merging that pull request is a separate owner-authorized
operation.

Before merge, the pushed final commit must reach a terminal successful CI
result for the checks selected by the repository workflows. A pull request
description should state:

- the purpose and scope of the change;
- verification performed;
- checks not run and why;
- Domain impact;
- migration impact; and
- remaining risk.

The repository's `CODEOWNERS` file routes review of governance-sensitive paths
to verified owners. It does not grant permission, change canonical authority,
or make owner review a branch-protection requirement by itself. The absence of
a CODEOWNER entry does not permit contributors to ignore repository rules or
the affected canonical documents.

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
`main`. After an exact pushed main SHA completes Full CI and `CI Gate`,
semantic-release may determine the version and create the Git tag and GitHub
Release for that same SHA. Semantic-release is not deployment authority.

Production environment governance and production evidence are separate,
explicitly authorized gates. A prepared candidate or GitHub Release does not
activate production, enable deployment, or switch traffic automatically.

Candidate evidence must be reviewed before a separately approved activation.
Follow [production deployment safety](docs/production-deployment.md) for the
release gate, backup, configuration, activation, and rollback boundaries.
