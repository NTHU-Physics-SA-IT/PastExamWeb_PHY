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
| `CourseSubmission` | Separate historical course-request record with requester/reviewer, independent soft-delete metadata, and nullable `created_course_id` using `ON DELETE SET NULL` | Retains the request and review history without owning the resulting Category/Course | Course deletion detaches the optional historical link; submission deletion never cascades to Course |
| `Archive` | Required `course_id`, optional uploader, one `object_name`, optional soft-delete metadata; at most one submission points to it through the named nullable unique `created_archive_id` constraint | One independently accessible approved public file for authenticated system users, optionally created by exactly one submission | Administrator-created Archives may have no source submission; approval, exact restore, and source projection fail closed on occupancy or cardinality violations |
| `ArchiveSubmission` | Required requester and object name; optional reviewer, legacy owner, nullable unique `created_archive_id`, and nullable `source_wish_id`; review/trash fields and monotonic owner-self-delete eligibility coexist | One independent submission and PDF, optionally paired with exactly one Archive. Ownership survives eligibility consumption, and Help Upload retains its source wish without creating a separate upload lifecycle | Database uniqueness, application fail-fast guards, and exact-pair soft-lifecycle coverage are enforced; deleting a wish sets the optional source link null |
| `ArchiveSubmissionEvent` | Unique `submission_id` integer and timestamp, without a declared FK | Immutable statistical event retained after submission deletion, with active link/PII detached as needed | Implementation gap: permanent-delete helper currently deletes events |
| `ArchiveDiscussionMessage` / `ArchiveDiscussionLike` | Message requires archive and user IDs; parent/reply references form a thread; likes cascade with message/user deletion | Discussion belongs to the referenced public item; soft-deleted messages should not remain an active source | Confirmed by code and `test_archive_discussion.py` |
| `CommentReport` | Reporter FK cascades; target and actor/resource FKs mostly `SET NULL`; snapshots preserve context; independent soft delete | Report history survives source changes while active uniqueness and source availability remain explicit | Partially implemented |
| `ArchiveReport` | Optional archive/submission/user FKs with `SET NULL`; required snapshots preserve archive context | May report both submission-backed and legacy archives; review can optionally take down the target | A source-less legacy takedown soft-trashes the exact Archive without fabricating an ArchiveSubmission |
| `SystemIssueReport` | Optional reporter, read/review metadata, GitHub-sync metadata, independent soft delete | Operational report independent of archive/submission lifecycle | Confirmed by code and tests |
| `Notification` / announcement receipts | Global announcement plus per-user read receipt; optional English title/body coexist with required Chinese content | Site-wide bilingual announcement with locale fallback to Chinese, distinct from a personal event notification | Confirmed by code and focused API tests |
| `AboutUsEntry` | Independent persisted Markdown title/body entries, optional English title/body, and an optional last-editor reference | Authenticated-readable bilingual managed information with Chinese locale fallback; administrators may permanently delete an entry without Trash | Confirmed by code and focused API tests |
| `ArchiveWish` | Creator-owned immutable exam target snapshot with a unique canonical `target_key`; optional Course FK and nullable `academic_year` | Persists a term-specific or Any Semester Wish without creating a Course or Category. Fulfillment is derived from a matching effective-public Archive; fulfilled rows remain persisted but leave the user-facing pool | Confirmed by API and migration tests |
| `ArchiveWishHeart` | Unique `(wish_id, user_id)` row; both FKs cascade | At most one heart per user per wish; the API toggles the row under a wish lock | Confirmed by named uniqueness and focused API tests |
| `ArchiveWishReport` | Optional Wish/reporter/reviewer FKs use `SET NULL`; snapshots preserve the reported target | Moderation record survives Wish or User deletion and moves once from pending to upheld/dismissed | Confirmed by API and schema contracts |
| `PersonalNotification` | Required recipient; optional actor/source fields; unique `dedupe_key`; source message FK uses `SET NULL` | Durable, recipient-owned event record retained when its source is permanently deleted; source availability and actions follow source lifecycle | Confirmed by code; unavailable-source presentation and source resolution differ by Domain |
| MinIO object | Referenced by `Archive.object_name` and `ArchiveSubmission.object_name`; no dedicated database entity | One stored object belongs to one independent PDF lifecycle; deletion result must be reconciled with DB state | No cross-system transaction; current cleanup can partially succeed |

## NTHU authentication identity

`User.oauth_provider` and `User.oauth_sub` form the provider identity. For the
NTHU integration the only valid mapping is `oauth_provider="nthu"` and
`oauth_sub=<NTHU uuid>`. `userid`, email, and name are profile attributes and
must never substitute for a missing, blank, or malformed `uuid`.

`User.student_id` is the single nullable persisted copy of the NTHU resource
`userid`. It is an affiliation attribute, not an identity or account-linking
key. Local accounts keep it null. A successful NTHU login synchronizes it from
the current provider profile; a denied login does not mutate it.

The backend owns one parser, one derived affiliation classifier, and one
Registrar-derived department catalog. A standard nine-digit value is split into
admission year `[0:3]`, college code `[3:5]`, department code `[3:6]`, and
program code `[3:7]`. The parser does not infer bachelor, master, or doctoral
status from one digit. A parsed value whose department exists in the catalog is
`standard_student`; staff-like employee identifiers may be shown as `staff`
with a heuristic classification source. Missing, non-standard, and unsupported
values remain `unresolved` and receive no inferred department or special status.
These classifications are derived on read and are never persisted as identity
or authorization facts. Full userids and derived affiliation fields are
projected only by the administrator user-management API, not by general user
responses.

The named PostgreSQL unique constraint `uq_users_oauth_provider_sub` is the
concurrency arbiter for provider identity. Both columns remain nullable so
local users may keep `(NULL, NULL)`; application-created NTHU users require
both values. Identity lookup is always by the provider/sub pair. Email is not
an account-linking key, and a collision with any existing User fails closed
with `oauth_account_link_required` rather than linking or revealing that User.

On first login, provider email and name initialize `email`, `name`, and
`nickname`. Repeat login may synchronize email and name only when neither
conflicts with another User. A later login never overwrites the user-managed
nickname. A matching soft-deleted NTHU User remains the same identity but is
denied; OAuth does not restore it or change its lifecycle metadata.

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

`test_public_catalog_keeps_same_metadata_approved_sibling_independent` protects
the effective-public query across approved, pending, rejected, takedown, and
soft-deleted same-metadata siblings. Authenticated coverage confirms exact
`source_submission_ids` and exact preview, preview-file, and download object
resolution for two independent one-to-one pairs.

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

## ArchiveSubmission requested parent metadata

### Intended invariant

An upload that requests a new Course, or a new Category plus Course, remains
one ordinary `ArchiveSubmission`. The requested names and keys are review-time
metadata, not separate Course/Category applications or permanent ownership
links.

- A new Course request always includes the exam-file upload.
- A new Category request always includes both a new Course request and the
  exam-file upload; category-only requests are invalid.
- Approval resolves parents from current normalized state. An active matching
  Category or Course is reused even when the request originally marked it as
  new or another actor created it after submission.
- Only approval may create a missing Category or Course. Pending, rejected,
  edit/return, trash, and restore operations do not create them.
- Category, Course, Archive creation/linking, approval metadata, and durable
  approval notification share one PostgreSQL transaction.
- A failed approval retains the original submission and uploaded object but
  leaves no new Category, Course, Archive, link, approved state, or approval
  notification.
- After approval, Category and Course lifecycle is independent from the source
  submission. No `created_course_id`, `created_category_id`, cascade ownership,
  or equivalent permanent relation is added.

The only exact approval result link remains the optional one-to-one
`ArchiveSubmission.created_archive_id → Archive`. Consequently
`source_submission_ids` remains `[]` or `[submission_id]`; parent resolution
does not expand that compatibility shape.

### Current implementation and test evidence

`archives.py::approve_archive_submission` owns the transaction. Its approval
Category helper flushes without committing; Course and Archive work, the exact
link, review transition, and notification enqueue are committed together.
The approval namespace mutex serializes the normalized Category/Course
identity before the canonical parent-first row-lock plan.

Focused approval atomicity and concurrency tests protect missing-parent
creation, parent reuse after submission, rollback at intermediate boundaries,
and two independent approvals reusing one concurrently created Course.

### Frontend rendering evidence

`renders_each_archive_when_exam_metadata_matches_but_ids_differ` confirms that,
when the Archive list response contains two records with matching exam
metadata but different Archive identities, the frontend preserves two cards
and identity-specific preview and download operations. Backend tests separately
protect sibling visibility and exact object-name resolution; object-storage
availability remains outside this repository safety net.

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
The same-metadata sibling tests additionally protect both reversible paths:
Submission A trash/restore and Archive A trash/restore retain the exact link
and object identity, leave pair B byte-for-byte unchanged in lifecycle fields,
keep Archive B publicly visible throughout, and emit no lifecycle notification.

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

S3A-1 connects that durable state to the deletion routes. Ownership is checked
before a deleted-row retry is classified; the first owner mutation consumes
eligibility, its authorized retry is a mutation-free `changed=false` success,
and a later new owner mutation fails with the stable
`archive_submission_self_delete_consumed` conflict. Administrator and
system/cascade deletion preserve the stored value. Read capability projection
and frontend controls remain later application work.

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

- It is the existing separate legacy Course request flow; it is not created by
  the ArchiveSubmission upload/approval contract above.
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

`CourseSubmission` has requester/reviewer history plus `deleted_at`, exact
`previous_status`, delete/restore actor metadata, and a nullable
`created_course_id`. New deletions snapshot the exact non-deleted state;
restore consumes only that snapshot. Legacy `DELETED` rows without an
authoritative snapshot remain non-restorable but may be permanently deleted.

The database link to `Course` uses `ON DELETE SET NULL`. Course soft trash and
restore do not rewrite the request, permanent Course deletion preserves the
request as detached history, and permanent CourseSubmission deletion does not
mutate the Course. An active pending request may block Category permanent
deletion; approved, rejected, and deleted history does not. Archive approval
continues to carry its own requested-parent snapshots and does not create or
link a `CourseSubmission`.

## Legacy Archive without ArchiveSubmission

### Intended invariant

A historical `Archive` without an `ArchiveSubmission` remains reportable by an
authenticated user and can be taken down directly by an administrator.

### Current implementation

`reports.py` permits creation of an archive report when no linked submission
exists and retains archive snapshots.
`test_legacy_archive_can_be_reported_without_submission` confirms that an
authenticated reporter can create the pending report with no submission link,
the Archive snapshots and report-submission audit are retained, and one
submitted notification is created. When such a pending report is upheld with
takedown requested, the review path locks and soft-trashes the exact active
Archive directly. It does not create an ArchiveSubmission, change the Archive
identity or object name, or perform a storage operation. The Archive mutation,
final Report decision, and result notification share the route-owned database
transaction.

## Blocking and orphan risks

- String category keys can orphan logical relationships without an application
  guard.
- `SET NULL` report/source FKs preserve history, but a permanently deleted
  source must render as `來源已不存在` without an active source action or
  navigation. The complete API/UI treatment remains an implementation gap.
- Historical shared Archive references are an integrity anomaly and must fail
  closed; supported exact one-to-one pairs do not borrow sibling lifecycle.
- PostgreSQL rows and MinIO objects can diverge because no atomic transaction
  spans them.

## Required follow-up

Public sibling visibility, exact file-action identity, and exact-pair reversible
soft lifecycle are characterized. Preserve these boundaries before schema or
service refactoring.
Any schema change must follow
[Migration safety](../migration-safety.md).
