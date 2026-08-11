# ADR-0002 — CI evidence and main Full authority

- ID: ADR-0002
- Title: CI evidence and main Full authority
- Status: Accepted
- Date: 2026-08-11
- Scope:
  - Paths: `.github/workflows/`, `.github/project-governance.json`,
    `scripts/ci/`, and CI-related operating documentation
  - Concepts / Domain: Full, Equivalent, and docs-only evidence authority
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Project governance configuration](../../.github/project-governance.json)
- Related PR / issue: None known
- Supersedes: None
- Superseded by: None

## Context

The repository already implements three CI evidence modes and fail-closed
classification. Their names can be mistaken for product-impact labels or for
permission to transfer evidence into later formal gates. This record preserves
the rationale and authority boundaries of the existing policy; it does not
redesign its implementation.

## Decision

Pull requests targeting `main` use Full CI. An exact pushed or merged `main`
SHA also uses Full CI. Main never uses Equivalent evidence.

An ordinary eligible pull request or merge involving the exact machine-resolved
coordination branch may use the existing Equivalent provenance path only when
current repository contracts permit it. Governance-sensitive coordination
changes fall back to Full. Documentation-only source changes may use docs-only
when the classifier's current path and event rules permit. Unknown, malformed,
stale, unavailable, or otherwise unsafe evidence fails closed according to the
current implementation.

The exact `.github/CODEOWNERS` path is allowlisted as lightweight repository
metadata for ordinary source-branch classification and uses the existing
docs-only mode when every changed path is lightweight. This does not treat
arbitrary `.github/` content as documentation, create a new CI mode, or exempt
main PRs and exact main pushes from Full. A mixed change follows the highest-risk
path under the existing fail-closed priority rules.

Successful source evidence does not authorize weakening a later formal PR,
main, or merge-commit gate. Full, Equivalent, and docs-only describe CI
evidence modes; they are not product-impact or Domain-risk labels.

For pull-request runs, the GitHub-tested synthetic merge SHA and the PR source
or execution-head SHA have distinct roles. Current CI scripts remain
implementation authority for exact run and attempt identity, tree and workflow
revision evidence, required jobs, provenance, and fail-closed validation.

## Rationale

Full CI protects the repository's final integration authority on `main`.
Equivalent avoids redundant work only when an exact, fresh, topology-bound
Full source result proves the same eligible content. Docs-only permits bounded
validation for qualifying changes. Keeping those paths fail-closed prevents
missing or ambiguous evidence from silently weakening a formal gate.

## Alternatives considered

- Allow main to reuse Equivalent source evidence: rejected because main is the
  final repository integration authority and must retain Full evidence.
- Treat CI mode as a product-risk label: rejected because mode selection is an
  execution-evidence policy, not a Domain classification.
- Hardcode successful historical run IDs: rejected because current exact
  run/attempt and SHA validation must determine authority.
- Force all changes through Full: rejected because the established Equivalent
  and docs-only paths are safe only under their current bounded contracts.

## Invariants

- A `main` PR and exact pushed or merged `main` SHA use Full CI.
- Main never uses Equivalent evidence.
- Coordination can use Equivalent only when the current machine contracts
  prove eligibility and exact provenance.
- Governance-sensitive coordination falls back to Full.
- Docs-only applies only when current classifier rules permit.
- Unknown or unsafe evidence fails closed.
- Source success never weakens a later formal gate.
- Synthetic merge and execution/source-head identities remain distinct where
  the current PR attestation contract requires them.

## Consequences

- CODEOWNERS-only source changes can use the lightweight docs-only path because
  broad runtime suites do not validate review-routing metadata; mixed
  higher-risk changes and formal main gates still use Full.
- Coordination evidence can reduce duplication without transferring authority
  to main.
- Durable documentation records policy and rationale while exact workflow,
  run, attempt, and SHA checks remain in machine-enforced implementation.

## Conflict / integration guidance

Do not change CI mode semantics from this rationale record alone. Reconcile any
workflow, classifier, attestation, or project-governance change against the
current machine contracts and validation policy. If a requested change would
make main Equivalent, bypass exact evidence, or weaken fail-closed behavior,
stop for explicit authority and supersede this record if the decision is
intentionally replaced.
