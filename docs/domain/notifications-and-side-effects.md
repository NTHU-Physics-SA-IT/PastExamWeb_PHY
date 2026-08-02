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

Review side effects are gated by the expected-state check and transition
policy:

- a true transition calls the existing notification owner inside the caller's
  database transaction;
- a same-target no-op does not enqueue a notification or any other event;
- a stale expected-state mismatch does not enqueue a notification or any other
  event;
- an illegal transition does not enqueue a notification or any other event.

The four direct review routes enforce these classifications after
administrator authorization and a submission row lock. Missing, stale,
illegal, and same-target requests release the transaction without mutation;
only a true transition reaches the existing notification owner. The
archive-report uphold flow remains an internal, report-owned takedown operation
and does not require a client expected-state field.

### Current implementation and gap

Status helpers create the four notification types. Rejection copy still uses
`已退回` in backend code. Course/archive lifecycle helpers generally avoid
review notifications.
`test_archive_trash_restore_temporarily_takes_down_submission_without_notification`
and `test_submission_trash_moves_only_its_paired_archive_to_trash` protect the
focused approved, independent-pair paths with notification counts recorded
after approval setup: Archive trash/restore and Submission trash add no
personal notification. Shared-Archive sibling behavior remains outside this
evidence.
`test_course_trash_restore_preserves_approved_submission_without_notification`
and `test_course_trash_restore_preserves_rejected_submission_without_notification`
record their notification baselines after the legal review setup and protect
that Course trash/restore adds no personal notification for either prior
state.

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
- The caller can distinguish the no-op from a new transition, without this
  stage prescribing the response field name.
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
| Report create/review | Report mutation and durable personal notification share a commit; archive report takedown is included | Comparatively complete and protected by focused tests |
| Republish | Transition and notification share the caller transaction | Comparatively complete |
| Permanent delete | MinIO call and DB delete cannot be atomic; helper may downgrade storage failure to warning | Retry and truthful result gap |
| WebSocket discussion update | Database commit precedes broadcast | Durable write succeeds even if live delivery fails |
| Redis | Used primarily for authentication token blacklist/state | Not part of archive lifecycle atomicity |

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
Deterministic independent-session race tests remain necessary to prove
first-writer-wins under controlled concurrency.

## Required follow-up

Prioritize characterization tests for permanent-delete partial failure,
multi-commit approval, repeated notification cycles, and source resolution.
Implement storage consistency only in the later safety-net and conformance
stages; do not infer atomicity from the current API response.
