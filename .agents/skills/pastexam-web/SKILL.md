---
name: pastexam-web
description: Route and execute work only in the PastExamWeb_PHY repository. Use for PastExamWeb_PHY feature development, debugging, code review, documentation, Vue/PrimeVue UI, FastAPI/SQLModel backend, Domain contracts, Alembic migrations, validation or CI, and production-readiness tasks.
---

# PastExamWeb_PHY workflow

## Scope

- Use this Skill only for work in the PastExamWeb_PHY repository.
- Follow the repository `AGENTS.md` before this workflow.
- Treat the Active documents indexed by `docs/README.md` as the canonical
  sources for project facts and contracts.
- Use this Skill only to route tasks and guide execution. Do not maintain a
  second copy of project rules here.

## Instruction precedence

Apply instructions in this order:

1. System, developer, and current user instructions.
2. Repository `AGENTS.md`.
3. Active canonical documents in `docs/README.md`.
4. This Skill workflow.
5. Optional advisory user Skills.

Never use this Skill to override `AGENTS.md` or a Domain contract.

## Task routing

Read only the smallest set needed for the task:

- Feature or behavior work: start with
  `docs/development/feature-development-workflow.md` when the task adds a
  feature or API; changes product behavior; crosses frontend and backend;
  affects state, permissions, notifications, visibility, trash, restore,
  permanent deletion, storage, transactions, migrations, or other Domain
  side effects; fixes a Domain bug; or performs an architectural refactor.
- General development, architecture, or code responsibility:
  `docs/development/code-organization.md`.
- Local environment, Docker, or environment configuration:
  `docs/development/local-environment.md`.
- Validation, tests, or CI: `docs/development/validation.md`.
- UI, responsive behavior, theme, accessibility, or display:
  `docs/ui/guidelines.md`.
- Entity relationships, state, authorization, visibility, notifications, or
  side effects: start with `docs/domain/README.md`, then read only the affected
  Domain child documents.
- Migration work: `docs/migration-safety.md`.
- Production or deployment readiness: `docs/production-deployment.md`.
- Skill governance: `docs/governance/codex-skill-security-review.md`.

Do not load every document for every task.

For schema-changing milestones, route the work through the canonical completion
layers instead of treating branch CI as sufficient:

1. establish Repository Green on isolated PostgreSQL;
2. use `scripts/dev-compose.sh schema-status` for the sealed persistent-local
   aggregate preflight;
3. keep remediation, guarded migration rehearsal, and runtime operations in
   separately authorized tasks;
4. require Environment Green and applicable Human Verification Green before
   merge authorization; and
5. require the milestone merge commit's own exact-SHA CI for Merge Green.

When the repository head will move ahead of the persistent-local ledger, route
through `backend-pause` before exposing the incompatible tree and
`backend-resume` only after `schema-status` proves compatibility. Never
automatically downgrade persistent local data. Production comparison always
uses actual ledger, deployed-release expected head, and development head as
three separate facts; only a separately authorized production aggregate audit
may select the runner's production mode.

### Feature and behavior classification

- Class 0 non-behavioral work uses the minimum applicable documentation and
  verification; it does not need the full feature gate.
- Class 1 localized behavior uses the workflow's concise contract, focused
  search, impact, tests, and bounded verification.
- Class 2 feature, cross-layer, or Domain work must complete the workflow's
  pre-implementation gate before application changes.
- A bug fix identifies the canonical expected behavior and begins with focused
  failing evidence. Domain or cross-layer bug fixes also use the Class 2 gate.
- A refactor declares behavior unchanged and uses characterization evidence as
  needed; stop and reclassify if behavior must change.

Add only the documents selected by the task: code organization for placement,
validation for checks and CI, UI guidance for presentation, affected Domain
documents for product behavior, migration safety for persisted schema or data,
and production safety only for production work.

This Skill identifies the task, selects documents, confirms the applicable
pre-implementation gate, and applies stop conditions. Contract templates,
test matrices, red-green details, validation commands, and Domain transition
rules remain in their canonical documents.

## Standard workflow

1. Complete repository preflight: confirm the root, branch, HEAD, and
   working-tree state, then define the files and operations that are allowed
   and prohibited.
2. Make an initial Class 0, 1, or 2 classification and identify any bug-fix or
   refactor overlay and its applicable gate. Do not claim that gate complete
   yet. Reclassify if later reading or search reveals higher risk.
3. Read the minimum canonical documents selected by task routing. Do not load
   unrelated guidance.
4. Search for the canonical implementation, responsibility owner, analogous
   routes, services, policies, components, tests, and fixtures. Identify
   parallel logic to avoid; similarity alone is not permission to copy.
5. Determine Domain impact and the necessary impact scope. Separate rules
   already answered by canonical documents from genuinely blocking product
   decisions; do not repeatedly ask the user about internal implementation
   details.
6. Only after the preceding reading, search, and impact analysis, complete the
   applicable canonical pre-implementation gate. Class 0 uses its lightweight
   scope and verification gate; Class 1 uses its concise contract, focused
   search, and matrix; Class 2 completes the Feature contract, product-decision
   gate, existing-implementation decision, impact map, responsibility
   placement, test matrix, and implementation slices. A bug fix adds focused
   failing evidence; a refactor states its behavior-preservation invariant and
   existing safety net. Do not modify application code while a blocking gate
   remains incomplete.
7. Implement the smallest coherent slice under the canonical responsibility
   owner. Do not create parallel logic or expand into opportunistic
   repository-wide refactoring; synchronize product behavior and its
   canonical documents.
8. Apply targeted-first bounded verification, neighboring regressions, finite
   retries, and terminal CI waiting as required by
   `docs/development/validation.md`.
9. Report completion using `AGENTS.md`. Perform commit, push, or merge only
   with user authorization, and route milestone integration and merge-commit
   CI through `CONTRIBUTING.md`.

## Domain impact routing

Treat a change as Domain-impacting when it affects any of the following:

- entity relationships;
- state transitions;
- authorization or public visibility;
- notification creation or deduplication;
- transaction guarantees;
- PostgreSQL, MinIO, Redis, or WebSocket side effects;
- trash, restore, or permanent-delete behavior;
- API business-error semantics.

For Domain-impacting changes, read the affected Domain documents and update
the contract and focused tests in the same change. If code, tests, and
documents conflict, stop and report the conflict rather than choosing an
intended behavior.

## Verification routing

Use `docs/development/validation.md` as the sole validation policy. Start with
targeted checks, keep retries finite and evidence-based, and follow its stop
conditions. Do not create an unexplained second Compose project for ordinary
task verification.

## UI advisory Skill

If `ui-ux-pro-max` is available in user scope, use it only as optional advice
for explicit redesign, UX, or accessibility tasks. The project UI authority
remains `docs/ui/guidelines.md`, and this workflow must not require the
advisory Skill to be installed.

## Stop conditions

Stop and report when:

- the working tree contains changes of unknown ownership;
- completing the task requires expanding beyond its authorized scope;
- a Class 2 pre-implementation gate is incomplete;
- a refactor requires an unresolved behavior change;
- code, tests, and canonical documents disagree;
- a product decision is required;
- a destructive, production, or migration operation lacks explicit authority;
- the same validation fails again without a new hypothesis;
- a required permission, credential, service, or environment is unavailable.

Do not reset, clean, overwrite, weaken a test, or broaden the task to hide a
blocker.

## Output contract

Use the completion report defined by `AGENTS.md`. At minimum, report the branch
and HEAD, scope, Domain impact, affected contracts and tests, verification,
commit/push/merge status, residual risks, and final working-tree state.
