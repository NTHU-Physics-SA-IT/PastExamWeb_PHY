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
from pathlib import Path
from typing import Any, BinaryIO

from fastapi import UploadFile

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_PDF_OBJECTS = 50_000
PDF_VALIDATION_TIMEOUT_SECONDS = 20
PDF_VALIDATION_MEMORY_LIMIT_MIB = 256

_COPY_CHUNK_BYTES = 1024 * 1024
_HELPER_RESULT_LIMIT_BYTES = 64 * 1024
_LINUX_LOCK_PATH = "/tmp/pastexam-pdf-validator.lock"
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
    duration_ms: int | None = None,
    parser_lock_wait_ms: int | None = None,
) -> None:
    fields: dict[str, str | int] = {"event": event}
    if code is not None:
        fields["code"] = _bounded_rejection_code(code)
    if duration_ms is not None:
        fields["duration_ms"] = max(duration_ms, 0)
    if parser_lock_wait_ms is not None:
        fields["parser_lock_wait_ms"] = max(parser_lock_wait_ms, 0)
    logger.info(event, extra=fields)


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
    try:
        try:
            staged = await stage_pdf_upload(upload)
        except PdfValidationError as exc:
            _log_pdf_security_event("pdf_validation_rejected", code=exc.code)
            raise
        await validate_staged_pdf(staged.path)
        yield staged
    finally:
        _remove_staged_file(staged.path if staged else None)


async def _terminate_and_reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.kill()
    await process.communicate()


async def validate_staged_pdf(
    path: Path,
    *,
    timeout_seconds: float = PDF_VALIDATION_TIMEOUT_SECONDS,
    command: list[str] | None = None,
) -> PdfInspection:
    loop = asyncio.get_running_loop()
    worker_lock = _worker_helper_lock()
    started_at = loop.time()
    deadline = loop.time() + timeout_seconds
    try:
        await asyncio.wait_for(
            worker_lock.acquire(), timeout=max(deadline - loop.time(), 0)
        )
    except TimeoutError as exc:
        duration_ms = round((loop.time() - started_at) * 1000)
        _log_pdf_security_event(
            "pdf_validation_rejected",
            code="validation_timeout",
            duration_ms=duration_ms,
            parser_lock_wait_ms=duration_ms,
        )
        raise PdfValidationError(
            "validation_timeout", "Invalid or unsupported PDF file"
        ) from exc

    lock_acquired_at = loop.time()
    parser_lock_wait_ms = round((lock_acquired_at - started_at) * 1000)
    try:
        try:
            return await _validate_staged_pdf_locked(
                path,
                deadline=deadline,
                command=command,
            )
        except PdfValidationError as exc:
            _log_pdf_security_event(
                "pdf_validation_rejected",
                code=exc.code,
                duration_ms=round((loop.time() - started_at) * 1000),
                parser_lock_wait_ms=parser_lock_wait_ms,
            )
            raise
    finally:
        worker_lock.release()


async def _validate_staged_pdf_locked(
    path: Path,
    *,
    deadline: float,
    command: list[str] | None,
) -> PdfInspection:
    helper_command = command or [
        sys.executable,
        "-m",
        "app.services.pdf_security",
        "--validate",
        os.fspath(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *helper_command,
        stdin=subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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

    if process.returncode != 0 or result.get("status") != "ok":
        code = str(result.get("code") or "invalid_pdf")
        raise PdfValidationError(code, "Invalid or unsupported PDF file")

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

            if str(value.get("/Subtype", "")) == "/FileAttachment":
                forbidden.add("file_attachment")
            stack.extend(item for _key, item in items)
        elif isinstance(value, pikepdf.Array):
            stack.extend(value)

    return forbidden


def _inspect_pdf(
    path: Path,
    *,
    max_pages: int = MAX_PDF_PAGES,
    max_objects: int = MAX_PDF_OBJECTS,
) -> dict[str, Any]:
    import pikepdf

    try:
        with pikepdf.open(path, attempt_recovery=False) as pdf:
            if pdf.is_encrypted:
                raise _PdfPolicyViolation("encrypted")
            page_count = len(pdf.pages)
            object_count = len(pdf.objects)
            if page_count > max_pages:
                raise _PdfPolicyViolation("page_limit")
            if object_count > max_objects:
                raise _PdfPolicyViolation("object_limit")

            syntax_issues = list(pdf.check_pdf_syntax())
            parser_warnings = list(pdf.get_warnings())
            if syntax_issues or parser_warnings:
                raise _PdfPolicyViolation("syntax_warning")
            if _find_forbidden_features(pdf, pikepdf):
                raise _PdfPolicyViolation("forbidden_feature")
    except pikepdf.PasswordError as exc:
        raise _PdfPolicyViolation("encrypted") from exc
    except pikepdf.PdfError as exc:
        raise _PdfPolicyViolation("invalid_pdf") from exc

    return {
        "pages": page_count,
        "objects": object_count,
        "pikepdf_version": pikepdf.__version__,
        "qpdf_version": pikepdf.__libqpdf_version__,
    }


def _helper_result(path: Path) -> dict[str, Any]:
    memory_limit_applied = _apply_memory_limit()
    with _global_parser_lock() as global_lock_applied:
        result = _inspect_pdf(path)
    return {
        "status": "ok",
        **result,
        "memory_limit_applied": memory_limit_applied,
        "global_lock_applied": global_lock_applied,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--validate", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = _helper_result(arguments.validate)
    except _PdfPolicyViolation as exc:
        result = {"status": "rejected", "code": exc.code}
    except (MemoryError, OSError, RuntimeError, ValueError):
        result = {"status": "error", "code": "helper_failure"}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] in {"ok", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(_main())
