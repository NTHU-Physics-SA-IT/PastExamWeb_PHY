# Domain contracts

Status: Active

Source of truth for: Domain terminology, evidence labels, and contract maintenance

Applies to: Product behavior across API, frontend, persistence, storage, notifications, and tests

Related documents:
- [Entity relationships](entity-relationships.md)
- [State transitions](state-transitions.md)
- [Notifications and side effects](notifications-and-side-effects.md)
- [Code organization](../development/code-organization.md)

## Purpose

These documents define business outcomes that the system must guarantee. They
do not freeze function names, exact file layout, or a particular internal
implementation. Code paths are cited as evidence and may move while the
observable contract remains stable.

## Product-level concepts

- A **logical exam group** is formed by the same course, academic term/year,
  teacher, and exam name/type. It is a grouping identity, not one file.
- A **submission** has its own submission number, requester, review state, and
  lifecycle.
- A **PDF/stored object** is one independently stored file and MinIO object.
- A **public archive item** is one approved exam file that a user can open
  independently.

### Current implementation

`ArchiveSubmission` contains the submission and stored-object metadata, while
`Archive` is the current public record. `created_archive_id` links them
optionally and uniquely. Public projection and reversible soft-lifecycle
operations follow that exact link; matching metadata is not ownership.

### Intended invariant

The four concepts above remain distinct even if the current model names and
tables do not yet express that separation. Multiple approved files may belong
to one logical exam group without sharing review or delete outcomes.

### Current safety-net status

Focused public-catalog, authenticated source-projection, file-action, and
frontend tests now protect independent Archive identities when exam metadata
matches. Focused submission-initiated and Archive-initiated trash/restore tests
also protect the exact pair while a same-metadata sibling remains unchanged and
publicly visible.

## Evidence and status labels

- **Confirmed by code:** Directly implemented in the inspected repository.
- **Confirmed by test:** Protected by a focused test with a matching assertion.
- **Intended invariant:** An approved product requirement, whether or not code
  currently conforms.
- **Partially implemented:** Some paths conform but the guarantee is incomplete.
- **Implementation gap:** Code does not yet implement an intended invariant.
- **Observed likely bug:** Static evidence suggests unintended behavior, but
  runtime/product confirmation may still be needed.
- **Inconsistent:** Equivalent paths currently produce different behavior.
- **Unknown:** Available static evidence is insufficient.
- **Decision required:** Product or architecture direction is not approved.
- **Planned follow-up:** Work belongs to a later explicit stage.

## Update policy

- A Domain behavior change updates the affected contract and focused tests in
  the same change.
- An internal refactor with unchanged observable behavior need not rewrite the
  contract, but existing contract tests must continue to pass.
- If code, tests, and these documents disagree, stop and report the conflict;
  do not silently choose one source.
- Do not promote observed behavior to an intended invariant without a product
  decision.
- Update only affected sections; do not rewrite unrelated Domain documents.

## Document map

- [Entity relationships](entity-relationships.md) defines ownership,
  dependency, grouping, and lifecycle relationships.
- [State transitions](state-transitions.md) defines states, allowed actions,
  authorization, visibility, and business-error semantics.
- [Notifications and side effects](notifications-and-side-effects.md) defines
  durable notifications, transaction boundaries, and external effects.
