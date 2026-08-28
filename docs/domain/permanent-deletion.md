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

Stage 5F-A added the additive PostgreSQL persistence foundation, Stage 5F-B
added the internal accept/process saga, and Stage 5F-C first activated that
sealed saga for administrator single-item Trash deletion rooted at `Archive`,
`ArchiveSubmission`, or `Course`. Stage 5F-D extends the same durable path to
every remaining Trash root: `CourseCategory`, `CourseSubmission`,
`SystemIssueReport`, `CommentReport`, `ArchiveWishReport`, `ArchiveReport`,
`Notification`, and `User`.

For those roots, a new or unfinished durable operation returns HTTP `202`; only
an operation whose exact storage absence and final PostgreSQL transaction have
reached `COMPLETED` returns HTTP `200`. A deterministic server-owned identity
reuses the same operation for repeated requests, including a completed repeat
after the live Trash row has disappeared. The response and status surface expose
only the root identity, durable state, timestamps, stable redacted result code,
and capability flags. Object keys, buckets, Version IDs, target manifests, raw
exceptions, credentials, and descriptive snapshots remain private.

The current Trash list carries the same minimal operation projection so an
accepted unfinished root or a row covered by an unfinished containing operation
remains visible after reload. Lifecycle `status` continues to mean only
lifecycle truth such as deleted or taken down; operation state appears only in
the compact action/dependency area. The Admin UI treats `202` as
pending/attention truth, uses bounded read-only status polling for an explicit
single-item action, and shows final success/removes the row only after
`COMPLETED`.

Stage 5F-D also replaces the legacy bulk-delete result with per-item durable
truth. Bulk remains an outcome-bounded request, not a global transaction or a
durable batch ledger: it snapshots the selected Trash scope, evaluates each
item through the same idempotent accept/process-once path, and returns outer
HTTP `200` after the batch has been evaluated. Every requested item has exactly
one result: `COMPLETED`, `PENDING`, `MANUAL_REVIEW`, `FAILED`, or `SKIPPED`,
with explicit requested/completed/pending/manual-review/failed/skipped counts.
`SKIPPED` is permitted only when a durable target reservation or a current
batch operation proves that another operation covers the item. A missing row,
conflict, or error without that proof is `FAILED`; absence is never guessed to
mean success. Bulk performs one immediate Trash reload and does not create a
polling loop per result.

Stage 5F-E adds a dedicated backend reconciler process. Once intentionally
started, it discovers a bounded deterministic batch of due PostgreSQL
operations and passes each ID to the existing process-one claim/lease path.
It is not a FastAPI startup task and is not enabled by ordinary development or
production Compose startup. Production activation remains deferred and needs
separate Owner authorization. `MANUAL_REVIEW` remains inspect-only unless the
sealed backend policy explicitly marks a retry safe; there is no force-complete,
cancel, resurrection, or retry-budget reset.

## Authority and irreversibility

PostgreSQL is the only durable workflow ledger. MinIO answers only whether one
recorded exact object version exists; it is not workflow authority.

For every activated Trash root, permanent deletion becomes irreversible when the
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
surface for `ACCEPTED`, `VERIFICATION_REQUIRED`, and due `RETRYABLE_FAILED`;
Stage 5F-D reuses those surfaces for all Trash roots. Stage 5F-E's internal
worker selects claimable `ACCEPTED` and `VERIFICATION_REQUIRED`, due
`RETRYABLE_FAILED`, and expired-lease `PROCESSING` operations. It never selects
`MANUAL_REVIEW` or `COMPLETED`, creates no operation, scans no live Trash row or
storage object, and duplicates no claim, retry, verification, or lease policy.
Concurrent selectors may observe the same candidate; the existing atomic claim
and fresh ownership barriers decide the winner safely. No operation-history
dashboard, force-complete, cancel, restore action, or durable batch ledger is
added.

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

The Stage 5F-E operational pass also purges a bounded deterministic batch only
when an operation is already `COMPLETED` and its persisted
`audit_purge_after` is due. It does not recompute or shorten that deadline,
contact MinIO, or delete a live Domain row. Existing cascades remove only the
completed ledger's audit children. Unfinished operations, including
`MANUAL_REVIEW`, never expire merely because they are old. Reconciliation and
audit purge use independent transactions, so purge failure cannot reverse or
misreport already processed operations.

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
