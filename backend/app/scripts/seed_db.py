import argparse
import asyncio

from app.core.bootstrap_config import BootstrapSettings
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


def main() -> None:
    args = parse_args()
    bootstrap_settings = BootstrapSettings()
    asyncio.run(
        bootstrap_db(
            confirmed_database_name=args.confirm_database_name,
            bootstrap_password=(
                bootstrap_settings.BOOTSTRAP_ADMIN_PASSWORD.get_secret_value()
            ),
        )
    )


if __name__ == "__main__":
    main()
