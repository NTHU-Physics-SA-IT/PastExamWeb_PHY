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

### Archive metadata mutation and reparenting

Archive management is administrator-only. The editable metadata fields are
`name`, `professor`, `archive_type`, `has_answers`, and `academic_year`.
Mutation acquires and revalidates the canonical Course, Archive, and exact
ArchiveSubmission plan before writing, and it never changes Submission status,
delete provenance, ownership, or self-delete eligibility.

Archive reparenting preserves both the exact `course_id` input and the existing
normalized name/category input. A successful request resolves one active
Course ID and uses that ID for planning, locking, revalidation, mutation, and
the response. It never creates or restores a Course. A missing target returns
`404 archive_move_target_course_not_found` with
`目標課程不存在，請先建立課程。` and `reload_required=false`. A target found
only in trash returns `409 course_lifecycle_conflict` with
`目標課程已在垃圾桶，請先恢復課程。` and `reload_required=false`.

For normalized name/category lookup, one active match wins even when trashed
duplicates exist, without touching those trashed rows. Zero active matches and
one or more trashed matches use the trash conflict above. Multiple active
matches are a static integrity anomaly: the operation selects no Course, logs
sanitized aggregate context, and fails through the generic internal-error
boundary. Metadata mutation and reparenting retain one caller-owned database
transaction, so validation, lifecycle drift, or commit failure leaves both
metadata and the Course relationship unchanged.

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

### Frontend review presentation

The administrator review UI presents the approved product action matrix
intersected with backend `available_actions`; missing, malformed, empty, or
unknown capability values fail closed. A `changed=false` response is
informational, refreshes authoritative list data, and does not claim a new
mutation. The human-visible `rejected` status is `未通過`, while the action verb
remains `退回`.

Backend rejection notification copy still uses `已退回`; that action-oriented
copy remains a separate follow-up from the status-label contract.

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

Archive Wish reports use the same one-way moderation vocabulary as comment and
archive reports: `pending -> upheld|dismissed`. A final Wish report cannot be
reviewed again. Permanent Wish deletion is administrator-only, is not a Trash
transition, cascades hearts, detaches retained reports and Help Upload source
links through `SET NULL`, and does not delete a matching Archive or submission.

An Archive Wish itself has no fulfilled state column. Its `fulfilled` projection
is derived on every read from a matching effective-public Archive. Pending,
rejected, taken-down, soft-deleted, or parent-hidden Archives do not fulfill a
wish. Once a public match exists the Wish remains visible with a fulfilled
badge. Duplicate canonical targets fail with `409 wish_already_exists` and the
database unique constraint is the concurrency arbiter.

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
conflict, invalid action combination, result notification, soft-delete
metadata, or pending-report restore uniqueness gap. An upheld source-less
legacy report with takedown requested now applies the established Archive
soft-trash transition to the exact locked active Archive, without creating a
Submission or deleting its stored object. The Archive transition, Report
decision, and result notification commit atomically; a finalized retry remains
a conflict.

## NTHU login authorization

NTHU UUID remains the canonical external identity. Provider `userid` is a synchronized affiliation attribute and never an identity key. An `inschool=false` profile is always denied before any allow path.

`all_nthu` preserves the existing eligible-member behavior and ignores
department and staff lists. `selected_departments` authorizes through one of
two explicit paths: a standard student's parsed department is selected, or the
exact provider `userid` appears in the administrator-maintained staff allowlist.
Staff userids are trimmed at
configuration input but remain case-sensitive. A staff-like display
classification never grants access and never implies an organizational unit.

Authorization runs after the provider profile is established and before local User creation or profile synchronization. A denial produces no User mutation, login handoff, exchange success, or application JWT. Existing users remain persisted and unchanged when a later policy denies a login.

For a NTHU OAuth User, provider-synchronized `name` and `email` remain provider-owned profile attributes. An administrator may still update existing administrative metadata such as `is_admin`, but the admin user-update operation rejects an attempted change to either provider-owned field with `409` before applying any field mutation or commit. Local-account profile updates retain their existing behavior.

## Public visibility

### About Us managed content

- Authenticated users may list and read every About Us entry.
- Only administrators may create or update entries; the backend enforces this
  independently of hidden frontend controls.
- About Us content is separate from announcements and creates no notification
  or read-receipt state. Deletion is outside the current contract.
- Invalid content is rejected without persisting a partial mutation.

### Intended invariant

- Full public-Archive data is public only to an authenticated user who may use
  the system. Authentication is required for Archive browsing, list-carried
  detail data, preview metadata, preview-file streaming, and
  download/download-URL access.
- An anonymous read-only catalog may expose active, non-deleted Courses in
  active, non-deleted canonical Categories whether or not a Course currently
  has an effective public Archive. Its Archive projection is limited to `id`,
  `name`, `professor`, `archive_type`, `has_answers`, and `academic_year`.
- The anonymous catalog must not expose PDF bytes, preview data, object-storage
  keys or paths, signed URLs, uploader or submission identity, user data, or
  internal storage metadata. Backend queries enforce this boundary; frontend
  control visibility is not authorization.
- A Course without an effective public Archive remains anonymously
  discoverable and human-browsable, and its Archive endpoint returns an empty
  list. Its detail page is `noindex, follow` and is omitted from the sitemap.
  A Course becomes `index, follow` and sitemap-eligible only when at least one
  Archive satisfies the effective-public conditions. Empty catalog responses
  remain valid only when no canonical active Course is available.
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

Focused safety-net coverage confirms that the anonymous catalog keeps
same-metadata Archive identities independent across approved, pending,
rejected, takedown, and soft-deleted sibling states. Authenticated coverage
confirms exact source-submission projection and exact Archive/object selection
for preview, preview-file, and download actions. These tests do not change the
lifecycle transition matrix.

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

- The administrator Trash list projects `canRestore` and
  `canPermanentDelete` as non-null legal-action authority for every returned
  entity. The projection uses the same current parent, lifecycle, and
  dependency conditions enforced by the corresponding mutation.
- Trash dependency strings are display-only context. Frontends do not parse
  localized wording to grant an action; missing, malformed, or non-boolean
  authority fails closed.
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
Two same-metadata approved-pair scenarios protect the public boundary during
reversible soft lifecycle. Submission A trash/restore mutates only Submission A
and its exact Archive A; Archive A trash/restore temporarily takes down and
restores only its exact Submission A. In both paths pair B's persisted
lifecycle, link, and object identity remain unchanged, Archive B stays public,
and no lifecycle notification is emitted.

Deterministic independent-session PostgreSQL coverage closes the remaining
submission lifecycle races. Direct review and owner/admin deletion, direct
review and exact restore, and system/cascade deletion and owner deletion all
serialize on the same canonical Course, Archive, ArchiveSubmission plan.
The committed winner determines the legal second result: stale direct review
returns `archive_submission_stale_state`, completed deletion retries are
mutation-free, and exact restore consumes only persisted `previous_status`.
Owner deletion is the only one of these delete authorities that changes
`owner_self_delete_consumed` from `false` to `true`; no winner order can reset
it.

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

Soft delete snapshots the Category's current `is_active` value, then sets
`deleted_at` and `is_active=false` in the same transaction. Restore requires
that snapshot, restores the exact prior active state, clears the deletion
metadata and snapshot, and records the restore metadata in one transaction.
Thus an active Category restores active and an inactive Category restores
inactive; malformed deleted rows without a snapshot fail closed.

New Course creation, CourseSubmission creation or Category editing, and
CourseSubmission approval may target a Category only when it is both live
(`deleted_at IS NULL`) and active (`is_active IS TRUE`). The persisted Category
row is authoritative: a stored inactive or deleted default key cannot fall
through to the synthesized-default compatibility path. Rejection happens
before Course lookup, reuse, or creation, leaving the pending request and
related rows unchanged.

### Current implementation

`CourseCategoryConfig.pre_delete_is_active` stores the nullable lifecycle
snapshot. The additive migration preserves live active/inactive rows, snapshots
the previous state of existing deleted rows, and makes every deleted Category
inactive. Upgrade and downgrade validate the lifecycle shape and abort on
ambiguous rows rather than guessing. Focused API and migration tests protect
active/inactive delete-and-restore behavior, new-work eligibility, default-key
fail-closed behavior, reversible backfill, and anomaly rejection.

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

### Approval transaction

The legacy Course request approval path uses the same normalized
Category/Course approval-namespace mutex as ArchiveSubmission approval. It
discovers the request identity without a row lock, acquires that namespace,
then locks and revalidates the exact CourseSubmission row. An identity change
between discovery and lock fails closed with a reload-required conflict; the
transaction never acquires a second namespace while holding the request row.

For a pending request, the transaction revalidates the D1 live-and-active
Category requirement and the normalized Course identity while holding the
namespace. Exactly one live match is reused, no match is created with
`flush()`, and multiple matches fail closed as ambiguous. Course creation and
the request's approved review fields are owned by one caller transaction and
one final commit. Any exception before that commit rolls both back.

A repeated approval is a business-idempotent no-op only when the existing
approved request has a linked Course whose normalized Category/name identity
matches and whose reviewer and review timestamp are present. It does not
replace review metadata or commit a new mutation. An incoherent approved row
fails closed; rejected and other illegal states remain non-approvable.

Admin direct-approved request creation follows the same namespace and
transaction boundary: it rechecks Course and pending-request identity under
the mutex, flushes the new Course to obtain its ID, adds the approved request,
and commits once. These guarantees do not make CourseSubmission the permanent
owner of the resulting Course.

### Independent request history lifecycle

Administrator trash of an active CourseSubmission records the exact current
non-`DELETED` status in `previous_status`, changes the row to `DELETED`, and
records delete time and actor without changing the linked Course. Active
request lists exclude trashed and legacy-deleted rows. Restore is permitted
only when the exact snapshot exists: it restores that status, consumes the
snapshot, clears delete metadata, and records restore metadata. It never
searches for, recreates, or relinks a Course or Category.

A legacy `DELETED` row without `previous_status` is preserved as an explicit
unknown-history state. It is visible to backend Trash authority, cannot be
restored, and can be permanently deleted without inventing a prior status or
deletion timestamp. A restored pending row whose Category is now missing,
deleted, or inactive remains pending; the existing D1 approval eligibility
check rejects later approval.

Course soft trash/restore does not rewrite CourseSubmission state. The optional
`created_course_id` foreign key uses `ON DELETE SET NULL`, so permanent Course
deletion preserves an approved request as valid detached history. Re-approving
that detached approved row remains a fail-closed conflict under D2A and never
repairs the link. Permanent CourseSubmission deletion deletes only the request.
For Category permanent-delete authority, only a live pending request is an
operational blocker; approved, rejected, soft-deleted, and legacy-deleted rows
are historical and do not own the Category.

Admin Trash clients treat `course_submission` as a first-class history type.
They render restore and permanent-delete actions only from the backend's
explicit action-authority booleans, present a missing Course link as valid
detached history, and do not infer relink, recreation, or alternate lifecycle
actions from status or relationship display data.

## Authorization

### NTHU login policy

NTHU OAuth starts from an anonymous browser session and succeeds only through
all of these gates:

1. the one-time session-bound OAuth state matches;
2. token and resource responses satisfy the NTHU contract;
3. the resource has `success=true` and a required valid `uuid`, `userid`,
   `name`, `email`, and boolean `inschool`;
4. `inschool` is exactly `true`;
5. the server-persisted NTHU access policy permits the affiliation;
6. the matching provider identity is active, or a new identity has no email or
   name collision; and
7. the browser atomically consumes the short-lived login handoff.

`inschool=false` returns `oauth_not_in_school` and mutates no User. A matching
soft-deleted identity returns `oauth_account_deleted` and is never restored by
login. A new UUID whose email is already owned returns
`oauth_account_link_required`; this milestone has no implicit or interactive
account-linking transition. Profile synchronization collisions return
`oauth_profile_conflict`. Duplicate provider identity or a database uniqueness
race fails closed as `oauth_identity_conflict`. These are stable,
non-sensitive business errors and never expose provider payloads or the
colliding User.

The in-school decision is an authentication Domain policy independent of
identity mapping. A future policy change may permit another population without
changing `oauth_provider="nthu"` or the UUID subject.

The access policy defaults to `all_nthu`, preserving the existing in-school
eligibility rule. An administrator may persist `selected_departments` with any
non-empty combination of canonical three-digit department codes and exact staff
userids. Standard students require a selected parsed department; staff access
always requires an exact allowlist match. A staff display classification never
authorizes by itself. Missing, malformed, non-standard, and otherwise
unverifiable `userid` values are `unresolved` and fail closed with
the same friendly scope denial. The callback enforces this after
provider-profile validation and before provider-identity lookup, profile
synchronization, new User creation, PostgreSQL commit, Redis handoff, or
application JWT issuance. Existing accounts are retained when later denied.
Local password authentication never reads this policy.

The active mode and inactive custom configuration have separate lifecycles.
Switching to `all_nthu` preserves the last selected department codes, staff
access mode, and exact staff userid allowlist in the persisted setting so that
they can be restored when an administrator later selects
`selected_departments`. While `all_nthu` is active, those preserved custom
fields never participate in authorization: every profile that passes the
existing in-school gate remains eligible. An older `all_nthu` setting with
empty custom fields remains valid.

| Operation | Anonymous | Authenticated user | Owner | Administrator | System |
| --- | --- | --- | --- | --- | --- |
| View safe public Course/Archive metadata catalog | Allowed | Allowed | Allowed | Allowed | Allowed |
| View public effective archive | Denied | Allowed | Allowed | Allowed | Allowed |
| View About Us entries | Denied | Allowed | Allowed | Allowed | Denied unless authenticated |
| Create or update About Us entries | Denied | Denied | Denied unless also admin | Allowed | Denied |
| Create archive/comment report | Denied | Allowed | Allowed | Allowed | Allowed when explicitly designed |
| Submit archive | Denied | Allowed | Allowed | Allowed | Explicit system imports only |
| Review submission/report | Denied | Denied | Denied unless also admin | Allowed | Explicit automation only |
| Soft-delete own eligible submission | Denied | Denied for others | Allowed under lifecycle rules | Allowed | Allowed only for a declared lifecycle |
| Trash/restore/permanent-delete administrative entities | Denied | Denied | Denied unless endpoint explicitly grants ownership | Allowed | Declared maintenance only |
| Republish reviewed submission | Denied | Denied | Denied unless also admin | Allowed | Declared lifecycle only |

### Current implementation

Authentication dependencies and `is_admin`/owner checks are enforced in the
backend, often inline in endpoint modules. Anonymous catalog queries reuse the
canonical effective-public-Archive conditions and a dedicated safe response
projection. The authenticated Archive list, preview,
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

The public sibling-visibility and exact-pair reversible soft-lifecycle safety
nets are characterized. Follow-up slices should characterize the remaining
submission matrix, pending-report trash uniqueness, and category delete/restore
behavior before implementation changes.
