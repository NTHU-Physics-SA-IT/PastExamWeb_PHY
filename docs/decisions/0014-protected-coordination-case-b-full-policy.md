# ADR-0014 — Protected Coordination Case-B Full Policy

- ID: ADR-0014
- Title: Protected Coordination Case-B Full Policy
- Status: Accepted
- Date: 2026-08-28
- Scope:
  - Paths: `.github/project-governance.json`, `scripts/ci/`, focused CI tests,
    and protected-coordination operating documentation
  - Concepts / Domain: Current Case-B postmerge CI policy under ADR-0013
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Coordination runbook](../runbooks/coordination.md)
  - [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md)
  - [ADR-0007](0007-retain-full-fallback-for-post-case-b-reconciliation-tails.md)
  - [ADR-0010](0010-retain-full-fallback-for-governance-sensitive-ordinary-product-postmerge.md)
  - [ADR-0013](0013-simplified-protected-coordination.md)
- Related PR / issue: Round 3A ADR-0006 × ADR-0013 consistency audit
- Supersedes: [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md)
  for current ADR-0013 protected coordination
- Superseded by: None

## Context

ADR-0006 safely reused exact Source Full and PR Full evidence under the older
coordination model, where main and integration shared the same non-null project
governance. Historical PR #101 and the PR #95 contract fixture preserve that
positive evidence.

ADR-0013 later made canonical main permanently
`coordination_branch: null` while requiring every active integration branch to
name itself. The ADR-0006 verifier still requires the complete governance
inventory of the Case-B source `S` to be Git-object-identical to main `M`,
including `.github/project-governance.json`. A valid active ADR-0013 branch
therefore cannot satisfy the historical positive premise. Post-ADR-0013 exact
Case-B refreshes #177, #194, and #204 all ran postmerge Full.

## Decision

Current ADR-0013 protected coordination uses Full CI for Case-B Source pushes,
pull requests, and final postmerge pushes. The exact trusted Start bootstrap is
the only protected-coordination lightweight exception and retains its existing
`coordination-start` contract.

The classifier routes every active protected-coordination push after Start
directly to Full. It does not attempt the historical ADR-0006 verifier. The
historical verifier and fixtures may remain for bounded evidence and regression
context, but they are not current eligibility authority.

ADR-0007's post-Case-B-tail Full decision and ADR-0010's governance-sensitive
ordinary-product Full decision remain unchanged. Generic Equivalent behavior,
main docs-only behavior, required checks, workflows, and branch protection are
unchanged.

## Rationale

Explicit Full routing matches the only mechanically reachable safe behavior,
removes misleading evidence lookups, and makes current policy readable from
ADR-0013 and the operator documentation. It avoids introducing a special-case
comparison that would weaken complete-governance trust merely to recover a CI
optimization.

## Alternatives considered

- Exempt branch-local project governance from ADR-0006: rejected because it
  changes the trust proof and requires a separately reviewed design.
- Add split-TCB, protected-base inheritance, or an external verifier: rejected
  as new security infrastructure outside this correction.
- Keep fail-closed probing as the operational policy: rejected because it
  preserves unreachable authority and unnecessary control-flow complexity.

## Invariants

- Active protected coordination after Start is Full, including exact Case-B
  reconciliation and final postmerge.
- Exact canonical Start remains eligible only for `coordination-start`.
- Main, release, production, hotfix, docs-only, and generic Equivalent behavior
  remain governed by their existing independent authorities.
- ADR-0007 and ADR-0010 Full fallbacks remain unchanged.
- Historical ADR-0006 evidence must not be presented as current ADR-0013
  reachability.
- Missing or ambiguous authority continues to fail closed; no new CI mode,
  required check, App, credential, or ruleset is introduced.

## Consequences

- A protected Case-B refresh runs a postmerge Full even after Source Full and PR
  Full succeed.
- Current classifier routing no longer performs unreachable postmerge
  provenance API work.
- Historical ADR-0006 rationale and positive evidence remain available for
  audit, while current operating documents have one direct rule.

## Conflict / integration guidance

Reopening protected Case-B Equivalent requires a new Decision Record and
materially new evidence: a trustworthy platform/verifier identity and proof
model that accommodates mandatory branch-local governance, or economics that
justify explicitly operating such infrastructure. Do not weaken governance
identity, required checks, or fail-closed behavior inside an optimization.
