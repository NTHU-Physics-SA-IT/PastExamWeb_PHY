"""Capture a normalized, read-only schema manifest for review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, text

from app.db.migration_safety import capture_live_schema, database_url


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--revision", required=True)
    cli.add_argument("--output", type=Path, required=True)
    return cli


def main() -> int:
    args = parser().parse_args()
    engine = create_engine(database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            revisions = list(
                connection.scalars(
                    text("SELECT version_num FROM alembic_version")
                )
            )
            if revisions != [args.revision]:
                raise RuntimeError(
                    "Connected database revision does not match requested manifest"
                )
            payload = {
                "manifest_version": 1,
                "revision": args.revision,
                "schema": capture_live_schema(connection),
            }
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
