# ADR-0013 — Simplified Protected Coordination

- ID: ADR-0013
- Title: Simplified Protected Coordination
- Status: Accepted
- Date: 2026-08-23
- Scope:
  - Paths: `.github/project-governance.json`, `.github/coordination/`,
    `.github/workflows/`, `scripts/ci/`, focused CI tests, branch protection,
    integration rulesets, protected Environments, and operator documentation
  - Concepts: main-null semantics, temporary integration authority, operator
    usability, freshness, safe return, and ref retirement
- Related documents:
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Validation policy](../development/validation.md)
  - [Collaboration runbook](../development/collaboration-and-conflict-resolution.md)
  - [Coordination runbook](../runbooks/coordination.md)
  - [ADR-0002](0002-ci-evidence-and-main-full-authority.md)
  - [ADR-0003](0003-coordination-branch-freshness.md)
  - [ADR-0010](0010-retain-full-fallback-for-governance-sensitive-ordinary-product-postmerge.md)
- Related PR / issue: Trusted Activation simplification and safe recovery
- Supersedes: [ADR-0012](0012-trusted-ruleset-visibility-permission-boundary.md)
- Superseded by: None

## Context

The project needed one semantic distinction: canonical main with
`coordination_branch: null` is an ordinary development base that does not point
to a current coordination target. It does not prohibit a separately protected
`integration/*` branch from carrying branch-local coordination authority.

ADR-0011 and ADR-0012 expanded that need into a protected-main grant, claim,
UUID, ruleset digest, independent required check, revocation, tombstone, six
operational states, and mandatory second-person Environment approval. That
model primarily made candidate Full evidence eligible for Equivalent reuse.
It imposed a post-CI App-check tail on every ordinary main pull request and
made operators transcribe machine identifiers. Those costs do not match this
repository's real single-owner threat model.

The obsolete rehearsal grant
`714d9c51-8b6b-405d-bd7c-4c92f6f26699` was merged, but its issuance run was
cancelled before execution and its ref never existed. The identity and exact
name are permanently recorded as `aborted-before-issuance`; no fictitious
revocation is created.

## Threat model

The design protects against an Agent misreading main null, an arbitrary
candidate creating or self-authorizing a coordination ref, force-push or
deletion of active integration, stale work continuing as fresh, return before
containment, candidate impersonation of a retained integration check, and
accidental reuse of the obsolete rehearsal identity.

It does not optimize routine operation against a malicious repository Owner
who already has repository administration authority.

## Decision

PastExamWeb_PHY adopts the App-assisted minimal model (S1):

1. Canonical main always remains schema 1, default base `main`, and
   `coordination_branch: null`.
2. A protected-main workflow accepts only `start|close` and a short human name.
   It resolves exact main and settings, generates the suffix, and uses the
   existing App only for exact integration ref lifecycle writes.
3. Start creates one commit directly from exact Green main whose only content
   change makes branch-local project governance name the new exact branch.
4. The pre-existing `integration/*` ruleset restricts creation/deletion to the
   lifecycle App, blocks non-fast-forward updates, requires pull requests,
   strict `check-branch`, strict `CI Gate`, and conversation resolution.
5. Routine integration review requires no approval count, CODEOWNER review, or
   last-push approval. One Owner remains sufficient.
6. Coordination changes use Full CI. Equivalent eligibility no longer depends
   on a candidate-authenticated Trusted Activation protocol.
7. The App-owned Trusted Governance Gate is required by neither ordinary main
   nor integration. Its historical verifier becomes dormant after live
   required-check dependencies are removed.
8. Main advancing beyond an integration head makes that coordination STALE.
   Normal reconciliation is required before freshness-sensitive operations.
9. Final coordinated work returns through a normal main pull request with
   canonical main governance restored to null. Close requires the frozen
   integration head to be an ancestor of exact Green main, creates an App-owned
   closeout commit with main's exact tree and both heads as parents, verifies
   branch-local governance is null, then deletes only that exact ref.
10. New names use a generated random suffix and uniqueness is not an authority
    predicate. The obsolete already-granted identity remains explicitly and
    permanently retired.

The stable human interface is:

> Start `<name>` coordination.

> Close `<name>` coordination.

The Actions fallback requires only `operation` and `name`. Humans never enter
UUIDs, SHAs, repository/App/installation/ruleset IDs, or digests.

The workflow keeps three privilege boundaries: the ref-lifecycle App token has
only Contents write; exact-main CI evidence uses the workflow's separate
Actions-read `GITHUB_TOKEN`; and the Administration-write token enters only a
dedicated exact ruleset-by-ID GET auditor with no general request or mutation
method.

## Component complexity review

| Component | Decision and concrete failure prevented | Why simpler existing control is insufficient | Operator / CI / recovery cost |
| --- | --- | --- | --- |
| App 4688858 | Retain only for exact protected ref create/update/delete. Prevents arbitrary candidates from creating their own active integration ref. | GitHub Actions App 15368 is shared by candidate workflows; an Owner token would create a hidden human-only path. | No identifier entry; one lifecycle run with separated short-lived tokens; bounded retry from exact read-back. |
| `integration/*` ruleset | Retain. Prevents force push, deletion, direct unreviewed updates, and non-Green merges. | Branch naming and documentation cannot enforce Git writes. | Normal PR/CI only; settings read-back makes recovery explicit. |
| Trusted Governance Gate | Remove from main and integration active use. It authenticated candidate Equivalent evidence, which S1 no longer permits. | Strict `check-branch`, strict `CI Gate`, App-only ref creation, and Full-only coordination cover the selected threat model. | Zero main or integration tail. |
| `trusted-governance-verifier` Environment | Retain dormant for audit/rollback only. | Deletion is outside scope and adds no safety. | Zero runtime or human review. |
| `trusted-coordination-issuance` Environment | Retain for secret and protected-main scope; remove reviewer and prevent-self-review. Prevents candidate access to App credentials. | Repository variables alone do not scope the private key to protected-main workflow use. | One Owner; no waiting approval; admin bypass stays disabled. |
| Grant / claim / activation UUID | Do not use for new coordination. They authenticated Equivalent eligibility that no longer exists. | Protected App-only creation plus branch-local exact identity is sufficient for Full-only coordination. | Historical files remain immutable; no new ceremony or recovery chain. |
| Revocation ledger | Do not use. Safe close is based on exact containment, null closeout tree, and exact ref deletion. | A revocation adds a main PR without preventing a failure not already blocked by containment and ruleset checks. | Eliminates an extra main merge and partial-pair recovery. |
| Tombstone ledger | Do not use for random-suffixed new branches. Retain one explicit obsolete-identity retirement record. | New uniqueness is not authority; the already-granted obsolete identity needs permanent historical rejection. | No routine ledger PR; one bounded historical record. |
| Heavy lifecycle states | Replace with `ACTIVE`, `STALE`, `RETURN_READY`, and `RETIRED`; ordinary main is simply ordinary. | The removed states represented grant/claim/revocation transitions that no longer exist. | Plain Git recovery language; fewer partial states. |
| Manual issuance and replay preflight | Replace with name-only start/close. Prevents transcription errors and stale identifier reuse. | Documentation cannot make multi-ID copy/paste reliable. | Two human intents, one actor, machine-generated metadata. |

## Alternatives considered

### S0 — GitHub-native minimal

Rejected because the current ruleset must restrict first creation and deletion,
but GitHub's shared Actions identity cannot safely perform that bypass. An
Owner-token-only script would split Codex and human operation and make the
privileged path depend on ambient human credentials.

### Preserve the heavy model

Rejected because its primary benefit is trusted Equivalent reuse. It requires
manual machine identifiers, a second actor, three immutable ledgers, additional
states, a broad App permission workaround, and an ordinary-main required-check
tail. Sunk implementation cost is not a reason to retain it.

### Branch-local governance with unrestricted ref creation

Rejected because a candidate with contents write could create an integration
ref whose initial tree names itself. App-only creation is the external fact
that prevents that self-authorization.

## Invariants

- Main null means main has no coordination target; it does not mean no
  integration coordination exists.
- Main is never rewritten to name an integration branch.
- An active integration branch names exactly itself and current main is its
  ancestor.
- Only the retained App may create or delete matching refs.
- Integration refs cannot be force-pushed or directly mutated outside the
  protected lifecycle and normal PR rules.
- Coordination uses Full CI; no candidate evidence authenticates Equivalent.
- Main advancement makes coordination STALE without mutating it.
- Close requires final integration containment in Green main, clears local
  governance, and deletes only the exact resolved ref.
- Ordinary main development has no coordination action, approval, secret use,
  App gate, or coordination-only latency.
- The obsolete rehearsal UUID and name are never reused.

## Consequences

Coordination gives up Equivalent CI reuse in exchange for a much smaller trust
protocol. Start and close consume one short lifecycle workflow each; ordinary
main returns to its pre-Trusted-Activation check set. Existing App,
installation, key, Environments, legacy workflows, and historical ledgers may
remain dormant for audit and rollback; deleting permanent resources is outside
this decision.

## Conflict / integration guidance

Any change that lets candidate code create the protected ref, makes main
non-null, makes coordination eligible for Equivalent without a new explicit
trust decision, permits force/deletion, closes before containment, or adds
machine-ID or second-person steps conflicts with this decision. A future
high-risk dual-control mode must be optional and separately justified.
