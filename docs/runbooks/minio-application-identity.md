# MinIO application identity

Status: Active

Source of truth for: SEC-04 application identity, production cutover stop gate,
and retained-release rollback

## Authority split

MinIO root credentials remain infrastructure/control-plane authority and stay
only in the MinIO server/operator configuration. The backend uses a child
access key under a dedicated non-root parent user. The parent owns the exact
policy in `docker/minio/application-policy.template.json`; its credential is
operator-controlled and is never stored in `backend.env`.

The backend requires `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`. It does not
accept the legacy root-named variables and never provisions a bucket. The
bucket-wide orphan audit/cleanup requires separate
`MINIO_OPERATOR_ACCESS_KEY` and `MINIO_OPERATOR_SECRET_KEY` values supplied
only to that explicit maintenance process. It never falls back to backend or
root credentials.

## Production cutover stop gate

Production activation remains blocked until a separately authorized operation
has enabled versioning on the existing application bucket. The activation
preflight is read-only and requires both an existing bucket and `Enabled`
versioning. It must never create the bucket or change versioning.

After source, PR, and main Full evidence and immutable candidate preparation:

1. complete the separately authorized bucket-versioning gate;
2. verify the bucket is private and no unexpected broad IAM authority exists;
3. create the exact application policy and dedicated non-root parent;
4. create a child application access key under that parent;
5. replace `backend.env` atomically with generic child credentials only;
6. verify real root and legacy root-named variables are absent from backend env;
7. leave the MinIO server root configuration unchanged;
8. run the read-only storage preflight and activate the candidate once;
9. compare backend and server-root credential pairs in memory; they must differ;
10. verify health and an authorized existing-object/presigned read, then observe.

No production write/delete probe, root rotation, bucket split, or historical
orphan cleanup is implied by this procedure.

## Retained-release rollback

The retained pre-SEC-04 release calls `bucket_exists`, which requires
bucket-wide `s3:ListBucket` on this MinIO release. That permission is excluded
from normal runtime and exists separately in
`docker/minio/rollback-list-bucket-policy.template.json`.

For an emergency rollback only:

1. attach the rollback-only policy to the non-root application parent;
2. temporarily set `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` to the same
   scoped child values (never the real root values);
3. activate the retained release; `CreateBucket` remains denied;
4. when returning to SEC-04, remove the legacy aliases; and
5. detach the rollback-only policy.

Do not make `ListBucket` permanent and do not rotate or inject root credentials
as part of routine rollback.
