# ADR-0004 — Decision Record and semantic-conflict authority

- ID: ADR-0004
- Title: Decision Record and semantic-conflict authority
- Status: Accepted
- Date: 2026-08-11
- Scope:
  - Paths: `docs/decisions/`, collaboration guidance, and any path governed by
    an applicable Decision Record
  - Concepts / Domain: Durable design rationale, semantic conflict, authority
    conflict, and explicit supersession
- Related documents:
  - [Decision Record index](README.md)
  - [Collaboration and conflict resolution](../development/collaboration-and-conflict-resolution.md)
  - [Documentation authority map](../README.md)
- Related PR / issue: None known
- Supersedes: None
- Superseded by: None

## Context

Commit history is essential for concrete changes but rarely captures every
rejected alternative, non-goal, compatibility constraint, or intentional
oddity. Two branches can edit different lines and still implement mutually
incompatible assumptions. Conversely, durable decisions must remain capable of
intentional evolution rather than freezing design forever.

## Decision

Commit history is evidence, not complete design authority. When an intended
target advanced after a feature branch's merge-base, the later integrator must
inspect:

- new target commits and merge commits;
- associated relevant pull requests;
- related Accepted Decision Records;
- current affected Domain and operational canonical documents;
- changed-path overlap; and
- semantic dependencies even when Git reports no textual conflict.

Conflicts have three classes:

1. **Textual conflict:** Git detects overlapping edits.
2. **Semantic conflict:** Git can merge the text, but the branches' assumptions
   or contracts conflict.
3. **Authority conflict:** accepted documents, decisions, machine contracts,
   or explicit product intent disagree and cannot be reconciled within the
   task's authority.

Authority conflicts require a stop and owner or product-authority decision.
Developers and Agents must not guess.

Accepted Decision Records preserve current durable rationale and invariants
within scope. They can be intentionally superseded only through an explicitly
authorized new record, two-way supersession links, and coherent updates to the
affected operating sources.

## Rationale

Combining commit, PR, Decision, and canonical-document evidence makes hidden
assumptions reviewable. Explicit conflict classes prevent a clean textual merge
from being treated as proof of compatibility, while explicit supersession
allows design to evolve without erasing why the prior decision existed.

## Alternatives considered

- Use commits as the sole history: rejected because design intent and durable
  invariants are often missing.
- Require Decision Records for every PR: rejected because ceremony would
  obscure the selective durable decisions that matter.
- Treat Accepted records as immutable forever: rejected because intentional
  design evolution must remain possible.
- Edit an Accepted record in place to reverse it: rejected because that erases
  historical rationale and makes integration context ambiguous.

## Invariants

- Target advancement triggers review of relevant commit, PR, Decision, and
  current canonical context.
- Semantic dependencies are assessed even without textual overlap.
- API contracts, authorization and visibility, lifecycle state, transactions
  and side effects, schema and migration order, notifications, storage, shared
  frontend state, UI invariants, and CI/release/governance authority receive
  explicit semantic-conflict attention when affected.
- Unresolved authority conflict stops work for owner or product direction.
- Accepted decisions are not silently reversed or edited out of history.
- Explicit supersession is allowed and linked in both directions.

## Consequences

- Pull requests and Decision Records must state usable invariants and
  conflict-sensitive areas.
- Later integrators may need to inspect semantically dependent consumers beyond
  the directly overlapping files.
- Durable rationale remains available after a decision is replaced.

## Conflict / integration guidance

Use the collaboration runbook to build a short reconciliation note for new
target changes. Resolve textual conflicts from design authority rather than
choosing a side mechanically. Search consumers and contracts for semantic
conflicts. Stop on authority conflict unless the current task explicitly
authorizes and documents a superseding decision.
