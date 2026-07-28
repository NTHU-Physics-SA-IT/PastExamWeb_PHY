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

1. System and user instructions.
2. Repository `AGENTS.md`.
3. Active canonical documents in `docs/README.md`.
4. This Skill workflow.
5. Optional advisory user Skills.

Never use this Skill to override `AGENTS.md` or a Domain contract.

## Task routing

Read only the smallest set needed for the task:

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

## Standard workflow

1. Confirm the repository root, branch, HEAD, and working-tree state.
2. Define the files and operations that are allowed and prohibited.
3. Search for the nearest existing implementation of the same responsibility.
4. Read the minimum canonical documents selected by task routing.
5. Determine and report whether the task has Domain impact.
6. Implement the smallest coherent change across every affected layer.
7. Apply bounded verification from the canonical validation policy.
8. When CI evidence is required, wait for the selected run to reach a terminal
   state.
9. Report completion using the contract in `AGENTS.md`.

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
