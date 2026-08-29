# Protected coordination operator runbook

Status: Active

Source of truth for: starting, inspecting, reconciling, returning, and closing
temporary protected integration coordination under ADR-0013

Related authority:

- [ADR-0013](../decisions/0013-simplified-protected-coordination.md)
- [ADR-0014](../decisions/0014-protected-coordination-exact-state-postmerge-reuse.md)
- [Validation policy](../development/validation.md)
- [Collaboration runbook](../development/collaboration-and-conflict-resolution.md)
- [Contributor workflow](../../CONTRIBUTING.md)

## What does main null mean?

Canonical main stays:

```json
{
  "schema_version": 1,
  "default_development_base": "main",
  "coordination_branch": null
}
```

This means main is the ordinary development base and does not point to an
active coordination target. It does not prohibit a separately protected
`integration/*` branch. An active integration branch carries its own copy of
project governance naming that exact branch.

Ordinary main-target feature, fix, documentation, and Dependabot work requires
no coordination command, UUID, SHA, App/ruleset identifier, Environment
approval, reviewer, or knowledge of this lifecycle.

## Start with Codex

Say:

> Start Stage 5E coordination.

Codex uses the same protected workflow as the manual fallback. It refreshes
main and live settings, verifies exact-main CI and the integration ruleset,
checks that no integration coordination exists, generates a safe suffix,
creates the branch through the lifecycle App, publishes a short-lived non-secret
Start attestation, and reads the final state back. The resulting bootstrap may
use lightweight CI only when the independent provenance job revalidates the
exact App origin, unchanged ruleset, one-parent current-main topology,
governance-only tree identity, and fresh parent Full evidence. Missing,
ambiguous, stale, or changed evidence runs Full instead.

## Start manually

In GitHub, open **Actions → Start or Close Coordination → Run workflow** and
choose:

- operation: `start`
- name: `stage-5e`

Use a short lowercase semantic name containing at least one letter. Purely
numeric values are machine identifiers and are rejected, as are names that
look like full UUIDs, full commit SHAs, or complete ref names.

Do not enter a UUID, SHA, repository/App/installation/ruleset ID, or digest.
The system prints the generated branch, exact base main SHA, `ACTIVE` state,
and expected pull-request base.

## Know whether coordination is active

An active summary has all four facts:

- generated `integration/<name>-<suffix>` branch;
- branch-local `coordination_branch` equals that exact branch;
- current main is an ancestor (`ACTIVE`, otherwise `STALE`); and
- future coordinated pull requests target that exact integration branch.

The existence of a visible branch alone is not authority. Missing, malformed,
ambiguous, unprotected, or multiple integration refs fail closed.

## If main advances

The integration branch becomes `STALE`. No history is rewritten and no branch
is silently called fresh. Reconcile main through an ordinary protected Full-CI
pull request to the integration branch, resolve semantic conflicts using the
collaboration runbook, and confirm current main is again an ancestor. Push the
exact reconciliation source and promptly open its normal pull request so the
independent Source Full and PR Full workflows may overlap. Source and pull-
request workflows remain Full. After the Owner's normal same-repository merge,
only an exact C/H/P/Q state with both Full results may use lightweight
Equivalent; every mismatch, reconciliation tail, or unavailable proof remains
Full.

## Return coordinated work to main

Freeze the final integration head. Build the normal reviewable return candidate
from fresh main, true-merge the exact frozen head, and restore the candidate's
project governance to canonical main/null. Open the normal main pull request,
wait for its required Full evidence, merge normally, and wait for exact-main
Full. Close is not eligible until the frozen integration head is contained in
that exact Green main.

## Close with Codex

Say:

> Close Stage 5E coordination.

Codex uses the same protected workflow and human name. The system resolves the
exact branch, refreshes main, rejects `STALE` or unreturned work, proves the
integration head is contained in exact Green main, creates an App-owned
closeout commit with main's exact tree and null governance, verifies it, and
deletes only the exact integration ref.

## Close manually

After the return merge and exact-main Full are Green, open
**Actions → Start or Close Coordination → Run workflow** and choose:

- operation: `close`
- name: `stage-5e`

The result reports the final main SHA, retired branch, frozen integration SHA,
closeout SHA, and `RETIRED`. No second person or machine identifier is entered.

## Failure and recovery

- Start failure before ref creation leaves no integration ref; correct the
  reported authority problem and issue one new start intent.
- A created branch that fails exact read-back remains protected. Do not delete
  or mutate it blindly; inspect the exact ref and workflow result.
- Close rejects work not contained in main. Complete the normal return; do not
  bypass containment.
- A closeout commit that exists before deletion has null governance and main's
  exact tree. Resume only after proving those exact facts.
- Never force-push, weaken protection, use a candidate workflow, transcribe
  hidden identifiers, or reuse the obsolete rehearsal identity.
- Do not treat `coordination-start` as an ordinary coordination optimization.
  Pull requests, feature pushes, reconciliation sources and tails, return, and
  closeout remain Full. Only ADR-0014's exact final normal merge may reuse its
  mandatory Source and PR Full evidence.

The old run `32628689925`, UUID
`714d9c51-8b6b-405d-bd7c-4c92f6f26699`, and branch name
`integration/trusted-activation-rehearsal-714d9c51` were cancelled/retired
before issuance and must never be approved, rerun, or reused.
