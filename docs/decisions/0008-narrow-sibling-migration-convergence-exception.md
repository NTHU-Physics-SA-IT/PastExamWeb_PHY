# ADR-0008 — Narrow sibling-migration convergence exception

- ID: ADR-0008
- Title: Narrow sibling-migration convergence exception
- Status: Proposed
- Date: 2026-08-18
- Scope:
  - Paths:
    `backend/alembic/versions/e8a4c1d7b2f6_add_category_pre_delete_active_state.py`,
    `backend/alembic/versions/a9c2e5f7b1d4_add_course_submission_lifecycle.py`,
    and
    `backend/alembic/versions/a9c4e7b2d6f1_add_bilingual_content_and_wish_pool.py`
  - Concepts / Domain: One known sibling-head migration convergence, exact
    branch-aware source-ledger and schema compatibility, and preservation of
    published migration immutability as the general rule
- Related documents:
  - [Alembic migration safety](../migration-safety.md)
  - [ADR-0003 — Coordination-branch freshness](0003-coordination-branch-freshness.md)
  - [ADR-0004 — Decision Record and semantic-conflict authority](0004-decision-record-and-semantic-conflict-authority.md)
  - [Decision Record index](README.md)
- Related PR / issue: PR #136, PR #134, and the bounded post-D3 migration
  convergence investigation
- Supersedes: None
- Superseded by: None

## Context

Stage 5D coordination and `main` both descended from the reviewed migration
revision `e6a1b3c5d7f9`, then independently introduced migrations before their
histories could be reconciled. The Stage 5D line is:

```text
e6a1b3c5d7f9 -> e8a4c1d7b2f6 -> a9c2e5f7b1d4
```

The `main` line introduced by PR #136 is:

```text
e6a1b3c5d7f9 -> a9c4e7b2d6f1
```

A Git reconciliation containing both lines therefore has two Alembic heads.
Their schema and data intentions are compatible, but each migration protects
its reviewed source with an exclusive ledger guard: `e8a4c1d7b2f6` requires
exactly `e6a1b3c5d7f9`, `a9c2e5f7b1d4` requires exactly
`e8a4c1d7b2f6`, and `a9c4e7b2d6f1` requires exactly
`e6a1b3c5d7f9`.

Disposable PostgreSQL experiments established that each branch upgrades
successfully alone, while stock Alembic cannot complete both branches from a
fresh `e6a1b3c5d7f9` database or from a database already at either sibling
head. Once one branch has run, the next sibling migration rejects the changed
ledger before applying its DDL. A standard no-op Alembic merge revision is
insufficient because execution never reaches that merge revision.

Scratch-only experiments also established technical viability for finite,
branch-aware guard compatibility from three reviewed starting baselines:
`e6a1b3c5d7f9`, `a9c2e5f7b1d4`, and `a9c4e7b2d6f1`. Those experiments were
design evidence, not production proof or migration authority. The revisions
present in production, shared persistent databases, and external developer
databases remain unknown unless separately proven.

Current migration safety makes published or deployed revision files
immutable. Guard changes inside these published revisions therefore require
explicit governance authority before implementation.

## Decision

This record is **Proposed** and is not operative authority. If it is later
Accepted together with the required operating-document updates, it authorizes
one narrow compatibility exception for the exact sibling convergence formed
by `e8a4c1d7b2f6`, `a9c2e5f7b1d4`, and `a9c4e7b2d6f1`.

Published and deployed migration revisions remain immutable by default. This
exception does not permit general historical migration edits, arbitrary
concurrent migration branches, or multiple repository heads as a final state.

Only the pre-DDL source-compatibility guards in the three named revisions may
be changed, and only as needed to recognize mechanically enumerated states
created by the other named sibling branch. The following elements remain
immutable:

- revision IDs;
- `down_revision` identities and order;
- `branch_labels` and `depends_on`;
- schema DDL and data backfill or transformation intent;
- named constraint and index intent;
- locking intent;
- post-upgrade target-schema intent; and
- downgrade schema and data intent.

Sibling ledger identity alone is never sufficient. Each accepted
compatibility state must prove both:

1. an exact, finite, reviewed migration-ledger identity or transition state;
   and
2. the exact sibling-specific schema continuity required for that state.

Unknown, malformed, partial, multiple, unreviewed, or schema-inconsistent
states fail closed. The later implementation may choose repository-consistent
helper names and Python structure, but it must keep the accepted combinations
finite, explicit, testable, and schema-backed.

The eventual convergence must prove safe upgrade to one merged head from at
least:

- `e6a1b3c5d7f9`;
- `a9c2e5f7b1d4`; and
- `a9c4e7b2d6f1`.

After the sibling guards are safely branch-aware, the implementation may add
a normal Alembic merge revision joining `a9c2e5f7b1d4` and
`a9c4e7b2d6f1`. The merge revision does not replace or pretend to perform
either sibling's DDL or data work.

The design must not rely on `alembic stamp`, manual insertion, update, or
deletion of `alembic_version` rows, skipped DDL, fictitious migration
execution, reparenting, or deletion of accepted revisions.

Before the later reconciliation can be accepted, its evidence must include:

- a static graph with exactly one head;
- disposable PostgreSQL upgrades from `e6a1b3c5d7f9`, `a9c2e5f7b1d4`, and
  `a9c4e7b2d6f1` to that head;
- rejection tests for unknown ledger and sibling-schema combinations;
- migration-safety and revision-specific guard tests;
- schema-manifest coverage and sealed-audit continuity;
- rollback and downgrade evidence required by repository policy;
- no canonical persistent database mutation; and
- the combined product and Domain tests required by the eventual ADR-0003
  Case-B reconciliation.

This decision does not authorize implementation while Proposed. Even after
acceptance, it does not authorize production or canonical-local migration,
stamping or repair, deployment, or the ADR-0003 Case-B execution. Each remains
a separately authorized operation.

## Rationale

The sibling schemas are compatible and the exclusive source guards, rather
than conflicting DDL or data intent, are the execution blocker. Preserving the
published revision IDs, ancestry, DDL, data transformations, and downgrade
intent is safer than rewriting migration history. Requiring a finite ledger
state together with exact sibling-schema continuity remains fail closed while
supporting databases that legitimately applied either branch.

This approach also retains the repository's guarded Alembic workflow instead
of introducing a second migration runner with separate ledger, transaction,
and recovery semantics.

## Alternatives considered

- **Standard Alembic merge revision only:** Rejected. Disposable PostgreSQL
  evidence showed that a guarded sibling fails before the merge revision is
  reached.
- **New forward revisions only with existing guards unchanged:** Rejected.
  Descendants cannot bypass the guarded sibling revision that Alembic must
  execute first.
- **Custom migration runner or Alembic environment:** Not selected. It would
  introduce a durable second orchestration contract with complex ledger,
  transaction, downgrade, and recovery semantics.
- **Rewrite, remove, or reparent accepted migrations:** Rejected. It violates
  published migration history and could make already-applied databases
  irreconcilable.
- **Manual stamp or version-table manipulation:** Rejected. Ledger identity
  cannot substitute for missing DDL, data transformations, or schema proof.
- **Leave the histories divergent indefinitely:** Rejected as the long-term
  state. ADR-0003 requires current `main` ancestry before the next coordinated
  task or closeout boundary.

## Invariants

- The exception applies only to `e8a4c1d7b2f6`, `a9c2e5f7b1d4`, and
  `a9c4e7b2d6f1`.
- Published migration immutability remains the repository default.
- Revision IDs, ancestry, DDL, data, locking, target-schema, and downgrade
  intent remain unchanged.
- An exact sibling ledger and exact sibling-schema continuity are both
  required; neither substitutes for the other.
- Unknown, partial, malformed, or unreviewed states fail closed.
- Every supported baseline converges to one repository head.
- No manual stamp or migration-ledger manipulation is permitted.
- This record grants no canonical-local or production database mutation,
  repair, deployment, or migration authority.
- ADR-0003 freshness remains required.
- D1, D2A, D2B, D3, and PR #136/#139 product semantics are reconciled
  independently of the migration-graph mechanics.
- This record does not broaden CI Equivalent policy.
- This record does not authorize arbitrary future sibling migration branches.

## Consequences

Benefits:

- the known divergent histories can converge safely;
- published identities, ancestry, schema intent, and data intent are
  preserved;
- reviewed databases already on either sibling branch have a tested forward
  path; and
- the repository can return to one migration head and satisfy ADR-0003
  freshness.

Costs and obligations:

- a narrow edit to already-published migration files becomes explicitly
  governed;
- three-baseline PostgreSQL matrix tests, rejection tests, manifests, audits,
  and rollback evidence are required; and
- future integrators must distinguish this exact compatibility exception from
  generic guard weakening or concurrent-migration support.

## Conflict / integration guidance

Stop for new owner and governance authority if implementation would require:

- changing revision IDs, `down_revision`, or other ancestry metadata;
- changing DDL, data transformation, lock, target-schema, or downgrade intent;
- accepting an unenumerated ledger or sibling-schema state;
- applying this exception to another revision or sibling branch;
- stamping, manual ledger repair, or skipped migration work;
- weakening sibling-schema continuity checks;
- applying a canonical-local or production migration; or
- modifying ADR-0003 or CI policy to make reconciliation easier.

An Accepted ADR-0008 would authorize only the exact guard-compatibility
boundary described here. Any broader migration policy requires a new,
explicitly reviewed decision.
