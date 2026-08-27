"""Exact-version MinIO safety boundary for permanent deletion.

This module deliberately owns no workflow state. PostgreSQL remains the saga
authority; this adapter answers only whether one recorded exact object version
is present or conclusively absent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from minio.error import S3Error


class ExactVersionState(StrEnum):
    PRESENT = "PRESENT"
    VERIFIED_ABSENT = "VERIFIED_ABSENT"


class StorageSafetyError(RuntimeError):
    """A stable fail-closed result that requires manual review."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RetryableStorageError(RuntimeError):
    """The exact target is known to remain present after a failed attempt."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DeleteOutcomeUnknown(RuntimeError):
    """The destructive request may have reached storage and must be verified."""

    def __init__(self, code: str = "delete_outcome_unknown") -> None:
        self.code = code
        super().__init__(code)


class RetryBudgetExhausted(RuntimeError):
    pass


class _MinioClient(Protocol):
    def get_bucket_versioning(self, bucket_name: str): ...

    def list_objects(self, bucket_name: str, **kwargs): ...

    def stat_object(
        self, bucket_name: str, object_name: str, version_id: str | None = None
    ): ...

    def remove_object(
        self, bucket_name: str, object_name: str, version_id: str | None = None
    ) -> None: ...


_EXACT_ABSENCE_CODES = {"NoSuchKey", "NoSuchObject", "NoSuchVersion"}
_RETRYABLE_CODES = {
    "InternalError",
    "RequestTimeout",
    "ServiceUnavailable",
    "SlowDown",
}


class ExactVersionMinioAdapter:
    def __init__(self, client: _MinioClient, *, bucket_name: str) -> None:
        if not bucket_name.strip():
            raise ValueError("bucket_name must be non-empty")
        self._client = client
        self.bucket_name = bucket_name

    def _require_enabled(self) -> None:
        try:
            config = self._client.get_bucket_versioning(self.bucket_name)
        except Exception as exc:
            raise StorageSafetyError("versioning_state_unavailable") from exc
        status = str(getattr(config, "status", "") or "").upper()
        if status != "ENABLED":
            raise StorageSafetyError("versioning_not_enabled")

    def _history(self, object_key: str) -> list[object]:
        if not object_key.strip():
            raise StorageSafetyError("empty_object_key")
        try:
            return [
                item
                for item in self._client.list_objects(
                    self.bucket_name,
                    prefix=object_key,
                    recursive=True,
                    include_version=True,
                )
                if getattr(item, "object_name", None) == object_key
            ]
        except Exception as exc:
            raise StorageSafetyError("object_history_unavailable") from exc

    @staticmethod
    def _listed_version_id(item: object) -> str:
        raw = getattr(item, "version_id", None)
        if raw is None:
            return "null"
        value = str(raw).strip()
        if not value:
            raise StorageSafetyError("empty_version_id")
        return value

    def _stat_exact(self, object_key: str, version_id: str) -> object | None:
        try:
            return self._client.stat_object(
                self.bucket_name,
                object_key,
                version_id=version_id,
            )
        except S3Error as exc:
            if exc.code in _EXACT_ABSENCE_CODES:
                return None
            raise StorageSafetyError("exact_stat_failed") from exc
        except Exception as exc:
            raise StorageSafetyError("exact_stat_unavailable") from exc

    def capture_version_id(self, object_key: str) -> str:
        self._require_enabled()
        history = self._history(object_key)
        if len(history) != 1 or bool(getattr(history[0], "is_delete_marker", False)):
            raise StorageSafetyError("ambiguous_object_history")

        version_id = self._listed_version_id(history[0])
        if self._stat_exact(object_key, version_id) is None:
            raise StorageSafetyError("exact_identity_unverifiable")

        try:
            current = self._client.stat_object(self.bucket_name, object_key)
        except Exception as exc:
            raise StorageSafetyError("current_identity_unavailable") from exc
        current_raw = getattr(current, "version_id", None)
        current_version = "null" if current_raw is None else str(current_raw).strip()
        if current_version != version_id:
            raise StorageSafetyError("current_identity_mismatch")
        return version_id

    def inspect_exact_version(
        self, object_key: str, version_id: str
    ) -> ExactVersionState:
        self._require_enabled()
        if not version_id.strip():
            raise StorageSafetyError("empty_recorded_version_id")

        history = self._history(object_key)
        recorded = []
        unexpected = []
        for item in history:
            listed_version = self._listed_version_id(item)
            if listed_version == version_id and not bool(
                getattr(item, "is_delete_marker", False)
            ):
                recorded.append(item)
            else:
                unexpected.append(item)
        if unexpected or len(recorded) > 1:
            raise StorageSafetyError("identity_drift")
        if not recorded:
            if self._stat_exact(object_key, version_id) is not None:
                raise StorageSafetyError("storage_observation_inconsistent")
            return ExactVersionState.VERIFIED_ABSENT
        if self._stat_exact(object_key, version_id) is None:
            raise StorageSafetyError("storage_observation_inconsistent")
        return ExactVersionState.PRESENT

    def delete_exact_version(
        self, object_key: str, version_id: str
    ) -> ExactVersionState:
        before = self.inspect_exact_version(object_key, version_id)
        if before is ExactVersionState.VERIFIED_ABSENT:
            return before
        try:
            self._client.remove_object(
                self.bucket_name,
                object_key,
                version_id=version_id,
            )
        except S3Error as exc:
            if exc.code in _RETRYABLE_CODES:
                raise RetryableStorageError("storage_retryable_failure") from exc
            if exc.code in _EXACT_ABSENCE_CODES:
                return self.inspect_exact_version(object_key, version_id)
            raise StorageSafetyError("storage_delete_rejected") from exc
        except Exception as exc:
            raise DeleteOutcomeUnknown() from exc

        after = self.inspect_exact_version(object_key, version_id)
        if after is ExactVersionState.PRESENT:
            raise RetryableStorageError("exact_version_still_present")
        return after


def next_retry_at(
    *,
    accepted_at: datetime,
    attempt_count: int,
    now: datetime,
    jitter_fraction: float,
) -> datetime:
    """Return one deterministic bounded retry time or fail at the sealed budget."""

    if attempt_count >= 10 or now >= accepted_at + timedelta(hours=24):
        raise RetryBudgetExhausted("automatic_retry_budget_exhausted")
    if not 0.0 <= jitter_fraction <= 1.0:
        raise ValueError("jitter_fraction must be between zero and one")

    base_seconds = min(30 * (2 ** max(attempt_count - 1, 0)), 3600)
    delay = timedelta(seconds=base_seconds * (1.0 + 0.2 * jitter_fraction))
    deadline = accepted_at + timedelta(hours=24)
    scheduled = min(now + delay, deadline)
    if scheduled <= now:
        raise RetryBudgetExhausted("automatic_retry_deadline_reached")
    return scheduled
