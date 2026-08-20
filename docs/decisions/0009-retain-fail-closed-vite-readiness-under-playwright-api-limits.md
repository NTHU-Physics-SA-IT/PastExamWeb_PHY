# ADR-0009 — Retain Fail-Closed Vite Readiness Under Playwright Public-API Limits

- ID: ADR-0009
- Title: Retain Fail-Closed Vite Readiness Under Playwright Public-API Limits
- Status: Accepted
- Date: 2026-08-20
- Scope:
  - Paths: Frontend readiness logic, Playwright readiness tests, and related CI
    operating documentation
  - Concepts / Domain: Vite 8 frontend readiness, Playwright Firefox
    request/network lifecycle, and the CI frontend-readiness safety boundary
- Related documents:
  - [Validation policy](../development/validation.md)
  - [Historical Vite 8 / Playwright readiness research archive](../development/vite8-playwright-readiness-research-archive.md)
  - [ADR-0002 — CI evidence and main Full authority](0002-ci-evidence-and-main-full-authority.md)
  - [ADR-0003 — Coordination-branch freshness](0003-coordination-branch-freshness.md)
  - [ADR-0007 — Retain Full Fallback for Post-Case-B Reconciliation Tails](0007-retain-full-fallback-for-post-case-b-reconciliation-tails.md)
- Related PR / issue: None known
- Supersedes: None
- Superseded by: None

## Context

The Playwright Firefox frontend-readiness path occasionally failed during a
cold Vite 8 dependency-discovery cycle with `504 Outdated Optimize Dep`,
aborted requests, reloads, an Admin lazy-module prewarm timeout, and navigation
instability. A whole-workflow or Playwright retry usually passed after Vite's
dependency graph had warmed, creating a known false-negative reliability cost.

Research on Playwright 1.62.1, Vite 8.2.1, and Firefox proved that the
persistent user-side request tracker could retain active membership belonging
to superseded documents even after the current document graph had stabilized.
In the ownership-decisive run, every member of the final 15-request plateau
belonged to navigation revision 6 while accepted baselines advanced through
revisions 9, 11, 13, and 15. The retry's fresh tracker then passed against the
warmed graph in about four seconds.

The research also established a safety boundary. Supported public Playwright
signals in the studied design do not safely provide both a general mapping
from a `Request` to the accepted document/loader that owns it and an
authoritative current-inflight level snapshot. `networkidle` is a latched
lifecycle event here, not a supported current-inflight query. Browser Resource
Timing is not authoritative for native module traffic, and private
`_inflightRequests` state is not an acceptable production contract.

This creates competing risks. Retaining historical `activeRequests === 0`
authority can reject a healthy current graph, but retiring requests without a
fail-closed ownership boundary can misclassify genuine current work as stale
and create a false Green.

## Decision

PastExamWeb_PHY does not promote any current Vite/Playwright readiness research
prototype into production CI and does not implement a replacement quiescence
architecture under the currently supported public API boundary.

The project deliberately retains the known false-negative/retry reliability
debt rather than introducing an unresolved false-Green path. This is a safety
decision made after root-cause and architecture research, not an untriaged or
abandoned defect.

No part of this decision weakens Full authority, CI Gate, Full Attestation,
browser coverage, or the fail-closed classification and evidence requirements
defined by current repository governance. The research branch and commits are
historical evidence only and were not merged into `main`.

Future work may reopen this boundary only with explicit new evidence and a
separately reviewed fail-closed design. If that work changes this Accepted
decision, it must create a new or superseding Decision Record rather than
silently editing the decision's substance.

## Rationale

The research proved the false-negative mechanism and excluded several tempting
fixes, but it did not prove a supported invariant that distinguishes historical
stale requests from genuine current inflight work. A false negative costs a
retry and CI reliability; a false Green could allow readiness to be declared
while required frontend work is incomplete. Preserving the stronger safety
failure mode is therefore the bounded choice.

Documenting the result still has durable value: the root cause is known,
unsafe approaches are closed, the supported public-API capability boundary is
explicit, and future work has concrete reopening criteria instead of repeating
the same experiments.

## Alternatives considered

- **Keep historical active-request lifetime as an unquestioned hard gate:**
  Not selected as a new architecture. It is known to produce false negatives,
  although the existing fail-closed behavior remains until a safe replacement
  exists.
- **Precisely retire stale `Request` objects:** Rejected for production because
  a safe general request-to-accepted-document ownership boundary was not
  provable through supported public APIs.
- **Retire by navigation revision alone or weaken ownership to a
  `tokenChanged OR revisionChanged` predicate:** Rejected because navigation
  revision proves activity, not safe document identity, and could retire real
  current work.
- **Replace request lifetime with bounded activity quiescence:** Rejected under
  the current capability boundary because no supported atomic zero-work
  checkpoint plus future-start subscription was found. Current-inflight
  false-Green safety remains unresolved.
- **Treat `networkidle` as current-level proof:** Rejected for this design
  because Playwright 1.62.1 exposes it as a latched lifecycle state, not an
  authoritative query of current inflight work.
- **Depend on Playwright's private `_inflightRequests`:** Rejected because
  private internals are unsupported and cannot be production authority.
- **Increase readiness timeouts or retry counts:** Rejected because it masks
  the poisoned historical membership, increases cost, and does not establish a
  safe readiness invariant.
- **Reduce browsers, jobs, checks, or assertions:** Rejected because it weakens
  CI authority rather than resolving readiness correctness.
- **Broadly prewarm Admin/product modules or add `optimizeDeps.include`:**
  Rejected without new independent evidence because it couples the workaround
  to current graph shape and does not prove readiness safety.

## Invariants

- No current research prototype is production readiness authority.
- Readiness changes must fail closed against both false-negative and
  false-Green hazards; eliminating the former does not justify introducing the
  latter.
- Full authority, CI Gate, Full Attestation, browser coverage, and current
  fail-closed CI classification remain unchanged.
- Navigation revision is activity evidence, not accepted-document identity.
- A latched `networkidle` lifecycle state is not treated as an authoritative
  current-inflight level query in this studied design.
- Unsupported private Playwright state is not a production contract.
- Timeout, retry, browser, job, check, and assertion weakening are not accepted
  substitutes for a proved readiness invariant.
- The Historical archive records evidence and discarded prototypes; this ADR
  owns the durable current decision.

## Consequences

Benefits:

- the repository does not accept an unresolved false-Green path;
- current CI authority and browser coverage remain intact;
- future investigators can begin from a proved root cause and capability
  boundary; and
- unsafe or duplicate tracker-retirement work has explicit closure criteria.

Costs and limitations:

- cold Firefox/Vite readiness may still fail on the first attempt and pass on
  retry;
- the historical request-lifetime gate remains a known false-negative source;
  and
- a production change remains blocked until a supported fail-closed ownership
  or current-work signal is independently proven.

## Conflict / integration guidance

Do not cherry-pick or wholesale carry the research prototypes into a future
final PR. A later implementation must classify the four research commits using
the dispositions in the Historical archive and re-establish the safety
invariant from current supported APIs and versions.

Stop for new architecture and repository authority if a proposal would retire
requests without supported accepted-document ownership, treat activity or a
latched lifecycle event as current-inflight proof, depend on private Playwright
internals, or weaken timeouts, retries, browser coverage, required jobs, CI
Gate, Full Attestation, or Full authority. A design that intentionally changes
this Accepted decision requires a new or superseding Decision Record.
