import asyncio
import io
import logging
import os
import stat
import sys
import zlib
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


def _truncated_flate_pdf(tmp_path: Path, *, with_attachment: bool) -> Path:
    path = tmp_path / (
        "truncated-with-attachment.pdf"
        if with_attachment
        else "truncated-without-attachment.pdf"
    )
    content = b"q\n0 0 10 10 re\nS\nQ\n" * 32
    compressed = zlib.compress(content)[:-4]
    page_attachment = b" /AF [5 0 R]" if with_attachment else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
        b"/Contents 4 0 R /Resources << >>" + page_attachment + b" >>",
        b"<< /Length "
        + str(len(compressed)).encode("ascii")
        + b" /Filter /FlateDecode >>\nstream\n"
        + compressed
        + b"\nendstream",
    ]
    if with_attachment:
        embedded_payload = b"pastexam-synthetic-private-attachment"
        objects.extend(
            [
                b"<< /Type /Filespec /F (metadata.json) /EF << /F 6 0 R >> >>",
                b"<< /Type /EmbeddedFile /Length "
                + str(len(embedded_payload)).encode("ascii")
                + b" >>\nstream\n"
                + embedded_payload
                + b"\nendstream",
            ]
        )

    payload = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode("ascii"))
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(payload)
    return path


def _assert_rejected(path: Path, code: str) -> None:
    with pytest.raises(_PdfPolicyViolation) as error:
        pdf_security._inspect_pdf(path)
    assert error.value.code == code


def _inspection() -> pdf_security.PdfInspection:
    return pdf_security.PdfInspection(
        pages=1,
        objects=4,
        pikepdf_version=pikepdf.__version__,
        qpdf_version=pikepdf.__libqpdf_version__,
        memory_limit_applied=False,
        global_lock_applied=False,
    )


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


def _add_safe_catalog_fit_open_destination(pdf, page) -> None:
    pdf.Root.OpenAction = pikepdf.Array([page.obj, pikepdf.Name.Fit])


def test_catalog_same_document_fit_open_destination_is_allowed(
    tmp_path: Path,
) -> None:
    path = _save_mutated_pdf(tmp_path, _add_safe_catalog_fit_open_destination)

    classification = pdf_security._classify_pdf(path)

    assert classification["disposition"] == "pass"
    assert pdf_security._inspect_pdf(path)["pages"] == 1


@pytest.mark.parametrize(
    "case",
    [
        "javascript-action",
        "launch-action",
        "goto-action",
        "named-destination",
        "string-destination",
        "empty-array",
        "short-array",
        "indirect-array",
        "fit-h-array",
        "xyz-array",
        "non-page-tree-object",
        "non-catalog-owner",
        "safe-plus-additional-action",
    ],
)
def test_other_open_action_forms_remain_fatal(tmp_path: Path, case: str) -> None:
    def mutate(pdf, page) -> None:
        same_page_fit = pikepdf.Array([page.obj, pikepdf.Name.Fit])
        if case == "javascript-action":
            pdf.Root.OpenAction = pikepdf.Dictionary(
                S=pikepdf.Name.JavaScript,
                JS="noop",
            )
        elif case == "launch-action":
            pdf.Root.OpenAction = pikepdf.Dictionary(
                S=pikepdf.Name.Launch,
                F="external",
            )
        elif case == "goto-action":
            pdf.Root.OpenAction = pikepdf.Dictionary(
                S=pikepdf.Name.GoTo,
                D=same_page_fit,
            )
        elif case == "named-destination":
            pdf.Root.OpenAction = pikepdf.Name("/Start")
        elif case == "string-destination":
            pdf.Root.OpenAction = pikepdf.String("Start")
        elif case == "empty-array":
            pdf.Root.OpenAction = pikepdf.Array()
        elif case == "short-array":
            pdf.Root.OpenAction = pikepdf.Array([page.obj])
        elif case == "indirect-array":
            pdf.Root.OpenAction = pdf.make_indirect(same_page_fit)
        elif case == "fit-h-array":
            pdf.Root.OpenAction = pikepdf.Array(
                [page.obj, pikepdf.Name.FitH, 0]
            )
        elif case == "xyz-array":
            pdf.Root.OpenAction = pikepdf.Array(
                [page.obj, pikepdf.Name.XYZ, 0, 0, 1]
            )
        elif case == "non-page-tree-object":
            fake_page = pdf.make_indirect(
                pikepdf.Dictionary(Type=pikepdf.Name.Page)
            )
            pdf.Root.OpenAction = pikepdf.Array([fake_page, pikepdf.Name.Fit])
        elif case == "non-catalog-owner":
            page.obj.OpenAction = same_page_fit
        elif case == "safe-plus-additional-action":
            pdf.Root.OpenAction = same_page_fit
            pdf.Root.AA = pikepdf.Dictionary(
                O=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS="noop")
            )
        else:  # pragma: no cover - the parameter list is closed above
            raise AssertionError(f"unhandled test case: {case}")

    _assert_rejected(_save_mutated_pdf(tmp_path, mutate), "forbidden_feature")


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
                            A=pikepdf.Dictionary(S=pikepdf.Name.Launch, F="external"),
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
                            Subtype=pikepdf.Name.RichMedia,
                            Rect=pikepdf.Array([0, 0, 10, 10]),
                        )
                    )
                ]
            ),
        ),
        lambda pdf, _page: setattr(
            pdf.Root,
            "OpenAction",
            pikepdf.Dictionary(S=pikepdf.Name.GoToR, F="external.pdf"),
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
        "multimedia",
        "external-action",
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


def test_minimized_flate_fixture_matches_only_the_pinned_incident_condition(
    tmp_path: Path,
) -> None:
    path = _truncated_flate_pdf(tmp_path, with_attachment=False)
    with pikepdf.open(path, attempt_recovery=False) as pdf:
        issues = list(pdf.check_pdf_syntax()) + list(pdf.get_warnings())

    assert pikepdf.__version__ == pdf_security._SUPPORTED_PIKEPDF_VERSION
    assert pikepdf.__libqpdf_version__ == pdf_security._SUPPORTED_QPDF_VERSION
    assert pdf_security._normalized_parser_findings(
        issues,
        pikepdf_version=pikepdf.__version__,
        qpdf_version=pikepdf.__libqpdf_version__,
    ) == {"flate_incomplete_termination"}
    assert (
        pdf_security._normalized_parser_findings(
            issues,
            pikepdf_version="10.12.1",
            qpdf_version=pikepdf.__libqpdf_version__,
        )
        is None
    )
    _assert_rejected(path, "syntax_warning")


def test_only_removable_attachment_findings_can_make_incident_flate_sanitizable(
    tmp_path: Path,
) -> None:
    combined = pdf_security._classify_pdf(
        _truncated_flate_pdf(tmp_path, with_attachment=True)
    )
    assert combined["disposition"] == "sanitizable"
    assert combined["findings"] == [
        "embedded_files",
        "flate_incomplete_termination",
    ]

    def add_javascript(pdf, page):
        page.obj.Annots = pikepdf.Array(
            [
                pdf.make_indirect(
                    pikepdf.Dictionary(
                        Type=pikepdf.Name.Annot,
                        Subtype=pikepdf.Name.Link,
                        Rect=pikepdf.Array([0, 0, 10, 10]),
                        A=pikepdf.Dictionary(
                            S=pikepdf.Name.JavaScript,
                            JS="app.alert('x')",
                        ),
                    )
                )
            ]
        )
        pdf.attachments["metadata.json"] = b"{}"

    _assert_rejected(
        _save_mutated_pdf(tmp_path, add_javascript),
        "forbidden_feature",
    )


def test_ambiguous_attachment_graph_and_arbitrary_forms_remain_fatal(
    tmp_path: Path,
) -> None:
    def add_orphan_embedded_file(pdf, _page):
        stream = pdf.make_stream(b"private")
        stream.Type = pikepdf.Name.EmbeddedFile
        pdf.Root.Orphan = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Filespec,
                F="orphan.bin",
                EF=pikepdf.Dictionary(F=stream),
            )
        )

    ambiguous = _save_mutated_pdf(tmp_path, add_orphan_embedded_file)
    _assert_rejected(ambiguous, "forbidden_feature")

    def add_signature_form(pdf, _page):
        signature_field = pdf.make_indirect(
            pikepdf.Dictionary(FT=pikepdf.Name.Sig, T="Signature1")
        )
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([signature_field]))
        pdf.attachments["metadata.json"] = b"{}"

    signature_form = _save_mutated_pdf(tmp_path, add_signature_form)
    _assert_rejected(signature_form, "forbidden_feature")


def test_detached_signature_marker_does_not_broaden_acroform_policy(
    tmp_path: Path,
) -> None:
    def add_detached_signature_and_attachment(pdf, _page):
        pdf.Root.SignatureMetadata = pdf.make_indirect(
            pikepdf.Dictionary(Type=pikepdf.Name.Sig)
        )
        pdf.attachments["metadata.json"] = b"{}"

    source = _save_mutated_pdf(tmp_path, add_detached_signature_and_attachment)
    classified = pdf_security._classify_pdf(source)
    assert classified["findings"] == ["embedded_files", "signature_present"]
    destination = tmp_path / "signature-normalized.pdf"
    pdf_security._sanitize_pdf(source, destination)
    assert pdf_security._inspect_pdf(destination)["pages"] == 1


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

    async def accept(_path, *, deadline):
        assert deadline > 0
        return pdf_security.PdfClassification(
            disposition=pdf_security.PdfDisposition.PASS,
            inspection=_inspection(),
        )

    monkeypatch.setattr(pdf_security, "stage_pdf_upload", fake_stage)
    monkeypatch.setattr(pdf_security, "inspect_staged_pdf", accept)
    async with pdf_security.validated_pdf_upload(object()) as staged:
        assert staged.path.exists()
        assert staged.path.read_bytes() == b"%PDF-"
    assert not path.exists()

    async def reject(_path, *, deadline):
        assert deadline > 0
        raise PdfValidationError("invalid_pdf", "Invalid or unsupported PDF file")

    monkeypatch.setattr(pdf_security, "inspect_staged_pdf", reject)
    with pytest.raises(PdfValidationError):
        async with pdf_security.validated_pdf_upload(object()):
            pass
    assert not path.exists()


@pytest.mark.asyncio
async def test_valid_pdf_fast_path_never_calls_sanitizer_and_preserves_bytes(
    monkeypatch, tmp_path: Path
) -> None:
    source = _pdf_path(tmp_path)
    original = source.read_bytes()

    async def sanitizer_must_not_run(*_args, **_kwargs):
        raise AssertionError("sanitizer called for a valid PDF")

    monkeypatch.setattr(pdf_security, "sanitize_staged_pdf", sanitizer_must_not_run)
    monkeypatch.setattr(pdf_security, "validate_staged_pdf", sanitizer_must_not_run)
    upload = UploadFile(
        filename="valid.pdf",
        file=io.BytesIO(original),
        size=len(original),
    )
    candidate_path = None
    async with pdf_security.validated_pdf_upload(upload) as candidate:
        candidate_path = candidate.path
        assert candidate.path.read_bytes() == original
        assert candidate.size == len(original)
    assert candidate_path is not None and not candidate_path.exists()


@pytest.mark.asyncio
async def test_catalog_fit_open_destination_uses_byte_identical_fast_path(
    monkeypatch, tmp_path: Path
) -> None:
    source = _save_mutated_pdf(tmp_path, _add_safe_catalog_fit_open_destination)
    original = source.read_bytes()

    async def fallback_must_not_run(*_args, **_kwargs):
        raise AssertionError("fallback called for a safe open destination")

    monkeypatch.setattr(pdf_security, "sanitize_staged_pdf", fallback_must_not_run)
    monkeypatch.setattr(pdf_security, "validate_staged_pdf", fallback_must_not_run)
    upload = UploadFile(
        filename="safe-fit.pdf",
        file=io.BytesIO(original),
        size=len(original),
    )

    async with pdf_security.validated_pdf_upload(upload) as candidate:
        assert candidate.path.read_bytes() == original
        assert candidate.size == len(original)


@pytest.mark.asyncio
async def test_combined_fallback_sanitizes_once_and_strictly_revalidates(
    caplog, monkeypatch, tmp_path: Path
) -> None:
    # Alembic's logging configuration disables existing application loggers
    # when this test runs as part of the complete backend shard.
    monkeypatch.setattr(pdf_security.logger, "disabled", False)
    monkeypatch.setattr(pdf_security.logger, "propagate", True)
    source = _truncated_flate_pdf(tmp_path, with_attachment=True)
    original = source.read_bytes()
    upload = UploadFile(
        filename="scanner.pdf",
        file=io.BytesIO(original),
        size=len(original),
    )
    candidate_path = None
    with caplog.at_level(logging.INFO, logger=pdf_security.logger.name):
        async with pdf_security.validated_pdf_upload(upload) as candidate:
            candidate_path = candidate.path
            output = candidate.path.read_bytes()
            assert candidate.size == len(output)
            assert output != original
            assert stat.S_IMODE(candidate.path.stat().st_mode) == 0o600
            assert b"pastexam-synthetic-private-attachment" not in output
            assert pdf_security._inspect_pdf(candidate.path)["pages"] == 1
            with pikepdf.open(candidate.path, attempt_recovery=False) as pdf:
                assert not pdf.attachments
                assert not pdf_security._find_forbidden_features(pdf, pikepdf)
    assert candidate_path is not None and not candidate_path.exists()
    event_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) is not None
    ]
    events = [record.event for record in event_records]
    assert events == [
        "pdf_sanitization_candidate",
        "pdf_sanitization_started",
        "pdf_sanitization_succeeded",
    ]
    candidate_record = event_records[0]
    assert candidate_record.finding == ("embedded_files+flate_incomplete_termination")
    assert "scanner.pdf" not in caplog.text
    assert "pastexam-synthetic-private-attachment" not in caplog.text


def test_file_attachment_annotation_is_removed_by_sanitizer(tmp_path: Path) -> None:
    def add_file_attachment(pdf, page):
        pdf.attachments["metadata.json"] = b"private"
        file_spec = pdf.attachments["metadata.json"].obj
        page.obj.Annots = pikepdf.Array(
            [
                pdf.make_indirect(
                    pikepdf.Dictionary(
                        Type=pikepdf.Name.Annot,
                        Subtype=pikepdf.Name.FileAttachment,
                        Rect=pikepdf.Array([0, 0, 10, 10]),
                        FS=file_spec,
                    )
                )
            ]
        )

    source = _save_mutated_pdf(tmp_path, add_file_attachment)
    classified = pdf_security._classify_pdf(source)
    assert classified["findings"] == ["embedded_files", "file_attachment"]
    destination = tmp_path / "sanitized.pdf"
    pdf_security._sanitize_pdf(source, destination)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert pdf_security._inspect_pdf(destination)["pages"] == 1
    with pikepdf.open(destination, attempt_recovery=False) as pdf:
        assert "/Annots" not in pdf.pages[0].obj


def test_each_partial_rewrite_still_fails_the_unchanged_strict_policy(
    tmp_path: Path,
) -> None:
    from pikepdf.sanitize import remove_attachments

    source = _truncated_flate_pdf(tmp_path, with_attachment=True)
    attachments_only = tmp_path / "attachments-only.pdf"
    with pikepdf.open(source, attempt_recovery=False) as pdf:
        remove_attachments(pdf)
        pdf.save(attachments_only)
    _assert_rejected(attachments_only, "syntax_warning")

    flate_only = tmp_path / "flate-only.pdf"
    with pikepdf.open(source, attempt_recovery=False) as pdf:
        pdf.save(flate_only, recompress_flate=True)
    _assert_rejected(flate_only, "forbidden_feature")


@pytest.mark.asyncio
async def test_fallback_uses_one_shared_deadline_and_one_sanitizer_attempt(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-source")
    sanitized_path = tmp_path / "sanitized.pdf"
    deadlines: list[float] = []
    sanitizer_calls = 0

    async def fake_stage(_upload):
        return pdf_security.StagedPdf(path=source, size=source.stat().st_size)

    async def candidate(_path, *, deadline):
        deadlines.append(deadline)
        return pdf_security.PdfClassification(
            disposition=pdf_security.PdfDisposition.SANITIZABLE,
            inspection=_inspection(),
            findings=("embedded_files",),
        )

    async def sanitize(_path, *, deadline):
        nonlocal sanitizer_calls
        sanitizer_calls += 1
        deadlines.append(deadline)
        sanitized_path.write_bytes(b"%PDF-sanitized")
        return pdf_security.StagedPdf(
            path=sanitized_path,
            size=sanitized_path.stat().st_size,
        )

    async def reject_final(_path, *, deadline, **_kwargs):
        deadlines.append(deadline)
        raise PdfValidationError("syntax_warning", "Invalid or unsupported PDF file")

    monkeypatch.setattr(pdf_security, "stage_pdf_upload", fake_stage)
    monkeypatch.setattr(pdf_security, "inspect_staged_pdf", candidate)
    monkeypatch.setattr(pdf_security, "sanitize_staged_pdf", sanitize)
    monkeypatch.setattr(pdf_security, "validate_staged_pdf", reject_final)

    with pytest.raises(PdfValidationError, match="post_sanitization_rejected"):
        async with pdf_security.validated_pdf_upload(object()):
            pass
    assert sanitizer_calls == 1
    assert len(set(deadlines)) == 1
    assert not source.exists()
    assert not sanitized_path.exists()


@pytest.mark.asyncio
async def test_insufficient_shared_deadline_rejects_before_sanitizer(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-source")

    async def fake_stage(_upload):
        return pdf_security.StagedPdf(path=source, size=source.stat().st_size)

    async def candidate(_path, *, deadline):
        return pdf_security.PdfClassification(
            disposition=pdf_security.PdfDisposition.SANITIZABLE,
            inspection=_inspection(),
            findings=("embedded_files",),
        )

    async def sanitizer_must_not_run(*_args, **_kwargs):
        raise AssertionError("sanitizer ran without enough shared deadline")

    monkeypatch.setattr(pdf_security, "stage_pdf_upload", fake_stage)
    monkeypatch.setattr(pdf_security, "inspect_staged_pdf", candidate)
    monkeypatch.setattr(pdf_security, "sanitize_staged_pdf", sanitizer_must_not_run)
    monkeypatch.setattr(
        pdf_security,
        "PDF_FALLBACK_MIN_REMAINING_SECONDS",
        pdf_security.PDF_VALIDATION_TIMEOUT_SECONDS + 1,
    )

    with pytest.raises(PdfValidationError, match="fallback_deadline_exhausted"):
        async with pdf_security.validated_pdf_upload(object()):
            pass
    assert not source.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("helper_code", "expected_code"),
    [
        ("validation_timeout", "sanitizer_timeout"),
        ("helper_failure", "sanitizer_failure"),
    ],
)
async def test_sanitizer_failures_are_bounded_and_cleaned(
    monkeypatch, tmp_path: Path, helper_code: str, expected_code: str
) -> None:
    destination = tmp_path / "bounded-output.pdf"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-source")

    monkeypatch.setattr(
        pdf_security.tempfile,
        "mkstemp",
        lambda **_kwargs: (
            os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600),
            os.fspath(destination),
        ),
    )

    async def fail(*_args, **_kwargs):
        raise PdfValidationError(helper_code, "Invalid or unsupported PDF file")

    monkeypatch.setattr(pdf_security, "_run_helper_command", fail)
    with pytest.raises(PdfValidationError, match=expected_code):
        await pdf_security.sanitize_staged_pdf(
            source,
            deadline=asyncio.get_running_loop().time() + 10,
        )
    assert not destination.exists()


@pytest.mark.asyncio
async def test_sanitizer_cancellation_cleans_partial_output(
    monkeypatch, tmp_path: Path
) -> None:
    destination = tmp_path / "cancelled-output.pdf"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-source")
    monkeypatch.setattr(
        pdf_security.tempfile,
        "mkstemp",
        lambda **_kwargs: (
            os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600),
            os.fspath(destination),
        ),
    )

    async def cancel(*_args, **_kwargs):
        destination.write_bytes(b"partial")
        raise asyncio.CancelledError

    monkeypatch.setattr(pdf_security, "_run_helper_command", cancel)
    with pytest.raises(asyncio.CancelledError):
        await pdf_security.sanitize_staged_pdf(
            source,
            deadline=asyncio.get_running_loop().time() + 10,
        )
    assert not destination.exists()


def test_global_sanitizer_admission_is_non_blocking(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pdf_security.sys, "platform", "linux-test")
    monkeypatch.setattr(
        pdf_security,
        "_LINUX_SANITIZER_ADMISSION_PATH",
        os.fspath(tmp_path / "sanitizer.lock"),
    )
    with (
        pdf_security._global_sanitizer_admission() as first,
        pdf_security._global_sanitizer_admission() as second,
    ):
        assert first is True
        assert second is False


def test_sanitizer_limits_keep_approved_memory_output_and_cpu_bounds(
    monkeypatch,
) -> None:
    import resource

    applied: dict[int, tuple[int, int]] = {}
    monkeypatch.setattr(pdf_security.sys, "platform", "linux-test")
    monkeypatch.setattr(
        resource,
        "getrlimit",
        lambda _kind: (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
    )
    monkeypatch.setattr(
        resource,
        "setrlimit",
        lambda kind, limits: applied.__setitem__(kind, limits),
    )

    assert pdf_security._apply_sanitizer_limits() == (True, True, True)
    memory_bytes = pdf_security.PDF_VALIDATION_MEMORY_LIMIT_MIB * 1024 * 1024
    assert applied[resource.RLIMIT_AS] == (memory_bytes, memory_bytes)
    assert applied[resource.RLIMIT_FSIZE] == (
        pdf_security.MAX_PDF_BYTES,
        pdf_security.MAX_PDF_BYTES,
    )
    assert applied[resource.RLIMIT_CPU] == (
        pdf_security.PDF_SANITIZATION_CPU_SOFT_SECONDS,
        pdf_security.PDF_SANITIZATION_CPU_HARD_SECONDS,
    )


@pytest.mark.asyncio
async def test_sanitized_output_size_mismatch_fails_closed_and_cleans_up(
    monkeypatch, tmp_path: Path
) -> None:
    destination = tmp_path / "oversized-output.pdf"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-source")
    monkeypatch.setattr(
        pdf_security.tempfile,
        "mkstemp",
        lambda **_kwargs: (
            os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600),
            os.fspath(destination),
        ),
    )

    async def inconsistent_size(*_args, **_kwargs):
        destination.write_bytes(b"partial")
        return {
            "status": "ok",
            "output_size": pdf_security.MAX_PDF_BYTES + 1,
        }, 0

    monkeypatch.setattr(pdf_security, "_run_helper_command", inconsistent_size)
    with pytest.raises(PdfValidationError, match="sanitized_file_too_large"):
        await pdf_security.sanitize_staged_pdf(
            source,
            deadline=asyncio.get_running_loop().time() + 10,
        )
    assert not destination.exists()


@pytest.mark.asyncio
async def test_helper_timeout_is_sanitized_and_process_is_reaped(
    tmp_path: Path,
) -> None:
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
async def test_validation_rejection_logs_only_bounded_metadata(
    caplog, monkeypatch, tmp_path: Path
) -> None:
    # Keep this assertion independent from logging configuration installed by
    # earlier tests in the complete backend shard.
    monkeypatch.setattr(pdf_security.logger, "disabled", False)
    monkeypatch.setattr(pdf_security.logger, "propagate", True)
    private_detail = "private parser detail and /tmp/private-name.pdf"
    command = [
        sys.executable,
        "-c",
        (
            "import json; "
            f"print(json.dumps({{'status': 'rejected', 'code': {private_detail!r}}}))"
        ),
    ]

    with (
        caplog.at_level(logging.INFO, logger=pdf_security.logger.name),
        pytest.raises(PdfValidationError) as error,
    ):
        await pdf_security.validate_staged_pdf(
            _pdf_path(tmp_path),
            command=command,
        )

    assert error.value.code == private_detail
    record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "pdf_validation_rejected"
    )
    assert record.code == "unclassified"
    assert record.duration_ms >= 0
    assert record.parser_lock_wait_ms >= 0
    assert private_detail not in caplog.text


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
