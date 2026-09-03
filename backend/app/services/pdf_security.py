from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import weakref
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO

from fastapi import UploadFile

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_PDF_OBJECTS = 50_000
PDF_VALIDATION_TIMEOUT_SECONDS = 20
PDF_VALIDATION_MEMORY_LIMIT_MIB = 256
PDF_SANITIZATION_TIMEOUT_SECONDS = 4
PDF_SANITIZATION_CPU_SOFT_SECONDS = 3
PDF_SANITIZATION_CPU_HARD_SECONDS = 4
PDF_FALLBACK_MIN_REMAINING_SECONDS = 8

_COPY_CHUNK_BYTES = 1024 * 1024
_HELPER_RESULT_LIMIT_BYTES = 64 * 1024
_LINUX_LOCK_PATH = "/tmp/pastexam-pdf-validator.lock"
_LINUX_SANITIZER_ADMISSION_PATH = "/tmp/pastexam-pdf-sanitizer.lock"
_SUPPORTED_PIKEPDF_VERSION = "10.12.0"
_SUPPORTED_QPDF_VERSION = "12.3.2"
_FLATE_INCOMPLETE_TERMINATION_MESSAGE = (
    "input stream is complete but output may still be valid"
)
_ATTACHMENT_FEATURES = frozenset({"embedded_files", "file_attachment"})
_BOUNDED_FINDINGS = frozenset(
    {
        "embedded_files",
        "file_attachment",
        "flate_incomplete_termination",
        "signature_present",
    }
)
_WORKER_HELPER_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = weakref.WeakKeyDictionary()

logger = logging.getLogger(__name__)

_BOUNDED_REJECTION_CODES = frozenset(
    {
        "encrypted",
        "file_too_large",
        "forbidden_feature",
        "helper_failure",
        "invalid_pdf",
        "object_limit",
        "page_limit",
        "syntax_warning",
        "sanitized_file_too_large",
        "sanitizer_busy",
        "sanitizer_failure",
        "sanitizer_timeout",
        "fallback_deadline_exhausted",
        "post_sanitization_rejected",
        "validation_timeout",
        "wrong_extension",
    }
)


def _bounded_rejection_code(code: str) -> str:
    return code if code in _BOUNDED_REJECTION_CODES else "unclassified"


def _log_pdf_security_event(
    event: str,
    *,
    code: str | None = None,
    finding: str | None = None,
    duration_ms: int | None = None,
    parser_lock_wait_ms: int | None = None,
) -> None:
    fields: dict[str, str | int] = {"event": event}
    if code is not None:
        fields["code"] = _bounded_rejection_code(code)
    if finding is not None:
        findings = finding.split("+")
        fields["finding"] = (
            finding
            if findings and all(item in _BOUNDED_FINDINGS for item in findings)
            else "unclassified"
        )
    if duration_ms is not None:
        fields["duration_ms"] = max(duration_ms, 0)
    if parser_lock_wait_ms is not None:
        fields["parser_lock_wait_ms"] = max(parser_lock_wait_ms, 0)
    logger.info(event, extra=fields)


class PdfDisposition(StrEnum):
    PASS = "pass"
    SANITIZABLE = "sanitizable"


def _worker_helper_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _WORKER_HELPER_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _WORKER_HELPER_LOCKS[loop] = lock
    return lock


class PdfValidationError(Exception):
    def __init__(self, code: str, public_detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.public_detail = public_detail


class _PdfPolicyViolation(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StagedPdf:
    path: Path
    size: int


@dataclass(frozen=True)
class PdfInspection:
    pages: int
    objects: int
    pikepdf_version: str
    qpdf_version: str
    memory_limit_applied: bool
    global_lock_applied: bool


@dataclass(frozen=True)
class PdfClassification:
    disposition: PdfDisposition
    inspection: PdfInspection
    findings: tuple[str, ...] = ()


def _remove_staged_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        # The request boundary must not expose local paths or replace the
        # original validation/upload result with a cleanup error.
        logger.error("PDF staging cleanup failed (%s)", type(exc).__name__)


def _copy_limited(source: BinaryIO, destination: Path) -> int:
    total = 0
    with destination.open("wb") as target:
        while True:
            chunk = source.read(_COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_PDF_BYTES:
                raise PdfValidationError(
                    "file_too_large",
                    "File size exceeds 20MB limit",
                )
            target.write(chunk)
        target.flush()

    if total == 0:
        raise PdfValidationError("invalid_pdf", "Invalid or unsupported PDF file")
    with destination.open("rb") as staged:
        if staged.read(5) != b"%PDF-":
            raise PdfValidationError("invalid_pdf", "Invalid or unsupported PDF file")
    return total


async def stage_pdf_upload(upload: UploadFile) -> StagedPdf:
    filename = upload.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise PdfValidationError("wrong_extension", "Only PDF files are allowed")
    if upload.size is not None and upload.size > MAX_PDF_BYTES:
        raise PdfValidationError("file_too_large", "File size exceeds 20MB limit")

    file_descriptor, raw_path = tempfile.mkstemp(prefix="pastexam-pdf-", suffix=".pdf")
    os.close(file_descriptor)
    path = Path(raw_path)
    try:
        os.chmod(path, 0o600)
        await upload.seek(0)
        copy_task = asyncio.create_task(
            asyncio.to_thread(_copy_limited, upload.file, path)
        )
        try:
            size = await asyncio.shield(copy_task)
        except asyncio.CancelledError:
            # Do not unlink a path while its worker thread is still writing it.
            try:
                await copy_task
            except (OSError, PdfValidationError):
                pass
            raise
        return StagedPdf(path=path, size=size)
    except BaseException:
        _remove_staged_file(path)
        raise


@asynccontextmanager
async def validated_pdf_upload(upload: UploadFile) -> AsyncIterator[StagedPdf]:
    staged: StagedPdf | None = None
    sanitized: StagedPdf | None = None
    try:
        try:
            staged = await stage_pdf_upload(upload)
        except PdfValidationError as exc:
            _log_pdf_security_event("pdf_validation_rejected", code=exc.code)
            raise
        loop = asyncio.get_running_loop()
        deadline = loop.time() + PDF_VALIDATION_TIMEOUT_SECONDS
        classification = await inspect_staged_pdf(staged.path, deadline=deadline)
        if classification.disposition is PdfDisposition.PASS:
            yield staged
            return

        finding = "+".join(classification.findings)
        _log_pdf_security_event("pdf_sanitization_candidate", finding=finding)
        if deadline - loop.time() < PDF_FALLBACK_MIN_REMAINING_SECONDS:
            error = PdfValidationError(
                "fallback_deadline_exhausted", "Invalid or unsupported PDF file"
            )
            _log_pdf_security_event("pdf_sanitization_failed", code=error.code)
            raise error

        sanitized = await sanitize_staged_pdf(staged.path, deadline=deadline)
        revalidation_started_at = loop.time()
        try:
            await validate_staged_pdf(sanitized.path, deadline=deadline)
        except PdfValidationError as exc:
            _log_pdf_security_event(
                "pdf_sanitization_failed",
                code="post_sanitization_rejected",
                duration_ms=round((loop.time() - revalidation_started_at) * 1000),
            )
            raise PdfValidationError(
                "post_sanitization_rejected", "Invalid or unsupported PDF file"
            ) from exc
        yield sanitized
    finally:
        _remove_staged_file(sanitized.path if sanitized else None)
        _remove_staged_file(staged.path if staged else None)


async def _terminate_and_reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.kill()
    await process.communicate()


async def validate_staged_pdf(
    path: Path,
    *,
    timeout_seconds: float = PDF_VALIDATION_TIMEOUT_SECONDS,
    deadline: float | None = None,
    command: list[str] | None = None,
) -> PdfInspection:
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    parser_lock_wait_ms = 0
    effective_deadline = deadline or (loop.time() + timeout_seconds)
    try:
        result, parser_lock_wait_ms = await _run_helper_command(
            path,
            mode="validate",
            deadline=effective_deadline,
            command=command,
        )
        if result.get("status") != "ok":
            code = str(result.get("code") or "invalid_pdf")
            raise PdfValidationError(code, "Invalid or unsupported PDF file")
        return _inspection_from_result(result)
    except PdfValidationError as exc:
        _log_pdf_security_event(
            "pdf_validation_rejected",
            code=exc.code,
            duration_ms=round((loop.time() - started_at) * 1000),
            parser_lock_wait_ms=parser_lock_wait_ms,
        )
        raise


async def inspect_staged_pdf(
    path: Path,
    *,
    deadline: float,
) -> PdfClassification:
    try:
        result, _parser_lock_wait_ms = await _run_helper_command(
            path,
            mode="inspect",
            deadline=deadline,
        )
        status = result.get("status")
        if status == "ok":
            return PdfClassification(
                disposition=PdfDisposition.PASS,
                inspection=_inspection_from_result(result),
            )
        if status == "candidate":
            findings = result.get("findings")
            if not isinstance(findings, list) or not findings:
                raise PdfValidationError(
                    "helper_failure", "Invalid or unsupported PDF file"
                )
            bounded_findings = tuple(sorted(str(finding) for finding in findings))
            allowed_findings = {
                "embedded_files",
                "file_attachment",
                "flate_incomplete_termination",
                "signature_present",
            }
            if any(finding not in allowed_findings for finding in bounded_findings):
                raise PdfValidationError(
                    "helper_failure", "Invalid or unsupported PDF file"
                )
            return PdfClassification(
                disposition=PdfDisposition.SANITIZABLE,
                inspection=_inspection_from_result(result),
                findings=bounded_findings,
            )
        code = str(result.get("code") or "invalid_pdf")
        raise PdfValidationError(code, "Invalid or unsupported PDF file")
    except PdfValidationError as exc:
        _log_pdf_security_event("pdf_validation_rejected", code=exc.code)
        raise


async def sanitize_staged_pdf(path: Path, *, deadline: float) -> StagedPdf:
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix="pastexam-pdf-sanitized-", suffix=".pdf"
    )
    os.close(file_descriptor)
    destination = Path(raw_path)
    try:
        os.chmod(destination, 0o600)
        _log_pdf_security_event("pdf_sanitization_started")
        sanitizer_deadline = min(
            deadline,
            loop.time() + PDF_SANITIZATION_TIMEOUT_SECONDS,
        )
        try:
            result, _parser_lock_wait_ms = await _run_helper_command(
                path,
                mode="sanitize",
                deadline=sanitizer_deadline,
                command=[
                    sys.executable,
                    "-m",
                    "app.services.pdf_security",
                    "--sanitize",
                    os.fspath(path),
                    "--output",
                    os.fspath(destination),
                ],
            )
        except PdfValidationError as exc:
            code = (
                "sanitizer_timeout"
                if exc.code == "validation_timeout"
                else (
                    exc.code
                    if exc.code in {"sanitizer_busy", "sanitized_file_too_large"}
                    else "sanitizer_failure"
                )
            )
            raise PdfValidationError(code, "Invalid or unsupported PDF file") from exc

        if result.get("status") != "ok":
            raw_code = str(result.get("code") or "sanitizer_failure")
            code = (
                raw_code
                if raw_code in {"sanitizer_busy", "sanitized_file_too_large"}
                else "sanitizer_failure"
            )
            raise PdfValidationError(code, "Invalid or unsupported PDF file")
        try:
            reported_size = int(result["output_size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PdfValidationError(
                "sanitizer_failure", "Invalid or unsupported PDF file"
            ) from exc
        os.chmod(destination, 0o600)
        actual_size = destination.stat().st_size
        if (
            reported_size != actual_size
            or actual_size == 0
            or actual_size > MAX_PDF_BYTES
        ):
            raise PdfValidationError(
                "sanitized_file_too_large", "Invalid or unsupported PDF file"
            )
        sanitized = StagedPdf(path=destination, size=actual_size)
        _log_pdf_security_event(
            "pdf_sanitization_succeeded",
            duration_ms=round((loop.time() - started_at) * 1000),
        )
        return sanitized
    except BaseException as exc:
        code = exc.code if isinstance(exc, PdfValidationError) else "sanitizer_failure"
        _log_pdf_security_event(
            "pdf_sanitization_failed",
            code=code,
            duration_ms=round((loop.time() - started_at) * 1000),
        )
        _remove_staged_file(destination)
        raise


async def _run_helper_command(
    path: Path,
    *,
    mode: str,
    deadline: float,
    command: list[str] | None = None,
) -> tuple[dict[str, Any], int]:
    loop = asyncio.get_running_loop()
    worker_lock = _worker_helper_lock()
    lock_started_at = loop.time()
    try:
        await asyncio.wait_for(
            worker_lock.acquire(), timeout=max(deadline - loop.time(), 0)
        )
    except TimeoutError as exc:
        raise PdfValidationError(
            "validation_timeout", "Invalid or unsupported PDF file"
        ) from exc

    parser_lock_wait_ms = round((loop.time() - lock_started_at) * 1000)
    try:
        result = await _run_helper_command_locked(
            path,
            mode=mode,
            deadline=deadline,
            command=command,
        )
        return result, parser_lock_wait_ms
    finally:
        worker_lock.release()


async def _run_helper_command_locked(
    path: Path,
    *,
    mode: str,
    deadline: float,
    command: list[str] | None,
) -> dict[str, Any]:
    helper_command = command or [
        sys.executable,
        "-m",
        "app.services.pdf_security",
        f"--{mode}",
        os.fspath(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *helper_command,
        stdin=subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        remaining_seconds = max(deadline - asyncio.get_running_loop().time(), 0)
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(), timeout=remaining_seconds
        )
    except TimeoutError as exc:
        await _terminate_and_reap(process)
        raise PdfValidationError(
            "validation_timeout", "Invalid or unsupported PDF file"
        ) from exc
    except asyncio.CancelledError:
        await _terminate_and_reap(process)
        raise

    if len(stdout) > _HELPER_RESULT_LIMIT_BYTES:
        raise PdfValidationError("helper_failure", "Invalid or unsupported PDF file")
    try:
        result = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PdfValidationError(
            "helper_failure", "Invalid or unsupported PDF file"
        ) from exc

    if process.returncode != 0:
        raise PdfValidationError("helper_failure", "Invalid or unsupported PDF file")
    if not isinstance(result, dict):
        raise PdfValidationError("helper_failure", "Invalid or unsupported PDF file")
    return result


def _inspection_from_result(result: dict[str, Any]) -> PdfInspection:
    try:
        return PdfInspection(
            pages=int(result["pages"]),
            objects=int(result["objects"]),
            pikepdf_version=str(result["pikepdf_version"]),
            qpdf_version=str(result["qpdf_version"]),
            memory_limit_applied=bool(result["memory_limit_applied"]),
            global_lock_applied=bool(result["global_lock_applied"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PdfValidationError(
            "helper_failure", "Invalid or unsupported PDF file"
        ) from exc


def _apply_memory_limit() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    import resource

    limit = PDF_VALIDATION_MEMORY_LIMIT_MIB * 1024 * 1024
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    return True


def _apply_sanitizer_limits() -> tuple[bool, bool, bool]:
    memory_limit_applied = _apply_memory_limit()
    if not sys.platform.startswith("linux"):
        return memory_limit_applied, False, False

    import resource

    output_limit = MAX_PDF_BYTES
    _file_soft, file_hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    if file_hard != resource.RLIM_INFINITY:
        output_limit = min(output_limit, file_hard)
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))

    cpu_hard = PDF_SANITIZATION_CPU_HARD_SECONDS
    _cpu_soft, existing_cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
    if existing_cpu_hard != resource.RLIM_INFINITY:
        cpu_hard = min(cpu_hard, existing_cpu_hard)
    cpu_soft = min(PDF_SANITIZATION_CPU_SOFT_SECONDS, cpu_hard)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_hard))
    return memory_limit_applied, True, True


@contextmanager
def _global_parser_lock() -> Iterator[bool]:
    if not sys.platform.startswith("linux"):
        yield False
        return

    import fcntl

    with open(_LINUX_LOCK_PATH, "a+b", buffering=0) as lock_file:
        os.chmod(_LINUX_LOCK_PATH, 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _global_sanitizer_admission() -> Iterator[bool]:
    if not sys.platform.startswith("linux"):
        yield False
        return

    import fcntl

    with open(_LINUX_SANITIZER_ADMISSION_PATH, "a+b", buffering=0) as lock_file:
        os.chmod(_LINUX_SANITIZER_ADMISSION_PATH, 0o600)
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _object_identity(value: Any) -> tuple[str, int, int] | tuple[str, int]:
    try:
        object_number, generation = value.objgen
    except (AttributeError, TypeError, ValueError):
        return ("direct", id(value))
    if object_number:
        return ("indirect", int(object_number), int(generation))
    return ("direct", id(value))


def _find_forbidden_features(pdf: Any, pikepdf: Any) -> set[str]:
    forbidden: set[str] = set()
    stack = list(pdf.objects)
    seen: set[tuple[Any, ...]] = set()

    while stack:
        value = stack.pop()
        if isinstance(value, (pikepdf.Dictionary, pikepdf.Array, pikepdf.Stream)):
            identity = _object_identity(value)
            if identity in seen:
                continue
            seen.add(identity)

        if isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            items = list(value.items())
            keys = {str(key) for key, _item in items}
            if "/OpenAction" in keys:
                forbidden.add("open_action")
            if "/AA" in keys:
                forbidden.add("additional_actions")
            if "/EmbeddedFiles" in keys or "/EF" in keys:
                forbidden.add("embedded_files")
            if "/AcroForm" in keys:
                forbidden.add("acroform")
            if "/XFA" in keys:
                forbidden.add("xfa")
            if "/JS" in keys:
                forbidden.add("javascript")

            action_type = str(value.get("/S", ""))
            if action_type == "/JavaScript":
                forbidden.add("javascript")
            elif action_type == "/Launch":
                forbidden.add("launch")
            elif action_type in {"/GoToE", "/GoToR", "/ImportData", "/SubmitForm"}:
                forbidden.add("external_action")

            subtype = str(value.get("/Subtype", ""))
            if subtype == "/FileAttachment":
                forbidden.add("file_attachment")
            elif subtype in {"/3D", "/Movie", "/RichMedia", "/Screen", "/Sound"}:
                forbidden.add("multimedia")
            stack.extend(item for _key, item in items)
        elif isinstance(value, pikepdf.Array):
            stack.extend(value)

    return forbidden


def _is_embedded_file_spec(value: Any, pikepdf: Any) -> bool:
    if not isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
        return False
    if str(value.get("/Type", "")) != "/Filespec":
        return False
    embedded_files = value.get("/EF")
    if not isinstance(embedded_files, pikepdf.Dictionary):
        return False
    streams = list(embedded_files.values())
    return bool(streams) and all(
        isinstance(stream, pikepdf.Stream)
        and str(stream.get("/Type", "")) == "/EmbeddedFile"
        for stream in streams
    )


def _file_specs(value: Any, pikepdf: Any) -> list[Any] | None:
    if isinstance(value, pikepdf.Array):
        return list(value)
    if isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
        return [value]
    return None


def _attachment_graph_is_removable(pdf: Any, pikepdf: Any) -> bool:
    allowed_specs: set[tuple[Any, ...]] = set()
    names = pdf.Root.get("/Names")
    embedded_names_owner = (
        _object_identity(names) if isinstance(names, pikepdf.Dictionary) else None
    )

    try:
        for attachment in pdf.attachments.values():
            if not _is_embedded_file_spec(attachment.obj, pikepdf):
                return False
            allowed_specs.add(_object_identity(attachment.obj))
    except (AttributeError, KeyError, TypeError, ValueError, pikepdf.PdfError):
        return False

    for value in pdf.objects:
        if not isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            continue
        if "/AF" in value:
            associated = _file_specs(value.get("/AF"), pikepdf)
            if not associated or any(
                not _is_embedded_file_spec(spec, pikepdf) for spec in associated
            ):
                return False
            allowed_specs.update(_object_identity(spec) for spec in associated)
        if str(value.get("/Subtype", "")) == "/FileAttachment":
            file_spec = value.get("/FS")
            if not _is_embedded_file_spec(file_spec, pikepdf):
                return False
            allowed_specs.add(_object_identity(file_spec))

    for value in pdf.objects:
        if not isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            continue
        if "/EF" in value and _object_identity(value) not in allowed_specs:
            return False
        if "/EmbeddedFiles" in value and (
            embedded_names_owner is None
            or _object_identity(value) != embedded_names_owner
        ):
            return False
    return bool(allowed_specs) or (
        isinstance(names, pikepdf.Dictionary) and "/EmbeddedFiles" in names
    )


def _normalized_parser_findings(
    issues: list[str], *, pikepdf_version: str, qpdf_version: str
) -> set[str] | None:
    if not issues:
        return set()
    if (
        pikepdf_version != _SUPPORTED_PIKEPDF_VERSION
        or qpdf_version != _SUPPORTED_QPDF_VERSION
    ):
        return None

    findings: set[str] = set()
    for issue in issues:
        prefix, separator, message = issue.rpartition("): ")
        if separator != "): " or not prefix.startswith("WARNING: "):
            return None
        _path, offset_separator, offset = prefix.rpartition(" (offset ")
        if offset_separator != " (offset " or not offset.isdigit():
            return None
        if message != _FLATE_INCOMPLETE_TERMINATION_MESSAGE:
            return None
        findings.add("flate_incomplete_termination")
    return findings


def _has_signature_structure(pdf: Any, pikepdf: Any) -> bool:
    return any(
        isinstance(value, (pikepdf.Dictionary, pikepdf.Stream))
        and (
            str(value.get("/FT", "")) == "/Sig" or str(value.get("/Type", "")) == "/Sig"
        )
        for value in pdf.objects
    )


def _classify_open_pdf(
    pdf: Any,
    pikepdf: Any,
    *,
    max_pages: int = MAX_PDF_PAGES,
    max_objects: int = MAX_PDF_OBJECTS,
) -> dict[str, Any]:
    if pdf.is_encrypted:
        raise _PdfPolicyViolation("encrypted")
    page_count = len(pdf.pages)
    object_count = len(pdf.objects)
    if page_count > max_pages:
        raise _PdfPolicyViolation("page_limit")
    if object_count > max_objects:
        raise _PdfPolicyViolation("object_limit")

    raw_issues = list(pdf.check_pdf_syntax()) + list(pdf.get_warnings())
    normalized_findings = _normalized_parser_findings(
        raw_issues,
        pikepdf_version=pikepdf.__version__,
        qpdf_version=pikepdf.__libqpdf_version__,
    )
    forbidden_features = _find_forbidden_features(pdf, pikepdf)
    metadata = {
        "pages": page_count,
        "objects": object_count,
        "pikepdf_version": pikepdf.__version__,
        "qpdf_version": pikepdf.__libqpdf_version__,
    }

    if not raw_issues and not forbidden_features:
        return {"disposition": PdfDisposition.PASS.value, **metadata}

    if normalized_findings is None:
        raise _PdfPolicyViolation("syntax_warning")
    fatal_features = forbidden_features - _ATTACHMENT_FEATURES
    if fatal_features:
        raise _PdfPolicyViolation(
            "syntax_warning" if raw_issues else "forbidden_feature"
        )
    if not forbidden_features or not _attachment_graph_is_removable(pdf, pikepdf):
        raise _PdfPolicyViolation(
            "syntax_warning" if raw_issues else "forbidden_feature"
        )

    findings = set(forbidden_features) | normalized_findings
    if _has_signature_structure(pdf, pikepdf):
        findings.add("signature_present")
    return {
        "disposition": PdfDisposition.SANITIZABLE.value,
        "findings": sorted(findings),
        "legacy_code": "syntax_warning" if raw_issues else "forbidden_feature",
        **metadata,
    }


def _classify_pdf(
    path: Path,
    *,
    max_pages: int = MAX_PDF_PAGES,
    max_objects: int = MAX_PDF_OBJECTS,
) -> dict[str, Any]:
    import pikepdf

    try:
        with pikepdf.open(path, attempt_recovery=False) as pdf:
            return _classify_open_pdf(
                pdf,
                pikepdf,
                max_pages=max_pages,
                max_objects=max_objects,
            )
    except pikepdf.PasswordError as exc:
        raise _PdfPolicyViolation("encrypted") from exc
    except pikepdf.PdfError as exc:
        raise _PdfPolicyViolation("invalid_pdf") from exc


def _inspect_pdf(
    path: Path,
    *,
    max_pages: int = MAX_PDF_PAGES,
    max_objects: int = MAX_PDF_OBJECTS,
) -> dict[str, Any]:
    result = _classify_pdf(
        path,
        max_pages=max_pages,
        max_objects=max_objects,
    )
    if result["disposition"] != PdfDisposition.PASS.value:
        raise _PdfPolicyViolation(str(result["legacy_code"]))
    return {
        key: result[key]
        for key in ("pages", "objects", "pikepdf_version", "qpdf_version")
    }


def _remove_file_attachment_annotations(pdf: Any, pikepdf: Any) -> None:
    for page in pdf.pages:
        annotations = page.obj.get("/Annots")
        if not isinstance(annotations, pikepdf.Array):
            continue
        retained = pikepdf.Array(
            [
                annotation
                for annotation in annotations
                if not (
                    isinstance(annotation, pikepdf.Dictionary)
                    and str(annotation.get("/Subtype", "")) == "/FileAttachment"
                )
            ]
        )
        if retained:
            page.obj.Annots = retained
        else:
            del page.obj["/Annots"]


def _sanitize_pdf(source: Path, destination: Path) -> dict[str, Any]:
    import pikepdf
    from pikepdf.sanitize import remove_attachments

    try:
        with pikepdf.open(source, attempt_recovery=False) as pdf:
            classification = _classify_open_pdf(pdf, pikepdf)
            if classification["disposition"] != PdfDisposition.SANITIZABLE.value:
                raise _PdfPolicyViolation("sanitizer_failure")
            remove_attachments(pdf)
            _remove_file_attachment_annotations(pdf, pikepdf)
            pdf.save(destination, recompress_flate=True)
            os.chmod(destination, 0o600)
    except pikepdf.PasswordError as exc:
        raise _PdfPolicyViolation("encrypted") from exc
    except pikepdf.PdfError as exc:
        raise _PdfPolicyViolation("sanitizer_failure") from exc

    output_size = destination.stat().st_size
    if output_size == 0 or output_size > MAX_PDF_BYTES:
        raise _PdfPolicyViolation("sanitized_file_too_large")
    return {"output_size": output_size}


def _helper_result(path: Path, *, inspect: bool = False) -> dict[str, Any]:
    memory_limit_applied = _apply_memory_limit()
    with _global_parser_lock() as global_lock_applied:
        result = _classify_pdf(path) if inspect else _inspect_pdf(path)
    disposition = result.pop("disposition", PdfDisposition.PASS.value)
    status = "candidate" if disposition == PdfDisposition.SANITIZABLE.value else "ok"
    return {
        "status": status,
        **result,
        "memory_limit_applied": memory_limit_applied,
        "global_lock_applied": global_lock_applied,
    }


def _sanitizer_helper_result(source: Path, destination: Path) -> dict[str, Any]:
    memory_applied, output_applied, cpu_applied = _apply_sanitizer_limits()
    with _global_sanitizer_admission() as sanitizer_admitted:
        if sys.platform.startswith("linux") and not sanitizer_admitted:
            raise _PdfPolicyViolation("sanitizer_busy")
        with _global_parser_lock() as global_lock_applied:
            result = _sanitize_pdf(source, destination)
    return {
        "status": "ok",
        **result,
        "memory_limit_applied": memory_applied,
        "output_limit_applied": output_applied,
        "cpu_limit_applied": cpu_applied,
        "global_lock_applied": global_lock_applied,
        "sanitizer_admitted": sanitizer_admitted,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", type=Path)
    mode.add_argument("--inspect", type=Path)
    mode.add_argument("--sanitize", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.validate is not None:
            result = _helper_result(arguments.validate)
        elif arguments.inspect is not None:
            result = _helper_result(arguments.inspect, inspect=True)
        elif arguments.sanitize is not None and arguments.output is not None:
            result = _sanitizer_helper_result(arguments.sanitize, arguments.output)
        else:
            result = {"status": "error", "code": "helper_failure"}
    except _PdfPolicyViolation as exc:
        result = {"status": "rejected", "code": exc.code}
    except (MemoryError, OSError, RuntimeError, ValueError):
        result = {"status": "error", "code": "helper_failure"}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] in {"ok", "candidate", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(_main())
