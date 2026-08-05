import argparse
import asyncio

from app.db.init_db import bootstrap_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicitly seed an already-migrated database."
    )
    parser.add_argument(
        "--confirm-database-name",
        required=True,
        help="Must exactly match the configured DB_NAME.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        bootstrap_db(confirmed_database_name=args.confirm_database_name)
    )
