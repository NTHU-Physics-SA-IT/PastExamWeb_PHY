# ADR-XXXX — Title

- ID: ADR-XXXX
- Title: Title
- Status: Proposed
- Date: YYYY-MM-DD
- Scope:
  - Paths: Not applicable
  - Concepts / Domain: Describe the affected responsibility.
- Related documents:
  - [Documentation authority map](../README.md)
- Related PR / issue: None known
- Supersedes: None
- Superseded by: None

## Context

What durable problem or constraint requires a decision? Explain enough context
for a future developer who was not present for the original change.

## Decision

State the selected design and the boundary of its authority.

## Rationale

Explain why this design was selected.

## Alternatives considered

- Alternative: Why it was not selected.

## Invariants

- State the behavior, compatibility constraint, or safety property that future
  work must preserve while this record is Accepted.

## Consequences

- Record benefits, costs, limitations, and follow-up obligations.

## Conflict / integration guidance

Explain how later work should reconcile with this decision and which conflict
would require owner, product, or architecture authority.

---

This repository uses "ADR" and "Decision Record" broadly for durable
architecture, Domain, CI, repository-governance, and collaboration decisions.
Create one when future developers would be at material risk of breaking intent
without the rationale. Do not require one for typo fixes, routine
implementation details, ordinary refactors already uniquely governed by
current documentation, or every pull request. Write `None` or `Not applicable`
for metadata that does not apply instead of deleting it.

Accepted records are append-only in design substance by default. Superseding a
durable Accepted record requires an explicitly authorized replacement record,
two-way links, and coherent updates to affected operating documents or code.
