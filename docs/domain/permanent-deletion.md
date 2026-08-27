# Permanent deletion

Status: Active

Source of truth for: Durable permanent-deletion workflow authority, exact
storage identity, recovery-state separation, and retention boundaries

Related documents:

- [Entity relationships](entity-relationships.md)
- [State transitions](state-transitions.md)
- [Notifications and side effects](notifications-and-side-effects.md)
- [Migration safety](../migration-safety.md)

## Activation status

Stage 5F-A added the additive PostgreSQL persistence foundation, and Stage 5F-B
added the internal accept/process saga. Stage 5F-C activates that sealed saga
only for administrator single-item Trash deletion rooted at `Archive`,
`ArchiveSubmission`, or `Course`.

For those roots, a new or unfinished durable operation returns HTTP `202`; only
an operation whose exact storage absence and final PostgreSQL transaction have
reached `COMPLETED` returns HTTP `200`. A deterministic server-owned identity
reuses the same operation for repeated requests, including a completed repeat
after the live Trash row has disappeared. The response and status surface expose
only the root identity, durable state, timestamps, stable redacted result code,
and capability flags. Object keys, buckets, Version IDs, target manifests, raw
exceptions, credentials, and descriptive snapshots remain private.

The current Trash list carries the same minimal operation projection so an
accepted unfinished root remains visible after reload. Lifecycle `status`
continues to mean only lifecycle truth such as deleted or taken down; operation
state appears only in the compact action/dependency area. The Admin UI treats
`202` as pending/attention truth, uses bounded read-only status polling, and
shows final success/removes the row only after `COMPLETED`.

The existing bulk route and excluded single-item roots remain on their prior
behavior until Stage 5F-D. Stage 5F-C adds no scheduler or recurring worker;
bounded administrator process-one/status/retry actions cover only currently
claimable states until Stage 5F-E. `MANUAL_REVIEW` is inspect-only unless the
sealed backend policy explicitly marks a retry safe; there is no force-complete,
cancel, resurrection, or retry-budget reset.

## Authority and irreversibility

PostgreSQL is the only durable workflow ledger. MinIO answers only whether one
recorded exact object version exists; it is not workflow authority.

For the Stage 5F-C roots, permanent deletion becomes irreversible when the
backend durably commits the `ACCEPTED` operation, targets, and exact storage
identity. Before that commit, a pre-accept failure leaves the row restorable.
After it, restore/cancel is unavailable even while storage processing is
unfinished, uncertain, retryable, or in manual review. The Trash projection
removes restore authority, and the restore endpoint rechecks the durable
operation after acquiring the existing lifecycle locks so acceptance and
restore cannot both succeed.

The operation state namespace is independent of `SubmissionStatus` and
contains exactly:

- `ACCEPTED`;
- `PROCESSING`;
- `VERIFICATION_REQUIRED`;
- `RETRYABLE_FAILED`;
- `MANUAL_REVIEW`; and
- `COMPLETED`.

No Trash lifecycle state changes. Object-processing state remains explicit and
separate from submission lifecycle state.

## Durable records

`permanent_deletion_operations` owns one reusable durable operation per
logical deletion intent. It records the root logical identity, a deletion-safe
nullable requester reference without an actor snapshot, a unique idempotency
identity, accepted and completion times, automatic-attempt count, retry
deadline and due time, bounded lease identity/expiry, stable redacted result
code, and completed-audit purge schedule.

`permanent_deletion_targets` records logical target identity without a foreign
key to the live entity. It can retain a role and a paired membership
fingerprint/capture time for later final database-membership revalidation. A
partial unique reservation prevents two unreleased operations from reserving
the same logical target. Releasing a reservation permits a later distinct
intent without rewriting historical operation identity.

`permanent_deletion_objects` is active recovery data owned by a logical target
and its operation. It records the bucket, object key, identity scheme, exact
Version ID, explicit processing state, capture/attempt/unknown-outcome/
verification times, bounded attempt count, stable redacted result code, and
verified-absence time. The child record may be deleted or compacted after
completion; the 180-day minimal operation audit does not require retaining
storage identity for that entire period.

No table stores PDF contents, title, filename solely for audit, Course,
Category, Professor, Archive or submission description snapshots, raw
exceptions, arbitrary reconstruction JSON, credentials, or tokens.

## Exact MinIO identity

The only storage identity scheme is `MINIO_VERSION_ID_V1`.

- Key-only deletion is forbidden.
- A content fingerprint is not a deletion fallback.
- Future acceptance requires live bucket versioning to be `ENABLED`.
- A normal versioned object records its exact non-empty Version ID.
- A verified legacy pre-versioning object records the literal string `"null"`;
  SQL NULL and an empty string are invalid.
- The legacy literal may be captured only after versioning is enabled and an
  exact `stat_object(..., version_id="null")` resolves the intended target.
- Future stat, retry, delete, and verification use that exact Version ID.
- Completion requires verification that the recorded exact version is absent.
- Key-level `NoSuchKey` or a delete marker is not completion evidence.
- Suspended/disabled versioning or known identity drift fails closed.

Stage 5F-B's internal adapter reads live bucket versioning, captures and uses
only the recorded exact Version ID, and verifies exact-version absence. It
never changes bucket versioning, deletes by key alone, substitutes a content
fingerprint, or treats a key-level delete marker as completion evidence.

## Retry, reconciliation, and manual review

The schema limits automatic attempts to 10 and represents a maximum automatic
retry window of 24 hours from acceptance. It supports due-work selection,
next-attempt scheduling, bounded claim leases, unknown/timeout verification,
stable result codes, `MANUAL_REVIEW`, and later retry after revalidation.

Stage 5F-B implements deterministic bounded retry policy, a claim/lease-safe
process-one primitive, and unknown-outcome verification. Stage 5F-C exposes one
minimal administrator status read and one capability-gated process-one retry
surface for `ACCEPTED`, `VERIFICATION_REQUIRED`, and due `RETRYABLE_FAILED`.
It adds no operation-history dashboard, scheduler, recurring reconciliation
worker, force-complete, cancel, or restore action.

## Internal Stage 5F-B processing

Internal acceptance builds and revalidates the complete logical deletion plan,
reserves every logical target, captures each exact object version only while
versioning is enabled, and commits the operation, target, and object recovery
records together in PostgreSQL. Repeating the same idempotency identity reuses
the same operation; a conflicting active target reservation fails closed.

One process invocation claims a bounded PostgreSQL lease, revalidates logical
membership and storage identity before each destructive step, and performs no
unbounded polling or sleeping. An unknown or timeout outcome enters
`VERIFICATION_REQUIRED` and must be exactly verified before another delete.
Known retryable failures remain bounded by 10 automatic attempts and 24 hours;
identity, reference, versioning, or budget drift enters `MANUAL_REVIEW`.

After every recorded exact storage version is conclusively absent, one
PostgreSQL transaction revalidates membership again, applies the live-row
deletion effects, detaches retained `ArchiveSubmissionEvent` links, preserves
`PersonalNotification` history, completes the operation, and releases target
reservations and the lease. A database failure rolls back both live-row effects
and completion; a later process invocation recognizes already-absent storage
and retries only database finalization.

## Completion and retention

`COMPLETED` requires a completion timestamp and a purge time at least 180 days
later. Incomplete or live operations do not expire merely because time passes.
The retained operation is minimal audit only; descriptive snapshots are
forbidden. Exact storage child identity remains recoverable while needed and
can be removed after completion.

The additive migration backfills or rewrites no existing row. Its downgrade
is permitted only while all three new ledger tables are empty. Once any
operation, logical target, or object recovery row exists, downgrade fails
before dropping data or schema.

## Preserved Stage 5E relationships

`ArchiveSubmissionEvent` remains creation-only aggregate history. Later true
permanent deletion retains the event ID and exact `submitted_at`, nulls only
its live `submission_id` link, and performs that detach with live submission
database deletion in one PostgreSQL transaction. No actor or descriptive
snapshot is retained.

`Archive.course_id` remains current placement authority. Requested or proposed
submission metadata remains historical and does not imply transfer or
reparenting. `PersonalNotification` remains recipient-owned durable history,
not restore or permanent-deletion workflow authority.
