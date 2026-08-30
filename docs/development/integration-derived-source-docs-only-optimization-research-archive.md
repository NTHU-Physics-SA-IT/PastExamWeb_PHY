# Integration-Derived Source Docs-Only Optimization Research Archive

- Status: **Historical / Research — not operational authority**
- Research completed: **2026-08-30**
- Adoption: **Not adopted**
- Current policy: **Retain Option C / ADR-0014 current authority**

If this archive conflicts with current Accepted Decision Records, CI workflows,
classifiers, rulesets, or project governance, the current operational authority
wins. In particular, [ADR-0014](../decisions/0014-protected-coordination-exact-state-postmerge-reuse.md)
continues to require Source Full and PR Full before a qualifying final protected-
integration merge may use Equivalent.

## Purpose and motivating problem

PR #211 was documentation-only at the source-specific level. Its source branch
was derived from protected integration state, while the ordinary Source
classifier conservatively compared the source head with its merge base against
main. Inherited protected-integration application, migration, and governance
state therefore entered the comparison. The presence of
`.github/project-governance.json` correctly forced Source Full under the
existing authority.

The research asked whether an exact protected-integration base `B` could be
bound to source head `H` so that the complete source-specific `B..H` history,
rather than the broader main-relative history, could safely qualify as docs-
only. The existing classifier was not considered broken; it behaved
conservatively according to its current scope and policy.

## Research authority and status

| Item | Value |
| --- | --- |
| Final-analysis main | `8199d1f16d13b62a54bd706924feb9b562ee8170` |
| Archive PR base | `8199d1f16d13b62a54bd706924feb9b562ee8170` |
| Technical finding | Acceptable with strict bounds |
| Adoption decision | Not adopted |
| Operational recommendation | Retain Option C |
| Implementation | Not authorized |

The analysis authority and archive base were identical at archival execution.
ADR-0014 remains operational authority unless a future Owner-approved
governance decision explicitly changes it.

## Verified PR #211 specimen

| Evidence | Exact value |
| --- | --- |
| Protected integration ref | `integration/stage-5f-5696d6fa` |
| Protected integration base `B` | `b01924b948655a3445dec7beedf5227dfc967974` |
| Source head `H` | `d65bb677359b9e3ed79440d37728f12eb4e1e0d5` |
| Synthetic PR merge `P` | `ad4c03ad11449bd34fb1fd760787347172926420` |
| Final normal merge `Q` | `43502f78c6f5e35c6f6bda2f03a44f151f7bd64a` |
| Shared H/P/Q tree | `a3aff8b510274f83f43c942a2153b20f36048235` |
| Source run | `33126057315` |
| PR run | `33126076902` |

### Reconstruction

- The main-relative Source comparison contained 36 unique commits and 40
  paths, including inherited governance, application, and migration state.
- The exact source-specific `B..H` delta was one commit and two paths:
  - `docs/README.md`
  - `docs/domain/state-transitions.md`
- `P` had ordered parents `(B,H)`, and `tree(P)=tree(H)=tree(Q)`.

Inspecting only the final commit was explicitly rejected as a general design.
A first push can contain multiple commits, older non-docs work, merges, or
rewritten history; the complete source-specific history must be proven.

## Historical classifier finding

The ordinary Source behavior examined by the research was:

```text
B = merge-base(H, origin/main)
paths = diff --name-only --no-renames B H
```

For ordinary generic Source classification, `event.before` did not select the
comparison scope. Consequently, `before=ZERO_SHA` was not permission to inspect
only the last commit. Governance and control paths forced Full before docs-only
eligibility was considered.

This describes the classifier at the research authority. It is historical
evidence, not a new normative policy.

## Strongest bounded Option-B research candidate

The strongest design found technically defensible was:

```text
trusted Full-tested protected-integration B
+ exact same-repository H
+ exact complete linear B..H provenance
+ current docs-only authority over all touched and final paths
+ forced=false
+ no merge commits
+ stable exact integration binding
+ PR Full on synthetic P
+ tree(P)=tree(H)
+ trusted Owner normal Q
+ tree(Q)=tree(P)=tree(H)
+ lightweight exact-state Q provenance
```

All evidence would need to be reread stably. Any missing, stale, malformed,
ambiguous, unavailable, or conflicting fact would fall back to Full.

This was a **research candidate only**. It is not implemented, adopted, or
authorized by this archive.

## Threat and fail-closed boundaries

The bounded candidate intentionally rejected or selected Full for:

- older non-docs commits hidden before a final docs commit;
- first pushes with multiple commits unless the complete `B..H` history could
  be proven;
- every governance or control path;
- a stale or unexpected integration base;
- any source merge commit;
- rewritten or forced history;
- fork or cross-repository history;
- ambiguous protected-integration ancestors or evidence;
- missing or malformed GitHub API evidence; and
- unsupported source, PR, or final-merge topology.

The path audit had to include the union of every path touched by every linear
commit as well as the final tree delta. A later revert could not erase an older
control-path touch from the proof.

## Source Full versus PR Full differential

| Class | Research conclusion |
| --- | --- |
| Common | Source Full and PR Full executed the same required heavy validation families under the examined workflow semantics. |
| Source-only | Source Full supplied an independent push-event Full execution and earlier heavy feedback. This remained meaningful defense-in-depth. |
| PR-only | PR Full added exact protected base/ref, same-repository base/head, PR identity, synthetic `P`, ordered parent/topology, and attestation/context binding. |

For the strictly bounded candidate class, the research found no demonstrated
security-relevant Source-only application validation left uncovered after
combining trusted-base provenance, complete docs-only history, PR Full, and
exact P/H/Q tree identity.

That conclusion does **not** make Source Full globally unnecessary. Removing it
would give up an independent Full sample and explicitly change ADR-0014's dual-
Full defense-in-depth contract.

## CI policy preservation lock

Any future reconsideration must preserve these existing policies and
optimizations unless separately and explicitly superseded:

| Flow | Preserved result |
| --- | --- |
| Exact main push | Full |
| Main Equivalent | Never allowed |
| Main PR, conclusively docs-only | Existing ADR-0005 docs-only exception |
| Main PR, non-docs or uncertain | Full |
| Generic ordinary Source, docs-only | Existing generic docs-only behavior |
| Generic ordinary Source, non-docs/governance | Full |
| Canonical protected-integration Start | Existing `coordination-start` path |
| PR into protected integration | Full |
| Existing qualifying final Q | ADR-0014 Source Full + PR Full + Equivalent |
| Nonqualifying final Q | Full |
| Reconciliation tails | Full |
| Return/close lifecycle | Full or dedicated lifecycle authority |
| Release, production, production hotfix | Full |
| Fork, force, squash, rebase, unsupported topology | Full |
| Missing, stale, malformed, ambiguous evidence | Full |

A future Option-B implementation was considered acceptable only as a narrow
additive exception. The research did not support a broad classifier redesign,
a wider docs allowlist, or a governance/control-path exemption.

## Option comparison and decision

| Option | Contract | Research result |
| --- | --- | --- |
| A | Source docs-only + PR Full + Q Full | Technically safe, but no structural Full-run reduction versus Option C and may move heavy work onto the postmerge critical path. Not worthwhile. |
| B | Source docs-only + PR Full + Q Equivalent | Technically defensible only under the strict bounded proof. It would replace ADR-0014's mandatory Source Full prerequisite for one narrow class and requires a future explicit Owner/governance decision. Not adopted. |
| C | Source Full + PR Full + Q Equivalent | Current operational authority. Retained. |

## Natural eligibility and structural value

The final targeted study sampled nine PRs in the Stage 5F protected-integration
lifecycle.

| Criterion | Observed |
| --- | ---: |
| Same-repository | 9/9 |
| Exact then-current integration-head base | 9/9 |
| Base with successful terminal Full evidence | 9/9 |
| Linear, no-merge `B..H` | 8/9 |
| Docs-only under the current allowlist | 1/9 |
| Strictly Option-B eligible | 1/9 |

The sole eligible specimen was PR #211. Observed eligibility was **1/9 =
11.1%**.

For PR #211, Option B would have removed one Source Full, saving approximately
39–40 job-minutes. The observed merge-readiness improvement was about 1 minute
46 seconds because Source Full and PR Full substantially overlapped. Runner
savings were real, but the human critical-path benefit was modest.

This was one milestone, not a statistically stable long-term eligibility rate.

## Final decision

**RETAIN OPTION C.**

Option B was technically defensible, but observed eligibility was sparse,
runner savings did not translate into substantial human latency reduction, and
adoption would permanently add a second ADR-0014 trust contract plus its
maintenance burden.

> Technically feasible; not adopted due to low current value relative to
> governance and maintenance complexity.

The current operational contract remains:

```text
Source Full
+ PR Full
+ qualifying final Q Equivalent
```

## Reopening criteria

A future Owner may reopen this research if:

- integration-derived docs-only changes become materially more frequent;
- GitHub Actions runner cost becomes an operational concern;
- protected-integration workflow semantics materially change;
- the Source Full versus PR Full differential materially changes; or
- the Owner wishes to reconsider the dual-Full defense-in-depth contract.

Future work should begin with this archive and fresh current authority rather
than reconstructing PR #211 from scratch. Reopening research does not itself
authorize implementation or supersede ADR-0014.
