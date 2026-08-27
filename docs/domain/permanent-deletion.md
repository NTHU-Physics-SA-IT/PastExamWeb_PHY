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

Stage 5F-A adds only an additive, initially empty PostgreSQL persistence
foundation. It does not accept a permanent-deletion request, change an
existing Trash action, call MinIO, process or reconcile work, emit a
notification, expose an API, or add UI behavior. Existing permanent-delete
runtime behavior and its documented consistency gap remain unchanged until a
later explicitly reviewed stage activates this contract.

## Authority and irreversibility

PostgreSQL is the only durable workflow ledger. MinIO answers only whether one
recorded exact object version exists; it is not workflow authority.

Permanent deletion becomes irreversible only when a later backend stage
durably commits a deletion intent and explicitly accepts it. The durable
initial operation state is `ACCEPTED`, never `PENDING`. Stage 5F-A can
represent that acceptance but does not accept any real request.

The operation state namespace is independent of `SubmissionStatus` and
contains exactly:

- `ACCEPTED`;
- `PROCESSING`;
- `VERIFICATION_REQUIRED`;
- `RETRYABLE_FAILED`;
- `MANUAL_REVIEW`; and
- `COMPLETED`.

No current Trash lifecycle state or projection changes. Object-processing
state is also explicit and separate from submission lifecycle state.

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

Stage 5F-A stores this representation only. It performs no storage read or
write and does not enable, suspend, or inspect bucket versioning.

## Retry, reconciliation, and manual review

The schema limits automatic attempts to 10 and represents a maximum automatic
retry window of 24 hours from acceptance. It supports due-work selection,
next-attempt scheduling, bounded claim leases, unknown/timeout verification,
stable result codes, `MANUAL_REVIEW`, and later retry after revalidation.

Stage 5F-A implements no backoff algorithm, processor, scheduler,
reconciliation worker, manual-review endpoint, force-complete, cancel, or
restore action.

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
