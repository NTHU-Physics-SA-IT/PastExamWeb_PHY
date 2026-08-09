#!/usr/bin/env python3
"""Read-only Git/source/runtime/service/data health classification."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
DEV_COMPOSE = REPOSITORY_ROOT / "scripts" / "dev-compose.sh"
EXPECTED_ALEMBIC_HEAD = "9f1c2a7e4b63"
ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXIT_CODES = {
    "healthy": 0,
    "source_mismatch": 10,
    "current_code_startup_failure": 11,
    "reload_only_failure": 12,
    "healthcheck_only_failure": 13,
    "postgres_environment_incident": 14,
    "inconclusive": 15,
}
STARTUP_FAILURE_PATTERN = re.compile(
    r"(SyntaxError|ImportError|ModuleNotFoundError|FileNotFoundError|"
    r"Traceback \(most recent call last\))"
)
TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:token|secret|password|authorization|cookie)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
URL_USERINFO_PATTERN = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+(?::[^\s/@]*)?@")


class CheckerFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandExecutor:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path = REPOSITORY_ROOT,
        timeout: float = 30,
    ) -> CommandResult:
        process = subprocess.run(
            list(args),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            shell=False,
        )
        return CommandResult(process.returncode, process.stdout, process.stderr)


def dev_compose_command(action: str) -> tuple[str, ...]:
    if os.name != "nt":
        return (str(DEV_COMPOSE), action)

    git_bash = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Git"
        / "bin"
        / "bash.exe"
    )
    if not git_bash.is_file():
        raise CheckerFailure("Git Bash is required on Windows")
    return (str(git_bash), str(DEV_COMPOSE), action)


@dataclass
class Finding:
    layer: str
    code: str
    severity: str
    evidence_classification: str
    message: str


@dataclass
class Report:
    schema_version: int = 1
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    classification: str = "inconclusive"
    exit_code: int = 15
    summary: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(
        default_factory=lambda: {
            "git": {},
            "source": {},
            "runtime": {},
            "service": {},
            "data": {},
        }
    )
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    redactions_applied: int = 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-container-id", required=True)
    parser.add_argument("--postgres-container-id", required=True)
    parser.add_argument("--source-file", action="append", required=True)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    for value in (args.backend_container_id, args.postgres_container_id):
        if not ID_PATTERN.fullmatch(value):
            parser.error("container IDs must be exact 64-character lowercase hex IDs")
    try:
        args.source_file = [
            str(validate_source_path(value).relative_to(REPOSITORY_ROOT))
            for value in args.source_file
        ]
    except CheckerFailure as exc:
        parser.error(str(exc))
    return args


def validate_source_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CheckerFailure("source paths must be repository-relative")
    if not candidate.parts or candidate.parts[0] != "backend":
        raise CheckerFailure("source paths must be under backend/")
    resolved = (REPOSITORY_ROOT / candidate).resolve(strict=False)
    try:
        resolved.relative_to(BACKEND_ROOT.resolve())
    except ValueError as exc:
        raise CheckerFailure("source path escapes the backend bind mount") from exc
    if resolved.exists():
        if resolved.is_dir():
            raise CheckerFailure("source paths must name files")
        if not resolved.is_file():
            raise CheckerFailure("source path is not a regular file")
    return resolved


def sanitized(value: str, report: Report) -> str:
    value, urls = URL_USERINFO_PATTERN.subn(r"\1[REDACTED]@", value)
    value, tokens = TOKEN_PATTERN.subn("[REDACTED]", value)
    report.redactions_applied += urls + tokens
    return value


def command(
    executor: CommandExecutor,
    args: Sequence[str],
    *,
    timeout: float = 30,
) -> str:
    result = executor.run(args, timeout=timeout)
    if result.returncode:
        raise CheckerFailure(f"read-only command failed: {' '.join(args[:2])}")
    return result.stdout.strip()


def inspect_container(
    executor: CommandExecutor, container_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(command(executor, ("docker", "inspect", container_id)))
    item = payload[0]
    if item.get("Id") != container_id:
        raise CheckerFailure("exact container identity mismatch")
    state = item.get("State") or {}
    health = state.get("Health") or {}
    return item, {
        "id": item["Id"],
        "name": item.get("Name"),
        "state": state.get("Status"),
        "health": health.get("Status"),
        "restart_count": int(item.get("RestartCount") or 0),
        "oom_killed": bool(state.get("OOMKilled")),
        "error": state.get("Error") or "",
        "started_at": state.get("StartedAt"),
        "health_log": [
            {
                "start": entry.get("Start"),
                "end": entry.get("End"),
                "exit_code": entry.get("ExitCode"),
                "output": entry.get("Output"),
            }
            for entry in (health.get("Log") or [])[-5:]
        ],
    }


def parse_schema_status(output: str) -> dict[str, Any]:
    values: dict[str, str] = {}
    aggregates: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("aggregates="):
            for item in line.removeprefix("aggregates=").split(","):
                key, separator, value = item.partition(":")
                if separator:
                    aggregates[key] = value
        else:
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
    required = {
        "audit",
        "status",
        "expected_ledger",
        "explicit_rollback",
    }
    aggregate_required = {
        "total",
        "active",
        "deleted",
        "created_archive_id_non_null",
        "created_archive_id_null",
        "max_created_archive_cardinality",
        "dangling_created_archive_links",
        "created_archive_link_checksum",
        "submission_state_checksum",
    }
    if not required.issubset(values) or not aggregate_required.issubset(aggregates):
        raise CheckerFailure("sealed schema-status output was incomplete")
    return {
        "audit": values["audit"],
        "status": values["status"],
        "alembic_head": values["expected_ledger"],
        "explicit_rollback": values["explicit_rollback"].lower() == "true",
        "total": int(aggregates["total"]),
        "active": int(aggregates["active"]),
        "deleted": int(aggregates["deleted"]),
        "linked": int(aggregates["created_archive_id_non_null"]),
        "unlinked": int(aggregates["created_archive_id_null"]),
        "max_cardinality": int(aggregates["max_created_archive_cardinality"]),
        "dangling": int(aggregates["dangling_created_archive_links"]),
        "link_checksum": aggregates["created_archive_link_checksum"],
        "state_checksum": aggregates["submission_state_checksum"],
    }


def http_probe(
    executor: CommandExecutor,
    args: Sequence[str],
) -> dict[str, Any]:
    started = time.monotonic()
    result = executor.run(args, timeout=5)
    elapsed = round(time.monotonic() - started, 3)
    output = (result.stdout or result.stderr).strip()
    status_match = re.search(r"STATUS=(\d{3})", output)
    return {
        "ok": result.returncode == 0
        and status_match is not None
        and 200 <= int(status_match.group(1)) < 300,
        "exit_code": result.returncode,
        "status": int(status_match.group(1)) if status_match else None,
        "elapsed_seconds": elapsed,
        "output": output[:500],
    }


def gather_source(
    executor: CommandExecutor,
    backend_id: str,
    paths: list[str],
) -> tuple[list[dict[str, Any]], bool, bool]:
    records: list[dict[str, Any]] = []
    all_match = True
    parse_failure = False
    for path_string in paths:
        path = validate_source_path(path_string)
        relative = path.relative_to(REPOSITORY_ROOT)
        record: dict[str, Any] = {"path": str(relative)}
        if not path.exists() or not path.is_file():
            record.update({"exists": False, "match": False})
            all_match = False
            records.append(record)
            continue
        content = path.read_bytes()
        record["exists"] = True
        record["size"] = len(content)
        record["host_sha256"] = hashlib.sha256(content).hexdigest()
        record["parse_ok"] = True
        if path.suffix == ".py":
            try:
                ast.parse(content, filename=str(relative))
            except SyntaxError as exc:
                record["parse_ok"] = False
                record["parse_error"] = f"{exc.__class__.__name__}: {exc.msg}"
                parse_failure = True
        git_result = executor.run(("git", "show", f"HEAD:{relative}"), timeout=15)
        if git_result.returncode:
            record["head_sha256"] = None
        else:
            record["head_sha256"] = hashlib.sha256(
                git_result.stdout.encode()
            ).hexdigest()
        container_path = "/app/" + str(path.relative_to(BACKEND_ROOT))
        container_result = executor.run(
            (
                "docker",
                "exec",
                backend_id,
                "python",
                "-c",
                (
                    "import hashlib,pathlib,sys;"
                    "p=pathlib.Path(sys.argv[1]);"
                    "print(p.stat().st_size);"
                    "print(hashlib.sha256(p.read_bytes()).hexdigest())"
                ),
                container_path,
            ),
            timeout=15,
        )
        if container_result.returncode:
            record["container_sha256"] = None
        else:
            lines = container_result.stdout.strip().splitlines()
            record["container_size"] = int(lines[0])
            record["container_sha256"] = lines[1]
        record["match"] = bool(
            len(content)
            and record["host_sha256"]
            == record.get("head_sha256")
            == record.get("container_sha256")
        )
        all_match = all_match and record["match"]
        records.append(record)
    return records, all_match, parse_failure


def classify(report: Report) -> str:
    source = report.evidence["source"]
    runtime = report.evidence["runtime"]
    service = report.evidence["service"]
    data = report.evidence["data"]
    source_match = source.get("all_match") is True
    parse_failure = source.get("parse_failure") is True
    postgres_green = data.get("green") is True
    supervisor = runtime.get("supervisor_present") is True
    child = runtime.get("application_child_present") is True
    listener = runtime.get("listener_present") is True
    docker_healthy = runtime.get("health") == "healthy"
    direct = service.get("internal", {}).get("ok") is True
    proxy = service.get("proxy", {}).get("ok") is True
    traceback = runtime.get("startup_failure_signature") is True
    git_clean = report.evidence["git"].get("clean") is True

    competing = sum(
        (
            not source_match or not git_clean,
            parse_failure or (traceback and not child),
            not postgres_green,
        )
    )
    if competing > 1:
        return "inconclusive"
    if not source_match or not git_clean:
        return "source_mismatch"
    if parse_failure or (traceback and not child and not supervisor):
        return "current_code_startup_failure"
    if not postgres_green:
        return "postgres_environment_incident"
    if (
        supervisor
        and not child
        and traceback
        and not direct
        and not proxy
        and runtime.get("state") == "running"
    ):
        return "reload_only_failure"
    if child and listener and direct and proxy and not docker_healthy:
        return "healthcheck_only_failure"
    if (
        runtime.get("state") == "running"
        and docker_healthy
        and supervisor
        and child
        and listener
        and direct
        and proxy
        and postgres_green
    ):
        return "healthy"
    return "inconclusive"


def gather(args: argparse.Namespace, executor: CommandExecutor) -> Report:
    report = Report(
        inputs={
            "backend_container_id": args.backend_container_id,
            "postgres_container_id": args.postgres_container_id,
            "source_files": list(args.source_file),
        }
    )
    branch = command(executor, ("git", "branch", "--show-current"))
    head = command(executor, ("git", "rev-parse", "HEAD"))
    upstream_result = executor.run(("git", "rev-parse", "@{upstream}"), timeout=15)
    upstream = (
        upstream_result.stdout.strip() if upstream_result.returncode == 0 else None
    )
    status = command(
        executor,
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
    )
    report.evidence["git"] = {
        "branch": branch,
        "head": head,
        "upstream": upstream,
        "clean": not status,
    }

    backend_item, backend = inspect_container(executor, args.backend_container_id)
    _, postgres = inspect_container(executor, args.postgres_container_id)
    mounts = backend_item.get("Mounts") or []
    bind = next(
        (
            mount
            for mount in mounts
            if mount.get("Type") == "bind" and mount.get("Destination") == "/app"
        ),
        None,
    )
    source_records, source_match, parse_failure = gather_source(
        executor, args.backend_container_id, args.source_file
    )
    report.evidence["source"] = {
        "bind_source": bind.get("Source") if bind else None,
        "bind_target": bind.get("Destination") if bind else None,
        "bind_matches_repository": bool(
            bind and Path(str(bind.get("Source"))).resolve() == BACKEND_ROOT.resolve()
        ),
        "files": source_records,
        "all_match": source_match
        and bool(bind)
        and Path(str(bind.get("Source"))).resolve() == BACKEND_ROOT.resolve(),
        "parse_failure": parse_failure,
        "bytecode_writes": False,
    }

    processes = command(
        executor,
        (
            "docker",
            "top",
            args.backend_container_id,
            "-eo",
            "pid,ppid,stat,lstart,args",
        ),
    )
    process_lines = processes.splitlines()[1:]
    supervisor_lines = [
        line for line in process_lines if "uvicorn" in line and "--reload" in line
    ]
    child_lines = [
        line
        for line in process_lines
        if "multiprocessing.spawn" in line or "spawn_main" in line
    ]
    zombies = [line for line in process_lines if re.search(r"\sZ\w*\s", line)]
    blocked = [line for line in process_lines if re.search(r"\sD\w*\s", line)]
    tcp = command(
        executor,
        (
            "docker",
            "exec",
            args.backend_container_id,
            "python",
            "-c",
            "from pathlib import Path;print(Path('/proc/net/tcp').read_text())",
        ),
    )
    listener = any(
        len(fields := line.split()) > 3
        and fields[1].endswith(":1F40")
        and fields[3] == "0A"
        for line in tcp.splitlines()[1:]
    )
    logs_result = executor.run(
        (
            "docker",
            "logs",
            "--timestamps",
            "--tail",
            "300",
            args.backend_container_id,
        ),
        timeout=20,
    )
    logs = sanitized((logs_result.stdout + "\n" + logs_result.stderr)[-30000:], report)
    backend.update(
        {
            "healthcheck": (backend_item.get("Config") or {}).get("Healthcheck"),
            "supervisor_present": bool(supervisor_lines),
            "application_child_present": bool(child_lines),
            "listener_present": listener,
            "zombie_processes": len(zombies),
            "blocked_processes": len(blocked),
            "processes": process_lines,
            "startup_failure_signature": bool(STARTUP_FAILURE_PATTERN.search(logs)),
            "recent_logs": logs,
        }
    )
    report.evidence["runtime"] = backend

    internal = http_probe(
        executor,
        (
            "docker",
            "exec",
            args.backend_container_id,
            "python",
            "-c",
            (
                "import urllib.request;"
                "r=urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3);"
                "print(r.read().decode());print('STATUS='+str(r.status))"
            ),
        ),
    )
    proxy = http_probe(
        executor,
        (
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "3",
            "--write-out",
            "\nSTATUS=%{http_code}\n",
            "http://127.0.0.1:8080/api/health",
        ),
    )
    internal["output"] = sanitized(internal["output"], report)
    proxy["output"] = sanitized(proxy["output"], report)
    report.evidence["service"] = {"internal": internal, "proxy": proxy}

    schema = parse_schema_status(
        command(executor, dev_compose_command("schema-status"), timeout=60)
    )
    data_green = bool(
        postgres["id"] == args.postgres_container_id
        and postgres["state"] == "running"
        and postgres["health"] == "healthy"
        and postgres["restart_count"] == 0
        and not postgres["oom_killed"]
        and schema["status"] == "complete"
        and schema["alembic_head"] == EXPECTED_ALEMBIC_HEAD
        and schema["explicit_rollback"]
        and schema["max_cardinality"] == 1
        and schema["dangling"] == 0
    )
    report.evidence["data"] = {
        "postgres": postgres,
        "baseline": schema,
        "green": data_green,
    }
    report.classification = classify(report)
    report.exit_code = EXIT_CODES[report.classification]
    report.summary = {
        "healthy": "Source, runtime, service, and data layers are Green.",
        "source_mismatch": "Host, container, Git source, or cleanliness differs.",
        "current_code_startup_failure": "Current source has a deterministic startup failure.",
        "reload_only_failure": "Reload supervisor survived without a serving child.",
        "healthcheck_only_failure": "Application serves while Docker health is failing.",
        "postgres_environment_incident": "PostgreSQL identity or sealed baseline is not Green.",
        "inconclusive": "Evidence is incomplete, contradictory, or unsupported.",
    }[report.classification]
    report.findings.append(
        Finding(
            layer="overall",
            code=report.classification,
            severity="info" if report.classification == "healthy" else "error",
            evidence_classification="Verified Fact",
            message=report.summary,
        )
    )
    return report


def render_text(report: Report) -> str:
    lines = [
        "Backend runtime health",
        f"Classification: {report.classification}",
        f"Exit code: {report.exit_code}",
        f"Summary: {report.summary}",
    ]
    for finding in report.findings:
        lines.append(f"[{finding.layer}] {finding.code}: {finding.message}")
    for error in report.errors:
        lines.append(f"ERROR: {error}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    executor = CommandExecutor()
    try:
        report = gather(args, executor)
    except (
        CheckerFailure,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        report = Report(
            classification="inconclusive",
            exit_code=15,
            summary="Evidence collection failed closed.",
            inputs={
                "backend_container_id": args.backend_container_id,
                "postgres_container_id": args.postgres_container_id,
                "source_files": list(args.source_file),
            },
            errors=[str(exc)],
        )
    if args.output == "json":
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
