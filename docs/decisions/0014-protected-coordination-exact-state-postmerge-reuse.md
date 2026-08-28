# ADR-0014 — Protected Coordination Exact-State Postmerge Reuse

- ID: ADR-0014
- Title: Protected Coordination Exact-State Postmerge Reuse
- Status: Accepted
- Date: 2026-08-29
- Scope:
  - Paths: `.github/workflows/`, `scripts/ci/`, focused CI tests, and
    protected-coordination operating documentation
  - Concepts: Exact-state evidence reuse for a final same-repository protected
    integration merge
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Coordination runbook](../runbooks/coordination.md)
  - [ADR-0002](0002-ci-evidence-and-main-full-authority.md)
  - [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md)
  - [ADR-0007](0007-retain-full-fallback-for-post-case-b-reconciliation-tails.md)
  - [ADR-0010](0010-retain-full-fallback-for-governance-sensitive-ordinary-product-postmerge.md)
  - [ADR-0013](0013-simplified-protected-coordination.md)
- Related PR / issue: PR #207 and the protected postmerge Equivalent research
- Supersedes:
  - [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md), for current
    ADR-0013 protected coordination
  - [ADR-0010](0010-retain-full-fallback-for-governance-sensitive-ordinary-product-postmerge.md),
    only for the exact same-repository protected-integration postmerge route
  - [ADR-0013](0013-simplified-protected-coordination.md), only for its blanket
    Full conclusion on a qualifying final protected-integration merge
- Superseded by: None

## Context

ADR-0006 safely reused Source Full and PR Full evidence under the older shared-
governance coordination model. ADR-0013 later made canonical main permanently
`coordination_branch: null` while each active integration branch names itself,
so ADR-0006's complete-governance equality became unreachable.

Successive research rejected a broad trust-surface classifier, a growing path
allowlist, and a one-field governance exception because their value or
maintenance burden was disproportionate. A final differential audit found a
simpler boundary: Source Full and PR Full already execute the same heavy job
families as final-Q Full. For an exact normal merge, Q can prove that its tree is
the same repository state already tested as H and synthetic P.

This proof is not an independent verifier. The Q-side workflow and classifier
remain part of the candidate state. The repository Owner explicitly accepts a
normal protected merge as the trust-transfer point for that exact tested state,
including its CI semantics. This is the same bounded Owner boundary already
present when Q runs Full; it is not presented as stronger authentication.

## Decision

For a same-repository pull request into the exact active protected integration
branch, Source Full for H and PR Full for P remain mandatory and may overlap. A
normal Owner merge producing Q may use the existing `equivalent-merge` path
only when machine validation proves all of the following:

- the push is non-forced, targets the exact active integration ref, and contains
  exactly one normal two-parent Q with ordered parents `(C, H)` and `before=C`;
- H has supported linear history from C or is one exact two-parent merge from C;
  post-Case-B reconciliation tails and other embedded merge histories are Full;
- exactly one merged same-repository PR binds base C, head H, and merge Q;
- exact, fresh, unique, successful Source Full and PR Full runs use the approved
  workflow identity, distinct run IDs, and uniquely successful required jobs;
- the PR Full attestation identifies exact synthetic P, with
  `parents(P)=(C,H)` and `tree(P)=tree(H)=tree(Q)`;
- H to Q has no content difference or merge-only content;
- current main is contained in H; and the integration ref, main ref, and merged
  PR identity remain unchanged through validation.

Every missing, malformed, stale, failed, ambiguous, unsupported, unavailable,
or drifted fact falls back to Full. The proof does not compare governance or CI
paths with main and defines no path allowlist.

Source pushes and pull requests into protected coordination remain Full.
Canonical Start remains the only `coordination-start` event. Main pushes are
always Full and main never uses Equivalent. Reconciliation tails, return and
close lifecycle operations, release, production, and hotfix routes remain
Full. Squash, rebase, fast-forward, octopus, forced, fork-origin, and otherwise
unsupported final transitions remain Full.

No new workflow, required check, GitHub App, Environment, secret, Owner
ceremony, approval count, or auto-merge dependency is introduced. The existing
Equivalent provenance job and `CI Gate` topology carry the result.

## Rationale

The repository already accepts candidate-controlled CI semantics at the normal
Owner merge boundary. Requiring both heavy premerge gates and proving exact
C/H/P/Q state transfer avoids a third duplicate heavy execution without
claiming an independent trust root. A simple exact-state contract is smaller
and more auditable than classifying which governance-looking files are product
state or CI control state.

Historical analysis recovered exact P/Q evidence for all eight modern sampled
protected merges that were theoretical candidates. Their final-Q Full runs
totalled about 100 minutes 51 seconds of wall time and roughly 301 job-minutes,
while the historical lightweight path was about 30 seconds. Full remains the
safe and operationally simple fallback.

## Alternatives considered

- Keep every final Q Full: safe, but retains material duplicate heavy work.
- Restore complete governance equality or exempt selected governance paths:
  rejected because ADR-0013 makes the former unreachable and the latter grows
  a brittle trust-surface policy.
- Operate an independent App, Environment, or verifier: rejected as unnecessary
  for the explicitly accepted Owner trust-transfer model.
- Weaken Source Full or PR Full: rejected; each remains a distinct mandatory
  gate.
- Extend the route to main, lifecycle tails, release, or production: rejected;
  those authorities remain Full.

## Invariants

- Source Full and PR Full are both mandatory and may run independently.
- Only an exact same-repository protected-integration final Q may qualify.
- Main pushes are Full and main never uses Equivalent.
- Start, reconciliation tails, return/close, release, production, and hotfix
  remain governed by their existing Full or dedicated lifecycle paths.
- All ambiguity and unavailable evidence fail closed to Full.
- No governance equality, path exception list, or dynamic trust-surface engine
  authorizes this route.
- Required checks, Apps, Environments, rulesets, and heavy-job topology are
  unchanged.
- Equivalent is exact-state provenance, not independent verifier identity.

## Consequences

Qualifying final integration merges can finish through a lightweight existing
provenance job after the two retained Full workflows. Unsupported histories or
evidence failures still pay the existing Full cost. The first future natural
qualifying integration merge is the live canary; a main-target PR cannot
exercise this route.

The candidate-controlled Q verifier remains a conscious residual risk accepted
at the trusted Owner merge boundary. If Q gains materially different secrets,
permissions, Environment access, or push/ref-specific heavy behavior, this
decision must be reviewed before reuse continues.

## Conflict / integration guidance

Do not generalize this decision into governance exceptions or reuse on main.
Do not skip either Full input, weaken topology or freshness checks, admit forks
or unsupported merge methods, or make a reconciliation tail eligible. Changes
to merge strategy, rulesets, Full semantics, attestation availability, Q-only
permissions, or heavy push/ref behavior require explicit re-evaluation and a
new decision if the accepted boundary changes.
