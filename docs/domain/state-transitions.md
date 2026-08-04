# State transitions

Status: Active

Source of truth for: Domain states, allowed actions, authorization, visibility, and business-error semantics

Applies to: Archive submissions, reports, trash/restore, categories, and course-request approval

Related documents:
- [Domain contracts](README.md)
- [Entity relationships](entity-relationships.md)
- [Notifications and side effects](notifications-and-side-effects.md)
- [UI guidelines](../ui/guidelines.md)

## ArchiveSubmission review states

### Intended invariant

The review policy is exhaustive across every review status and direct review
action:

| Current status | `approve` | `reject` | `takedown` | `republish` |
| --- | --- | --- | --- | --- |
| `pending` | transition → `approved` | transition → `rejected` | transition → `takedown` | illegal |
| `approved` | no-op → `approved` | transition → `rejected` | transition → `takedown` | no-op → `approved` |
| `rejected` | transition → `approved` | no-op → `rejected` | illegal | illegal |
| `takedown` | illegal | illegal | no-op → `takedown` | transition → `approved` |
| `deleted` | illegal | illegal | illegal | illegal |

The matrix contains seven transitions, four no-ops, and nine illegal actions.
Deleted submissions can leave `deleted` only through the Trash restore
lifecycle.

A deliberate request based on the current state whose target is already
established is a successful no-op:

- the result is a no-op that the caller can distinguish from a new transition;
- it creates no new data, notification, statistical event, or audit event;
- it does not overwrite the actor or time of the transition that established
  the current state.

A request for a different target not listed in the matrix is invalid and
returns `409 Conflict`. This includes `rejected` to `takedown`.

Leaving a state through a legal transition and later returning to it, for
example `approved` to `takedown` to `approved`, is a new lifecycle event rather
than a retry.

`pending` to `takedown` lets an administrator stop processing a pending
duplicate or otherwise ineligible file after comparing its detail.

### Review precondition

Direct review requests carry the status observed by the caller as
`expected_status`. The final route contract requires this field. A missing or
explicitly null precondition returns `428 Precondition Required`; an unknown
status value fails request validation with `422 Unprocessable Entity`.

After authorization and row locking, the application handles the request in
this order:

1. establish that the submission exists;
2. reject a missing `expected_status`;
3. compare `expected_status` with the actual status;
4. classify a mismatch as stale and return `409 Conflict`;
5. only for a match, apply the review matrix above.

The expected-state comparison takes precedence over no-op or transition
classification. For example, a client that observed `pending` cannot submit
`reject` after another request has changed the row to `approved` and thereby
create a second `approved` to `rejected` transition. It receives a stale
conflict instead.

A transport retry retains its original expected status. If the first request
committed but its response was lost, retrying `approve(expected=pending)` after
the row became `approved` is stale, not a same-target no-op. The caller reloads
the resource; bounded Stage 5A does not add an idempotency-result ledger.

The precondition is intentionally status-only. It prevents competing direct
review requests based on one observed status, but it does not detect an ABA
cycle such as `approved → rejected → approved`. Stage 5A does not add a
version/revision column, ETag framework, or migration for generation tracking.

### Admin review capabilities

Administrator-facing submission responses project the basic actions available
from the current normalized submission status. The projection order is stable:
`approve`, `reject`, `takedown`, `republish`, then `delete`.

| Status | Advertised actions |
| --- | --- |
| `pending` | `approve`, `reject`, `takedown`, `delete` |
| `approved` | `reject`, `takedown`, `delete` |
| `rejected` | `approve`, `delete` |
| `takedown` | `republish`, `delete` |
| `deleted` | none |

The projection is a pure backend policy. `delete` is a trash-lifecycle action,
not an entry in the review-transition matrix. Same-target no-op actions are
accepted by the direct API contract but are not advertised. In particular,
`takedown` exposes both `republish` and `delete`. A non-null `deleted_at`
normalizes the row to `deleted` for both route enforcement and capability
projection.

### Direct administrator edit

After administrator authorization, the direct Submission edit route acquires
and revalidates the canonical Course, Archive, ArchiveSubmission plan before
classifying the locked status:

| Status | Direct Submission edit |
| --- | --- |
| `pending` | allowed |
| `approved` | forbidden |
| `rejected` | allowed |
| `takedown` | allowed without republishing |
| `deleted` | forbidden |

The editable states update only the Submission snapshot. They do not create or
move a Course, mutate a linked Archive, publish a linked Archive, or invoke a
review transition. Public approved content is edited through the Archive
management API; a deleted Submission must be restored before it can be edited.
The forbidden states return `409 Conflict` with
`archive_submission_edit_forbidden`, the message
`此狀態的投稿不可直接編輯。`, and `reload_required=false`. This stable
business restriction is distinct from stale expected-state, lifecycle drift,
one-to-one conflicts, static corruption, and
`archive_submission_illegal_transition`.

The edit route owns one database commit. Canonical plan acquisition, locked
state and membership revalidation, snapshot mutation, and response refresh are
inside that transaction. A failed request rolls the snapshot back and leaves
the linked Archive and notification/event state unchanged.

| Value | Canonical Chinese label |
| --- | --- |
| `pending` | 待審核 |
| `approved` | 已通過 |
| `rejected` | 未通過 |
| `takedown` | 已下架 |
| `deleted` | 已刪除 |

### Current implementation

`backend/app/services/archive_submission_status.py` implements takedown and
republish helpers. Review endpoints in `archives.py` implement approve/reject.
The status service also owns a synchronous, immutable, side-effect-free policy
result for the complete matrix and a separate expected-state classifier.
`SubmissionDecision.expected_status` remains parser-optional so the routes can
map a missing or null field to `428` instead of Pydantic mapping it to `422`.
The runtime contract is nevertheless mandatory: all four direct review routes
authorize the administrator, discover the exact parent relationship without
locking, then acquire the canonical lifecycle plan before enforcing the
expected-state classifier and transition policy. Existing exact parents lock
Course, Archive, then ArchiveSubmission rows by ascending numeric primary key;
approve also takes its established normalized approval-namespace advisory
mutex before any row lock and locks every exact-linked sibling when it may
update Archive metadata. The one-to-one guard requires that exact source set
to contain at most the target submission; multiple exact sources are a static
integrity anomaly and fail closed before a lock plan is accepted. Reject,
takedown, and republish lock only the target submission after its exact
ancestors. Missing, stale, illegal, and same-target requests short-circuit
before review mutation or notification.
Repository frontend callers send the status carried by the row or comparison
candidate being acted on.

The direct routes return stable error-detail codes:

- missing/null: `428 archive_submission_precondition_required`;
- expected-state mismatch: `409 archive_submission_stale_state`; and
- a matching-state illegal edge: `409 archive_submission_illegal_transition`.

Successful direct actions retain the existing flat submission fields. They add
admin-only `available_actions` and a required `changed` boolean: a true
transition returns `changed=true`, while a same-target no-op returns
`changed=false` with its original metadata and no writes. Admin list/update
responses add only `available_actions`; owner and public projections do not
expose administrator capabilities. The comparison response keeps its
compatibility `can_takedown` field, deriving it from the same backend capability
policy instead of a separate status mapping.

The exact Course/Archive/Submission membership fingerprint is re-read after
all locks. A mismatch rolls back that attempt and permits one bounded plan
rebuild; lock sets never expand after acquisition begins.
`created_archive_id = NULL` remains no exact Archive relationship and is never
replaced by a metadata guess.

Archive soft trash and restore use the same Course, Archive, exact-linked
ArchiveSubmission ordering. They discover the optional exact source before
their first row lock, reject more than one source as a static one-to-one
integrity anomaly, revalidate the legal zero-or-one membership afterward, and
then apply the existing transition to the locked row.

Owner delete, administrator delete, and exact Submission restore use the same
planner. An unlinked Submission locks only its own row. A legally linked
Submission discovers its retained exact parent before the first row lock, then
locks Course, Archive, and ArchiveSubmission in canonical rank and
ascending-primary-key order. Locked membership and requester/owner identity
are revalidated before mutation. One changed discovery may roll back and
rebuild internally; a second mismatch fails through the existing generic
internal-error boundary and never borrows the Archive-only
`archive_lifecycle_conflict` contract. Course lifecycle, report lifecycle, and
permanent-delete lock ordering remain outside this
slice.

If Archive trash or restore finds that a legal parent or zero-or-one exact
source membership changed between discovery and locked revalidation, it rolls
back and rebuilds the complete plan once. A stable second attempt proceeds
normally. If the second locked revalidation also differs, the second
transaction rolls back and returns
`409 archive_lifecycle_conflict` with the canonical message
`Archive lifecycle changed during this request. Please retry.` No lifecycle
write is committed. A static multi-source relation never enters this retry
path: it uses the existing generic internal-error response plus the structured
one-to-one integrity log. This contract does not replace not-found or
authorization handling, direct-review stale or illegal-transition errors,
same-target review no-ops, planner invariant failures, PostgreSQL deadlocks, or
lock timeouts.

Course soft trash and restore preserve their existing metadata candidate
resolver, lifecycle marker, child eligibility, restore counts, authorization,
and retry behavior while acquiring the same canonical resource ranks. Course
trash locks Course, Archive, then ArchiveSubmission rows; Course restore first
locks the matching CourseCategoryConfig row and then locks Course, Archive,
and ArchiveSubmission rows. Collections are discovered before the first row
lock, each resource class is locked by ascending numeric primary key, and the
locked membership fingerprint includes the Course identity, direct Archive
membership, exact Archive links, candidate Submission membership, and—during
restore—the Category identity and lifecycle state.

One changed Course membership rolls back the attempt and permits exactly one
complete plan rebuild. A stable second attempt applies the existing mutation.
A second dynamic mismatch rolls back and returns
`409 course_lifecycle_conflict` with
`Course lifecycle changed during this request. Please retry.` This contract is
limited to Course trash/restore collection drift. Static one-to-one anomalies
remain generic internal errors, and the Course contract does not replace
Category-deleted, missing/already-active, Archive lifecycle, occupied-link,
deadlock, timeout, serialization, or integrity-error behavior.

Deterministic PostgreSQL tests use independent request sessions and event
barriers while the first request holds its canonical plan through the commit
boundary. Double-approve and every pair among approve, reject, and takedown
from `pending` establish first-writer-wins: the winner returns `changed=true`,
the loser observes the committed state and returns stale `409`, and only the
winner produces transition metadata, Archive work, or a notification.
Approve-existing versus Archive trash, Archive trash versus restore, and
reverse-input plans over two independent one-to-one Archive/Submission pairs
also establish serial outcomes without a deadlock. A deliberate same-target
request with a matching expected state remains the distinct `changed=false`
control.

The separate archive-report uphold flow retains its report-owned transaction
and internal submission takedown; it does not use the direct-client
precondition or direct-action response contract.

### Archive link conflicts

Approval preserves an existing exact `created_archive_id` or establishes a
previously null link; normal application review and restore flows never relink
a non-null submission to a different Archive. Before link mutation, the
application verifies that the intended Archive has no other source submission.
The named nullable unique constraint remains the final arbiter when concurrent
transactions both pass that precheck.

An Archive already occupied by another submission, including an exact
`23505` violation of
`uq_archive_submissions_created_archive_id`, returns
`409 archive_submission_link_conflict` with no occupant identity. A non-null
relink attempt or static multi-occupant result is an internal integrity
anomaly: the operation stops, uses the repository's generic internal-server
response, and does not select, truncate, or repair a relationship. Submission
restore follows only its retained exact link; a null link remains null and does
not search for an Archive by metadata.

### Implementation gaps

- The frontend does not yet consume `available_actions` or `changed`; visible
  action projection and no-op/stale feedback remain later Stage 5A work.
- Backend rejection notification copy and `frontend/src/views/Admin.vue` still
  use `已退回` in places.

`test_archive_review_statuses_create_deduplicated_notifications` and
`test_republish_restores_approved_and_notifies_requester_once` cover parts of
the current behavior, not the complete intended matrix.
`test_approved_submission_can_be_rejected_or_taken_down` directly protects the
legal `approved` to `rejected` and `approved` to administrator `takedown`
edges, including review audit changes, the still-linked Archive identity, and
one matching notification per transition.
`test_rejected_submission_can_be_approved` directly protects the legal
`pending` to `rejected` to `approved` flow, including creation of exactly one
paired Archive and one approval notification after the rejection baseline.
These tests do not cover same-target retries, repeated transition cycles, or
sibling visibility.

## Report states

Both comment and archive reports use:

| Value | Canonical meaning |
| --- | --- |
| `pending` | Awaiting review |
| `upheld` | 回報成立 |
| `dismissed` | 回報不成立 |

A final report state cannot be reviewed again. Report `dismissed` is distinct
from submission `rejected`; labels and transition helpers must not mix the two
domains.

### Current implementation and test evidence

`reports.py` rejects repeat review of a final report. Focused coverage includes
`test_comment_report_admin_review_is_authorized_atomic_and_idempotent` and
`test_archive_report_review_optional_takedown_is_atomic_and_non_destructive`.

ArchiveReport review, soft trash, and soft restore discover their exact
references before the first row lock and then use the canonical lifecycle
order: Course, Archive, optional exact ArchiveSubmission, and ArchiveReport.
Legacy Archives omit the absent Submission without fabricating one. After the
locks are held, the operation revalidates the Report state and exact FK
membership before applying the existing transition. One changed discovery may
roll back and rebuild once; an unstable or static integrity anomaly fails
closed through the generic internal-error boundary and does not borrow the
Archive or Course lifecycle conflict contracts.

This lock adoption does not change the pending-to-final matrix, finalized
conflict, invalid action combination, legacy Archive takedown gap, result
notification, soft-delete metadata, or pending-report restore uniqueness gap.

## Public visibility

### Intended invariant

- A public Archive is public only to an authenticated user who may use the
  system; it is not anonymously accessible on the internet.
- Authentication is required for Archive browsing, list-carried detail data,
  preview metadata, preview-file streaming, and download/download-URL access.
- There is no independent Archive detail `GET` route in the current API;
  Archive detail data is carried by the authenticated list response.
- Authentication must reject access before object storage is read. Existing
  API authentication semantics may return `401` or `403`; this contract does
  not standardize those two statuses in this stage.
- Every effective approved submission can be public independently.
- One logical exam group can show several approved PDFs.
- Pending, rejected, takedown, or deleted siblings do not hide an approved PDF.
- An item may be hidden when that public item, its Course, or a required parent
  is explicitly trashed or blocked.

### One-to-one corruption boundary

The schema and application contract permit at most one source submission for
an `Archive`. Any historical result containing multiple exact sources is an
integrity anomaly, not a visibility group: mutation fails closed through the
generic internal-error boundary and no source is selected as a winner. Public
visibility correction remains outside this lifecycle-lock slice.

## Trash and restore

Review state, soft-delete state, system-induced takedown, and administrator
takedown are separate concepts.

### Intended invariant

- Course or Archive trash/restore does not notify submitters.
- Submission trash follows the paired-item rule in
  [Entity relationships](entity-relationships.md).
- Restore applies the saved previous state and lifecycle reason; it is not an
  approval action.
- `deleted` leaves review transitions and is handled only by trash lifecycle.

`ArchiveSubmission.previous_status` is a nullable, typed schema prerequisite
for reversible submission soft delete. It may preserve only `pending`,
`approved`, `rejected`, or `takedown`, and only after a submission truly enters
the `deleted` lifecycle. Every active row (`deleted_at IS NULL` and normalized
status other than `deleted`) keeps this column null. Historical deleted rows
whose prior state cannot be proven also keep it null. Submission restore uses
that missing provenance as the explicit compatibility case and returns the
Submission to `pending`; it never infers `approved` from `created_archive_id`,
a linked Archive, or review metadata. Permanent or otherwise unrestorable rows
have no restorable prior state.

Course trash is a separate active lifecycle. Its affected submissions remain
`takedown` with `deleted_at=NULL` and continue to store the exact prior state
in the existing versioned `course_trashed|previous_status=...` lifecycle
marker. The schema prerequisite migration validates and counts those markers
but does not copy them into `ArchiveSubmission.previous_status`, change their
status, or rewrite their lifecycle reason. A later successful exact restore
may clear the typed prior state only after it has consumed that state.

### Current implementation

Lifecycle reasons such as archive/course trash are stored on
`ArchiveSubmission`; `trash.py` and `archive_submission_lifecycle.py` perform
restore. Coverage is partial, including
`test_admin_delete_course_soft_deletes_archives` and trash dispatch tests.
`test_course_trash_restore_preserves_approved_submission_without_notification`
directly protects the approved prior-state path through Course trash and
restore.
`test_course_trash_restore_preserves_rejected_submission_without_notification`
uses the legal `pending` to `approved` to `rejected` review flow before Course
trash, and directly protects restoration to rejected. Both tests verify the
persisted Course lifecycle reason and previous-status marker; they do not
cover pending, administrator-takedown, or sibling-group cases.

S3A-1 makes deletion provenance authoritative at runtime. Every true owner,
administrator, or system/cascade soft-delete records the exact normalized
active source status before entering `deleted`; an authorized no-op retry does
not overwrite it. Owner deletion also consumes the submission's monotonic
self-delete eligibility, while administrator and system/cascade deletion
preserve the existing eligibility value. S3A-2 restores a known
`previous_status` exactly, falls back to `pending` when historical provenance
is null, and clears the delete-only value only after making the row active, as
required by the database guard. Only an exact `approved` restore makes the
retained linked Archive active; pending, rejected, takedown, and compatibility
fallback restores leave it non-public. Restore never resets owner self-delete
eligibility. Course trash/restore continues using its versioned marker.

Focused PostgreSQL coverage protects exact pending, approved, rejected, and
takedown restoration, the null-to-pending compatibility fallback, linked
Archive visibility, owner-eligibility preservation, exact one-to-one
membership, canonical lock order, and delete-versus-restore serialization.

### Owner self-delete eligibility persistence

Ownership and owner self-delete eligibility are separate persisted concepts.
`ArchiveSubmission.requester_id` is the normal owner identity; legacy
`owner_id` is a fallback only when a requester is genuinely absent. Conflicting
non-null identities are invalid and must fail closed.

`owner_self_delete_consumed` is a monotonic boolean:

- new and historically clean active submissions start as `false`;
- a historical owner self-delete is backfilled to `true`;
- a historical active restored row is conservatively backfilled to `true`
  because restore cleared its original deletion provenance;
- a submission that is currently identifiable only as an administrator
  deletion is conservatively backfilled to `true`;
- a historical, metadata-consistent recognized system/cascade deletion is
  conservatively backfilled to `true`;
- future administrator deletion preserves the existing value rather than
  consuming eligibility;
- the first authorized owner deletion from `approved` changes the value to
  `true`; after ownership authorization, retrying that completed deletion is a
  mutation-free success with `changed=false`;
- an authorized owner attempting a new deletion after the value is `true`
  receives `409 archive_submission_self_delete_consumed`;
- restoring a submission never resets the value;
- future system/cascade deletion preserves the existing value rather than
  consuming eligibility;
- restore, review transitions, and no-op operations never reset `true`.

The historical administrator and recognized system/cascade rules are
migration-only. Only the tracked, internally consistent system/cascade format
is accepted. Unknown provenance, mismatched system metadata, ownership
conflicts, lifecycle contradictions, overlapping classifications, and
unclassified rows abort the migration rather than selecting a value. Future
administrator and system/cascade preservation remains part of the later
application milestone.

The persisted field and fail-closed historical backfill are only the schema
prerequisite. Owner-delete authorization, retry/no-op responses, restore
lockout, and frontend capability enforcement remain part of the later Stage 5A
application milestone and are not claimed as implemented here.

## Category lifecycle

### Intended invariant

Soft delete sets `deleted_at` and `is_active=false`. Public category queries and
submission choices exclude both deleted and inactive categories. Restore
recovers the pre-delete active state rather than always enabling the category.

### Current implementation and gap

Public queries commonly filter `is_active=true`; admin queries use
`deleted_at`. `delete_course_category` sets `deleted_at` but does not set
`is_active=false`, while category restore in `trash.py` unconditionally assigns
`is_active=true`. This is an implementation gap. The category canonicalization
migration tests protect metadata preservation but not this full lifecycle.

## Pending report uniqueness

### Intended invariant

- A soft-deleted pending report does not consume active-pending uniqueness.
- Restoring an older pending report is blocked explicitly if a newer active
  pending report for the same uniqueness scope exists.

### Current implementation and gap

`CommentReport` and `ArchiveReport` use partial unique PostgreSQL indexes whose
predicate is only `status = 'pending'`. The predicate does not exclude
`deleted_at`, even though endpoint queries filter soft-deleted rows. This can
block a new report after trash and does not provide the required restore
conflict semantics.

## ArchiveSubmission parent resolution on approval

Approval resolves the requested Category/Course identity from current
normalized database state:

1. reuse an active matching Course and its Category;
2. otherwise reuse an active matching Category and create the missing Course;
3. otherwise, only for a valid new-Category plus new-Course upload request,
   create both missing parents; and
4. create or reuse the exact Archive, establish its optional one-to-one
   submission link, transition the submission to approved, and enqueue the
   approval notification.

All steps are one caller-owned PostgreSQL transaction. Any exception rolls
back parent creation, Archive work, link state, reviewer/reviewed-at metadata,
approved status, and approval notification together. The original pending or
rejected submission, its upload event, and its stored object remain under
their pre-existing lifecycle.

Two approvals for the same missing parent identity serialize through the
approval namespace mutex. The later transaction re-reads current state and
reuses the winner's active Course rather than returning a product-level
duplicate. Bounded lock-plan revalidation remains fail closed.

Only exact one-to-one occupancy is mapped to
`409 archive_submission_link_conflict`. Archive and Course lifecycle drift
retain their existing specific 409 contracts. Static relationship anomalies,
unclassified integrity failures, deadlocks, timeouts, and serialization
failures are not relabeled as lifecycle conflicts.

The approval does not create permanent Submission ownership of Category or
Course. Rejection, return/edit, pending state, trash, restore, or later
submission deletion does not create or cascade-delete these parents.

## CourseSubmission approval

The ArchiveSubmission requested-parent approval flow above is distinct from
this legacy `CourseSubmission` endpoint.

### Intended invariant

- Reuse an existing normalized category/course instead of creating a duplicate.
- Retry, restore, or republish of one request must not create another category
  or course.
- Approval is deduplicated and idempotent at the business boundary.
- Created category/course lifecycle is independent after approval.

### Current implementation

The legacy Course request approval path normalizes category/course identities
and reuses existing rows. It remains separate from the ArchiveSubmission
approval caller transaction above and has its own lifecycle and idempotency
scope.
`test_course_request_approval_reuses_existing_course_without_duplicates`
directly protects the separate `CourseSubmission` model's first
`pending`-to-`approved` path when a matching Course exists by approval time:
the request resolves to that Course and matching Category/Course counts do not
increase. It does not prescribe repeat-approval responses, notification
behavior, request trash, or the later lifecycle of the resolved Course.

## Authorization

| Operation | Anonymous | Authenticated user | Owner | Administrator | System |
| --- | --- | --- | --- | --- | --- |
| View public effective archive | Denied | Allowed | Allowed | Allowed | Allowed |
| Create archive/comment report | Denied | Allowed | Allowed | Allowed | Allowed when explicitly designed |
| Submit archive | Denied | Allowed | Allowed | Allowed | Explicit system imports only |
| Review submission/report | Denied | Denied | Denied unless also admin | Allowed | Explicit automation only |
| Soft-delete own eligible submission | Denied | Denied for others | Allowed under lifecycle rules | Allowed | Allowed only for a declared lifecycle |
| Trash/restore/permanent-delete administrative entities | Denied | Denied | Denied unless endpoint explicitly grants ownership | Allowed | Declared maintenance only |
| Republish reviewed submission | Denied | Denied | Denied unless also admin | Allowed | Declared lifecycle only |

### Current implementation

Authentication dependencies and `is_admin`/owner checks are enforced in the
backend, often inline in endpoint modules. The Archive list, preview,
preview-file, and download routes depend on `get_current_user`; the list route
has focused anonymous-access test evidence, and
`test_archive_file_endpoints_require_authentication` confirms that anonymous
preview, preview-file, and download requests are rejected before object
storage access. The frontend also hides controls but is not an authorization
boundary.

### Known gap

Permission logic is distributed across `archives.py`, `reports.py`, `trash.py`,
`courses.py`, and `notifications.py`. Equivalent lifecycle actions need focused
tests before centralization.

## Error semantics

| Condition | Intended semantic result | Current status |
| --- | --- | --- |
| Same-target action with a matching precondition | Successful no-op without writes, notification, statistics, or audit changes | Implemented as flat `200` action response with `changed=false` |
| Stale direct review request | `409 Conflict` without writes or notification | Implemented with stable `archive_submission_stale_state` detail |
| Different invalid transition | `409 Conflict` without writes or notification | Implemented for direct review routes with stable `archive_submission_illegal_transition` detail |
| Permission denied | Deny without revealing protected resource details | Backend enforcement exists; consistency requires review |
| Missing entity | Not found/unavailable without side effects | Generally implemented |
| Active uniqueness conflict | Explicit conflict and no duplicate row | Implemented for several report paths; soft-delete predicate has a gap |
| Restore conflict | Explicitly block restore and retain trashed row | Required follow-up for pending reports and previous-state restoration |
| Storage deletion failure | Do not report the single item as fully deleted; preserve retry evidence | Implementation gap; current cleanup may emit only a warning |

This contract does not standardize the precise `401`/`403` authentication
status. Future conformance work must coordinate the no-op response,
frontend handling, and tests.

## Required follow-up

The first safety-net slice should characterize the current submission matrix,
sibling visibility, pending-report trash uniqueness, and category
delete/restore behavior before implementation changes.
