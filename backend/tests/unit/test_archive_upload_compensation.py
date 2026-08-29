import inspect

import pytest

from app.api.services import archives


class RecordingMinio:
    def __init__(self, *, remove_error: Exception | None = None) -> None:
        self.removed: list[tuple[str, str]] = []
        self.remove_error = remove_error

    def remove_object(self, bucket: str, object_name: str) -> None:
        if self.remove_error is not None:
            raise self.remove_error
        self.removed.append((bucket, object_name))


@pytest.mark.asyncio
async def test_zero_committed_references_remove_only_the_exact_new_object(
    monkeypatch,
) -> None:
    client = RecordingMinio()

    async def no_references(_object_name: str) -> int:
        return 0

    monkeypatch.setattr(archives, "_committed_upload_reference_count", no_references)
    await archives._compensate_failed_upload("archive-submissions/1/new.pdf", client)

    assert client.removed == [
        (archives.settings.MINIO_BUCKET_NAME, "archive-submissions/1/new.pdf")
    ]


@pytest.mark.asyncio
async def test_committed_reference_retains_object(monkeypatch) -> None:
    client = RecordingMinio()

    async def one_reference(_object_name: str) -> int:
        return 1

    monkeypatch.setattr(archives, "_committed_upload_reference_count", one_reference)
    await archives._compensate_failed_upload("archives/1/new.pdf", client)
    assert client.removed == []


@pytest.mark.asyncio
async def test_uncertain_database_authority_retains_object(monkeypatch, caplog) -> None:
    client = RecordingMinio()

    async def unavailable(_object_name: str) -> int:
        raise RuntimeError("sensitive database detail")

    monkeypatch.setattr(archives, "_committed_upload_reference_count", unavailable)
    await archives._compensate_failed_upload("archives/1/new.pdf", client)

    assert client.removed == []
    assert "fresh database authority unavailable (RuntimeError)" in caplog.text
    assert "sensitive database detail" not in caplog.text
    assert "archives/1/new.pdf" not in caplog.text


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_replace_original_failure(
    monkeypatch, caplog
) -> None:
    client = RecordingMinio(remove_error=RuntimeError("sensitive storage detail"))

    async def no_references(_object_name: str) -> int:
        return 0

    monkeypatch.setattr(archives, "_committed_upload_reference_count", no_references)
    await archives._compensate_failed_upload("archives/1/new.pdf", client)

    assert "could not remove unreferenced object (RuntimeError)" in caplog.text
    assert "sensitive storage detail" not in caplog.text
    assert "archives/1/new.pdf" not in caplog.text


def test_upload_route_has_no_whole_file_read_or_bytesio_copy() -> None:
    source = inspect.getsource(archives.upload_archive)
    assert "await file.read()" not in source
    assert "BytesIO" not in source
    assert "validated_pdf_upload(file)" in source
