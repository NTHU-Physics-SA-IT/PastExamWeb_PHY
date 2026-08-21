# Ordinary-Product Postmerge Equivalent Research Archive

Status: Historical

This document preserves research and empirical evidence. It is not current
operational authority. [ADR-0010](../decisions/0010-retain-full-fallback-for-governance-sensitive-ordinary-product-postmerge.md)
owns the durable decision to retain Full fallback for governance-sensitive
ordinary-product coordination postmerge cases under current capabilities and
economics.

## 1. Motivation

Stage 5D D2A PR #128 received successful Source Full and PR Full evidence. Its
final coordination merge had the same tree as the tested source and synthetic
pull-request state and contained no merge-only content. The final postmerge
push nevertheless ran Full because governance-sensitive reuse under ADR-0006
requires the exact Case-B source shape.

The third Full appeared potentially redundant and cost roughly 14 minutes of
wall time. PR #128 therefore motivated research into a new, narrow
ordinary-product reuse contract. It was not itself evidence of an eligible
safe subset: the PR changed `scripts/ci/backend-test-shards.json`, a Full test-
selection manifest.

The later Vite 8 / Playwright readiness investigation was a separate
reliability and false-Green-safety research line. Its evidence and durable
decision remain in the [Vite research archive](vite8-playwright-readiness-research-archive.md)
and [ADR-0009](../decisions/0009-retain-fail-closed-vite-readiness-under-playwright-api-limits.md).

## 2. Existing Policy Baseline

- [ADR-0006](../decisions/0006-coordination-postmerge-full-evidence-reuse.md)
  permits postmerge Equivalent only for its exact Case-B coordination-refresh
  topology with exact, fresh, distinct Source Full and PR Full evidence.
- [ADR-0007](../decisions/0007-retain-full-fallback-for-post-case-b-reconciliation-tails.md)
  retains Full for post-Case-B reconciliation tails because trusted workflow
  identity remained unresolved.
- The generic non-governance coordination path already permits Equivalent when
  its exact source evidence, topology, tree, live-ref, and fail-closed contract
  succeeds.
- Main pushes remain Full, and main pull requests remain Full except for
  [ADR-0005's exact docs-only path](../decisions/0005-main-pr-docs-only-exception.md).

The research question was therefore not whether every ordinary product merge
could use Equivalent. It asked whether Source Full and PR Full could replace
the final Full for a new, strictly limited governance-sensitive ordinary
product subset.

## 3. Coordination Authority Correction

The research corrected an early interpretation of main governance:

```text
main:
  coordination_branch = null
```

This means main remains generic authority for ordinary development. It does
not prove that no branch-local coordinated milestone exists. An activated
milestone may carry its own machine-readable authority on a real protected
remote integration branch:

```text
origin/integration/stage-X:
  coordination_branch = integration/stage-X
```

At closeout, coordination is deactivated before the milestone returns to
main, preserving generic main authority. Historical Stage 5BD authority was
reconstructed from PR base branches, exact Git parents and first-parent
history, branch-local project-governance content, return/deactivation history,
and exact Actions evidence. This archive does not define the separate future
Trusted Activation mechanism.

## 4. Research Question and Model

The model used:

- `C`: exact coordination base before the ordinary product merge;
- `H`: exact ordinary product source/head;
- `P`: GitHub synthetic pull-request merge tested by PR Full;
- `Q`: final merge commit written to coordination; and
- `M`: current main authority when freshness or TCB identity matters.

The intended strict predicates included ordered parents `(C,H)`, equal
`H/P/Q` trees, and no merge-only content in `Q`. The research separated commit
object identity from parent and tree identity because a synthetic `P` may be
regenerated without changing its parents or content.

## 5. Round 1 — Authority and Evidence Reconstruction

Round 1 reconstructed the current Accepted policy, classifier, Full
Attestation, CI Gate, governance-path classification, and exact Source/PR
evidence semantics.

Source Full proved one exact successful push run for `H`, including repository,
workflow path/ID, run/attempt, required jobs, job heads, Full Attestation, CI
Gate, and workflow blob evidence when later consumed. It did not by itself
prove coordination ancestry, current refs, PR identity, final `Q`, or
independent workflow trust.

PR Full used the current live base rather than historical event-base metadata.
It bound the open PR, execution head `H`, live base `C`, and synthetic merge
parents `(C,H)`, and tolerated only content-equivalent regeneration. Later Q
consumption would still need to re-establish current PR association, refs,
topology, tree equality, freshness, and exact evidence.

Round 1 also inventoried candidate-controlled CI and TCB paths. Requiring those
paths to equal trusted authority appeared useful but incomplete: the proof
still needed an independent trusted executor. The initial outcome was:

**READY FOR BOUNDED ROUND 2 RESEARCH**

## 6. Round 2A — Trust and Value Kill Gates

### Trust path

For a postmerge push, Q supplies the root workflow, classifier, Equivalent
revalidation, and CI Gate code. GitHub creates a check bound to Q under the
GitHub Actions App. Branch protection can bind check context, App, and head,
but does not independently bind the result to an exact trusted workflow,
classifier, gate blob, run, event, or referenced-workflow revision.

A minimal adversary can weaken Q-side verification while retaining the
required `CI Gate` job name. The resulting check still carries the same shared
GitHub Actions App identity. API-visible workflow path, workflow ID, run,
attempt, event, and revision remain useful evidence but are not an independent
trust root under current enforcement.

### Trusted-base byte identity

The assessment separated three premises:

1. **Content:** Git can compare workflow, classifier, gate, governance, and TCB
   objects with trusted base or main.
2. **Bootstrap:** a trustworthy component must perform that comparison.
3. **Enforcement:** the consumer must distinguish that trustworthy proof from
   candidate code emitting the same required check.

The content premise appeared mechanically plausible. Bootstrap and enforcement
remained unsolved because the verifier executed from Q. Safe closure required
either a platform-enforced trusted required-workflow identity unavailable
under the verified GitHub Free organization plan or a separately operated
verifier/GitHub App and its security lifecycle.

The trust verdict was:

**TRUST GATE — REQUIRES DISPROPORTIONATE EXTERNAL VERIFIER / NEW TRUST INFRASTRUCTURE**

### Bounded value audit

The audit covered the completed Stage 5BD window from ADR-0006 acceptance
through the final merge into `integration/stage-5bd`. Branch-local governance
and PR/Git history established the coordination role; main's later null value
was not used to infer historical inactivity.

Six ordinary product coordination merges were identified:

| PR | Postmerge result | Conservative disposition |
| --- | --- | --- |
| #102 | Generic Equivalent | Already handled; no new policy needed |
| #115 | Generic Equivalent | Already handled; no new policy needed |
| #124 | Full | Excluded: migration/schema-sensitive |
| #128 | Full | Excluded: shard/test-selection manifest |
| #132 | Full | Excluded: migration/schema plus shard/test-selection |
| #134 | Generic Equivalent | Already handled; no new policy needed |

The bounded population was therefore:

- total ordinary product coordination merges: 6;
- already generic Equivalent: 3;
- definitely excluded: 3;
- unresolved: 0; and
- conservatively eligible new-policy cases: 0.

The value verdict was:

**VALUE GATE — TOO SMALL / TOO RARE FOR ADDED TRUST COMPLEXITY**

The combined outcome was:

**ROUND 2A — STOP: TRUST SOLUTION DISPROPORTIONATE**

No TCB-closure or mechanical provenance prototype followed.

## 7. Empirical Evidence

### Successful ADR-0006 Case-B example

PR #101 demonstrated the exact accepted Case-B path:

- `C`: `17d5c79d55fb1a0cff2d09370f0fe7e832826884`
- `M`: `2eef089a4384a889c4066da07bd1f8559c505ad0`
- `H/S`: `fbf402638fbf3f4d8b4ba305936ec2d7a9e47436`
- `P`: `8b41fa23c5d413c37008a32ab4859e4d7a029325`
- `Q`: `791ddf70fb5a2927f1479830ee6f9ba4e7601857`
- shared `H/P/Q` tree:
  `52c2121713cbe4fe9ea8921f3430bf85df5d2a49`
- Source Full: run `31733366840`
- PR Full: run `31733425799`
- final Equivalent: run `31734770696`

`P` is retained accepted research evidence recovered from the historical Full
Attestation record. The post-merge PR API reports final `Q`, so it does not by
itself reproduce the earlier synthetic object identity.

### Ordinary-product Full examples

PR #128:

- Source Full: run `31968835683`
- PR Full: run `31969565436`
- final Q Full: run `31998378115`
- attempt 1 failed in browser-family aggregation; attempt 2 succeeded
- final tree matched the tested source state
- excluded because `scripts/ci/backend-test-shards.json` changed

PR #132:

- Source Full: run `32013257715`
- PR Full: run `32014412722`
- final Q Full: run `32033838377`
- final tree matched the tested source state
- excluded because migration/schema and shard/test-selection authority changed

The SHA and run identifiers in this section were established by the accepted
Round 1 and Round 2A Git/GitHub audits. Formal closeout did not rerun historical
workflows or treat a retry as new correctness evidence.

## 8. Benefit Baseline

The representative sample found approximately:

- 14 minutes wall time for a Full workflow;
- 13 minutes 55 seconds for the sampled ordinary postmerge Full workflows;
- 31 runner-minutes per Full; and
- 30 seconds for Equivalent.

Avoiding one eligible Full would therefore be meaningful. The final decision
does not call Full cheap. It records that the bounded completed milestone had
zero conservatively eligible new-policy occurrences while safe closure would
require new security-critical trust infrastructure.

## 9. Final Research Classification

**ORDINARY PRODUCT POSTMERGE REUSE — NOT WORTH COMPLEXITY**

`TRUST BOUNDARY UNSOLVED` is technically part of the result. `NOT WORTH
COMPLEXITY` is the project-level classification because closing that boundary
would require disproportionate infrastructure for zero observed
conservatively eligible new-policy cases.

Conservative false Full is acceptable. False Green from circular verifier
trust is not.

## 10. What Was Not Done

The research produced no:

- production classifier or workflow implementation;
- new CI mode, required check, or CI Gate behavior;
- TCB-closure phase or production path inventory;
- mechanical provenance production code;
- external verifier or GitHub App;
- policy weakening; or
- research prototype merged into main.

The completed research worktree remained uncommitted and unpushed at its fixed
research base. Historical prototype worktrees were not imported or modified.

## 11. Reopening Criteria

Reopen only with materially new evidence, such as:

- a platform-native capability that independently binds exact-Q success to a
  trusted workflow/verifier revision;
- explicit owner acceptance of a dedicated verifier/App and its security,
  credential, webhook, replay, availability, and maintenance lifecycle;
- future coordinated milestones with materially higher conservatively
  eligible frequency or cost; and
- a design that proves complete maintainable TCB closure and independent
  verifier trust together.

Any reopening requires a new explicit design and Decision Record. It must not
silently widen ADR-0006, weaken ADR-0007, reinterpret generic Equivalent, or
fold Trusted Activation into this closed research question.

## 12. Research Scope and Evidence Provenance

- Repository: `NTHU-Physics-SA-IT/PastExamWeb_PHY`
- Research branch: `research/ci-ordinary-product-postmerge-reuse-v1`
- Fixed research base: `a6eb665707236d96f82146d0ccc330d42b54bfba`
- Research phases: Round 1 authority/evidence reconstruction; Round 2A trust
  and value kill gates
- Durable decision: [ADR-0010](../decisions/0010-retain-full-fallback-for-governance-sensitive-ordinary-product-postmerge.md)

This archive is retained background evidence. Current operational behavior is
owned by the Accepted Decision Records and active CI/validation documents.
