#!/usr/bin/env python3

import argparse
import re
from pathlib import Path

FORBIDDEN_PRODUCTION_KEYS = frozenset({"DEFAULT_ADMIN_PASSWORD"})
ENVIRONMENT_KEY = re.compile(
    r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*="
)


def forbidden_keys(path: Path) -> set[str]:
    """Return forbidden key names without retaining or emitting their values."""
    found: set[str] = set()
    with path.open(encoding="utf-8") as environment_file:
        for line in environment_file:
            match = ENVIRONMENT_KEY.match(line)
            if match and match.group("key") in FORBIDDEN_PRODUCTION_KEYS:
                found.add(match.group("key"))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject forbidden keys in production environment files."
    )
    parser.add_argument("environment_files", nargs="+", type=Path)
    args = parser.parse_args()

    rejected = False
    for path in args.environment_files:
        for key in sorted(forbidden_keys(path)):
            rejected = True
            print(f"{path}: forbidden production environment key: {key}")
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
