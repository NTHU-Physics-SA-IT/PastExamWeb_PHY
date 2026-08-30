from datetime import timedelta

from app.utils import storage


class FakeMinio:
    def presigned_get_object(self, bucket_name, object_name, expires):
        return (
            f"http://{storage.settings.MINIO_ENDPOINT}/{bucket_name}/"
            f"{object_name}?expires={int(expires.total_seconds())}"
        )


def test_get_minio_client_uses_scoped_credentials_without_provisioning(monkeypatch):
    fake = FakeMinio()
    captured = {}
    monkeypatch.setattr(storage, "_minio_client", None)

    def construct(*args, **kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr(storage, "Minio", construct)

    client = storage.get_minio_client()
    assert client is fake
    assert captured == {
        "endpoint": storage.settings.MINIO_ENDPOINT,
        "access_key": storage.settings.MINIO_ACCESS_KEY,
        "secret_key": storage.settings.MINIO_SECRET_KEY,
        "secure": False,
    }
    assert not hasattr(fake, "bucket_exists")
    assert not hasattr(fake, "make_bucket")


def test_presigned_get_url_rewrites_endpoint(monkeypatch):
    fake = FakeMinio()
    monkeypatch.setattr(storage, "_minio_client", fake)

    url = storage.presigned_get_url(
        "path/to/file.pdf",
        expires=timedelta(minutes=10),
    )
    assert url.startswith(storage.settings.EXTERNAL_ENDPOINT)
    assert "path/to/file.pdf" in url
