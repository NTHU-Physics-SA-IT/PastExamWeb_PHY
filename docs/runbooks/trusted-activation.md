# Trusted Activation operator runbook

Status: Historical — superseded by ADR-0013 and the
[protected coordination runbook](coordination.md). Do not dispatch the legacy
grant/issuance workflow or reuse any historical identity.

Source of truth for: configuring and operating the temporary protected
coordination trust root defined by ADR-0012

Related authority:

- [ADR-0012](../decisions/0012-trusted-ruleset-visibility-permission-boundary.md)
- [ADR-0011](../decisions/0011-trusted-activation-for-protected-coordination.md)
  (superseded lifecycle foundation retained by ADR-0012)
- [Validation policy](../development/validation.md)
- [Collaboration runbook](../development/collaboration-and-conflict-resolution.md)
- [Contributor workflow](../../CONTRIBUTING.md)

## Boundary

This runbook operates repository governance only. It does not authorize product
changes, production activation, database work, force pushes, protection
weakening, administrator bypass, identity reuse, or an otherwise unauthorized
merge.

Protected main is the authority source. A claim, branch name, local governance
value, candidate workflow, or GitHub Actions App check cannot authorize
coordination by itself. Missing, stale, malformed, unavailable, duplicate, or
ambiguous evidence fails closed.

## Fixed identities

- Repository: NTHU-Physics-SA-IT/PastExamWeb_PHY
- Repository ID: 1271339534
- Candidate workflow issuer that cannot satisfy the trusted check: App 15368
- Required trusted context: Trusted Governance Gate
- Ruleset: trusted-integration-lifecycle
- Environments: trusted-governance-verifier and trusted-coordination-issuance
- Policy and schemas: .github/trusted-activation/
- Branch-local claim: .github/trusted-activation/claim.json

Record the live independent App ID, client ID, installation ID, ruleset ID and
normalized digest, and protected-main SHA. Never record a private key, token,
secret value, or authorization header.

## Read-only lock

Before any setting or ledger mutation:

1. Fetch main and prove origin/main equals the GitHub main ref.
2. Require terminal successful Full CI for that exact SHA.
3. Confirm schema 1, default base main, coordination null, and no active claim.
4. Snapshot redacted main protection, rulesets, Environments, Actions
   permissions, installed Apps, open governance PRs, and integration refs.
5. Confirm the operation uses code from current protected main.
6. Record the expected mutation and exact rollback boundary.

Stop on concurrent governance mutation, an unexplained integration ref, stale
main, unavailable authority API, or a conflicting Accepted Decision.

## Independent GitHub App

Create a private repository- or organization-owned App with a unique
generation-specific name and install it only on this repository.

| Permission | Access | Exact use |
| --- | --- | --- |
| Metadata | Read | repository identity |
| Contents | Read and write | read state; trusted ref create/delete |
| Checks | Read and write | list, create, and update the App-owned gate |
| Actions | Read and write | allow downscoped Actions-read verifier tokens |
| Pull requests | Read | bind PR head/base/files |
| Administration | Write | make live ruleset `bypass_actors` visible to the isolated GET-only auditor |

The App has no unrelated permission. GitHub requires ruleset write access
before its read response includes `bypass_actors`; this platform capability is
not operational authority to mutate repository settings. Installation tokens
and clients are separated again:

- verifier/check client: Actions read, Contents read, Pull requests read, and
  Checks write, with no Administration permission;
- issuance/ref client: Contents write, with no Administration or Checks
  permission; and
- ruleset auditor: Administration write only, accepted by a dedicated client
  that permits GET solely to the exact repository-ruleset-by-ID endpoint.

The ruleset auditor rejects POST, PUT, PATCH, DELETE, branch-protection paths,
ruleset mutation paths, and every other administration endpoint before network
access. Never pass its token to the general verifier, check emitter, or ref
lifecycle client.

The App ID must differ from 15368. Record the permission response returned by
GitHub rather than only requested UI values.

### Private-key ceremony

1. Download one key through the authorized owner session.
2. Keep it only in a task-specific temporary file with mode 0600.
3. Upload it immediately as TRUSTED_GOVERNANCE_APP_PRIVATE_KEY to both
   protected Environments.
4. Store TRUSTED_GOVERNANCE_APP_CLIENT_ID and TRUSTED_GOVERNANCE_APP_ID in both
   Environments.
5. Verify only secret names and update times; never read values back.
6. Securely remove the exact temporary file.
7. Record creation, upload verification, and removal without key material.

Stop if safe creation, upload, or removal is unavailable. Never place the key
in a repository, transcript, issue, PR, artifact, cache, or evidence file.

## Protected Environments

Both Environments allow only protected main.

trusted-governance-verifier contains the App credentials, denies candidate
branch access and administrator bypass where supported, requires no approval
for availability, and never requests Contents write.

trusted-coordination-issuance contains the App credentials, requires the
governance Owner reviewer, enables prevent-self-review, denies administrator
bypass where supported, and permits only the downscoped issuance token.

Every future real grant requires explicit Owner approval. For an authorized
bounded rehearsal, the trigger actor must still differ from the Owner approval
actor. Record both immutable actor IDs. If GitHub cannot provide that
separation, stop; do not disable prevent-self-review.

## Protection before first existence

Create and activate trusted-integration-lifecycle before any matching branch.
Its target covers exactly one-level refs/heads/integration/* names.

The normalized contract:

- restricts creation and deletion to the independent App bypass actor;
- blocks non-fast-forward updates;
- requires a pull request, one approval, stale-review dismissal, last-push
  approval where supported, conversation resolution, and CODEOWNER review;
- requires strict check-branch and CI Gate bound to App 15368;
- requires strict Trusted Governance Gate bound only to the independent App.

Fetch the ruleset by ID, normalize it through trusted_governance_gate.py, and
record its digest. Confirm no integration ref exists. Unsupported rules, broad
bypass, inactive enforcement, wrong App binding, or digest mismatch block
issuance.

## Calibrate before main requirement

1. Preserve the exact prior main required-check configuration.
2. Branch from exact main and add one task-owned non-product CI fixture.
3. Open a ready main PR while the trusted gate is not required.
4. Wait for CI and the default-branch workflow-run verifier.
5. Prove successful exact-head/run binding, independent App issuer, and
   active=false for ordinary work.
6. Prove no candidate checkout, execution, artifact, cache, or environment use.
7. Close unmerged and delete only the exact calibration branch/worktree.
8. Add the App-bound gate to main while preserving check-branch, CI Gate,
   strictness, admin enforcement, conversation resolution, force-push
   prevention, and deletion prevention.
9. Read protection back and verify all three App bindings.

If the new requirement deadlocks valid PRs because the App cannot emit, restore
only the captured previous required-check list. Preserve every other
protection, repair, recalibrate, and re-add it.

## Immutable ledgers

Grant, revocation, and tombstone records use a lower-case UUIDv4 filename and
their strict schema. Unknown keys and duplicate JSON keys fail. Existing files
are immutable; main PRs only add records. Revocation and tombstone are paired.

Before committing:

    python3 scripts/ci/trusted_activation.py validate-ledgers
    python3 scripts/ci/trusted_activation.py validate-ledger-diff --base origin/main

A grant binds repository, branch, activation UUID, grant parent/current main,
grant blob, policy version/digest, ruleset ID/digest, App, and issuance
contract. Compute every value from live authority.

## Lifecycle

### Grant and issue

Generate a UUIDv4 and never-reused integration name. Merge a current-main grant
PR through Full CI and the App gate, then require exact-main Full. Dispatch the
protected-main issuance workflow with exact activation, main SHA, App ID,
ruleset ID, and digest. Approve its Environment with the distinct Owner actor.

The workflow proves grant, App, ruleset, current main, branch absence, and no
tombstone before creating the ref. Immediately verify exact grant commit,
protection from first existence, App creator, and PROTECTED_INACTIVE state.

### Negative self-authorization

Open a Full-only PR with an intentionally mismatched claim. Require the App gate
to reject it, no Equivalent, no merge, and no authority. Close unmerged and
remove only its task resources.

### Activate

Open a Full-only PR adding the exact claim and schema-1 local coordination
value. A Green gate means valid transition with active=false. Merge only after
exact Full/current checks and review. Resolve live state as ACTIVE afterward.

### Prove active coordination

Use a harmless non-governance, non-docs-only fixture branch from the active
head. Obtain Full source evidence, then open a PR to coordination. Equivalent
is allowed only when classifier, provenance, topology, current-main ancestry,
and independent authority validate. Remove the fixture during deactivation.

### Become stale and reconcile

Advance main with a real bounded governance checkpoint. Without mutating the
integration ref, require STALE and no Equivalent. Reconcile current main
through a protected Full PR and require ACTIVE afterward.

### Reject active return

Open one bounded return attempt while ACTIVE. Require App-gate rejection, no
merge or bypass, then close it and remove its task resources.

### Freeze, revoke, and deactivate

Freeze exact coordinated head F. Add a main revocation and permanent tombstone
binding activation, branch, F, and reason. Merge through current checks and
require exact-main Full. Prove authority false while the old claim remains.

Use a Full-only integration PR that incorporates main/revocation, removes claim
and temporary payload, and restores coordination null. A Green gate remains
active=false. Require current-main ancestry and RETURN_READY.

### Immutable return and retirement

Create the standard candidate from fresh main and true-merge the exact
return-ready head. Require exact topology/tree, Source Full, current-base PR
Full, the App gate, check-branch, CI Gate, clean mergeability, and review.
Merge with a GitHub merge commit and require exact-main Full.

Prove the integration tip is contained in main with zero unique commits.
Dispatch trusted retirement through the approved issuance Environment. Keep the
ruleset active. Run replay-preflight with the same name and UUID; it must reject
and the ref must remain absent.

## Recovery

For credential exposure: stop issuance and governed merges, revoke the exposed
key, rotate through the key ceremony, update both Environments, and recalibrate
before resuming.

For partial ref creation: do not activate, preserve protection and exact
evidence, revoke/tombstone any identity that could have existed, incorporate
revocation, retire only through the App after main containment, and reject
replay.

Never recover with force, history rewrite, direct owner ref mutation,
protection weakening, claim deletion without revocation, or identity reuse.

## Idle closure

Capture exact SHAs, PRs, workflow attempts, check-run IDs/issuers, normalized
settings/digests, actor IDs, and states without secrets. Require main schema
1/null with no claim; no integration ref or task PR; retained grant,
revocation, and tombstone; replay rejection; minimal App installation; both
protected Environments; active integration ruleset; main requiring the
App-owned gate plus existing checks; exact-main Full Green; and no production
or persistent-data mutation.
