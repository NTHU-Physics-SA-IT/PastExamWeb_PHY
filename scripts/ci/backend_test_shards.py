#!/usr/bin/env python3
"""Validate and resolve the canonical backend test-file partition."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any


SHARD_NAMES = ("a", "b")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("backend-test-shards.json")


class BackendShardManifestError(ValueError):
    """The backend test shard manifest is incomplete or malformed."""


@dataclass(frozen=True)
class BackendShardManifest:
    paths_by_shard: dict[str, tuple[str, ...]]

    @property
    def all_paths(self) -> tuple[str, ...]:
        return tuple(
            path for shard in SHARD_NAMES for path in self.paths_by_shard[shard]
        )

    def paths_for_shard(self, shard: str) -> tuple[str, ...]:
        if shard not in SHARD_NAMES:
            raise BackendShardManifestError(f"unknown backend test shard: {shard}")
        return self.paths_by_shard[shard]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BackendShardManifestError(
            f"unable to read backend shard manifest: {error}"
        ) from error


def _validate_path(path: Any) -> str:
    if not isinstance(path, str) or not path:
        raise BackendShardManifestError("backend shard paths must be non-empty strings")
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or pure.as_posix() != path
        or ".." in pure.parts
        or len(pure.parts) < 2
        or pure.parts[0] != "tests"
        or not pure.name.startswith("test_")
        or pure.suffix != ".py"
    ):
        raise BackendShardManifestError(f"invalid backend test path: {path}")
    return path


def load_manifest(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> BackendShardManifest:
    payload = _load_json(manifest_path)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "shards"}:
        raise BackendShardManifestError("backend shard manifest keys are invalid")
    if payload["schema_version"] != 1:
        raise BackendShardManifestError("unsupported backend shard manifest version")

    shards = payload["shards"]
    if not isinstance(shards, dict) or set(shards) != set(SHARD_NAMES):
        raise BackendShardManifestError(
            "backend shard manifest must define exactly shards a and b"
        )

    paths_by_shard: dict[str, tuple[str, ...]] = {}
    assigned_to: dict[str, str] = {}
    for shard in SHARD_NAMES:
        raw_paths = shards[shard]
        if not isinstance(raw_paths, list) or not raw_paths:
            raise BackendShardManifestError(f"backend shard {shard} must be non-empty")
        paths = tuple(_validate_path(path) for path in raw_paths)
        for path in paths:
            prior = assigned_to.get(path)
            if prior is not None:
                raise BackendShardManifestError(
                    f"duplicate backend test path in shards {prior} and {shard}: {path}"
                )
            assigned_to[path] = shard
        paths_by_shard[shard] = paths

    backend_root = repository_root / "backend"
    discovered = {
        path.relative_to(backend_root).as_posix()
        for path in backend_root.glob("tests/**/test_*.py")
        if path.is_file()
    }
    assigned = set(assigned_to)
    nonexistent = sorted(assigned - discovered)
    missing = sorted(discovered - assigned)
    if nonexistent:
        raise BackendShardManifestError(
            "nonexistent backend test paths: " + ", ".join(nonexistent)
        )
    if missing:
        raise BackendShardManifestError(
            "unassigned backend test paths: " + ", ".join(missing)
        )

    return BackendShardManifest(paths_by_shard=paths_by_shard)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    paths = subparsers.add_parser("paths")
    paths.add_argument("--shard", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        manifest = load_manifest(
            repository_root=arguments.repository_root.resolve(),
            manifest_path=arguments.manifest.resolve(),
        )
        if arguments.command == "validate":
            print(
                f"Validated {len(manifest.all_paths)} backend test files "
                "across shards a and b."
            )
        else:
            for path in manifest.paths_for_shard(arguments.shard):
                print(path)
    except BackendShardManifestError as error:
        print(f"Backend shard manifest validation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
