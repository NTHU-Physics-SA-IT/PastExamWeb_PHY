# Collaboration and conflict resolution

Status: Active

Source of truth for: Parallel-development target refresh, design-context
review, and textual, semantic, or authority conflict reconciliation

Applies to: Independent branches from `main` and tasks that explicitly declare
use of the optional coordination branch

Related documents:
- [Repository working agreement](../../AGENTS.md)
- [Contributor workflow](../../CONTRIBUTING.md)
- [Decision Record index](../decisions/README.md)
- [Feature development workflow](feature-development-workflow.md)
- [Validation policy](validation.md)

## Authority boundary

This runbook owns parallel-development reconciliation and semantic-conflict
procedure. It does not replace the feature workflow, validation command matrix,
Domain contracts, CI implementation, merge authorization, or production
authority.

A successful Git merge proves only textual integration. It is not semantic
compatibility evidence.

## Start work

1. Read root `AGENTS.md` and inspect the working tree.
2. Fetch fresh remote refs.
3. Choose fresh `main` for normal independent work. Use the optional
   coordination branch only when the task or milestone explicitly declares
   coordination.
4. Before using coordination, resolve its exact name with
   `python3 scripts/ci/project_governance.py coordination-branch`, fresh-fetch
   it and `main`, and prove current `main` is its ancestor. If not, stop: the
   branch is stale and needs a separately scoped protected refresh.
   Resolution also requires active Trusted Activation authority from protected
   main; a visible ref or local governance value cannot authorize coordination.
   Follow the [Trusted Activation runbook](../runbooks/trusted-activation.md).
5. Read the [Decision Record index](../decisions/README.md). Identify relevant
   Accepted records by changed path, affected conceptual or Domain scope, and
   linked canonical documents.
6. For non-trivial work, record the invariants that must remain true before
   changing established behavior or shared infrastructure.

## Reassess before merge readiness

1. Fetch the intended target again and record its exact ref and SHA.
2. Determine the branch merge-base with the intended target.
3. List target commits and merge commits added since that merge-base.
4. Map relevant merged changes to their pull requests. Use changed paths,
   merge-commit metadata, and the repository's GitHub PR ledger rather than
   assuming a commit subject contains the full design context.
5. For each relevant PR, review its Problem / Goal, Design intent, Non-goals,
   Invariants, Conflict-sensitive areas, and related Decision Records.
6. Read the relevant Accepted Decision Records and current affected Domain or
   operational canonical documents.
7. Write a short reconciliation note for each relevant upstream change:

   - upstream change;
   - upstream intent;
   - invariant to preserve;
   - overlap classification: textual, semantic, or none; and
   - planned integration treatment.

Commit history and diffs remain necessary evidence, but they are not complete
design authority.

## Integrate the target safely

Preserve shared and published history. Use the merge or update strategy
authorized for the task, do not silently rebase, reset, retarget, or force, and
do not bypass protected-branch workflows. Refreshing the latest target does not
by itself invent another Full CI gate; run risk-proportional focused checks
after integration, then obey the repository's formal PR and main CI policy.

## Conflict classes and treatment

### Textual conflict

Git detects overlapping edits. Do not choose "ours" or "theirs" merely to make
the index clean. Reconcile both changes against current canonical authority,
their PR design intent, and applicable Accepted Decision invariants.

### Semantic conflict

Git can merge the text, but assumptions or contracts are incompatible. Search
affected consumers and contracts even when there is no conflict marker.
Conflict-sensitive areas include:

- API request, response, and business-error contracts;
- authorization, public visibility, and lifecycle state transitions;
- transactions, side effects, notification deduplication, and storage;
- schema constraints and migration order;
- shared frontend state, responsive behavior, and UI invariants; and
- CI, release, repository-governance, and production authority.

Resolve the combined design explicitly, update affected canonical sources, and
verify the dependent consumers proportionately.

### Authority conflict

Current machine contracts, operating documents, Accepted Decisions, or
explicit product intent disagree and cannot be reconciled within the task's
authority. Stop and ask the owner or applicable product authority. Do not guess
and do not infer supersession from an ordinary feature request.

An Accepted Decision may be intentionally replaced when the task explicitly
authorizes reconsideration. Follow the Decision Record index's supersession
procedure rather than editing away historical rationale.

## Verify and report

After integration, run the focused, risk-proportional checks required by the
[validation policy](validation.md), then comply with the formal PR/main CI and
merge-commit evidence rules. Report the reconciliation note, unresolved
conflicts, checks run, and exact branch and target SHAs.

`git merge` succeeding without conflict markers is never, by itself, a claim
that the branch is semantically compatible or merge-ready.
