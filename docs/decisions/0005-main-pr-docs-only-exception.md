# ADR-0005 — Main pull-request docs-only exception

- ID: ADR-0005
- Title: Main pull-request docs-only exception
- Status: Accepted
- Date: 2026-08-13
- Scope:
  - Paths: `.github/workflows/main.yml`, `scripts/ci/classify_ci_mode.py`, and
    CI-related operating documentation
  - Concepts / Domain: Docs-only classification for pull requests targeting
    `main`
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [ADR-0001](0001-main-first-parallel-development.md)
  - [ADR-0002](0002-ci-evidence-and-main-full-authority.md)
- Related PR / issue: None known
- Supersedes: Only the clauses in ADR-0001 and ADR-0002 requiring every
  pull request targeting `main` to use Full CI
- Superseded by: None

## Context

The centralized classifier already defines a narrow lightweight path set and
uses docs-only mode for qualifying source-branch changes. Requiring Full CI for
every pull request targeting `main`, including changes conclusively limited to
that set, consumes application lint, test, build, and browser resources that
cannot validate the documentation change. The workflow's stable job and gate
structure can represent those heavy jobs as intentionally skipped without
removing required check names.

## Decision

Pull requests targeting `main` use Full CI by default. They may use docs-only
mode only when their event identity is complete and valid and every changed
path satisfies the existing centralized lightweight classifier. Governance,
CI, configuration, dependency, migration, application, mixed, unknown, empty,
or ambiguously classified changes remain Full.

The exact pushed or merged `main` SHA continues to use Full CI. Main never uses
Equivalent evidence. Coordination and ordinary feature-branch behavior are
unchanged.

## Rationale

This exception restores the existing bounded docs-only efficiency policy at
the classifier rather than duplicating path rules in workflow leaves. Keeping
the workflow active preserves stable checks and the final gate, while strict
identity and path validation preserves fail-closed behavior.

## Alternatives considered

- Keep every main pull request Full: rejected because it spends full CI
  resources on conclusively lightweight changes.
- Add workflow-level path filters or leaf-specific allowlists: rejected because
  they can destabilize required checks and duplicate classification policy.
- Broaden the lightweight path set: rejected because this decision authorizes
  only the existing centralized policy.

## Invariants

- Exact `main` pushes use Full CI.
- A main-target pull request uses docs-only only when every changed path is
  conclusively lightweight under the centralized classifier.
- Governance, CI, configuration, dependency, migration, application, mixed,
  unknown, empty, and ambiguous changes use Full CI.
- Main never uses Equivalent evidence.
- Stable workflow, job, and required-check names remain available when heavy
  work is skipped.
- Classification uncertainty fails closed.

## Consequences

- Qualifying documentation-only main pull requests avoid heavy application CI
  while still running classification, docs-gate revalidation, and CI Gate.
- Non-lightweight main pull requests and exact main pushes retain their prior
  workload and evidence requirements.
- Future lightweight-policy changes remain centralized in the classifier.

## Conflict / integration guidance

This record supersedes only the blanket Full-CI requirement for conclusively
docs-only main pull requests in ADR-0001 and ADR-0002. Preserve every unrelated
main-first, reconciliation, provenance, Full-main-push, Equivalent, and
fail-closed invariant from those records. Any broader exemption requires a new
explicit policy decision.
