# Notifications and side effects

Status: Active

Source of truth for: Durable notifications, external effects, transaction boundaries, and deletion outcomes

Applies to: Submission review, reports, discussion events, PostgreSQL, MinIO, Redis, and WebSocket behavior

Related documents:
- [Domain contracts](README.md)
- [Entity relationships](entity-relationships.md)
- [State transitions](state-transitions.md)
- [Migration safety](../migration-safety.md)

## Notification types

- **PersonalNotification** is a persistent, recipient-owned Domain event row.
- **Announcement** (`Notification` plus read receipts) is site-wide published
  content.
- **Frontend toast** is temporary UI feedback and is not Domain history.
- **WebSocket broadcast** propagates live state and is not a durable
  notification.

These mechanisms must not be described or tested as if they provide the same
guarantee.

## Current notification inventory

| Event | Durable notification | Recipient/source | Current transaction evidence |
| --- | --- | --- | --- |
| Discussion reply | `discussion_reply` | Replied-to participant; discussion source | Created in course/discussion service; covered by API tests |
| Discussion like | `discussion_like` | Message author; message source | One durable row; duplicate like constrained |
| Discussion pin | `discussion_pin` | Message author; message source | Created with the pin operation |
| Comment report submitted | `comment_report_submitted` | Reporter; report/source metadata | Enqueued in the report transaction |
| Comment report result | `comment_report_result` | Reporter; report/source metadata | Enqueued with final review |
| Archive report submitted | `archive_report_submitted` | Reporter; archive report source | Enqueued in the report transaction |
| Archive report result | `archive_report_result` | Reporter; report/source/takedown result | Enqueued with final review |
| Submission approved/rejected/takedown | Matching submission type | Submission requester; submission source | Helper enqueues before caller commit |
| Submission republished | `archive_submission_republished` | Submission requester; submission source | Enqueued with republish transition |

`backend/app/services/personal_notifications.py` inserts with
`ON CONFLICT DO NOTHING` on the dedupe key and flushes without committing.
Callers own the surrounding commit.

## Submission notifications

### Intended invariant

Notify the submitter when a submission is:

- approved;
- rejected (`未通過`);
- taken down;
- republished.

Do not notify submitters merely because a Course or Archive is moved to trash
or restored.

ArchiveSubmission owner, administrator, and system/cascade deletion remain
silent while recording exact delete provenance in the caller-owned database
transaction. An authorized completed-delete retry is a mutation-free
`changed=false` response and does not enqueue duplicate notifications or
events. A failed transaction rolls provenance, owner eligibility, the linked
Archive lifecycle, and side effects back together. Restore remains silent, and
Course trash/restore retains its existing notification semantics.

Direct administrator edit of an editable Submission state is also silent. The
route owns the canonical lock/revalidation and its single database commit;
pending, rejected, and takedown edits update only the Submission snapshot.
Takedown edit does not republish or restore its linked Archive. Forbidden,
stale, and failed edits leave Submission, linked Archive, notification, and
event state unchanged.

Review side effects are gated by the expected-state check and transition
policy:

- a true transition calls the existing notification owner inside the caller's
  database transaction;
- a same-target no-op does not enqueue a notification or any other event;
- a stale expected-state mismatch does not enqueue a notification or any other
  event;
- an illegal transition does not enqueue a notification or any other event.
- an Archive-link occupancy conflict, forbidden relink, or cardinality anomaly
  rolls back the approval transaction and does not retain Category, Course,
  Archive, status, link, notification, or event work.

The four direct review routes enforce these classifications after
administrator authorization and their canonical parent-first lifecycle locks.
The route/session remains the transaction owner; the shared planner neither
commits nor writes transition or notification state. Missing, stale, illegal,
and same-target requests release the transaction without mutation; only a true
transition reaches the existing notification owner after the locked canonical
re-read. A successful true transition returns `changed=true`; a same-target
no-op returns `changed=false`. The archive-report uphold flow remains an
internal, report-owned takedown operation and does not require a client
expected-state field.

Deterministic PostgreSQL race coverage pauses the first direct review request
after the real notification owner has enqueued and flushed its row but before
the caller commit. A second independent request has already attempted the same
canonical parent-first lock plan. Releasing the winner proves that the loser
reads the committed status and exits stale with no notification, metadata,
Archive, Category, Course, or event side effect. The winning transition owns
exactly one effective notification and one transaction outcome.

### Current implementation and gap

Status helpers create the four notification types. Rejection copy still uses
`已退回` in backend code. Course/archive lifecycle helpers generally avoid
review notifications.
`test_archive_trash_restore_temporarily_takes_down_submission_without_notification`
and `test_submission_trash_moves_only_its_paired_archive_to_trash` protect the
focused approved, independent-pair paths with notification counts recorded
after approval setup: Archive trash/restore and Submission trash add no
personal notification. Parent-first PostgreSQL coverage additionally protects
one-to-one Archive trash/restore and approve-versus-trash serialization:
lifecycle trash/restore remains silent, and only a successful direct review
transition can enqueue its existing single notification. A static
multi-source Archive relation fails closed through the generic internal-error
boundary and structured integrity log before lifecycle mutation; it does not
enter the retryable lifecycle-conflict path and produces no notification or
event.
If Archive trash or restore observes one locked membership mismatch, the route
rolls back before its one permitted plan rebuild. A second mismatch rolls back
before returning `409 archive_lifecycle_conflict`; neither attempt retains a
notification, event, lifecycle mutation, dirty ORM state, or transaction lock.
Planner invariant failures and database deadlock or timeout errors are not
translated into this public conflict contract.
`test_course_trash_restore_preserves_approved_submission_without_notification`
and `test_course_trash_restore_preserves_rejected_submission_without_notification`
record their notification baselines after the legal review setup and protect
that Course trash/restore adds no personal notification for either prior
state.
Course trash/restore now acquires its complete immutable parent-first plan
before mutation and revalidates the locked collection. The first dynamic
membership mismatch rolls back before one bounded rebuild; a second mismatch
rolls back before returning `409 course_lifecycle_conflict`. Neither attempt
retains Course, Archive, Submission, notification, or event work. Static
integrity anomalies and database deadlock/timeout errors do not enter this
public conflict boundary.

`test_archive_review_statuses_create_deduplicated_notifications` and
`test_republish_restores_approved_and_notifies_requester_once` provide partial
test evidence.

## Repeated transition cycles

### Intended invariant

- Leaving a state and later entering it again is a new transition cycle and
  sends another notification.
- Repeating a request for the current target state is a successful no-op and
  sends nothing.
- A same-target retry creates no other data, statistical event, or audit event
  and does not overwrite the original transition actor or time.
- The caller distinguishes a no-op (`changed=false`) from a new transition
  (`changed=true`).
- A dedupe key distinguishes a retry of one event from a later real cycle.

### Implementation gap

`enqueue_submission_status_notification` currently uses a permanent
`submission_id + target status` dedupe key for approve/reject/takedown. It can
suppress a legitimate later cycle. Republish includes transition-time context,
so the strategies are inconsistent.

## Report notifications

### Current implementation

Creating comment/archive reports records a submitted acknowledgement for the
reporter. Final review records a result notification; archive-report result
metadata also describes whether takedown occurred. The notification row is
written in the same database transaction as the corresponding report create or
review operation.

If notification enqueue raises, the transaction is expected to fail rather
than commit the report alone. The unique dedupe key protects retry of the same
logical create/review event.

ArchiveReport review acquires the exact Course, Archive, optional
ArchiveSubmission, and ArchiveReport rows in canonical parent-first order
before either the Report decision or optional Submission takedown is mutated.
For a source-less legacy report, an upheld takedown soft-trashes the exact
Archive under the same locks without fabricating a Submission or touching
object storage. That Archive mutation shares the Report and result-notification
transaction.
Soft trash and restore use the same ordering and remain notification-free. The
route/session continues to own commit and rollback; the planner performs no
mutation, notification insert, or commit. Revalidation failure therefore
leaves Report, Archive or Submission, and notification state unchanged.

### Test evidence

- `test_comment_report_creation_validates_auth_reason_scope_and_duplicates`
- `test_comment_report_admin_review_is_authorized_atomic_and_idempotent`
- `test_archive_report_creation_auth_validation_duplicate_and_notification`
- `test_archive_report_review_optional_takedown_is_atomic_and_non_destructive`
- `test_archive_report_concurrent_create_and_review_have_single_winner`

## Source availability

### Intended invariant

| Source state | Link behavior |
| --- | --- |
| Active and authorized | Link may open the source |
| Soft-deleted | Do not expose an active link; an authorized historical view may be designed separately |
| Hard-deleted | Retain the notification, mark the source unavailable, display `來源已不存在`, and expose no active source action or navigation |
| Missing or unauthorized | Mark unavailable without revealing protected existence |

Permanent source deletion does not delete durable notification history. A
replacement or historical source view may be designed later, but no operation
may continue to navigate to the deleted source.

### Current implementation and gap

`backend/app/api/services/notifications.py` resolves source availability by
notification type. Discussion, submission, and archive-report sources use
different queries and soft-delete checks. Frontend handling in
`NotificationCenterModal.vue` opens only selected available source types.
Hard-delete and legacy-source behavior is not yet one consistent contract.
The complete source-availability API and `來源已不存在` UI presentation remain
an implementation gap and are not yet protected by a focused test.

## ArchiveSubmissionEvent side effect

### Intended invariant

The statistical event survives deletion. Permanent deletion removes its active
submission link and unnecessary identity, but does not create a link to deleted
content and does not block the deletion.

### Current implementation and gap

Creation writes the event in the submission transaction. Permanent lifecycle
cleanup currently deletes events through
`delete_archive_submission_events`, conflicting with the intended retention
contract. The later technical design must define a nullable link and/or stable
snapshot without retroactively changing statistical meaning.

## PostgreSQL and MinIO permanent deletion

### Product contract

- A single item that succeeds in only PostgreSQL or only MinIO is not reported
  as wholly successful.
- Failure is explicit, diagnosable, and retryable.
- The system does not claim that PostgreSQL and MinIO share one atomic
  transaction.

### Current implementation

Archive upload writes the MinIO object before all database work is committed.
Some upload/approval paths contain multiple database commits. Permanent-delete
helpers attempt MinIO cleanup and database deletion, but storage exceptions can
be converted into warnings before the database commit.

### Implementation gap and future direction

A MinIO delete failure can leave an orphan object while the API reports the
database deletion as successful. The planned direction is staged deletion with
explicit pending/failed state plus retry or compensation. This direction is
not implemented and may require a separately reviewed additive migration.

## Bulk permanent delete

### Intended invariant

Bulk permanent delete intentionally permits partial success between items:

- return an independent result for every item;
- keep successful items successful;
- retain a retryable failure state and reason for failed items;
- retry only failed items;
- do not process completed items again;
- show item-level failures in the UI.

One item may not conceal a half-completed internal deletion even though
different items in the batch may have different final results.

### Current implementation

`trash.py` processes and commits bulk items independently and returns successes
and failures. This supports cross-item partial success. The single-item
PostgreSQL/MinIO guarantee remains incomplete because storage errors can be
warnings rather than failed item results.

`test_bulk_permanent_delete_commits_successes_and_reports_item_failures`
protects the bulk orchestration boundary with mocked items: every item is
attempted, one item's commit is retained when a later item rolls back, and the
response identifies both the success and the failure reason. It does not prove
single-item PostgreSQL/MinIO atomicity, staged deletion, or real storage
integration.

## Transaction boundaries

| Operation | Current boundary | Risk/status |
| --- | --- | --- |
| Archive upload | MinIO put, then database work; admin/course/archive paths may commit in stages | Partial object/DB or partial DB state is possible |
| Submission approve | Category/Course/Archive work, submission review metadata, and notification enqueue share the approve caller's commit | PostgreSQL operation is caller-owned and protected by focused rollback tests |
| Submission owner/admin delete | The route owns authorization, canonical parent-first locks, lifecycle mutation, and commit | Existing delete behavior remains silent; lock/revalidation failure commits no quota, status, Archive, notification, or event change |
| Submission exact restore | The route owns canonical parent-first locks, occupancy validation, lifecycle mutation, and commit; conflict or integrity failure rolls back before returning | Restore remains silent, consumes exact prior-state provenance, falls back to pending when it is absent, and only republishes the retained exact Archive for an approved restore |
| Submission direct administrator edit | The route owns authorization, canonical parent-first locks, locked state/membership validation, snapshot mutation, and one commit | Pending/rejected/takedown edits are silent and Submission-only; approved/deleted rejection or any failure leaves the linked Archive and side effects untouched |
| Archive metadata mutation/reparent | The route owns administrator authorization, canonical source/target Course, Archive, and exact Submission locks, post-lock validation, mutation, and one commit | Silent and database-only; it creates/restores no Course, changes no Submission, performs no MinIO operation, and rolls back the complete mutation on failure |
| Course soft trash/restore | The route owns discovery, canonical Category/Course/Archive/Submission locks, one bounded membership rebuild, lifecycle mutation, and commit | Existing Course results and counts remain unchanged; both operations remain silent |
| Report create/review | Report mutation and durable personal notification share a commit; ArchiveReport review uses canonical Course/Archive/optional Submission/Report locks and includes optional linked-Submission takedown or exact legacy-Archive soft trash | Database-atomic; legacy takedown fabricates no Submission and performs no storage operation |
| ArchiveReport soft trash/restore | Route-owned canonical parent-first lock plan, Report metadata mutation, then commit | Silent; existing status and pending-uniqueness behavior are unchanged |
| Republish | Transition and notification share the caller transaction | Comparatively complete |
| Permanent delete | MinIO call and DB delete cannot be atomic; helper may downgrade storage failure to warning | Retry and truthful result gap |
| WebSocket discussion update | Database commit precedes broadcast | Durable write succeeds even if live delivery fails |
| Redis | Used primarily for authentication token blacklist/state | Not part of archive lifecycle atomicity |

## NTHU OAuth and login handoff

The provider callback owns NTHU profile validation and one PostgreSQL User
transaction. A denied, malformed, conflicting, or soft-deleted identity rolls
back that transaction. A successful resolution commits the User before
creating a Redis handoff; Redis failure returns a generic login failure and
does not issue an application token. The committed identity remains safe for a
fresh OAuth retry.

The handoff is a cryptographically random opaque code. Redis stores only its
SHA-256-derived key and the local User ID, with a 90-second TTL. The exchange
uses atomic `GETDEL`; unknown, expired, malformed, or replayed codes fail
closed. The callback URL contains only this one-time code. It never contains
the NTHU access token or the application JWT. The repository Nginx and Uvicorn
access-log paths omit the callback query string. The frontend removes the code
from browser history before the exchange request. Logs owned by an external
edge/CDN remain an environment-level verification responsibility.

Only a successful exchange issues the normal application bearer JWT in JSON,
updates `last_login` and `last_seen_at`, creates/touches presence state, and
commits those database effects together. Local login, logout, heartbeat, and
their existing token owner remain unchanged. OAuth state is stored in the
existing signed session and removed before validation, making success,
mismatch, missing-state, and replay paths one-time.

### Intended invariant

Every business operation has a visible database transaction owner. Helpers do
not hide commits. Non-transactional effects occur at a declared point, and
their failure policy, retry safety, idempotency, and compensation are explicit.

## Test evidence

Current tests directly cover report atomicity/deduplication, discussion durable
notifications, personal-notification ownership, archive storage upload
failures, and bulk dispatch. They do not yet cover rollback/compensation across
PostgreSQL and MinIO or all repeated submission transition cycles.

The pure review-policy matrix and expected-state classifier have exhaustive
unit coverage. Focused PostgreSQL API tests protect direct-route precondition,
error, no-op snapshot, transition, rollback, and notification behavior.
Deterministic independent-session PostgreSQL race tests protect
first-writer-wins for double approval and both winner orders for every pair
among approve, reject, and takedown from `pending`. Later-cycle notification
identity and dedupe remain Stage 5C work.

The S3C closure matrix additionally holds the first complete canonical lock
plan while a competing transaction reaches the same lock boundary. It covers
both winner orders for direct review versus owner deletion, direct review
versus administrator deletion, direct takedown versus exact restore, and the
service-level system/cascade delete primitive versus owner deletion. Only a
committed review transition enqueues its single existing notification.
Deletion, exact restore, stale losers, and completed-delete retries remain
notification- and event-free, and the final state is independently reloaded
after both transactions complete.

ArchiveSubmission approval evidence additionally injects failure after
Category flush, after Course/Archive flush before link, after link/status
mutation before notification, after notification flush, and at final commit.
Every case retains the pre-existing submission and upload event while removing
all transaction-local parent, Archive, link, status, reviewer, and notification
work. A separate independent-session race holds the first approval at its
commit boundary while a second approval requests the same missing
Category/Course identity; both complete without deadlock, with one Category,
one Course, two independent Archives/links, and one approval notification per
submission.

## Required follow-up

Prioritize characterization tests for permanent-delete partial failure,
multi-commit approval, repeated notification cycles, and source resolution.
Implement storage consistency only in the later safety-net and conformance
stages; do not infer atomicity from the current API response.
