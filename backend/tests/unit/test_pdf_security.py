import asyncio
import io
import os
import sys
from pathlib import Path

import pikepdf
import pytest
from fastapi import UploadFile

from app.services import pdf_security
from app.services.pdf_security import PdfValidationError, _PdfPolicyViolation


def _pdf_path(tmp_path: Path, *, pages: int = 1) -> Path:
    path = tmp_path / "fixture.pdf"
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    pdf.save(path)
    return path


def _save_mutated_pdf(tmp_path: Path, mutate) -> Path:
    path = tmp_path / "mutated.pdf"
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page()
    mutate(pdf, page)
    pdf.save(path)
    return path


def _assert_rejected(path: Path, code: str) -> None:
    with pytest.raises(_PdfPolicyViolation) as error:
        pdf_security._inspect_pdf(path)
    assert error.value.code == code


def test_valid_pdf_and_explicit_uri_are_allowed(tmp_path: Path) -> None:
    def add_uri(pdf, page):
        action = pikepdf.Dictionary(S=pikepdf.Name.URI, URI="https://example.invalid")
        annotation = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 10, 10]),
            A=action,
        )
        page.obj.Annots = pikepdf.Array([pdf.make_indirect(annotation)])

    path = _save_mutated_pdf(tmp_path, add_uri)
    result = pdf_security._inspect_pdf(path)
    assert result["pages"] == 1
    assert result["objects"] > 0
    assert result["pikepdf_version"] == "10.12.0"
    assert result["qpdf_version"] == "12.3.2"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda pdf, _page: setattr(
            pdf.Root,
            "OpenAction",
            pikepdf.Dictionary(S=pikepdf.Name.URI, URI="https://example.invalid"),
        ),
        lambda pdf, page: setattr(
            page.obj,
            "Annots",
            pikepdf.Array(
                [
                    pdf.make_indirect(
                        pikepdf.Dictionary(
                            Type=pikepdf.Name.Annot,
                            Subtype=pikepdf.Name.Link,
                            Rect=pikepdf.Array([0, 0, 10, 10]),
                            A=pikepdf.Dictionary(
                                S=pikepdf.Name.JavaScript, JS="app.alert('x')"
                            ),
                        )
                    )
                ]
            ),
        ),
        lambda pdf, _page: setattr(
            pdf.Root,
            "AA",
            pikepdf.Dictionary(
                O=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS="noop")
            ),
        ),
        lambda pdf, _page: setattr(
            pdf.Root,
            "Names",
            pikepdf.Dictionary(EmbeddedFiles=pikepdf.Dictionary(Names=pikepdf.Array())),
        ),
        lambda pdf, _page: setattr(
            pdf.Root,
            "AcroForm",
            pikepdf.Dictionary(Fields=pikepdf.Array()),
        ),
        lambda pdf, _page: setattr(pdf.Root, "XFA", pikepdf.String("xfa")),
        lambda pdf, page: setattr(
            page.obj,
            "Annots",
            pikepdf.Array(
                [
                    pdf.make_indirect(
                        pikepdf.Dictionary(
                            Type=pikepdf.Name.Annot,
                            Subtype=pikepdf.Name.FileAttachment,
                            Rect=pikepdf.Array([0, 0, 10, 10]),
                        )
                    )
                ]
            ),
        ),
        lambda pdf, page: setattr(
            page.obj,
            "Annots",
            pikepdf.Array(
                [
                    pdf.make_indirect(
                        pikepdf.Dictionary(
                            Type=pikepdf.Name.Annot,
                            Subtype=pikepdf.Name.Link,
                            Rect=pikepdf.Array([0, 0, 10, 10]),
                            A=pikepdf.Dictionary(
                                S=pikepdf.Name.Launch, F="external"
                            ),
                        )
                    )
                ]
            ),
        ),
    ],
    ids=[
        "open-action",
        "javascript",
        "additional-action",
        "embedded-files",
        "acroform",
        "xfa",
        "file-attachment",
        "launch",
    ],
)
def test_forbidden_active_and_embedded_features_are_rejected(
    tmp_path: Path, mutate
) -> None:
    _assert_rejected(_save_mutated_pdf(tmp_path, mutate), "forbidden_feature")


def test_encrypted_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(
        path,
        encryption=pikepdf.Encryption(owner="owner", user="user", R=6),
    )
    _assert_rejected(path, "encrypted")


def test_invalid_and_recovery_required_pdfs_are_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"%PDF-not-a-document")
    _assert_rejected(invalid, "invalid_pdf")

    recoverable = _pdf_path(tmp_path)
    payload = recoverable.read_bytes()
    marker = payload.rfind(b"startxref\n")
    assert marker > 0
    number_start = marker + len(b"startxref\n")
    number_end = payload.find(b"\n", number_start)
    recoverable.write_bytes(payload[:number_start] + b"0" + payload[number_end:])
    with pikepdf.open(recoverable):
        pass
    _assert_rejected(recoverable, "invalid_pdf")


def test_page_and_object_limits_are_enforced_with_small_test_thresholds(
    tmp_path: Path,
) -> None:
    path = _pdf_path(tmp_path, pages=2)
    with pytest.raises(_PdfPolicyViolation, match="page_limit"):
        pdf_security._inspect_pdf(path, max_pages=1)
    with pytest.raises(_PdfPolicyViolation, match="object_limit"):
        pdf_security._inspect_pdf(path, max_objects=1)


def test_syntax_warning_policy_rejects_even_when_open_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    class WarningPdf:
        is_encrypted = False

        def __init__(self) -> None:
            self.pages = [object()]
            self.objects = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def check_pdf_syntax(self):
            return ["synthetic syntax warning"]

        def get_warnings(self):
            return []

    monkeypatch.setattr(pikepdf, "open", lambda *_args, **_kwargs: WarningPdf())
    with pytest.raises(_PdfPolicyViolation) as error:
        pdf_security._inspect_pdf(tmp_path / "synthetic.pdf")
    assert error.value.code == "syntax_warning"


def test_production_page_limit_accepts_a_200_page_pdf(tmp_path: Path) -> None:
    path = _pdf_path(tmp_path, pages=pdf_security.MAX_PDF_PAGES)
    assert pdf_security._inspect_pdf(path)["pages"] == 200


@pytest.mark.asyncio
async def test_staging_rejects_extension_size_and_header_without_leaking_temp_files(
    monkeypatch, tmp_path: Path
) -> None:
    paths: list[Path] = []

    def controlled_mkstemp(**_kwargs):
        path = tmp_path / f"staged-{len(paths)}.pdf"
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        paths.append(path)
        return descriptor, os.fspath(path)

    monkeypatch.setattr(pdf_security.tempfile, "mkstemp", controlled_mkstemp)

    with pytest.raises(PdfValidationError, match="wrong_extension"):
        await pdf_security.stage_pdf_upload(
            UploadFile(filename="exam.txt", file=io.BytesIO(b"%PDF-"), size=5)
        )
    assert paths == []

    with pytest.raises(PdfValidationError, match="file_too_large"):
        await pdf_security.stage_pdf_upload(
            UploadFile(
                filename="exam.pdf",
                file=io.BytesIO(b"%PDF-"),
                size=pdf_security.MAX_PDF_BYTES + 1,
            )
        )
    assert paths == []

    with pytest.raises(PdfValidationError, match="invalid_pdf"):
        await pdf_security.stage_pdf_upload(
            UploadFile(filename="exam.pdf", file=io.BytesIO(b"not-pdf"))
        )
    assert paths and all(not path.exists() for path in paths)


@pytest.mark.asyncio
async def test_chunked_copy_enforces_limit_when_upload_size_is_unknown(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pdf_security, "MAX_PDF_BYTES", 8)
    monkeypatch.setattr(pdf_security, "_COPY_CHUNK_BYTES", 4)
    path = tmp_path / "bounded.pdf"
    monkeypatch.setattr(
        pdf_security.tempfile,
        "mkstemp",
        lambda **_kwargs: (
            os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600),
            os.fspath(path),
        ),
    )

    with pytest.raises(PdfValidationError, match="file_too_large"):
        await pdf_security.stage_pdf_upload(
            UploadFile(filename="exam.pdf", file=io.BytesIO(b"%PDF-1234"))
        )
    assert not path.exists()


@pytest.mark.asyncio
async def test_validated_context_removes_temp_file_on_success_and_failure(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "context.pdf"

    async def fake_stage(_upload):
        path.write_bytes(b"%PDF-")
        return pdf_security.StagedPdf(path=path, size=5)

    async def accept(_path):
        return None

    monkeypatch.setattr(pdf_security, "stage_pdf_upload", fake_stage)
    monkeypatch.setattr(pdf_security, "validate_staged_pdf", accept)
    async with pdf_security.validated_pdf_upload(object()) as staged:
        assert staged.path.exists()
    assert not path.exists()

    async def reject(_path):
        raise PdfValidationError("invalid_pdf", "Invalid or unsupported PDF file")

    monkeypatch.setattr(pdf_security, "validate_staged_pdf", reject)
    with pytest.raises(PdfValidationError):
        async with pdf_security.validated_pdf_upload(object()):
            pass
    assert not path.exists()


@pytest.mark.asyncio
async def test_helper_timeout_is_sanitized_and_process_is_reaped(tmp_path: Path) -> None:
    path = _pdf_path(tmp_path)
    with pytest.raises(PdfValidationError) as error:
        await pdf_security.validate_staged_pdf(
            path,
            timeout_seconds=0.05,
            command=[sys.executable, "-c", "import time; time.sleep(5)"],
        )
    assert error.value.code == "validation_timeout"
    assert error.value.public_detail == "Invalid or unsupported PDF file"


@pytest.mark.asyncio
async def test_malformed_helper_result_is_sanitized(tmp_path: Path) -> None:
    with pytest.raises(PdfValidationError) as error:
        await pdf_security.validate_staged_pdf(
            _pdf_path(tmp_path),
            command=[sys.executable, "-c", "print('not-json')"],
        )
    assert error.value.code == "helper_failure"
    assert error.value.public_detail == "Invalid or unsupported PDF file"


@pytest.mark.asyncio
async def test_real_helper_reports_platform_resource_boundary(tmp_path: Path) -> None:
    report = await pdf_security.validate_staged_pdf(_pdf_path(tmp_path))
    expected_linux = sys.platform.startswith("linux")
    assert report.memory_limit_applied is expected_linux
    assert report.global_lock_applied is expected_linux


@pytest.mark.asyncio
async def test_high_structure_pdf_remains_inside_real_helper_boundary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "structured.pdf"
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.Root.SecurityStructureTest = pikepdf.Array(
        [pdf.make_indirect(pikepdf.Dictionary(Index=index)) for index in range(500)]
    )
    pdf.save(path)

    report = await pdf_security.validate_staged_pdf(path)
    assert report.objects >= 500
    assert report.pages == 1


@pytest.mark.asyncio
async def test_one_helper_at_a_time_per_worker(monkeypatch, tmp_path: Path) -> None:
    active = 0
    maximum_active = 0
    helper_result = (
        b'{"status":"ok","pages":1,"objects":4,'
        b'"pikepdf_version":"10.12.0","qpdf_version":"12.3.2",'
        b'"memory_limit_applied":false,"global_lock_applied":false}'
    )

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            return helper_result, b""

    async def create_process(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    path = _pdf_path(tmp_path)
    await asyncio.gather(
        pdf_security.validate_staged_pdf(path),
        pdf_security.validate_staged_pdf(path),
    )
    assert maximum_active == 1
