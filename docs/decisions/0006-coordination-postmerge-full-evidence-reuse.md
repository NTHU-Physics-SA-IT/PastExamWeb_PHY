# ADR-0006 — Coordination postmerge Full-evidence reuse

- ID: ADR-0006
- Title: Coordination postmerge Full-evidence reuse
- Status: Superseded
- Date: 2026-08-14
- Scope:
  - Paths: `.github/workflows/`, `.github/project-governance.json`,
    `scripts/ci/`, focused CI contract tests, and CI operating documentation
  - Concepts / Domain: Case-B coordination refresh orchestration and exact
    postmerge reuse of successful Full evidence
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Contributor workflow](../../CONTRIBUTING.md)
  - [Project governance configuration](../../.github/project-governance.json)
  - [ADR-0001](0001-main-first-parallel-development.md)
  - [ADR-0002](0002-ci-evidence-and-main-full-authority.md)
  - [ADR-0003](0003-coordination-branch-freshness.md)
  - [ADR-0005](0005-main-pr-docs-only-exception.md)
  - [ADR-0013](0013-simplified-protected-coordination.md)
  - [ADR-0014](0014-protected-coordination-case-b-full-policy.md)
- Related PR / issue: None known
- Supersedes: Only ADR-0002's blanket requirement that every governance-
  sensitive coordination stage fall back to Full, and only for the exact
  postmerge Case-B evidence-reuse contract defined here
- Superseded by: [ADR-0014](0014-protected-coordination-case-b-full-policy.md)

This record remains the historical authority for the pre-ADR-0013
shared-governance model and its accepted PR #101/#95 evidence. ADR-0014 owns
current protected-coordination Case-B policy.

## Context

A governance-sensitive Case-B refresh of a diverged coordination branch
currently receives three different Full CI executions: one for the combined
source tree, one for the formal pull-request candidate, and one for the final
coordination merge. The first two gates have distinct authority. Source Full
tests the reconciled source itself, while PR Full tests the formal GitHub pull
request candidate against the exact coordination target and remains the
protected pull-request gate.

When the final coordination merge contains no content beyond that already
tested source and pull-request state, the third heavy execution may be
redundant. The repository already starts source-push and pull-request workflows
independently, so their Full runs can overlap without a new orchestration
workflow. The durable question is whether exact postmerge evidence can safely
replace only the third Full while keeping current Full authority, freshness,
required-check, and fail-closed boundaries intact.

This record authorizes only the narrow postmerge exception described below.

## Decision

An eligible Case-B coordination refresh uses this canonical sequence:

1. create source `S` by explicitly reconciling coordination state `C` with
   current main authority `M`;
2. push `S` and promptly open the normal pull request so Source Full and PR
   Full may run independently and overlap;
3. require both exact Full runs to succeed;
4. revalidate current source, target, and main refs and complete the existing
   semantic and topology review before merge;
5. merge the exact source into the exact coordination base, producing `Q`; and
6. use `equivalent-merge` for the postmerge push only when exact provenance
   proves that `Q` contains no content beyond the already Full-tested state.

The durable Case-B topology is:

- `S` is the exact reconciliation of coordination `C` and main `M`, with the
  parent identities and order required by the machine contract;
- `Q` is the exact final two-parent coordination merge of `S` into `C`; and
- `Q` is content-equivalent to `S`, with no merge-only content.

Eligibility additionally requires exact, fresh, unique, successful Source
Full and PR Full evidence bound to the expected repository, workflow, run,
attempt, required jobs, source/head, and coordination base. The machine-resolved
coordination branch and live refs remain authority. Exact API fields and query
mechanics are implementation details owned by the focused machine contract.

Unknown, missing, stale, ambiguous, malformed, advanced, or mismatched
topology, refs, content, pull-request identity, or CI evidence fails closed to
Full.

This decision introduces no new external CI mode or required-check name. It
maps the successful postmerge proof to the existing `equivalent-merge`
execution topology. It introduces no workflow solely to create parallelism.

A Draft pull request is not required and Draft-to-Ready is not a CI gate. The
canonical policy is to open the normal pull request promptly and wait for both
Full runs plus the existing freshness, semantic, and topology checks before
merge.

## Rationale

Retaining Source Full preserves validation of interactions between imported
main authority and coordination-only application, dependency, migration,
build, and test state. Retaining PR Full preserves the formal target-integration
gate and avoids allowing candidate-side evidence reuse to replace that gate.

The postmerge workflow executes from `Q`; it is not an independent trust root
when `Q` is proven content-identical to `S`. Exact topology, tree, live-ref,
and dual-Full evidence can therefore replace only that redundant third heavy
execution without broadening governance-sensitive PR eligibility.

This saves one Full execution and permits the two retained Full executions to
overlap while preserving stable check topology. Lightweight provenance work is
restricted to an exact candidate coordination postmerge event, so generic
Full classification and heavy-job parallelism remain unchanged.

## Alternatives considered

- Keep serial Full → Full → Full: safe but retains all latency and duplicate
  heavy compute.
- Run Source Full and PR Full in parallel but keep postmerge Full: improves
  latency but preserves all three heavy executions.
- Replace PR Full and postmerge Full with Equivalent: rejected because it
  permits evidence reuse to replace the formal protected pull-request gate and
  reintroduces the broader candidate self-attestation problem.
- Add a fourth CI mode or a new required check: rejected because the existing
  `equivalent-merge` execution and stable CI Gate topology can represent the
  proposed evidence result.
- Make Draft pull requests mandatory: rejected because Draft is an optional
  GitHub lifecycle tool, not CI evidence or existing merge authority.

## Invariants

- Exact `main` pushes remain Full, and main never uses Equivalent.
- Main pull requests retain ADR-0005's exact policy; this record creates no new
  main exception.
- Release, production, and production-hotfix refs remain Full.
- Both Source Full and formal PR Full are required for an eligible Case-B
  refresh and may run concurrently through their existing independent events.
- Governance-sensitive PRs remain Full. The exception applies only to the
  exact final coordination postmerge push.
- Ordinary governance changes and any topology other than the exact approved
  Case-B contract remain Full.
- `Q` must contain no content beyond the exact Full-tested source/PR state.
- A passing Full run does not establish freshness. If main advances beyond
  `M` before merge, the refresh is stale and must be reconciled again under
  ADR-0003.
- Missing, stale, ambiguous, malformed, advanced, or mismatched evidence fails
  closed to Full.
- No branch-protection weakening, new external CI mode, or new required-check
  name is authorized.
- No new heavy job, duplicated heavy work, or provenance/API work on generic
  main, release, production, or ordinary Full paths is authorized.
- Draft pull requests and Draft-to-Ready transitions are not policy gates.

## Consequences

- An eligible refresh can approach the duration of the slower retained Full
  run plus a lightweight postmerge proof instead of three serial Full runs.
- Two Full workflows may consume runners concurrently, matching existing
  source/PR behavior.
- The classifier and evidence API require a narrowly scoped, contract-tested
  postmerge provenance subtype and explicit ambiguity handling.
- Operators must still wait for both Full results and recheck source, base, and
  main freshness before merge.
- Focused contract tests preserve the positive Case-B eligibility and its
  adversarial fail-closed boundary.

## Conflict / integration guidance

ADR-0002 remains operative except for this exact postmerge Case-B exception.
Governance-sensitive pull requests and all other governance-sensitive
coordination pushes continue to use Full.

If later work would skip Source Full or PR Full, make main Equivalent, broaden
the exception beyond the exact Case-B postmerge shape, weaken required checks
or branch protection, add heavy work to generic Full, or relax fail-closed
behavior, stop for a new explicit policy decision. Preserve ADR-0001's
development-base authority, ADR-0003's current-main freshness semantics, and
ADR-0005 unchanged.
