from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.permanent_deletion_storage import (
    DeleteOutcomeUnknown,
    ExactVersionMinioAdapter,
    ExactVersionState,
    RetryBudgetExhausted,
    StorageSafetyError,
    next_retry_at,
)


class FakeMinio:
    def __init__(
        self,
        *,
        status: str = "Enabled",
        versions: list[tuple[str, str, bool]] | None = None,
        unknown_after_delete: bool = False,
    ) -> None:
        self.status = status
        self.versions = list(versions or [])
        self.unknown_after_delete = unknown_after_delete
        self.removals: list[tuple[str, str, str | None]] = []

    def get_bucket_versioning(self, _bucket: str):
        return SimpleNamespace(status=self.status)

    def list_objects(self, _bucket: str, **_kwargs):
        return [
            SimpleNamespace(
                object_name=key,
                version_id=version_id,
                is_delete_marker=is_delete_marker,
            )
            for key, version_id, is_delete_marker in self.versions
        ]

    def stat_object(self, _bucket: str, key: str, version_id: str | None = None):
        candidates = [
            row
            for row in self.versions
            if row[0] == key and not row[2] and (version_id is None or row[1] == version_id)
        ]
        if not candidates:
            raise _missing_version_error()
        selected = candidates[-1]
        return SimpleNamespace(object_name=key, version_id=selected[1])

    def remove_object(
        self, bucket: str, key: str, version_id: str | None = None
    ) -> None:
        self.removals.append((bucket, key, version_id))
        self.versions = [
            row for row in self.versions if not (row[0] == key and row[1] == version_id)
        ]
        if self.unknown_after_delete:
            raise TimeoutError("synthetic timeout after server-side delete")


def _missing_version_error():
    from minio.error import S3Error

    return S3Error(
        None,
        "NoSuchVersion",
        "missing",
        "resource",
        "request-id",
        "host-id",
    )


def test_capture_requires_enabled_and_one_unambiguous_exact_version() -> None:
    normal = ExactVersionMinioAdapter(
        FakeMinio(versions=[("archive/a.pdf", "v-normal", False)]),
        bucket_name="test-bucket",
    )
    assert normal.capture_version_id("archive/a.pdf") == "v-normal"

    legacy = ExactVersionMinioAdapter(
        FakeMinio(versions=[("archive/legacy.pdf", "null", False)]),
        bucket_name="test-bucket",
    )
    assert legacy.capture_version_id("archive/legacy.pdf") == "null"

    with pytest.raises(StorageSafetyError, match="versioning_not_enabled"):
        ExactVersionMinioAdapter(
            FakeMinio(
                status="Suspended",
                versions=[("archive/a.pdf", "v-normal", False)],
            ),
            bucket_name="test-bucket",
        ).capture_version_id("archive/a.pdf")

    with pytest.raises(StorageSafetyError, match="ambiguous_object_history"):
        ExactVersionMinioAdapter(
            FakeMinio(
                versions=[
                    ("archive/a.pdf", "v-old", False),
                    ("archive/a.pdf", "v-current", False),
                ]
            ),
            bucket_name="test-bucket",
        ).capture_version_id("archive/a.pdf")


def test_delete_is_exact_and_requires_post_delete_exact_absence() -> None:
    client = FakeMinio(versions=[("archive/a.pdf", "v1", False)])
    adapter = ExactVersionMinioAdapter(client, bucket_name="test-bucket")

    assert adapter.delete_exact_version("archive/a.pdf", "v1") == (
        ExactVersionState.VERIFIED_ABSENT
    )
    assert client.removals == [("test-bucket", "archive/a.pdf", "v1")]


def test_replacement_drift_fails_closed_without_deleting_any_version() -> None:
    client = FakeMinio(
        versions=[
            ("archive/a.pdf", "v-recorded", False),
            ("archive/a.pdf", "v-replacement", False),
        ]
    )
    adapter = ExactVersionMinioAdapter(client, bucket_name="test-bucket")

    with pytest.raises(StorageSafetyError, match="identity_drift"):
        adapter.delete_exact_version("archive/a.pdf", "v-recorded")
    assert client.removals == []


def test_timeout_after_delete_is_unknown_until_exact_verification() -> None:
    client = FakeMinio(
        versions=[("archive/a.pdf", "v1", False)], unknown_after_delete=True
    )
    adapter = ExactVersionMinioAdapter(client, bucket_name="test-bucket")

    with pytest.raises(DeleteOutcomeUnknown):
        adapter.delete_exact_version("archive/a.pdf", "v1")
    assert adapter.inspect_exact_version("archive/a.pdf", "v1") == (
        ExactVersionState.VERIFIED_ABSENT
    )


def test_retry_policy_stays_within_ten_attempts_and_twenty_four_hours() -> None:
    accepted_at = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)

    scheduled = next_retry_at(
        accepted_at=accepted_at,
        attempt_count=1,
        now=accepted_at + timedelta(minutes=1),
        jitter_fraction=0.0,
    )
    assert accepted_at < scheduled <= accepted_at + timedelta(hours=24)

    with pytest.raises(RetryBudgetExhausted):
        next_retry_at(
            accepted_at=accepted_at,
            attempt_count=10,
            now=accepted_at + timedelta(hours=1),
            jitter_fraction=0.0,
        )
    with pytest.raises(RetryBudgetExhausted):
        next_retry_at(
            accepted_at=accepted_at,
            attempt_count=2,
            now=accepted_at + timedelta(hours=24),
            jitter_fraction=0.0,
        )
