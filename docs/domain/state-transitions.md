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
authorize the administrator, load the submission once with `FOR UPDATE`,
enforce the expected-state classifier before the transition policy, and
short-circuit missing, stale, illegal, and same-target requests before review
mutation or notification. Repository frontend callers send the status carried
by the row or comparison candidate being acted on.

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

Deterministic PostgreSQL tests use independent request sessions and an event
barrier while the first request holds the submission row lock through its
commit boundary. Double-approve and every pair among approve, reject, and
takedown from `pending` establish first-writer-wins: the winner returns
`changed=true`, the loser observes the committed state and returns stale
`409`, and only the winner produces transition metadata, Archive work, or a
notification. A deliberate same-target request with a matching expected state
remains the distinct `changed=false` control.

The separate archive-report uphold flow retains its report-owned transaction
and internal submission takedown; it does not use the direct-client
precondition or direct-action response contract.

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

### Observed likely bug

Some current queries evaluate all submissions linked to one `Archive`; a
non-approved linked submission can make the shared archive unavailable. This
conflicts with the independent-file contract and requires characterization
tests before conformance changes.

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
whose prior state cannot be proven also keep it null; a future restore must
fail closed for those rows rather than infer from `created_archive_id`, a
linked Archive, or review metadata. Permanent or otherwise unrestorable rows
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

The current P0 milestone adds only the typed nullable column, its database
guards, deterministic historical owner-delete backfill, schema manifest, and
sealed read-only audit. Owner/admin delete routes do not yet write the column,
restore does not yet consume it, and Course trash/restore continues using its
versioned marker. S3A and S3B remain required before the new field governs
runtime deletion or restoration.

### Known gap

Current grouped restore can approve linked submissions without reliably
recovering a pending/rejected previous state.

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

## CourseSubmission approval

### Intended invariant

- Reuse an existing normalized category/course instead of creating a duplicate.
- Retry, restore, or republish of one request must not create another category
  or course.
- Approval is deduplicated and idempotent at the business boundary.
- Created category/course lifecycle is independent after approval.

### Current implementation

Archive approval paths normalize category/course identities, use advisory
locking, and reuse existing rows. Multi-step commits and the separate
`CourseSubmission` model leave the end-to-end idempotency contract only
partially implemented.
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
