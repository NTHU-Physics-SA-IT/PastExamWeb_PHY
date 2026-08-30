from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_POLICY = (
    REPOSITORY_ROOT / "docker" / "minio" / "application-policy.template.json"
)
ROLLBACK_POLICY = (
    REPOSITORY_ROOT
    / "docker"
    / "minio"
    / "rollback-list-bucket-policy.template.json"
)


def _policy(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _actions(policy: dict) -> set[str]:
    actions: set[str] = set()
    for statement in policy["Statement"]:
        value = statement["Action"]
        actions.update([value] if isinstance(value, str) else value)
    return actions


def test_application_policy_is_exact_and_prefix_scoped() -> None:
    policy = _policy(APPLICATION_POLICY)
    assert _actions(policy) == {
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning",
        "s3:ListBucketVersions",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
    }
    assert "s3:ListBucket" not in _actions(policy)
    assert "s3:CreateBucket" not in _actions(policy)
    assert "s3:*" not in _actions(policy)

    version_statement = next(
        statement
        for statement in policy["Statement"]
        if statement["Sid"] == "ApprovedPrefixVersionEnumeration"
    )
    assert version_statement["Condition"]["StringLike"]["s3:prefix"] == [
        "archives/*",
        "archive-submissions/*",
    ]
    object_statement = next(
        statement
        for statement in policy["Statement"]
        if statement["Sid"] == "ApplicationObjects"
    )
    assert object_statement["Resource"] == [
        "arn:aws:s3:::<bucket>/archives/*",
        "arn:aws:s3:::<bucket>/archive-submissions/*",
    ]
    assert "arn:aws:s3:::<bucket>/*" not in object_statement["Resource"]


def test_application_settings_and_client_have_no_legacy_root_fallback() -> None:
    config_path = REPOSITORY_ROOT / "backend" / "app" / "core" / "config.py"
    storage_path = REPOSITORY_ROOT / "backend" / "app" / "utils" / "storage.py"
    config_source = config_path.read_text(encoding="utf-8")
    storage_source = storage_path.read_text(encoding="utf-8")
    ast.parse(config_source)
    ast.parse(storage_source)

    assert "MINIO_ACCESS_KEY" in config_source
    assert "MINIO_SECRET_KEY" in config_source
    assert "MINIO_ROOT_USER" not in config_source
    assert "MINIO_ROOT_PASSWORD" not in config_source
    assert "settings.MINIO_ACCESS_KEY" in storage_source
    assert "settings.MINIO_SECRET_KEY" in storage_source
    assert ".bucket_exists(" not in storage_source
    assert ".make_bucket(" not in storage_source


def test_nginx_minio_proxy_preserves_native_range_contract() -> None:
    proxy_source = (REPOSITORY_ROOT / "proxy" / "nginx.conf").read_text(
        encoding="utf-8"
    )
    minio_location = proxy_source.split("location /minio/ {", 1)[1].split(
        "\n        }", 1
    )[0]

    assert "proxy_pass http://minio:9000/;" in minio_location
    assert "proxy_pass_request_headers on;" in minio_location
    assert "proxy_set_header Range \"\";" not in minio_location
    assert "Content-Length,Content-Range" in minio_location


def test_compose_keeps_root_only_on_server_and_scoped_backend_contract() -> None:
    production = (
        REPOSITORY_ROOT / "docker" / "docker-compose.prod.yml"
    ).read_text(encoding="utf-8")
    development = (
        REPOSITORY_ROOT / "docker" / "docker-compose.dev.yml"
    ).read_text(encoding="utf-8")

    assert "MINIO_ROOT_USER=${MINIO_ROOT_USER}" in production
    assert "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}" in production
    assert "MINIO_ACCESS_KEY" in development
    assert "MINIO_SECRET_KEY" in development
    assert "sed " not in development
    assert "policy_line//<bucket>" in development


def test_rollback_policy_grants_only_legacy_head_bucket() -> None:
    policy = _policy(ROLLBACK_POLICY)
    assert _actions(policy) == {"s3:ListBucket"}
    assert policy["Statement"][0]["Resource"] == "arn:aws:s3:::<bucket>"


@pytest.mark.parametrize(
    "forbidden",
    [
        "s3:DeleteBucket",
        "s3:PutBucketPolicy",
        "s3:PutLifecycleConfiguration",
        "s3:PutBucketVersioning",
        "s3:PutBucketObjectLockConfiguration",
    ],
)
def test_application_policy_has_no_control_plane_grant(forbidden: str) -> None:
    assert forbidden not in _actions(_policy(APPLICATION_POLICY))
