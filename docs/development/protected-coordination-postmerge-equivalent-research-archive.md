# Protected coordination postmerge Equivalent research archive

Status: **Historical / Research — not operational authority**

Current operating authority is
[ADR-0014](../decisions/0014-protected-coordination-exact-state-postmerge-reuse.md),
the [validation policy](validation.md), and the
[coordination runbook](../runbooks/coordination.md). This archive records why
the final design was selected and prevents repeated exploration of rejected
boundaries.

## Decision trail

### Historical generic and Case-B reuse

The repository's generic `equivalent-merge` mode predates protected ADR-0013
coordination. ADR-0006 added a strict Case-B route that retained Source Full and
PR Full, then replaced only final-Q heavy work with lightweight provenance when
topology, trees, refs, runs, and complete governance identity matched. The
retained PR #95 fixture and successful PR #101 history are the positive
evidence for that older model.

### ADR-0013 structural break

ADR-0013 established these different but intentional identities:

- canonical main: schema 1, default base `main`, `coordination_branch: null`;
- active integration: schema 1, default base `main`, and
  `coordination_branch` equal to the exact branch itself.

Because ADR-0006 compared the complete governance inventory, a valid active
integration could no longer equal main. The old proof became unreachable even
when H, synthetic P, and final Q had identical trees.

### Rejected research stages

1. **Broad field-sensitive trust surface — ARCH-RED.** A complete inventory of
   workflows, classifiers, gates, test selectors, migration/schema controls,
   dependency inputs, and transitive configuration was mechanically possible
   but remained candidate-verified and costly to maintain.
2. **Only the coordination semantic difference — NARROW-RED.** Treating main
   null versus integration self-name as the sole semantic exception was small
   and coherent, but matched 0/9 Stage 5F merges and 1/11 in the wider protected
   sample because other governance identities changed.
3. **Persistent blocker classification — REFINED-RED.** Alembic migrations were
   product-risk state, but audit/schema/migration-safety authorities and the
   backend shard manifest were mixed or CI-control state. A safe useful route
   still required a growing allowlist or semantic dependency analysis.
4. **Independent verifier/App/Environment.** Rejected as disproportionate. It
   would add credential, permission, availability, replay, and operator
   lifecycle solely to avoid a duplicate Full run.

These results rejected path-based authorization; they did not prove that exact
tested repository-state transfer was valueless.

## Accepted trust-policy boundary

The Owner explicitly accepts a same-repository protected PR normal merge as the
trust-transfer point for the exact PR-tested state. Policy result:
**POLICY-ACCEPTABLE-WITH-BOUNDED-RISK**.

Source Full tests H. PR Full tests synthetic P against C. The Owner merges the
exact PR normally. Q-side Equivalent then proves state transfer; it does not
claim an independent verifier identity. Candidate/Q-side CI semantics remain
part of the state accepted by the Owner. This residual risk already exists when
candidate-controlled Q runs Full, so the selected route does not add a new
human ceremony, App, Environment, required check, or auto-merge dependency.

## PR Full versus final-Q Full differential audit

Verdict: **EXACT-STATE-GREEN**.

For protected integration, PR Full and final-Q Full execute the same heavy
families: frontend/backend lint, migration safety, backend shards and coverage,
frontend unit and browser families, frontend/backend builds, Full Attestation,
and CI Gate. Image publication, release, and deployment are main-only and do
not distinguish PR P from integration Q.

The useful Q-only work is lightweight and state-specific:

- verify the non-forced exact integration push and `(C,H)` parent order;
- bind one merged same-repository PR to C, H, and Q;
- bind exact successful Source Full for H;
- recover exact P from the PR Full attestation and prove
  `parents(P)=(C,H)`;
- prove `tree(P)=tree(H)=tree(Q)` and no H-to-Q content difference;
- reject reconciliation tails and unsupported embedded merge history;
- recheck the integration ref, main freshness, and current merged PR; and
- feed the existing Equivalent provenance result into the existing CI Gate.

Everything else is duplicate heavy execution. Full remains the fallback when
any Q-only fact is absent or ambiguous.

## Historical exact-state sample

The audit recovered durable synthetic P objects rather than assuming the live
`refs/pull/*/merge` ref still existed. Every listed theoretical candidate had
ordered P and Q parents `(C,H)`, identical P/Q/H trees, and an empty H-to-Q
content diff.

| PR | Historical role | Exact P/Q result | Final interpretation |
| --- | --- | --- | --- |
| #101 | ADR-0006 historical positive | Exact | Compatible predecessor evidence |
| #177 | Protected integration merge | Exact | Exact-state candidate |
| #194 | Protected integration merge with migration state | Exact | Exact-state candidate; no path exemption needed |
| #204 | Protected integration merge | Exact | Exact-state candidate |
| #208 | Protected milestone merge | Exact | Exact-state candidate |
| #209 | Protected milestone merge | Exact | Exact-state candidate |
| #210 | Protected milestone merge | Exact | Exact-state candidate |
| #211 | Docs-only product PR | Exact | Positive Q specimen; Source and PR still stay Full |
| #213 | Protected milestone merge | Exact | Exact-state candidate |

The modern theoretical cohort was 8/8. PR #214 was a return-to-main/closeout
lifecycle operation and remains categorically Full outside the candidate set.
Reconciliation-tail shapes remain Full under ADR-0007.

Observed final-Q Full cost across the eight modern candidates was approximately
100 minutes 51 seconds of wall time and 301.0 job-minutes. The retained
historical lightweight Equivalent proxy was about 30 seconds. These are sample
observations, not guaranteed future performance.

## Final accepted design

The implemented route is:

> Source Full(H) + PR Full(P) + trusted Owner normal merge + lightweight exact-
> state provenance(Q).

No governance identity comparison, migration/audit/schema/shard exception, or
dynamic trust-surface engine participates. Unknowns fail closed to the existing
Full path. Main remains Full; Source and PR remain Full; Start keeps its
dedicated mode; tails, return/close, release, production, and hotfix remain
Full.

PR #211 is evidence only. This design does not make integration-derived Source
or protected-integration PR events docs-only. That is separate future research.

## DO NOT REPEAT

Do not reopen this route by:

- growing a broad governance or CI-control allowlist;
- semantically exempting migration, audit, schema, or shard files;
- building a dynamic trust-surface/dependency classifier;
- adding an independent App, Environment, or required check unless future
  premises materially change;
- weakening Source Full or PR Full;
- extending Equivalent to main, release, production, lifecycle close, or
  reconciliation tails; or
- treating #211 Source/PR docs-only as part of exact-state postmerge reuse.

## Review and reopening criteria

Review ADR-0014 before continued reuse if:

- heavy jobs gain material push/ref-specific behavior;
- integration Q receives new secrets, Environment access, or permissions not
  exercised by PR Full;
- GitHub no longer exposes durable P, run, job, or attestation evidence;
- merge strategy, integration ruleset, or required-check topology changes;
- Source Full or PR Full semantics materially change; or
- the candidate-controlled verifier risk is no longer acceptable to the Owner.

Any future change requires fresh authority and a new explicit decision. This
archive remains historical evidence, not an alternative operating contract.
