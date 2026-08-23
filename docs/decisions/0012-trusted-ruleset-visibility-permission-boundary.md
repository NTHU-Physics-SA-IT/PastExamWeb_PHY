# ADR-0012 — Trusted Ruleset Visibility Permission Boundary

- ID: ADR-0012
- Title: Trusted Ruleset Visibility Permission Boundary
- Status: Superseded
- Date: 2026-08-23
- Scope:
  - Paths: `.github/workflows/trusted-governance-gate.yml`,
    `.github/workflows/issue-coordination-grant.yml`,
    `scripts/ci/trusted_governance_gate.py`, focused governance tests, GitHub
    App permissions, and Trusted Activation operator documentation
  - Concepts / Domain: live ruleset bypass proof, installation-token
    downscoping, and an administration-capable but semantically read-only API
    boundary
- Related documents:
  - [ADR-0011](0011-trusted-activation-for-protected-coordination.md)
  - [Trusted Activation runbook](../runbooks/trusted-activation.md)
  - [Validation policy](../development/validation.md)
- Related PR / issue: Trusted Activation governance permission corrective
- Supersedes: [ADR-0011](0011-trusted-activation-for-protected-coordination.md)
- Superseded by: [ADR-0013](0013-simplified-protected-coordination.md)

## Context

ADR-0011 requires the protected-main verifier to prove the live integration
ruleset has exactly one bypass actor and that the actor is the independent
GitHub App. Live calibration showed that an installation token with
Administration read can fetch the ruleset but GitHub omits `bypass_actors`.
GitHub documents that `bypass_actors` is returned only when the caller has
write access to the ruleset.

The App therefore needs Administration write as a platform capability. That
capability is broader than the verifier's semantic job and must not create a
general settings-mutation client.

## Decision

All Trusted Activation architecture, lifecycle, CI-mode, fail-closed,
candidate-isolation, and replay invariants from ADR-0011 remain in force.
This record replaces only its App permission and client-boundary decision.

The independent App has this exact repository permission matrix:

- Actions: write;
- Administration: write;
- Checks: write;
- Contents: write;
- Pull requests: read; and
- Metadata: read.

All other permissions and event subscriptions remain absent. Installation
remains selected-repository scope for PastExamWeb_PHY only.

Workflows create separate installation tokens and client boundaries:

1. The verifier/check token has Actions read, Checks write, Contents read, and
   Pull requests read. It has no Administration permission.
2. The issuance token has Contents write. It has no Administration or Checks
   permission.
3. A separate ruleset-auditor token has Administration write. It is accepted
   only by a dedicated client that permits `GET` to the exact
   `/repos/{owner}/{repository}/rulesets/{ruleset_id}` endpoint family.

The ruleset-auditor client rejects every non-GET method and every
non-allowlisted path before network access. It exposes no POST, PUT, PATCH, or
DELETE helper. The Administration-write token is never passed to the general
GitHub client, check emitter, or ref lifecycle client.

## Rationale

Live `bypass_actors` is required to prevent a candidate, administrator, team,
or second integration from silently becoming a trusted bypass. Cached settings
or a human credential would weaken independent, fail-closed proof. Token and
client separation confines the platform-required write capability to a
machine-enforced read operation.

## Alternatives considered

- Keep Administration read: rejected because the required live field is
  withheld and calibration fails closed.
- Trust a cached ruleset snapshot: rejected because it is not live authority.
- Use a PAT or human credential: rejected because it is not the independent
  App trust root.
- Give the general verifier client Administration write: rejected because it
  would make repository-setting mutations reachable from the verifier.
- Omit the bypass check: rejected as self-authorization risk.

## Invariants

- `bypass_actors` must be present, well formed, and contain exactly App 4688858.
- Missing, duplicate, wrong, malformed, unavailable, or ambiguous bypass
  evidence fails closed.
- The administration-capable client performs only allowlisted GET requests.
- Ruleset, branch-protection, repository-setting, collaborator, team, Actions,
  Environment, and secret mutations are unreachable from that client.
- The general verifier/check and issuance/ref clients carry no Administration
  permission.
- The verifier remains protected-main sourced and consumes no candidate code,
  artifact, cache, environment, or executable content.
- Main remains schema 1 with `coordination_branch: null` outside an activated
  lifecycle; Full, Equivalent, docs-only, and ADR-0006 behavior are unchanged.
- Every unchanged ADR-0011 security and lifecycle invariant remains binding.

## Consequences

- App 4688858 and installation 155855905 require one explicit permission
  update from Administration read to write.
- Calibration must prove live bypass visibility and the exact App-owned check
  before main requires the gate.
- A defect in the allowlist or token separation is a security failure, not a
  documentation-only issue.

## Conflict / integration guidance

Changes that add an administration endpoint, allow a mutation method, merge
the auditor token into another client, weaken unique-bypass validation, or
broaden App/repository scope conflict with this decision and require explicit
replacement authority. Preserve the rest of ADR-0011 together with this
correction.
