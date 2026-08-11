# ADR-0003 — Coordination-branch freshness

- ID: ADR-0003
- Title: Coordination-branch freshness
- Status: Accepted
- Date: 2026-08-11
- Scope:
  - Paths: `.github/project-governance.json`, coordination workflow guidance,
    and branches selected by machine governance
  - Concepts / Domain: Optional coordination-base eligibility and protected
    refresh
- Related documents:
  - [Collaboration and conflict resolution](../development/collaboration-and-conflict-resolution.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Project governance configuration](../../.github/project-governance.json)
- Related PR / issue: None known
- Supersedes: None
- Superseded by: None

## Context

The canonical coordination branch is optional and can be dormant between
explicitly coordinated milestones. A dormant branch may legitimately lag
`main`; lag alone is not a defect. It becomes unsafe only if developers treat
that stale ref as a new task base without proving freshness.

Protected-branch policy may reject direct updates even when a coordination
branch has no unique commits. Freshness therefore needs a proof and a
PR-compatible refresh mechanism, not a blanket direct-push instruction.

## Decision

Do not use the optional coordination branch unless a task or milestone
explicitly declares coordinated work. Before using it as a base:

1. resolve its exact name with
   `python3 scripts/ci/project_governance.py coordination-branch`;
2. fresh-fetch `main` and the resolved coordination branch;
3. prove whether current `main` is an ancestor of coordination;
4. if it is, coordination is fresh enough for the declared work; and
5. if it is not, coordination is stale and cannot be used as the task base.

When protection requires PR-based updates, refresh coordination in a
separately scoped workflow without bypass, force, or rewrite.

### Case A — coordination has no unique commits and is behind main

Create a temporary owner-controlled refresh branch from fresh `main`, or use an
equivalent safe PR construction, and open a PR to the machine-resolved
coordination branch. Let the current classifier select Full or Equivalent from
the actual paths and evidence. Use a true merge when a durable merge boundary
is appropriate or current policy requires it. Do not push directly through
protection.

### Case B — coordination and main both have unique commits

Create a dedicated synchronization branch. Explicitly integrate main and
coordination, inspect relevant PR and Decision context on both sides, resolve
textual and semantic conflicts, validate proportionately, and open a PR back
to coordination. Do not force or rewrite either history.

### Current-state example (2026-08-11)

The machine-resolved branch `integration/stage-5bd` is a clean ancestor of
`main`, with main-only commits and no coordination-only commits. It is dormant,
and direct non-force fast-forward was rejected by enforced PR protection. This
state is acceptable while dormant, but the branch cannot be reused until the
pre-use freshness proof passes. This example records a checkpoint; the exact
active coordination name remains machine authority and must not be inferred
from this text.

## Rationale

Allowing dormant lag avoids unnecessary synchronization work. Requiring main
ancestry immediately before reuse ensures new coordinated work contains the
current accepted baseline. A protected PR refresh preserves branch governance
and provides review and CI evidence.

## Alternatives considered

- Require coordination to track main continuously: rejected because dormant
  lag has no operational cost until reuse.
- Permit use when coordination is merely an ancestor of main: rejected because
  that proves it is behind, not that it contains current main.
- Directly fast-forward or force the protected branch: rejected because branch
  protection and history safety remain authoritative.
- Hardcode a permanent coordination branch name in guidance: rejected because
  the exact branch is machine-resolved and may change.

## Invariants

- Coordination is optional and task-declared.
- Dormant lag is allowed and is not automatically a defect.
- A new coordinated task must prove current main is an ancestor of the
  machine-resolved coordination branch.
- Stale coordination is not a valid development base.
- Refresh is separately scoped and respects protection.
- Diverged histories receive explicit semantic reconciliation and no force or
  rewrite.

## Consequences

- The next coordinated milestone may require a refresh PR before feature work
  begins.
- Historical branch names may appear only as labeled examples; operating code
  and instructions continue to resolve the active name from machine authority.
- This decision does not authorize a current coordination refresh.

## Conflict / integration guidance

If ancestry or identity cannot be proven, stop rather than guessing a base. If
both branches have unique commits, review the design evidence for both sides
and use the collaboration runbook. If protection blocks the safe update, use a
separate owner-authorized refresh PR; do not bypass it.
