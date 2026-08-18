# Decision Records

Status: Active

Source of truth for: Durable repository decisions, their status, scope,
rationale, invariants, and supersession history

Related documents:
- [Documentation authority map](../README.md)
- [Collaboration and conflict resolution](../development/collaboration-and-conflict-resolution.md)
- [Feature development workflow](../development/feature-development-workflow.md)

## Purpose

This repository uses "ADR" and "Decision Record" broadly for selective,
durable architecture, Domain, CI, repository-governance, and collaboration
decisions. A record exists when future developers would face material risk of
breaking intent without the rationale. It is not a chronological development
log and does not duplicate every commit or pull request.

No Decision Record is required for typo fixes, routine implementation details,
ordinary refactors already uniquely governed by current documentation, or
every pull request.

## Evidence and authority

The collaboration evidence stack has distinct roles:

1. A commit records what changed.
2. A pull request records the change's purpose, design intent, scope,
   non-goals, invariants, and conflict-sensitive areas.
3. An Accepted Decision Record preserves durable rationale, alternatives,
   invariants, and consequences within its declared scope.
4. A handoff or milestone record states what the repository considered
   authoritative at a checkpoint.

No layer replaces the others. Handoffs and history remain evidence and cannot
silently override current authority.

Within repository governance, current operational authority descends from:

1. machine-enforced contracts such as Git topology, branch protection,
   required checks, CI workflows, `.github/project-governance.json`, and
   migrations or schema authority;
2. active operating instructions in `AGENTS.md`, `CONTRIBUTING.md`, and the
   canonical Active documentation indexed by `docs/README.md`;
3. Accepted Decision Records within their declared scope; and
4. pull-request context and commit history as concrete implementation evidence,
   not universal policy.

If those sources conflict, stop and report the authority conflict. Do not
silently choose the newest file, newest commit, or most convenient
interpretation.

## Statuses

- **Proposed:** Under discussion. It provides context but is not operative
  authority.
- **Accepted:** The current durable decision within its declared scope.
  Developers and Agents preserve its invariants unless a task explicitly
  authorizes supersession.
- **Superseded:** Retained historical rationale that is no longer current
  authority. It must link to the replacing record.
- **Deprecated:** Retained for context but must not guide new design.

These statuses are specific to Decision Records. `Superseded` is not an
undefined synonym for the documentation index's general `Historical` status.

## Applicability and required review

A record is relevant when either:

- changed paths fall within its path-oriented scope; or
- the work affects its named conceptual or Domain scope, even without path
  overlap.

Before changing established behavior or shared infrastructure, read all
relevant Accepted records and the linked canonical documents, then record the
applicable invariants for non-trivial work. When a target advanced after the
feature branch's merge-base, use the collaboration runbook to review relevant
new PR and Decision context before reconciliation.

## Required metadata and content

Each record includes:

- ID;
- title;
- status;
- date;
- path-oriented and/or conceptual scope;
- related canonical documents and PR or issue when known;
- `Supersedes` and `Superseded by` links; and
- Context, Decision, Rationale, Alternatives considered, Invariants,
  Consequences, and Conflict / integration guidance sections.

Start from [the template](TEMPLATE.md). Number records sequentially and use a
short kebab-case filename.

## Accepted-record maintenance and supersession

Accepted records are append-only in design substance by default. Minor typo,
link, and metadata corrections are allowed when they do not pretend that a new
decision was made.

To change a durable accepted decision:

1. obtain task authority that explicitly reconsiders or supersedes it;
2. create a new Decision Record with the replacement decision and rationale;
3. mark the old record `Superseded` and link both records in both directions;
4. update affected canonical operating documents, code, contracts, and tests
   in the same coherent change; and
5. apply the normal review and validation gates.

An ordinary feature request does not imply supersession. Accepted records do
not freeze design forever; they require intentional, reviewable replacement.

## Record index

| ID | Title | Status | Scope |
| --- | --- | --- | --- |
| [ADR-0001](0001-main-first-parallel-development.md) | Main-first parallel development | Accepted | Development bases and later-target reconciliation |
| [ADR-0002](0002-ci-evidence-and-main-full-authority.md) | CI evidence and main Full authority | Accepted | Full, Equivalent, and docs-only CI evidence modes |
| [ADR-0003](0003-coordination-branch-freshness.md) | Coordination-branch freshness | Accepted | Optional coordination branch selection and refresh |
| [ADR-0004](0004-decision-record-and-semantic-conflict-authority.md) | Decision Record and semantic-conflict authority | Accepted | Design evidence, conflict classification, and supersession |
| [ADR-0005](0005-main-pr-docs-only-exception.md) | Main pull-request docs-only exception | Accepted | Docs-only classification for pull requests targeting `main` |
| [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md) | Coordination postmerge Full-evidence reuse | Accepted | Exact Case-B coordination postmerge evidence reuse |
| [ADR-0007](0007-retain-full-fallback-for-post-case-b-reconciliation-tails.md) | Retain Full Fallback for Post-Case-B Reconciliation Tails | Accepted | Post-Case-B reconciliation-tail evidence reuse |
| [ADR-0008](0008-narrow-sibling-migration-convergence-exception.md) | Narrow sibling-migration convergence exception | Proposed | Exact three-revision sibling-migration compatibility boundary |
