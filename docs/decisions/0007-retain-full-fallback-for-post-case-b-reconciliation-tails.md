# ADR-0007 — Retain Full Fallback for Post-Case-B Reconciliation Tails

- ID: ADR-0007
- Title: Retain Full Fallback for Post-Case-B Reconciliation Tails
- Status: Accepted
- Date: 2026-08-15
- Scope:
  - Paths: `.github/workflows/`, `.github/project-governance.json`,
    `scripts/ci/`, focused CI contract tests, and CI operating documentation
  - Concepts / Domain: Post-Case-B reconciliation-tail evidence reuse and its
    CI trust boundary
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [ADR-0002](0002-ci-evidence-and-main-full-authority.md)
  - [ADR-0003](0003-coordination-branch-freshness.md)
  - [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md)
  - [ADR-0014](0014-protected-coordination-exact-state-postmerge-reuse.md)
- Related PR / issue: PR #114
- Supersedes: None
- Superseded by: None

## Context

ADR-0006 permits coordination postmerge Full-evidence reuse only when the
final source itself has the exact supported Case-B shape. PR #114 exposed a
legitimate history in which an exact Case-B anchor was followed by a linear
reconciliation commit. The final source was therefore no longer the exact
two-parent Case-B merge, and the classifier correctly failed closed to Full.

CI Optimization v3 investigated whether an exact Case-B anchor followed by a
bounded, linear, non-governance reconciliation tail could safely qualify for
Equivalent reuse.

Focused research contracts showed that the graph and evidence portions could
be made mechanically strict: a unique exact anchor and complete single-parent
tail interval; exact final-source Source Full and exact PR Full evidence;
distinct run IDs; live freshness; final `Q` tree equality with final source
`S`; no merge-only content; and conservative schema-sensitive ownership.
Path, ancestry, or Git-object ambiguity would fall back to Full, and an
operational traversal guard could only abort the proof to Full.

The remaining boundary is trusted execution. Current required checks are
bound to the shared GitHub Actions App identity. That identity does not prove
which workflow produced a result because candidate-controlled workflows also
run as GitHub Actions. The strongest platform-native design identified by the
research requires trusted workflow-level identity and exact-`Q` enforcement,
but the required organization-level workflow primitive is unavailable under
the project's current GitHub Free organization plan.

Post-verdict, pre-consumption advancement of live main also remains a
freshness concern. A dedicated GitHub App or external verifier could isolate
the verifier identity, but would introduce credential custody, hosting and
webhook lifecycle, replay and idempotence handling, and ongoing maintenance
disproportionate to this optimization.

## Decision

PastExamWeb_PHY retains the current Full fallback for post-Case-B
reconciliation tails.

ADR-0014 permits an exact supported final merge after dual Full evidence. This
record's separate tail decision remains unchanged: reconciliation-tail
Equivalent reuse will not be implemented. A
PR #114-like history falling back to Full is
deliberate safe behavior, not an unresolved classifier defect.

## Rationale

The proposed optimization cannot rely on candidate-controlled evidence or an
identity shared with candidate workflows. The available platform controls do
not close that trust boundary, and operating a dedicated verifier is not
justified by the saved Full runs. Retaining Full preserves the existing
fail-closed model without adding plan-dependent or externally hosted CI trust
infrastructure.

## Alternatives considered

- Enable the mechanically strict reconciliation-tail proof with current
  required checks: rejected because GitHub Actions App identity alone does not
  prove trusted workflow identity.
- Depend on organization-level required workflows: unavailable under the
  current organization plan.
- Operate a dedicated verifier or GitHub App: rejected because its security
  and operational lifecycle is disproportionate to this optimization.

## Invariants

- ADR-0014's exact-state final-Q route does not weaken this tail fallback.
- Any post-Case-B reconciliation tail falls back to Full.
- Ambiguous, incomplete, malformed, stale, or untrusted evidence fails closed
  to Full.
- No future implementation may silently add this reconciliation-tail reuse
  path.

## Consequences

- The current fail-closed trust model is preserved.
- The project avoids new CI trust infrastructure, higher-plan dependency for
  this optimization, and dedicated verifier operational burden.
- Some legitimate reconciliation-tail histories run an additional Full, and
  the corresponding CI savings are intentionally forgone.
- CI Optimization v3 research tests and prototypes remain feasibility and
  security research; they were not merged into main or production.

## Conflict / integration guidance

Reconsider this decision only if one or more of these conditions materially
changes:

1. available platform capabilities provide trustworthy workflow-level,
   exact-`Q` enforcement compatible with the threat model;
2. maintainers explicitly choose to operate a dedicated trusted verifier or
   GitHub App and accept its security and operational cost; or
3. CI frequency or cost grows enough that avoiding these Full runs justifies
   the added trust infrastructure.

Any reopening must preserve ADR-0014's invariants, fail closed on ambiguity,
and use a new explicit design and Decision Record rather than silently
adding reconciliation-tail reuse to current policy.
