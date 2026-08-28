# ADR-0010 — Retain Full Fallback for Governance-Sensitive Ordinary-Product Coordination Postmerge

- ID: ADR-0010
- Title: Retain Full Fallback for Governance-Sensitive Ordinary-Product
  Coordination Postmerge
- Status: Accepted
- Date: 2026-08-22
- Scope:
  - Paths: `.github/workflows/`, `.github/project-governance.json`,
    `scripts/ci/`, focused CI contract tests, and CI operating documentation
  - Concepts / Domain: Postmerge reuse of Source Full and PR Full evidence for
    governance- or CI-trust-boundary-sensitive ordinary product pull requests
    into a configured coordination branch
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Historical ordinary-product postmerge reuse research archive](../development/ordinary-product-postmerge-equivalent-research-archive.md)
  - [ADR-0002](0002-ci-evidence-and-main-full-authority.md)
  - [ADR-0003](0003-coordination-branch-freshness.md)
  - [ADR-0005](0005-main-pr-docs-only-exception.md)
  - [ADR-0006](0006-coordination-postmerge-full-evidence-reuse.md)
  - [ADR-0007](0007-retain-full-fallback-for-post-case-b-reconciliation-tails.md)
  - [ADR-0014](0014-protected-coordination-exact-state-postmerge-reuse.md)
- Related PR / issue: PR #128 motivated the research; PR #154 records the formal closeout
- Supersedes: None
- Superseded by:
  - [ADR-0014](0014-protected-coordination-exact-state-postmerge-reuse.md),
    only for exact same-repository protected-integration final-Q reuse after
    mandatory Source Full and PR Full

## Context

Stage 5D D2A PR #128 received successful exact Source Full and PR Full
evidence. Its final coordination merge `Q` had the same tree as the tested
source and synthetic pull-request state, with no merge-only content. The
postmerge classifier nevertheless selected Full because the source was not
the exact Case-B shape authorized by ADR-0006. That correct fail-closed result
raised a narrower question: could a new exception safely replace the third
Full for a strictly limited subset of governance-sensitive ordinary product
coordination merges?

PR #128 was a motivating observation, not a positive eligibility example. It
changed `scripts/ci/backend-test-shards.json`, which controls Full test
selection and belongs to the conservative governance/CI trust boundary.

Research established that strict `C/H/P/Q` topology, ordered parents, tree
equality, and absence of merge-only content appear mechanically modelable.
The unresolved boundary was independent verifier identity. The final push
workflow, classifier, Equivalent verifier, and CI Gate are loaded from `Q`.
Required checks bind the check context, GitHub Actions App, and head commit,
but do not independently bind success to an exact trusted workflow,
classifier, or gate revision.

The bounded post-ADR-0006 Stage 5BD sample contained six ordinary product
coordination merges. Existing generic non-governance Equivalent already
handled three. The remaining three touched migration/schema or test-shard/
test-selection authority and were conservatively excluded. No new-policy
eligible occurrence remained.

## Decision

PastExamWeb_PHY does not add a governance-path or trust-surface exception.
ADR-0014 later supersedes this record only for exact same-repository protected-
integration final-Q state transfer after mandatory Source Full and PR Full.

Governance-sensitive ordinary product cases not covered by an existing
Accepted exception retain their Full fallback. Conservative Full is accepted;
a circular or candidate-controlled verifier is not.

This record is complementary to existing CI authority:

- ADR-0014 permits exact-state final-Q reuse without classifying paths;
- ADR-0007 continues to require Full for post-Case-B reconciliation tails;
- existing generic non-governance Equivalent remains unchanged; and
- main remains Full except for ADR-0005's exact docs-only path.

This record does not define or authorize Trusted Activation for a future
coordination branch.

## Rationale

### Trust boundary

API-visible workflow path, workflow ID, run identity, attempt, event, head,
and referenced revisions are evidence fields, but current branch protection
does not independently enforce most of them. The required `CI Gate` context is
bound to the shared GitHub Actions App identity. Candidate-controlled
workflows execute under that same identity.

Requiring CI, TCB, and governance files in `H`, `P`, and `Q` to be Git-object-
identical to trusted base or main would strengthen the content premise, but it
cannot bootstrap verifier trust. If candidate-controlled Q-side code performs
and reports the equality proof, branch protection cannot distinguish that
proof from weakened Q-side code emitting the same required check.

Safe closure would require a platform-enforced trusted required-workflow
identity or a separately operated verifier/GitHub App with its own credential,
webhook, replay, idempotence, availability, and maintenance lifecycle. The
native required-workflow primitive identified by the research was unavailable
under the verified GitHub Free organization plan. Operating separate trust
infrastructure is disproportionate to this optimization.

### Value boundary

A sampled Full cost about 14 minutes of wall time and 31 runner-minutes, while
Equivalent cost about 30 seconds. The decision is not that an individual Full
is cheap. The bounded completed milestone produced zero conservatively
eligible new-policy cases after removing cases already handled by generic
Equivalent and cases touching mandatory exclusion surfaces. The potential
savings do not justify a larger security-critical trust system.

## Alternatives considered

- **Keep the current Full fallback:** Selected. It preserves the current
  simple, fail-closed trust model.
- **Use only strict `C/H/P/Q` graph and tree proof:** Rejected. Content
  equivalence does not independently authenticate the verifier performing the
  proof.
- **Require TCB paths to equal trusted base/main, verified from `Q`:** Rejected.
  The candidate-controlled verifier creates a circular bootstrap.
- **Build a complete hand-maintained TCB inventory:** Not pursued after the
  trust and value kill gates. It adds substantial maintenance and still does
  not create independent verifier identity.
- **Operate a dedicated external verifier or GitHub App:** Technically
  conceivable, but rejected as disproportionate to zero observed eligible
  cases and because it creates a new security and availability lifecycle.
- **Use an organization-level trusted required workflow:** Reconsider only if
  a suitable exact-Q primitive becomes genuinely available under future
  platform and plan capabilities.
- **Treat flaky or expensive Full as authority to weaken evidence:** Rejected.
  Reliability cost does not justify a false-Green path.

## Invariants

- ADR-0014 supersedes only this record's conclusion for an exact protected
  final Q; it does not authorize path-based governance exceptions.
- ADR-0007's post-Case-B reconciliation-tail Full fallback remains unchanged.
- Existing generic non-governance Equivalent remains unchanged.
- Main remains Full except for ADR-0005's exact docs-only path.
- Governance-sensitive ordinary product cases outside an existing Accepted
  exception remain Full.
- Migration/schema, dependency/lockfile, shard/test-selection, CI/workflow/
  classifier/attestation/gate, project-governance, mixed, and unknown scope
  remain conservative and fail closed under current authority.
- Candidate-controlled proof is not an independent trust root.
- False Green is not accepted to save runner time.
- `main` with `coordination_branch: null` is generic main authority and must
  not be treated as proof that no branch-local coordinated milestone exists.
- This record does not define Trusted Activation.
- Research prototypes and future experimental models are not production
  authority.

## Consequences

- Some postmerge Full executions remain intentionally duplicated.
- The current fail-closed security model remains simple and auditable.
- No new verifier service, GitHub App, required check, classifier branch, or
  TCB inventory is introduced.
- Current CI policy, required checks, and evidence modes remain unchanged.
- Future work has explicit reopening criteria and should not repeat the same
  trust and value investigation without materially new evidence.

## Conflict / integration guidance

Reopen this decision only when at least one material premise changes:

1. a platform-native capability independently binds exact-`Q` success to a
   trusted workflow/verifier revision;
2. the owner explicitly accepts operation of a dedicated verifier or GitHub
   App and its complete security and availability lifecycle;
3. future coordinated milestones demonstrate materially higher,
   conservatively eligible frequency or cost; or
4. a new design proves both complete, maintainable TCB closure and independent
   verifier trust.

Any reopening requires a new explicit design and Decision Record. Do not
silently weaken ADR-0014, weaken ADR-0007, reinterpret generic Equivalent, or
change main Full/docs-only authority. Treat future Trusted Activation as a
separate governance decision.
