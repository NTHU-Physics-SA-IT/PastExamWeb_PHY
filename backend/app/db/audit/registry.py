"""Sealed registry of versioned aggregate audit classifiers."""

from __future__ import annotations

from dataclasses import dataclass


ELIGIBILITY_AUDIT_ID = "archive-submission-self-delete-eligibility"


_CLASSIFICATION_CTE = r"""
WITH base AS (
    SELECT
        submission.*,
        (
            submission.requester_id IS NOT NULL
            AND (
                submission.owner_id IS NULL
                OR submission.owner_id = submission.requester_id
            )
        ) AS ownership_valid,
        EXISTS (
            SELECT 1
            FROM users AS actor
            WHERE actor.id = submission.deleted_by_id
        ) AS deleted_actor_exists,
        EXISTS (
            SELECT 1
            FROM users AS actor
            WHERE actor.id = submission.deleted_by_id
              AND actor.is_admin IS TRUE
        ) AS deleted_by_admin,
        (
            submission.status::text IN ('PENDING', 'APPROVED', 'REJECTED')
            AND submission.lifecycle_reason IS NULL
        ) OR (
            submission.status::text = 'TAKEDOWN'
            AND (
                submission.lifecycle_reason IS NULL
                OR submission.lifecycle_reason = 'archive_trashed'
                OR submission.lifecycle_reason = 'course_trashed'
                OR submission.lifecycle_reason ~
                    '^course_trashed\|previous_status='
                    '(pending|approved|rejected|takedown)'
                    '(\|course_id=[1-9][0-9]*)?'
                    '(\|archive_id=[1-9][0-9]*)?$'
            )
        ) AS active_lifecycle_valid
    FROM archive_submissions AS submission
),
flags AS (
    SELECT
        base.*,
        (
            ownership_valid
            AND status::text = 'DELETED'
            AND deleted_at IS NOT NULL
            AND deleted_by_id IS NOT NULL
            AND deleted_by_id = requester_id
            AND delete_reason = 'user deleted'
            AND lifecycle_reason IS NULL
            AND restored_at IS NULL
            AND restored_by_id IS NULL
        ) AS owner_self_delete,
        (
            ownership_valid
            AND status::text <> 'DELETED'
            AND active_lifecycle_valid
            AND deleted_at IS NULL
            AND deleted_by_id IS NULL
            AND delete_reason IS NULL
            AND restored_at IS NOT NULL
            AND restored_by_id IS NOT NULL
        ) AS active_restored_unknown,
        (
            ownership_valid
            AND status::text = 'DELETED'
            AND deleted_at IS NOT NULL
            AND deleted_by_id IS NOT NULL
            AND deleted_by_admin
            AND delete_reason = 'admin deleted'
            AND lifecycle_reason IS NULL
            AND restored_at IS NULL
            AND restored_by_id IS NULL
        ) AS historical_admin_delete,
        (
            ownership_valid
            AND status::text <> 'DELETED'
            AND active_lifecycle_valid
            AND deleted_at IS NULL
            AND deleted_by_id IS NULL
            AND delete_reason IS NULL
            AND restored_at IS NULL
            AND restored_by_id IS NULL
        ) AS clean_active,
        (
            ownership_valid
            AND status::text = 'DELETED'
            AND deleted_at IS NOT NULL
            AND deleted_by_id IS NOT NULL
            AND deleted_actor_exists
            AND restored_at IS NULL
            AND restored_by_id IS NULL
            AND delete_reason = 'linked archive permanently deleted'
            AND lifecycle_reason = 'linked_archive_permanently_deleted'
        ) AS recognized_system_delete
    FROM base
),
top_level AS (
    SELECT
        flags.*,
        (
            owner_self_delete
            OR active_restored_unknown
            OR historical_admin_delete
            OR recognized_system_delete
        ) AS automatic_true,
        clean_active AS automatic_false,
        (
            NOT ownership_valid
            OR ((status::text = 'DELETED') <> (deleted_at IS NOT NULL))
            OR ((restored_at IS NULL) <> (restored_by_id IS NULL))
            OR (
                status::text = 'DELETED'
                AND (restored_at IS NOT NULL OR restored_by_id IS NOT NULL)
            )
            OR (
                status::text <> 'DELETED'
                AND (
                    deleted_at IS NOT NULL
                    OR deleted_by_id IS NOT NULL
                    OR delete_reason IS NOT NULL
                )
            )
            OR (status::text <> 'DELETED' AND NOT active_lifecycle_valid)
            OR (
                status::text = 'DELETED'
                AND lifecycle_reason IS NOT NULL
                AND NOT (
                    delete_reason = 'linked archive permanently deleted'
                    AND lifecycle_reason = 'linked_archive_permanently_deleted'
                )
            )
            OR (
                ownership_valid
                AND status::text = 'DELETED'
                AND deleted_at IS NOT NULL
                AND restored_at IS NULL
                AND restored_by_id IS NULL
                AND NOT owner_self_delete
                AND NOT historical_admin_delete
                AND NOT recognized_system_delete
            )
        ) AS unsupported
    FROM flags
),
classified AS (
    SELECT
        top_level.*,
        (
            automatic_true::integer
            + automatic_false::integer
            + unsupported::integer
        ) AS bucket_memberships
    FROM top_level
)
"""


_SUMMARY_SQL = (
    _CLASSIFICATION_CTE
    + """
SELECT
    count(*)::bigint AS total,
    count(*) FILTER (WHERE automatic_true)::bigint AS automatic_true,
    count(*) FILTER (WHERE automatic_false)::bigint AS automatic_false,
    count(*) FILTER (WHERE unsupported)::bigint AS unsupported,
    count(*) FILTER (WHERE bucket_memberships = 0)::bigint AS unclassified,
    count(*) FILTER (WHERE bucket_memberships > 1)::bigint AS overlap,
    (
        count(*) FILTER (WHERE automatic_true)
        + count(*) FILTER (WHERE automatic_false)
        + count(*) FILTER (WHERE unsupported)
        + count(*) FILTER (WHERE bucket_memberships = 0)
    )::bigint AS bucket_sum,
    (
        count(*)
        - count(*) FILTER (WHERE automatic_true)
        - count(*) FILTER (WHERE automatic_false)
        - count(*) FILTER (WHERE unsupported)
        - count(*) FILTER (WHERE bucket_memberships = 0)
    )::bigint AS difference
FROM classified
"""
)


_COMBINATIONS_SQL = (
    _CLASSIFICATION_CTE
    + """
, unsupported_flags AS (
    SELECT
        ARRAY_REMOVE(
            ARRAY[
                CASE WHEN NOT ownership_valid THEN 'ownership_invalid' END,
                CASE
                    WHEN ((status::text = 'DELETED') <> (deleted_at IS NOT NULL))
                    THEN 'status_delete_mismatch'
                END,
                CASE
                    WHEN ((restored_at IS NULL) <> (restored_by_id IS NULL))
                    THEN 'restore_metadata_incomplete'
                END,
                CASE
                    WHEN status::text = 'DELETED'
                     AND (restored_at IS NOT NULL OR restored_by_id IS NOT NULL)
                    THEN 'deleted_restore_residue'
                END,
                CASE
                    WHEN status::text <> 'DELETED'
                     AND (
                        deleted_at IS NOT NULL
                        OR deleted_by_id IS NOT NULL
                        OR delete_reason IS NOT NULL
                     )
                    THEN 'active_delete_residue'
                END,
                CASE
                    WHEN status::text <> 'DELETED' AND NOT active_lifecycle_valid
                    THEN 'active_lifecycle_invalid'
                END,
                CASE
                    WHEN status::text = 'DELETED'
                     AND lifecycle_reason IS NOT NULL
                     AND NOT recognized_system_delete
                    THEN 'deleted_lifecycle_invalid'
                END,
                CASE
                    WHEN ownership_valid
                     AND status::text = 'DELETED'
                     AND deleted_at IS NOT NULL
                     AND restored_at IS NULL
                     AND restored_by_id IS NULL
                     AND NOT owner_self_delete
                     AND NOT historical_admin_delete
                     AND NOT recognized_system_delete
                    THEN 'delete_provenance_unsupported'
                END
            ],
            NULL
        )::text[] AS flags
    FROM classified
    WHERE unsupported
)
SELECT flags, count(*)::bigint AS count
FROM unsupported_flags
GROUP BY flags
ORDER BY flags
LIMIT 21
"""
)


@dataclass(frozen=True)
class AuditAdapter:
    audit_id: str
    version: int
    accepted_source_revisions: frozenset[str]
    approved_aggregate_labels: tuple[str, ...]
    approved_combination_flags: frozenset[str]
    summary_sql: str
    combinations_sql: str


_ELIGIBILITY_V1 = AuditAdapter(
    audit_id=ELIGIBILITY_AUDIT_ID,
    version=1,
    accepted_source_revisions=frozenset(
        {
            "a4c7e9d2f6b1",
            "a7c3e9f1b5d2",
            "f5e1d8c3a7b2",
        }
    ),
    approved_aggregate_labels=(
        "total",
        "automatic_true",
        "automatic_false",
        "unsupported",
        "unclassified",
        "overlap",
        "bucket_sum",
        "difference",
    ),
    approved_combination_flags=frozenset(
        {
            "ownership_invalid",
            "status_delete_mismatch",
            "restore_metadata_incomplete",
            "deleted_restore_residue",
            "active_delete_residue",
            "active_lifecycle_invalid",
            "deleted_lifecycle_invalid",
            "delete_provenance_unsupported",
        }
    ),
    summary_sql=_SUMMARY_SQL,
    combinations_sql=_COMBINATIONS_SQL,
)


_REGISTRY = {
    (_ELIGIBILITY_V1.audit_id, _ELIGIBILITY_V1.version): _ELIGIBILITY_V1,
}


def get_audit_adapter(audit_id: str, version: int) -> AuditAdapter:
    try:
        return _REGISTRY[(audit_id, version)]
    except KeyError as exc:
        raise KeyError(f"unknown sealed audit adapter: {audit_id}@{version}") from exc
