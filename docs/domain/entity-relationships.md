# Entity relationships

Status: Active

Source of truth for: Domain ownership, dependency, grouping, and lifecycle relationships

Applies to: SQLModel entities, public archive behavior, trash/restore, reports, and stored objects

Related documents:
- [Domain contracts](README.md)
- [State transitions](state-transitions.md)
- [Notifications and side effects](notifications-and-side-effects.md)
- [Migration safety](../migration-safety.md)

## Relationship inventory

The current database models and schemas are primarily defined in
`backend/app/models/models.py`. The table relationships below describe the
current implementation separately from the intended product relation.

| Entity | Current database/logical relation | Intended product/lifecycle relation | Evidence and gaps |
| --- | --- | --- | --- |
| `User` | Owns uploads, submissions, reports, discussion activity, and personal notifications through user IDs; many actor/deleter FKs use `SET NULL`, while some owned rows cascade | Authentication identity and audit actor; deletion must preserve required history without exposing unnecessary identity | Confirmed by code; deletion policy varies by entity |
| `CourseCategoryConfig` | `Course.category` stores its key as a string rather than an FK; submissions also retain category snapshots | Category controls discovery and creation choices, but its soft-delete lifecycle is independent from historical submissions | Confirmed by code; no DB FK means application checks carry integrity |
| `Course` | Required parent of `Archive`; category is a string key; has soft-delete metadata | Groups archives for navigation; course trash may hide/deactivate children but must not rewrite independent submission review results | Confirmed by code in `courses.py` and `trash.py` |
| `CourseSubmission` | Requester/reviewer and optional `created_course_id`; no soft-delete metadata in the current model | A course/category request attached to an archive-submission flow; created category/course becomes independent after approval | Implementation gap: current model is a separate review record and has no defined trash lifecycle |
| `Archive` | Required `course_id`, optional uploader, one `object_name`, optional soft-delete metadata; at most one submission points to it through the named nullable unique `created_archive_id` constraint | One independently accessible approved public file for authenticated system users, optionally created by exactly one submission | Administrator-created Archives may have no source submission; approval, exact restore, and source projection fail closed on occupancy or cardinality violations |
| `ArchiveSubmission` | Required requester and object name; optional reviewer, legacy owner, and nullable unique `created_archive_id`; review/trash fields and monotonic owner-self-delete eligibility coexist | One independent submission and PDF, optionally paired with exactly one Archive. Ownership survives eligibility consumption | Database uniqueness and application fail-fast guards are enforced; group-lifecycle corrections remain a later milestone |
| `ArchiveSubmissionEvent` | Unique `submission_id` integer and timestamp, without a declared FK | Immutable statistical event retained after submission deletion, with active link/PII detached as needed | Implementation gap: permanent-delete helper currently deletes events |
| `ArchiveDiscussionMessage` / `ArchiveDiscussionLike` | Message requires archive and user IDs; parent/reply references form a thread; likes cascade with message/user deletion | Discussion belongs to the referenced public item; soft-deleted messages should not remain an active source | Confirmed by code and `test_archive_discussion.py` |
| `CommentReport` | Reporter FK cascades; target and actor/resource FKs mostly `SET NULL`; snapshots preserve context; independent soft delete | Report history survives source changes while active uniqueness and source availability remain explicit | Partially implemented |
| `ArchiveReport` | Optional archive/submission/user FKs with `SET NULL`; required snapshots preserve archive context | May report both submission-backed and legacy archives; review can optionally take down the target | Legacy creation is supported; legacy direct takedown remains an implementation gap |
| `SystemIssueReport` | Optional reporter, read/review metadata, GitHub-sync metadata, independent soft delete | Operational report independent of archive/submission lifecycle | Confirmed by code and tests |
| `Notification` / announcement receipts | Global announcement plus per-user read receipt | Site-wide announcement, distinct from a personal event notification | Confirmed by code |
| `PersonalNotification` | Required recipient; optional actor/source fields; unique `dedupe_key`; source message FK uses `SET NULL` | Durable, recipient-owned event record retained when its source is permanently deleted; source availability and actions follow source lifecycle | Confirmed by code; unavailable-source presentation and source resolution differ by Domain |
| MinIO object | Referenced by `Archive.object_name` and `ArchiveSubmission.object_name`; no dedicated database entity | One stored object belongs to one independent PDF lifecycle; deletion result must be reconciled with DB state | No cross-system transaction; current cleanup can partially succeed |

## Independent approved files

### Intended invariant

- Matching course, year/term, teacher, and exam name/type forms only a logical
  exam group.
- Every submission number and PDF is independent.
- One logical group may expose multiple effective approved PDFs at the same
  time.
- A pending, rejected, takedown, or deleted sibling must not hide another
  effective approved PDF.
- One submission must not permanently delete or change the review result of a
  different submission.

### Current implementation

`backend/app/api/services/courses.py` derives public archive data and source
submission IDs. `archive_submission_lifecycle.py` resolves exact
`created_archive_id` links during delete/restore. Report-source resolution in
`reports.py` also considers the linked submission.

### Known gap

Historical data with multiple submissions pointing to one Archive is an
invalid relationship, not a supported logical group. The database constraint
prevents new duplicate non-null links. Approval and submission restore perform
an application precheck, with the named unique constraint remaining the final
concurrency arbiter. A legitimate occupied target returns
`409 archive_submission_link_conflict`; a non-null relink attempt or static
multi-occupant result is an internal integrity anomaly and fails closed without
choosing or exposing an occupant. Submission restore uses only the retained
exact `created_archive_id`; a null link does not trigger metadata-based Archive
inference.

`source_submission_ids` remains the compatibility response field. A normal
Archive has either `[]` or one source-submission ID. Source projection validates
cardinality before applying requester visibility and fails closed instead of
truncating an anomalous multi-source result.

### Frontend rendering evidence

`renders_each_archive_when_exam_metadata_matches_but_ids_differ` confirms that,
when the Archive list response contains two records with matching exam
metadata but different Archive identities, the frontend preserves two cards
and two identity-specific download operations. This test does not protect the
backend sibling-visibility query or object-storage availability.

## ArchiveSubmission comparison candidates

### Intended invariant

The administrator comparison view groups submissions by the existing
course, academic term/year, teacher, and exam-name identity predicates.
Within that group:

- course snapshot identity uses the first normalized non-blank value from
  `requested_course_name`, then `subject`; null, empty, and whitespace-only
  values do not block the fallback;
- current and candidate submissions use equivalent course normalization, while
  the existing linked-Course identity path remains valid in both directions;
- `pending`, `approved`, and `takedown` submissions are comparison candidates;
- `rejected` and `deleted` submissions are excluded;
- only the current `ArchiveSubmission` primary identity is excluded;
- requester, owner, Archive, course, or matching metadata does not merge or
  exclude a different submission; and
- two different submission IDs remain two comparison candidates even when
  every displayed metadata field is equal.

The comparison response is read-only and preserves each candidate's submission
identity and status for frontend rendering.

## Trash relationship

### Intended invariant

- Deleting a submission places that submission and its corresponding public
  archive item in trash.
- Deleting a public archive item places the item in trash; its corresponding
  submission is temporarily taken down for a system lifecycle reason but does
  not enter submission trash.
- A system-induced takedown is distinguishable from an administrator's
  independent takedown.
- Restore uses the previous state and lifecycle reason. It must not
  automatically approve a submission that was pending or rejected.

### Current implementation

`archive_submission_lifecycle.py` records lifecycle-reason strings and handles
archive/submission groups. `trash.py` dispatches entity-specific restore and
permanent deletion.

`test_archive_trash_restore_temporarily_takes_down_submission_without_notification`
directly protects the approved single-pair path: Archive trash leaves its
Submission outside submission trash, marks it as a system-induced temporary
takedown, and Archive restore returns it to approved.
`test_submission_trash_moves_only_its_paired_archive_to_trash` directly
protects two independent pairs: trashing Submission A trashes Archive A while
Submission B, Archive B, and B's object identity remain unchanged. These tests
cover the supported independent one-to-one pairs. Multiple submissions sharing
one Archive are an invariant violation, not an additional lifecycle case.

### Known gap

Submission-group restore can set a linked submission to approved without
preserving every prior review state, and group operations can affect siblings.
Characterization and transition tests are required before changing this code.

## ArchiveSubmission ownership and self-delete eligibility

The requester is the normal submission owner. Legacy `owner_id` applies only
when requester identity is genuinely absent; two conflicting identities do not
create two owners. Administrator authorization is independent.

Owner self-delete eligibility belongs to one `ArchiveSubmission`, not to its
paired Archive or any metadata-similar submission.
Consequently:

- each submission stores and backfills
  `owner_self_delete_consumed` independently;
- consuming eligibility does not remove ownership or submission-number
  visibility;
- restoring the submission or its paired Archive does not reset eligibility;
- metadata-consistent historical system/cascade deletion is conservatively
  backfilled as consumed, while a future system/cascade delete preserves the
  submission's existing value;
- conflicting requester and legacy owner identities remain invalid and fail
  closed during migration;
- an Archive cannot be linked to a second submission; duplicate historical
  links block the one-to-one schema migration without choosing a winner;
- the eligibility migration does not update Archive rows.

This schema establishes durable state and historical backfill only. The later
Stage 5A application milestone still owns route authorization, conflict/no-op
responses, future administrator and system/cascade value preservation, read
capability projection, and frontend controls.

## ArchiveSubmissionEvent

### Intended invariant

The event is immutable statistical history. Permanent submission deletion:

- retains the event;
- removes or anonymizes unnecessary personal data and the active entity link;
- does not expose a usable link to the deleted submission;
- is not blocked by the event.

The exact snapshot/anonymization schema is a later technical design.

### Current implementation and test evidence

`submission_statistics.py::record_submission_event` writes the minimal
submission ID and timestamp. `test_record_submission_event_keeps_only_stable_statistics_fields`
and `test_submission_event_survives_delete_restore_and_permanent_delete` express
the statistical retention goal.

### Implementation gap

`archive_submission_lifecycle.py::delete_archive_submission_events` currently
deletes matching events during permanent deletion. Focused unit tests cover the
helper's deletion behavior, demonstrating the current conflict rather than the
intended invariant.

## CourseSubmission

### Intended invariant

- It represents an archive submission that also requests a new course or
  category.
- Existing normalized category/course identities are reused rather than
  duplicated.
- Once created, the category and course are independent of the
  `CourseSubmission` lifecycle.
- Trashing a `CourseSubmission` does not trash the created category/course.
- Restore does not recreate them.
- The request must not permanently block deletion of an otherwise independent
  category/course.
- Necessary request snapshots and review history are retained.

### Current implementation

`CourseSubmission` has requester, reviewer, status, and `created_course_id`.
Archive approval paths also carry requested course/category snapshots directly
on `ArchiveSubmission` and reuse existing records under application-level
locking.

### Known gap

The two representations are not a single explicit lifecycle. `CourseSubmission`
does not currently have trash metadata, and idempotent restore behavior is not
fully specified by code/tests.

## Legacy Archive without ArchiveSubmission

### Intended invariant

A historical `Archive` without an `ArchiveSubmission` remains reportable by an
authenticated user and can be taken down directly by an administrator.

### Current implementation and gap

`reports.py` permits creation of an archive report when no linked submission
exists and retains archive snapshots.
`test_legacy_archive_can_be_reported_without_submission` confirms that an
authenticated reporter can create the pending report with no submission link,
the Archive snapshots and report-submission audit are retained, and one
submitted notification is created. The current optional report-takedown path
expects a linked active submission, so direct legacy takedown is not complete.
Whether later implementation manages the `Archive` directly or creates a
system-generated submission record is a decision required; this document does
not choose the mechanism.

## Blocking and orphan risks

- String category keys can orphan logical relationships without an application
  guard.
- `SET NULL` report/source FKs preserve history, but a permanently deleted
  source must render as `來源已不存在` without an active source action or
  navigation. The complete API/UI treatment remains an implementation gap.
- Shared archive/object references create sibling-deletion risk until the
  independent-file model is enforced.
- PostgreSQL rows and MinIO objects can diverge because no atomic transaction
  spans them.

## Required follow-up

Add characterization tests for sibling visibility and lifecycle grouping before
schema or service refactoring. Any schema change must follow
[Migration safety](../migration-safety.md).
