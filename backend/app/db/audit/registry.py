"""Sealed registry of versioned aggregate audit classifiers."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.db.audit.models import (
    AggregateCounts,
    OneToOneAggregateCounts,
    PreviousStatusAggregateCounts,
)


ELIGIBILITY_AUDIT_ID = "archive-submission-self-delete-eligibility"
PREVIOUS_STATUS_REVISION = "d8f2a6c1b4e7"
ONE_TO_ONE_REVISION = "6f3a9c2d8e41"


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
    aggregate_model: type[BaseModel]


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
    aggregate_model=AggregateCounts,
)


_PREVIOUS_STATUS_CLASSIFICATION_CTE = r"""
WITH base AS (
    SELECT
        submission.*,
        to_jsonb(submission) ? 'previous_status'
            AS has_previous_status_column,
        to_jsonb(submission)->>'previous_status' AS previous_status_text,
        (
            submission.deleted_at IS NULL
            AND submission.status::text <> 'DELETED'
        ) AS active_row,
        (
            submission.deleted_at IS NOT NULL
            OR submission.status::text = 'DELETED'
        ) AS deleted_row,
        (
            submission.status::text = 'TAKEDOWN'
            AND submission.deleted_at IS NULL
            AND submission.lifecycle_reason ~
                '^course_trashed\|previous_status='
                '(pending|approved|rejected|takedown)'
                '(\|course_id=[1-9][0-9]*)?'
                '(\|archive_id=[1-9][0-9]*)?$'
        ) AS valid_course_marker,
        (
            submission.lifecycle_reason LIKE
                'course_trashed|previous_status=%'
        ) AS course_marker_like,
        (
            submission.requester_id IS NOT NULL
            AND (
                submission.owner_id IS NULL
                OR submission.owner_id = submission.requester_id
            )
            AND submission.status::text = 'DELETED'
            AND submission.deleted_at IS NOT NULL
            AND submission.deleted_by_id IS NOT NULL
            AND submission.deleted_by_id = submission.requester_id
            AND submission.delete_reason = 'user deleted'
            AND submission.lifecycle_reason IS NULL
            AND submission.restored_at IS NULL
            AND submission.restored_by_id IS NULL
        ) AS deterministic_owner_delete,
        (
            submission.status::text = 'DELETED'
            AND submission.deleted_at IS NOT NULL
            AND (
                submission.delete_reason = 'admin deleted'
                OR submission.delete_reason = 'archive group deleted'
                OR submission.lifecycle_reason = 'archive_trashed'
            )
        ) AS admin_archive_group_delete,
        (
            submission.status::text = 'DELETED'
            AND submission.deleted_at IS NOT NULL
            AND submission.delete_reason =
                'linked archive permanently deleted'
            AND submission.lifecycle_reason =
                'linked_archive_permanently_deleted'
        ) AS permanent_delete
    FROM archive_submissions AS submission
),
classified AS (
    SELECT
        base.*,
        (
            deleted_row
            AND NOT deterministic_owner_delete
            AND NOT permanent_delete
            AND admin_archive_group_delete
        ) AS ambiguous_admin_archive_group,
        (
            deleted_row
            AND NOT deterministic_owner_delete
            AND NOT permanent_delete
            AND NOT admin_archive_group_delete
        ) AS unknown_deleted_provenance,
        (
            active_row::integer
            + deterministic_owner_delete::integer
            + (
                deleted_row
                AND NOT deterministic_owner_delete
                AND NOT permanent_delete
                AND admin_archive_group_delete
            )::integer
            + permanent_delete::integer
            + (
                deleted_row
                AND NOT deterministic_owner_delete
                AND NOT permanent_delete
                AND NOT admin_archive_group_delete
            )::integer
        ) AS bucket_memberships,
        (
            ((status::text = 'DELETED') <> (deleted_at IS NOT NULL))
            OR (
                active_row
                AND previous_status_text IS NOT NULL
            )
            OR previous_status_text = 'DELETED'
            OR (
                previous_status_text IS NOT NULL
                AND previous_status_text NOT IN (
                    'PENDING',
                    'APPROVED',
                    'REJECTED',
                    'TAKEDOWN',
                    'DELETED'
                )
            )
            OR (
                valid_course_marker
                AND previous_status_text IS NOT NULL
            )
            OR (
                course_marker_like
                AND NOT valid_course_marker
            )
            OR (
                permanent_delete
                AND previous_status_text IS NOT NULL
            )
            OR (
                has_previous_status_column
                AND deterministic_owner_delete
                AND previous_status_text IS DISTINCT FROM 'APPROVED'
            )
        ) AS unsupported
    FROM base
),
shared_archives AS (
    SELECT
        count(*)::bigint AS shared_created_archive_groups,
        COALESCE(sum(group_count), 0)::bigint
            AS shared_created_archive_submissions
    FROM (
        SELECT count(*)::bigint AS group_count
        FROM archive_submissions
        WHERE created_archive_id IS NOT NULL
        GROUP BY created_archive_id
        HAVING count(*) > 1
    ) AS grouped
)
"""

_PREVIOUS_STATUS_SUMMARY_SQL = (
    _PREVIOUS_STATUS_CLASSIFICATION_CTE
    + r"""
SELECT
    count(*)::bigint AS total,
    count(*) FILTER (WHERE active_row)::bigint AS active,
    count(*) FILTER (WHERE deleted_row)::bigint AS deleted,
    count(*) FILTER (
        WHERE previous_status_text = 'PENDING'
    )::bigint AS previous_status_pending,
    count(*) FILTER (
        WHERE previous_status_text = 'APPROVED'
    )::bigint AS previous_status_approved,
    count(*) FILTER (
        WHERE previous_status_text = 'REJECTED'
    )::bigint AS previous_status_rejected,
    count(*) FILTER (
        WHERE previous_status_text = 'TAKEDOWN'
    )::bigint AS previous_status_takedown,
    count(*) FILTER (
        WHERE previous_status_text IS NULL
    )::bigint AS previous_status_null,
    count(*) FILTER (
        WHERE previous_status_text = 'DELETED'
    )::bigint AS previous_status_deleted,
    count(*) FILTER (
        WHERE previous_status_text IS NOT NULL
          AND previous_status_text NOT IN (
              'PENDING',
              'APPROVED',
              'REJECTED',
              'TAKEDOWN',
              'DELETED'
          )
    )::bigint AS invalid_previous_status,
    count(*) FILTER (
        WHERE active_row
          AND previous_status_text IS NOT NULL
    )::bigint AS active_with_previous_status,
    count(*) FILTER (
        WHERE deleted_row
          AND previous_status_text IN (
              'PENDING',
              'APPROVED',
              'REJECTED',
              'TAKEDOWN'
          )
    )::bigint AS deleted_with_exact_previous_status,
    count(*) FILTER (
        WHERE deleted_row
          AND previous_status_text IS NULL
    )::bigint AS deleted_with_null_previous_status,
    count(*) FILTER (
        WHERE valid_course_marker
    )::bigint AS valid_course_marker,
    count(*) FILTER (
        WHERE valid_course_marker
          AND previous_status_text IS NOT NULL
    )::bigint AS valid_course_marker_with_previous_status,
    count(*) FILTER (
        WHERE course_marker_like
          AND NOT valid_course_marker
    )::bigint AS invalid_course_marker,
    count(*) FILTER (
        WHERE deterministic_owner_delete
    )::bigint AS deterministic_owner_delete_candidate,
    count(*) FILTER (
        WHERE deterministic_owner_delete
          AND previous_status_text = 'APPROVED'
    )::bigint AS deterministic_backfilled,
    count(*) FILTER (
        WHERE ambiguous_admin_archive_group
    )::bigint AS ambiguous_admin_archive_group,
    count(*) FILTER (WHERE permanent_delete)::bigint AS permanent,
    count(*) FILTER (
        WHERE unknown_deleted_provenance
    )::bigint AS unknown_deleted_provenance,
    count(*) FILTER (
        WHERE owner_self_delete_consumed
    )::bigint AS owner_self_delete_consumed_true,
    count(*) FILTER (
        WHERE NOT owner_self_delete_consumed
    )::bigint AS owner_self_delete_consumed_false,
    (
        SELECT shared_created_archive_groups
        FROM shared_archives
    ) AS shared_created_archive_groups,
    (
        SELECT shared_created_archive_submissions
        FROM shared_archives
    ) AS shared_created_archive_submissions,
    count(*) FILTER (
        WHERE owner_self_delete_consumed
    )::bigint AS automatic_true,
    count(*) FILTER (
        WHERE NOT owner_self_delete_consumed
    )::bigint AS automatic_false,
    count(*) FILTER (WHERE unsupported)::bigint AS unsupported,
    count(*) FILTER (WHERE bucket_memberships = 0)::bigint AS unclassified,
    count(*) FILTER (WHERE bucket_memberships > 1)::bigint AS overlap,
    (
        count(*) FILTER (WHERE active_row)
        + count(*) FILTER (WHERE deterministic_owner_delete)
        + count(*) FILTER (WHERE ambiguous_admin_archive_group)
        + count(*) FILTER (WHERE permanent_delete)
        + count(*) FILTER (WHERE unknown_deleted_provenance)
    )::bigint AS bucket_sum,
    (
        count(*)
        - count(*) FILTER (WHERE active_row)
        - count(*) FILTER (WHERE deterministic_owner_delete)
        - count(*) FILTER (WHERE ambiguous_admin_archive_group)
        - count(*) FILTER (WHERE permanent_delete)
        - count(*) FILTER (WHERE unknown_deleted_provenance)
    )::bigint AS difference
FROM classified
"""
)

_PREVIOUS_STATUS_COMBINATIONS_SQL = (
    _PREVIOUS_STATUS_CLASSIFICATION_CTE
    + r"""
, unsupported_flags AS (
    SELECT
        ARRAY_REMOVE(
            ARRAY[
                CASE
                    WHEN ((status::text = 'DELETED') <> (deleted_at IS NOT NULL))
                    THEN 'status_delete_mismatch'
                END,
                CASE
                    WHEN active_row AND previous_status_text IS NOT NULL
                    THEN 'active_previous_status'
                END,
                CASE
                    WHEN previous_status_text = 'DELETED'
                    THEN 'deleted_previous_status'
                END,
                CASE
                    WHEN previous_status_text IS NOT NULL
                     AND previous_status_text NOT IN (
                        'PENDING',
                        'APPROVED',
                        'REJECTED',
                        'TAKEDOWN',
                        'DELETED'
                     )
                    THEN 'invalid_previous_status'
                END,
                CASE
                    WHEN valid_course_marker
                     AND previous_status_text IS NOT NULL
                    THEN 'course_marker_previous_status'
                END,
                CASE
                    WHEN course_marker_like AND NOT valid_course_marker
                    THEN 'invalid_course_marker'
                END,
                CASE
                    WHEN permanent_delete
                     AND previous_status_text IS NOT NULL
                    THEN 'permanent_previous_status'
                END,
                CASE
                    WHEN has_previous_status_column
                     AND deterministic_owner_delete
                     AND previous_status_text IS DISTINCT FROM 'APPROVED'
                    THEN 'owner_backfill_mismatch'
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

_ELIGIBILITY_V2 = AuditAdapter(
    audit_id=ELIGIBILITY_AUDIT_ID,
    version=2,
    accepted_source_revisions=frozenset(
        {
            "f5e1d8c3a7b2",
            PREVIOUS_STATUS_REVISION,
        }
    ),
    approved_aggregate_labels=tuple(PreviousStatusAggregateCounts.model_fields),
    approved_combination_flags=frozenset(
        {
            "status_delete_mismatch",
            "active_previous_status",
            "deleted_previous_status",
            "invalid_previous_status",
            "course_marker_previous_status",
            "invalid_course_marker",
            "permanent_previous_status",
            "owner_backfill_mismatch",
        }
    ),
    summary_sql=_PREVIOUS_STATUS_SUMMARY_SQL,
    combinations_sql=_PREVIOUS_STATUS_COMBINATIONS_SQL,
    aggregate_model=PreviousStatusAggregateCounts,
)

_ONE_TO_ONE_SUMMARY_SQL = (
    r"""
WITH previous_status_summary AS (
"""
    + _PREVIOUS_STATUS_SUMMARY_SQL
    + r"""
),
link_cardinalities AS (
    SELECT
        created_archive_id,
        count(*)::bigint AS cardinality
    FROM archive_submissions
    WHERE created_archive_id IS NOT NULL
    GROUP BY created_archive_id
),
relationship_summary AS (
    SELECT
        count(*) FILTER (
            WHERE submission.created_archive_id IS NULL
        )::bigint AS created_archive_id_null,
        count(*) FILTER (
            WHERE submission.created_archive_id IS NOT NULL
        )::bigint AS created_archive_id_non_null,
        count(DISTINCT submission.created_archive_id)::bigint
            AS distinct_created_archive_ids,
        COALESCE((
            SELECT max(cardinality)
            FROM link_cardinalities
        ), 0)::bigint AS max_created_archive_cardinality,
        count(*) FILTER (
            WHERE submission.created_archive_id IS NOT NULL
              AND archive.id IS NULL
        )::bigint AS dangling_created_archive_links
    FROM archive_submissions AS submission
    LEFT JOIN archives AS archive
      ON archive.id = submission.created_archive_id
),
resource_counts AS (
    SELECT
        (SELECT count(*) FROM course_category_configs)::bigint
            AS course_category_configs_total,
        (SELECT count(*) FROM users)::bigint AS users_total,
        (SELECT count(*) FROM courses)::bigint AS courses_total,
        (SELECT count(*) FROM archives)::bigint AS archives_total
),
fingerprints AS (
    SELECT
        md5(COALESCE(string_agg(
            concat_ws(
                ':',
                submission.id::text,
                COALESCE(submission.created_archive_id::text, 'NULL')
            ),
            '|' ORDER BY submission.id
        ), '')) AS created_archive_link_checksum,
        md5(COALESCE(string_agg(
            concat_ws(
                ':',
                submission.id::text,
                submission.status::text,
                COALESCE(submission.previous_status::text, 'NULL'),
                submission.owner_self_delete_consumed::text,
                COALESCE(submission.deleted_at::text, 'NULL'),
                COALESCE(submission.deleted_by_id::text, 'NULL'),
                COALESCE(submission.delete_reason, 'NULL'),
                COALESCE(submission.lifecycle_reason, 'NULL'),
                COALESCE(submission.restored_at::text, 'NULL'),
                COALESCE(submission.restored_by_id::text, 'NULL')
            ),
            '|' ORDER BY submission.id
        ), '')) AS submission_state_checksum
    FROM archive_submissions AS submission
)
SELECT
    previous_status_summary.*,
    relationship_summary.created_archive_id_null,
    relationship_summary.created_archive_id_non_null,
    relationship_summary.distinct_created_archive_ids,
    relationship_summary.max_created_archive_cardinality,
    relationship_summary.dangling_created_archive_links,
    resource_counts.course_category_configs_total,
    resource_counts.users_total,
    resource_counts.courses_total,
    resource_counts.archives_total,
    fingerprints.created_archive_link_checksum,
    fingerprints.submission_state_checksum
FROM
    previous_status_summary,
    relationship_summary,
    resource_counts,
    fingerprints
"""
)

_ELIGIBILITY_V3 = AuditAdapter(
    audit_id=ELIGIBILITY_AUDIT_ID,
    version=3,
    accepted_source_revisions=frozenset(
        {
            PREVIOUS_STATUS_REVISION,
            ONE_TO_ONE_REVISION,
        }
    ),
    approved_aggregate_labels=tuple(OneToOneAggregateCounts.model_fields),
    approved_combination_flags=_ELIGIBILITY_V2.approved_combination_flags,
    summary_sql=_ONE_TO_ONE_SUMMARY_SQL,
    combinations_sql=_PREVIOUS_STATUS_COMBINATIONS_SQL,
    aggregate_model=OneToOneAggregateCounts,
)


_REGISTRY = {
    (_ELIGIBILITY_V1.audit_id, _ELIGIBILITY_V1.version): _ELIGIBILITY_V1,
    (_ELIGIBILITY_V2.audit_id, _ELIGIBILITY_V2.version): _ELIGIBILITY_V2,
    (_ELIGIBILITY_V3.audit_id, _ELIGIBILITY_V3.version): _ELIGIBILITY_V3,
}


def get_audit_adapter(audit_id: str, version: int) -> AuditAdapter:
    try:
        return _REGISTRY[(audit_id, version)]
    except KeyError as exc:
        raise KeyError(f"unknown sealed audit adapter: {audit_id}@{version}") from exc
