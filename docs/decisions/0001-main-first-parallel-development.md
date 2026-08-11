# ADR-0001 — Main-first parallel development

- ID: ADR-0001
- Title: Main-first parallel development
- Status: Accepted
- Date: 2026-08-11
- Scope:
  - Paths: Repository-wide development and integration workflow
  - Concepts / Domain: Development-base selection, parallel branches, and
    later-target reconciliation
- Related documents:
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Collaboration and conflict resolution](../development/collaboration-and-conflict-resolution.md)
  - [Validation policy](../development/validation.md)
- Related PR / issue: None known
- Supersedes: None
- Superseded by: None

## Context

Developers commonly branch from `main` in parallel. When one branch merges
first, a later branch may integrate cleanly at the text level while still
depending on assumptions that the newly merged change intentionally replaced.
Commit subjects and conflict markers cannot reliably convey non-goals,
rejected alternatives, or compatibility invariants.

The repository also has an optional coordination workflow for explicitly
declared milestones. Its existence must not turn it into the default base for
ordinary independent work.

## Decision

Normal independent work starts from freshly fetched `main`; developers may
branch from it in parallel. Coordination is optional and used only when the
task or milestone explicitly declares coordinated work.

The branch that becomes merge-ready later is responsible for refreshing and
reconciling the latest intended target. If the target advanced since the
branch merge-base, the later developer or Agent must inspect relevant new
target commits and merge commits, associated relevant PR context, current
canonical documents, and relevant Accepted Decision Records before
integration. Git conflict markers and commit history alone are insufficient.

Target refresh does not by itself create an extra Full CI gate. Verification
remains risk-proportional until the repository's formal source, PR, main, and
merge-commit gates apply. Main-target PRs remain Full under the current CI
contract.

Shared, published, external, bot, analytics, backup, and recovery work must not
be silently rebased, reset, retargeted, or rewritten.

## Rationale

Main-first development keeps the normal base simple and current while allowing
independent work to proceed concurrently. Assigning reconciliation to the
later integrator makes responsibility deterministic. Requiring PR and Decision
context captures semantic intent without copying every change into a separate
history system.

## Alternatives considered

- Use the coordination branch for all work: rejected because coordination is
  an explicit milestone mechanism, not a universal base.
- Treat a clean merge and passing tests as sufficient: rejected because tests
  may not cover incompatible design assumptions and Git detects only textual
  overlap.
- Run a new Full CI cycle after every target refresh: rejected because the
  existing risk-proportional and formal CI gates already define required
  evidence.
- Rewrite or rebase later branches automatically: rejected because shared
  history and ownership boundaries must be preserved.

## Invariants

- Independent work begins at fresh `main` unless coordination is explicitly
  declared.
- The later integrator reconciles the current intended target before merge
  readiness.
- When the target advanced, relevant merged PR and Accepted Decision context is
  reviewed in addition to commits and diffs.
- Textual cleanliness is not semantic compatibility evidence.
- Target refresh does not weaken or invent formal CI authority.
- Main-target PRs use Full CI.
- Shared or external history is not silently rewritten.

## Consequences

- Pull requests must carry enough design intent and invariants for a later
  integrator to understand the change.
- Later branches may need focused consumer and contract review even when Git
  reports no conflict.
- Explicit coordination remains available without imposing its overhead on
  ordinary work.

## Conflict / integration guidance

Follow the collaboration runbook whenever the target advanced. Preserve the
upstream change's relevant intent and invariants while reconciling the later
work. Classify conflicts as textual, semantic, or authority conflicts; stop
for owner or product direction when authority cannot be reconciled.
