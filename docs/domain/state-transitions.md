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

| From | Allowed target/action |
| --- | --- |
| `pending` | `approved`, `rejected`, `takedown` |
| `approved` | `rejected`, `takedown` |
| `rejected` | `approved` |
| `takedown` | `approved` through republish |
| `deleted` | Trash restore lifecycle only |

Requesting the current target state is a successful, idempotent retry:

- the result is a no-op that the caller can distinguish from a new transition;
- it creates no new data, notification, statistical event, or audit event;
- it does not overwrite the actor or time of the transition that established
  the current state;
- the response must expose the distinction, but this contract does not yet
  prescribe a JSON field name.

A request for a different target not listed in the matrix is invalid and
returns `409 Conflict`. This includes `rejected` to `takedown`.

Leaving a state through a legal transition and later returning to it, for
example `approved` to `takedown` to `approved`, is a new lifecycle event rather
than a retry.

`pending` to `takedown` lets an administrator stop processing a pending
duplicate or otherwise ineligible file after comparing its detail.

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
Republish requires `takedown`, but approve/reject mutability checks and the
takedown helper currently permit some same-state or disallowed transitions
without the complete no-op response and side-effect guarantees above.

### Implementation gaps

- `rejected` can currently be taken down.
- Repeated approve/reject paths can be accepted, but do not yet provide a
  confirmed distinguishable no-op contract or complete audit/side-effect
  protection.
- Backend rejection notification copy and `frontend/src/views/Admin.vue` still
  use `已退回` in places.

`test_archive_review_statuses_create_deduplicated_notifications` and
`test_republish_restores_approved_and_notifies_requester_once` cover parts of
the current behavior, not the complete intended matrix.

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

### Current implementation

Lifecycle reasons such as archive/course trash are stored on
`ArchiveSubmission`; `trash.py` and `archive_submission_lifecycle.py` perform
restore. Coverage is partial, including
`test_admin_delete_course_soft_deletes_archives` and trash dispatch tests.

### Known gap

Current grouped restore can approve linked submissions without reliably
recovering a pending/rejected previous state.

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
already has focused anonymous-access test evidence. The frontend also hides
controls but is not an authorization boundary.

### Known gap

Permission logic is distributed across `archives.py`, `reports.py`, `trash.py`,
`courses.py`, and `notifications.py`. Equivalent lifecycle actions need focused
tests before centralization.

## Error semantics

| Condition | Intended semantic result | Current status |
| --- | --- | --- |
| Same-target retry | Successful distinguishable no-op without writes, notification, statistics, or audit changes | Partially implemented; response schema and full side-effect protection require follow-up |
| Different invalid transition | `409 Conflict` without writes or notification | Partially implemented |
| Permission denied | Deny without revealing protected resource details | Backend enforcement exists; consistency requires review |
| Missing entity | Not found/unavailable without side effects | Generally implemented |
| Active uniqueness conflict | Explicit conflict and no duplicate row | Implemented for several report paths; soft-delete predicate has a gap |
| Restore conflict | Explicitly block restore and retain trashed row | Required follow-up for pending reports and previous-state restoration |
| Storage deletion failure | Do not report the single item as fully deleted; preserve retry evidence | Implementation gap; current cleanup may emit only a warning |

This contract does not standardize the precise `401`/`403` authentication
status or prescribe the same-target no-op response field name. Future
conformance work must coordinate API responses, frontend handling, and tests.

## Required follow-up

The first safety-net slice should characterize the current submission matrix,
sibling visibility, pending-report trash uniqueness, and category
delete/restore behavior before implementation changes.
