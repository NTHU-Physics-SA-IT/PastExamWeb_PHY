# ADR-0011 — Trusted Activation for Protected Coordination

- ID: ADR-0011
- Title: Trusted Activation for Protected Coordination
- Status: Superseded
- Date: 2026-08-23
- Scope:
  - Paths: .github/trusted-activation/, .github/workflows/,
    .github/project-governance.json, scripts/ci/, focused CI tests, branch
    protection, rulesets, GitHub Environments, and operator documentation
  - Concepts: temporary coordination authority, independent verifier identity,
    protected creation, freshness, revocation, return, and retirement
- Related documents:
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Validation policy](../development/validation.md)
  - [Collaboration runbook](../development/collaboration-and-conflict-resolution.md)
  - [Trusted Activation runbook](../runbooks/trusted-activation.md)
  - [ADR-0002](0002-ci-evidence-and-main-full-authority.md)
  - [ADR-0003](0003-coordination-branch-freshness.md)
  - [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md)
  - [ADR-0007](0007-retain-full-fallback-for-post-case-b-reconciliation-tails.md)
  - [ADR-0010](0010-retain-full-fallback-for-governance-sensitive-ordinary-product-postmerge.md)
- Related PR / issue: Trusted Activation governance closure
- Supersedes: None
- Superseded by: [ADR-0012](0012-trusted-ruleset-visibility-permission-boundary.md)

## Context

Main-first development intentionally keeps canonical main governance at schema
1, default base main, and coordination branch null. A future bounded milestone
still needs a way to activate one protected integration branch temporarily.
Branch-local governance alone is insufficient because a candidate could write
its own coordination value and then claim Equivalent evidence.

ADR-0007 and ADR-0010 established the trust problem. Candidate workflows and
trusted workflows otherwise share GitHub Actions App ID 15368. Exact graph,
tree, workflow-path, and byte identity are useful evidence, but candidate code
cannot authenticate its own proof.

The owner has accepted the operating cost of a private GitHub App, protected
Environments, a pre-existing ruleset, immutable protected-main ledgers, and a
bounded lifecycle rehearsal. This is a new coordination-authority decision;
it does not reopen ADR-0010's ordinary-product postmerge optimization.

## Threat model

An attacker may control a source branch and every file in its proposed tree,
including a fake claim, workflow, classifier, check name, or local governance
value. The attacker may replay historical identity, present stale ancestry,
omit or duplicate records, or exploit unavailable or ambiguous API results.

The normal candidate path does not control protected main, protected
Environment secrets, the independent App installation, the pre-existing
integration ruleset, or the App-owned required check. Administrative
compromise remains an operational risk.

## Decision

PastExamWeb_PHY adopts:

> protected-main activation grant + pre-existing integration protection +
> protected-main-sourced verifier + independent GitHub App required check +
> branch-local claim constrained by external authority.

Protected main owns the policy, schemas, immutable UUID-named grants,
revocations, retired-name tombstones, validator, verifier, and dormant
workflows. The integration branch owns only a strict claim and its existing
schema-1 project-governance value. Those branch-local values are claims, not
authority.

### Formal active-authority rule

For repository R, branch B, activation UUID A, branch head H, and current main
M, coordination authority is active only if:

1. live repository ID and name equal policy;
2. exactly one protected-main grant G for R/B/A exists and retains its exact
   recorded blob;
3. claim C binds G's path, protected-main commit, blob, policy version/digest,
   ruleset ID/digest, and verifier App ID;
4. branch-local schema-1 project governance names exactly B;
5. the live verifier App equals the grant and claim, differs from App 15368,
   and issues Trusted Governance Gate;
6. the live active ruleset ID/digest equals the grant and claim, covers
   refs/heads/integration/*, restricts creation/deletion to the App, blocks
   force push, requires protected PR review, and binds the App check;
7. live B is protected and equals H;
8. M is an ancestor of H;
9. no matching revocation exists;
10. neither B nor A is tombstoned; and
11. every identity, record, API result, and multiplicity is strict, available,
    supported, and unambiguous.

Any false, missing, stale, malformed, duplicate, unavailable, or ambiguous
predicate makes authority inactive.

### Lifecycle

- ORDINARY: no claim or grant applies.
- PROTECTED_INACTIVE: a grant exists but no claim is merged.
- ACTIVATION_TRANSITION: a Full PR proposes the exact claim and branch-local
  governance. The App gate may be Green, but authority remains inactive until
  merge.
- ACTIVE: every formal predicate holds.
- STALE: current main is not an ancestor. Equivalent is disabled until Full
  reconciliation.
- REVOKED: protected main has a matching revocation. Authority is already
  false even while the old claim remains.
- DEACTIVATION_TRANSITION: a Full PR incorporates current main/revocation and
  removes claim/local coordination. The gate may be Green but authority is
  false.
- RETURN_READY: revocation exists, claim is absent, local governance is null,
  and current main is an ancestor.
- retired: the ref is deleted only after its exact tip is contained in main;
  branch name and UUID remain permanently unusable.

Trusted Governance Gate success is intentionally not synonymous with active
coordination authority. Valid activation and deactivation transitions require
a Green gate while remaining Full-only and inactive.

### CI authority

This decision adds no fourth CI mode. Full, equivalent-merge, and docs-only
remain the only modes.

- Exact main pushes remain Full.
- Main PRs retain ADR-0005 Full/docs-only behavior.
- Activation, reconciliation, deactivation, governance, and ambiguity are Full.
- ADR-0006 exact Case-B behavior remains unchanged.
- An active branch may use existing generic Equivalent only after the
  classifier resolves the external grant/claim and trusted settings.
- A local coordination value or claim without external authority cannot enter
  the coordination allowlist.
- The App-owned gate separately re-verifies live authority from protected main.

### Verifier and issuance

The verifier runs from workflow_run on protected main. It checks out current
main only, uses exact-revision-pinned official actions, requests a
repository-scoped token downscoped to read metadata plus checks-write, never
checks out or executes candidate code, never downloads candidate artifacts or
restores candidate cache, consumes only bounded claim JSON and GitHub
metadata, and emits an App-owned exact-head check.

Issuance runs through the trusted-coordination-issuance Environment with a
separate token downscoped to administration-read and contents-write. It
requires exact main/grant/App/ruleset/branch absence/non-retirement, creates
the ref exactly at the grant commit under the pre-existing ruleset, and
deletes only a revoked/tombstoned ref already contained in main. Replay
preflight performs no mutation and must reject retired identity.

Real issuance retains explicit Owner Environment approval. Prevent-self-review
and no-admin-bypass are not disabled for convenience.

## Alternatives considered

- Branch-local governance alone: rejected as self-authorization.
- Protected-main grant without an independent check: rejected because
  candidate Actions retain the shared issuer.
- Candidate-proved graph/tree/TCB equality: rejected as circular.
- Permanent non-null main coordination: rejected because coordination is
  bounded and ordinary work stays main-first.
- Protect after branch creation: rejected due the first-existence race.
- Reuse a deleted branch name or UUID: rejected as replay ambiguity.
- Disable Environment approval boundaries: rejected because rehearsal must
  prove the future control.
- Use App 15368: rejected because it is not distinct from candidate workflows.

## Invariants

- An integration branch cannot authorize itself.
- A branch-local record alone is never authority.
- Trust originates outside untrusted branch content.
- Protection applies from first existence.
- The check issuer differs from App 15368.
- The verifier comes from protected main and executes no candidate code.
- Activation binds repository, branch, UUID, policy, ruleset, App, grant,
  blob, main, and SHA.
- Ambiguity/unavailability fail closed.
- Main advancement makes authority stale without branch mutation.
- Revocation ends authority before claim removal.
- Deactivation precedes return.
- Retired names and UUIDs are never reused.
- Main remains schema 1/null with no active claim.
- Ordinary independent work remains fresh-main-first.
- Protection and evidence are never weakened for availability.

## Failure and recovery

- Calibration failure before requirement leaves main protection unchanged.
- A newly required check that deadlocks valid PRs is rolled back only to the
  exact prior required-check list, repaired, recalibrated, then re-added.
- Partial creation remains protected inactive and is revoked/tombstoned before
  trusted retirement if abandoned.
- Failed activation does not merge.
- Failure after ACTIVE freezes, revokes, Full-deactivates, safely returns, and
  retires without bypass.
- Credential incident disables use, rotates the key, and blocks rehearsal
  until independent trust is restored.
- Recovery never uses force, protection weakening, candidate execution,
  history rewrite, or identity reuse.

## Consequences

Coordination now has an explicit credential and settings lifecycle. Ordinary
main development receives one additional independent required check after
calibration. App/API outage conservatively blocks governed merges.
Administrators must protect reviewers, secrets, bypass actors, App bindings,
and variables. A bounded real rehearsal is required before closure.

## Conflict / integration guidance

Changes to policy, schemas, verifier, workflows, ruleset, App permissions,
Environment boundaries, classifier eligibility, or return ordering are
governance-sensitive. Preserve ADR-0002, ADR-0003, ADR-0006, ADR-0007,
ADR-0010, and this record together.

If a change lets candidate content authenticate itself, makes main Equivalent,
activates before merge, returns while active, reuses identity, or weakens
protection, stop. Intentional replacement requires a superseding Decision
Record and coherent machine, settings, test, and runbook changes.
