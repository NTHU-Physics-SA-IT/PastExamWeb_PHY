from __future__ import annotations

import io
import os
import urllib.request
import uuid

import pytest
from minio import Minio
from minio.commonconfig import ENABLED
from minio.error import S3Error
from minio.versioningconfig import VersioningConfig

pytestmark = pytest.mark.skipif(
    not os.getenv("SEC04_MINIO_ENDPOINT"),
    reason="requires the task-owned SEC-04 synthetic MinIO lab",
)


def _client() -> Minio:
    return Minio(
        os.environ["SEC04_MINIO_ENDPOINT"],
        access_key=os.environ["SEC04_MINIO_ACCESS_KEY"],
        secret_key=os.environ["SEC04_MINIO_SECRET_KEY"],
        secure=False,
    )


def _denied(call) -> None:
    with pytest.raises(S3Error) as error:
        call()
    assert error.value.code in {"AccessDenied", "InvalidAccessKeyId"}


def test_scoped_identity_runtime_and_negative_contract() -> None:
    client = _client()
    bucket = os.environ["SEC04_MINIO_BUCKET"]
    unrelated_bucket = os.environ["SEC04_MINIO_UNRELATED_BUCKET"]
    marker = uuid.uuid4().hex
    archive_key = f"archives/{marker}.pdf"
    submission_key = f"archive-submissions/{marker}.pdf"
    forbidden_key = f"forbidden/{marker}.pdf"

    assert client._get_region(bucket) == "us-east-1"
    assert client.get_bucket_versioning(bucket).status == ENABLED

    small = b"%PDF-synthetic-sec04"
    multipart = b"x" * (10 * 1024 * 1024)
    client.put_object(bucket, archive_key, io.BytesIO(small), len(small))
    client.put_object(
        bucket,
        submission_key,
        io.BytesIO(multipart),
        len(multipart),
        part_size=5 * 1024 * 1024,
    )

    archive_stat = client.stat_object(bucket, archive_key)
    submission_stat = client.stat_object(bucket, submission_key)
    assert archive_stat.version_id
    assert submission_stat.version_id

    response = client.get_object(bucket, archive_key)
    try:
        assert response.read() == small
    finally:
        response.close()
        response.release_conn()

    signed = client.presigned_get_object(bucket, archive_key)
    with urllib.request.urlopen(signed, timeout=5) as signed_response:
        assert signed_response.read() == small

    range_request = urllib.request.Request(
        signed,
        headers={"Range": "bytes=0-7"},
    )
    with urllib.request.urlopen(range_request, timeout=5) as range_response:
        assert range_response.status == 206
        assert range_response.headers["Content-Range"] == f"bytes 0-7/{len(small)}"
        assert range_response.headers["Content-Length"] == "8"
        assert range_response.headers["Accept-Ranges"] == "bytes"
        assert range_response.read() == small[:8]

    versions = list(
        client.list_objects(
            bucket,
            prefix=archive_key,
            recursive=True,
            include_version=True,
        )
    )
    assert any(item.version_id == archive_stat.version_id for item in versions)

    _denied(lambda: list(client.list_objects(bucket, recursive=True)))
    _denied(
        lambda: client.put_object(
            bucket, forbidden_key, io.BytesIO(b"denied"), len(b"denied")
        )
    )
    _denied(lambda: client.stat_object(unrelated_bucket, "existing-object"))
    _denied(lambda: client.make_bucket(f"denied-{marker}"))
    _denied(lambda: client.remove_bucket(unrelated_bucket))
    _denied(
        lambda: client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
    )

    client.remove_object(bucket, archive_key, version_id=archive_stat.version_id)
    client.remove_object(
        bucket, submission_key, version_id=submission_stat.version_id
    )

    with pytest.raises(S3Error) as missing:
        client.stat_object(bucket, archive_key, version_id=archive_stat.version_id)
    assert missing.value.code in {"NoSuchKey", "NoSuchVersion"}


def test_legacy_bucket_exists_is_denied_by_core_policy() -> None:
    with pytest.raises(S3Error) as error:
        _client().bucket_exists(os.environ["SEC04_MINIO_BUCKET"])
    assert error.value.code == "AccessDenied"


@pytest.mark.skipif(
    not os.getenv("SEC04_ROLLBACK_POLICY_ATTACHED"),
    reason="rollback-only policy is not attached in the core-policy phase",
)
def test_legacy_bucket_exists_passes_with_temporary_list_bucket() -> None:
    client = _client()
    assert client.bucket_exists(os.environ["SEC04_MINIO_BUCKET"]) is True
    _denied(lambda: client.make_bucket(f"rollback-denied-{uuid.uuid4().hex}"))
