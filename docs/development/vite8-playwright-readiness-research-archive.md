# Vite 8 / Playwright Readiness Research Archive

Status: Historical

This document preserves research and background evidence. It is not
day-to-day operational authority. [ADR-0009](../decisions/0009-retain-fail-closed-vite-readiness-under-playwright-api-limits.md)
owns the durable current decision.

## 1. Executive Summary

The research established why Playwright Firefox readiness could fail during a
cold Vite 8 dependency-discovery cycle and then pass quickly on retry. Request
objects from superseded documents could remain in a persistent user-side
tracker after the current 79-resource module graph had stabilized. The hard
`activeRequests === 0` gate was therefore poisoned by historical membership,
while a retry received a fresh tracker and a warmed Vite graph.

Instrumentation proved this mechanism, including pre-baseline ownership of the
decisive plateau. The investigation did not find a supported public API that
could safely distinguish all stale historical work from genuine current work
or provide an authoritative atomic current-inflight checkpoint. Retiring
requests or replacing the gate with activity quiescence would therefore carry
an unresolved false-Green risk.

Research is complete; safe implementation is blocked. The selected outcome is
Architecture C: no safe change yet. The repository accepts the known
false-negative/retry debt rather than promote an unsafe prototype.

## 2. Initial Problem / Why Research Started

The observed frontend readiness instability included:

- Vite 8 cold dependency discovery and optimization;
- `504 Outdated Optimize Dep` responses and `net::ERR_ABORTED` requests;
- reloads and multiple documents during one readiness attempt;
- Admin lazy-module prewarm timeout and navigation instability;
- repeated discovery of the same 79-resource graph;
- Firefox behavior that could depend on Playwright retry; and
- occasional false-negative Red Full CI results.

The investigation aimed to remove the retry dependence without weakening the
meaning of frontend readiness.

## 3. Research Safety Constraints / Non-goals

The research was fail-closed. It did not authorize:

- a false Green that declares readiness while genuine current work remains;
- weaker Full, CI Gate, Full Attestation, browser, job, or check authority;
- increased timeout or retry counts as the solution;
- broad Admin/product prewarming without independent proof;
- private Playwright internals as production authority; or
- Vite implementation, CI policy, Docker, database, migration, or production
  changes outside the research branch.

The runtime observations below are evidence from the named runs. Conclusions
about tracker ownership are repository inferences supported by the added
instrumentation. Statements about supported signals are scoped public-API
capability findings for Playwright 1.62.1, Vite 8.2.1, and the studied Firefox
readiness design, not general claims that Playwright, Vite, Firefox, or
`networkidle` are universally broken.

## 4. Research Timeline / Phase Progression

1. **D2A observation:** A real Firefox Full failure passed after a
   whole-workflow retry. D2A entered `integration/stage-5bd`, not `main`.
2. **Source Full 1:** Added stronger optimized-resource identity and readiness
   observations. The workflow was Green only after the readiness retry.
3. **Source Full 2:** Proved bounded explicit recovery retirement could reach
   zero, then exposed a replacement 17-request plateau. A GitHub codeload 429
   prevented repository runtime on the first workflow attempt; the same
   run/SHA executed on attempt 2.
4. **Source Full 3:** Confirmed explicit recovery retirement while showing the
   unexpected-replacement retirement predicate did not activate.
5. **Ownership-decisive Source Full:** Instrumentation tied every member of the
   final plateau to pre-baseline revision 6, while accepted baselines advanced
   through later revisions.
6. **Phase 5K:** Stopped because an accepted-document boundary could not be
   safely proved through supported public signals. No Phase 5K commit was
   created.
7. **Architecture Review A:** Considered bounded activity quiescence after the
   historical lifetime gate was proven false-negative.
8. **Architecture Review B:** Rejected the quiescence replacement because no
   supported authoritative current-inflight level or atomic zero-work
   checkpoint existed for this case.
9. **Architecture C:** Closed the research with no safe production change.

## 5. Exact Runtime Evidence Table

| Evidence | Run / SHA | Runtime result | Research conclusion |
| --- | --- | --- | --- |
| Historical D2A | Run `31998378115` | Attempt 1 had a real Firefox Full failure; whole-workflow attempt 2 was Green | Retry dependence was real. D2A merged into `integration/stage-5bd`, not `main`. |
| Source Full 1 | Run `32040829272`; `9c0790ec668b3f0289421037a3773e443812beb6` | Workflow Green; readiness attempt about 25.592 s failed, retry about 4.415 s passed; active plateau `11 -> 15 -> 15 -> 15 -> 15`; the same 79-resource graph was repeatedly rediscovered | Reliability not accepted; discovery identity alone did not clear historical active lifetime. |
| Source Full 2 | Run `32044312143`; `8edeb313c67aa93d945d6c20a415b182fcf0d430` | Attempt 1 stopped at GitHub codeload HTTP 429 before repository runtime. Attempt 2 on the exact same run/SHA was Green; explicit recovery reached `active=0`, then a replacement plateau reached 17; readiness attempt about 26.024 s failed, retry about 5.124 s passed | Explicit recovery retirement could work in its bounded case, but request epochs were not a safe general ownership model. |
| Source Full 3 | Run `32059659374`; `a5f85303714fd46a24f208ba277bbbf339fbbaa8` | Workflow Green; explicit recovery retirement worked; unexpected-replacement retirement did not activate; active plateau 11; readiness attempt about 25.241 s failed, retry about 5.096 s passed | The replacement predicate was incomplete and ownership-dependent. Reliability not accepted. |
| Ownership-decisive Source Full | Run `32065177900`; `d9dfa75c8dbe512bbe35b133ad1b697970c796a6` | Workflow Green; readiness attempt about 24.844 s failed, retry about 4.355 s passed; plateau 15; every plateau request belonged to revision 6; accepted baselines advanced through revisions 9, 11, 13, and 15; no current-baseline ownership group existed | Pre-baseline superseded-document ownership was proven. |

A workflow-level Green above is a runtime observation, not acceptance of the
readiness design. Runs that required readiness retry remained reliability
failures for the research objective.

## 6. Proven Root Cause Chain

```text
Vite 8 cold dependency discovery
-> new dependency optimization
-> 504 Outdated Optimize Dep / aborts / reloads
-> multiple documents during readiness
-> Request objects from superseded documents may remain in the persistent
   user-side tracker without retained terminal events
-> the current document graph can stabilize at the same 79 identities and
   generation
-> hard activeRequests === 0 remains poisoned by historical membership
-> repeated identical discovery
-> the 25-second readiness deadline expires
-> Playwright retry creates a fresh tracker
-> the warmed Vite graph passes in about 4-5 seconds
```

## 7. What Was Proven

- Stale active membership was real, not merely inferred from retry timing.
- The decisive 15-request plateau belonged entirely to pre-baseline,
  superseded-document work.
- The current 79-resource graph could already be healthy while historical
  `Request` lifetime remained active in the persistent tracker.
- A fresh tracker plus warmed Vite graph explained the fast retry.
- Explicit recovery retirement could work in one bounded, proved recovery.
- Navigation revision recorded activity but did not safely identify the
  accepted document.
- Playwright 1.62.1 `networkidle` could not be used as a supported
  current-inflight level query in this design.

## 8. What Could Not Be Proven / Public API Limits

The research could not safely establish through supported public APIs:

- a general `Request` to accepted-document or accepted-loader ownership
  boundary;
- an authoritative current-inflight level snapshot for the studied Firefox
  native-module traffic;
- an atomic zero-work checkpoint combined with subscription to every future
  request start; or
- a replacement activity-quiescence invariant that prevents both historical
  false negatives and current-work false Greens.

Browser Resource Timing did not provide an authoritative current-inflight set
for native module traffic. Private Playwright `_inflightRequests` state could
offer implementation detail, but it is unsupported and was excluded from
production authority.

## 9. Approaches Tried and Why Rejected

- **Optimized-resource identity and graph stability:** Full optimized pathname
  plus nonempty `v` identity improved observation, but the same stable graph
  could coexist with poisoned historical active membership.
- **Request epoch retirement:** Explicit recovery retirement was runtime-proven
  in a bounded case, but epochs did not safely generalize to document
  ownership.
- **Unexpected replacement retirement:** The predicate did not activate in the
  Source Full 3 plateau and introduced incomplete ownership-dependent
  complexity.
- **Revision-only retirement:** Rejected because revision represented activity,
  not accepted-document identity.
- **`tokenChanged OR revisionChanged`:** Rejected because weakening ownership
  to either signal could retire genuine current work.
- **`activeRequests.clear()`:** Rejected because clearing membership discards
  safety evidence without proving current readiness.
- **Timeout or retry increases:** Rejected because they mask the mechanism and
  increase cost without creating a correctness invariant.
- **Broad prewarm or `optimizeDeps.include`:** Rejected without independent
  evidence; graph-shape workarounds do not prove readiness.
- **Browser, job, or check reduction:** Rejected because it weakens evidence
  authority rather than fixes readiness.

## 10. Tracker-retirement Research Closeout

Tracker-retirement patching is closed under the current public-API boundary.
No further revision-only retirement, token-or-revision weakening, bulk clear,
or additional ownership predicate should be layered onto the prototypes.

The closeout does not assert that precise retirement is impossible in every
future platform. It records that the studied supported signals did not safely
prove the boundary needed for production.

## 11. Architecture Review A

Review A accepted that historical active `Request` lifetime was a
false-negative hard gate and considered bounded activity quiescence as a
replacement. This could avoid waiting forever on objects from superseded
documents while requiring the observed module identity set and navigation
state to remain stable.

The unresolved question was current work: activity silence is not itself an
authoritative proof that there is no genuine inflight request. Without an
atomic boundary between observing zero work and subscribing to future starts,
a request can be missed and readiness can turn false Green.

## 12. Architecture Review B

Review B examined whether supported signals could close that race:

- Playwright 1.62.1 `networkidle` was a latched lifecycle state rather than a
  resettable, level-sensitive current-inflight query.
- Public request events provided transitions but no supported atomic current
  level snapshot.
- Browser Resource Timing was not authoritative for the native-module request
  set.
- Private `_inflightRequests` was unsupported and unsuitable as production
  authority.

No supported atomic zero-work checkpoint plus future-start subscription was
identified. Activity quiescence therefore remained unable to prove
current-inflight false-Green safety.

## 13. Final Decision / Known Reliability Debt

The final outcome is **Architecture C — No Safe Change Yet**.

PastExamWeb_PHY keeps the known cold-readiness false-negative and retry cost
rather than adopt an unresolved false-Green path. This is a deliberate safety
tradeoff recorded durably by ADR-0009. It does not weaken Full authority, CI
Gate, Full Attestation, browser coverage, timeouts, retries, assertions, or
other current CI semantics.

## 14. Research Commit Dispositions

Research history must not be rewritten. If future capability changes justify a
new implementation, classify these commits as follows rather than carrying the
branch wholesale:

| Commit | Disposition | Preserved research value |
| --- | --- | --- |
| `9c0790ec` | Partial survival / rework | Full optimized pathname plus nonempty `v` identity, discovery/stability separation, shared deadline, failure observation/consumption, document continuity, and final release checks are useful concepts. Its hard active-lifetime authority cannot survive unchanged. |
| `8edeb313` | Drop before any future final PR | Explicit recovery retirement was runtime-proven, but request epoch retirement is not a generally safe supported ownership model. |
| `a5f85303` | Drop before any future final PR | It exposed the limits of the unexpected-replacement predicate, but adds incomplete ownership-dependent complexity. |
| `d9dfa75c` | Research-only | Its instrumentation proved pre-baseline ownership decisively, but the large diagnostic and test expansion should not be carried wholesale into production readiness. |

## 15. Closed Directions

Under the current capability boundary, do not pursue:

- more tracker-retirement patches;
- revision-only retirement;
- `tokenChanged OR revisionChanged` weakening;
- `activeRequests.clear()`;
- activity-quiescence implementation;
- private Playwright inflight state;
- timeout or retry increases;
- browser, job, check, or assertion reduction;
- broad Admin/product prewarming; or
- `optimizeDeps.include` without new independent evidence.

## 16. Reopening Criteria

Reopen the design only if a material capability changes and a separately
reviewed implementation proves it fail closed. Qualifying evidence could be:

- a supported public current-inflight signal;
- a resettable, level-sensitive network-idle primitive;
- a supported atomic zero-work checkpoint plus future-start subscription;
- a supported Vite optimizer-ready or quiescence signal; or
- another separately approved public architecture that prevents both false
  negatives and false Greens.

A future decision must use current versions and fresh independent evidence. If
it changes ADR-0009's Accepted decision, it requires a new or superseding
Decision Record.

## 17. Evidence References / Run IDs / Research Branch / Final SHA

- Research branch: `fix/ci-vite-playwright-readiness-stability`
- Final research SHA:
  `d9dfa75c8dbe512bbe35b133ad1b697970c796a6`
- Historical D2A run: `31998378115`
- Source Full runs: `32040829272`, `32044312143`, `32059659374`, and
  `32065177900`

The research commits were not merged into `main`. After this documentation is
durable in `main`, the local and remote research branch refs are retired. The
local worktree remains registered at the exact final SHA, detached,
git-worktree-locked, and macOS `uchg`-protected as the preserved prototype and
evidence anchor.
