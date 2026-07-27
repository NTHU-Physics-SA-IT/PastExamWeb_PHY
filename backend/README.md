# pastexam API

1. Install [uv](https://docs.astral.sh/uv) if it is not already available:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. From the `backend` directory, run:

   ```bash
   uv sync
   uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. Open [http://localhost:8000/docs](http://localhost:8000/docs) to load Swagger UI and exercise the API endpoints.

## Updating the Database Schema

1. Update the models

   Edit `backend/app/models/models.py`:

   ```python
   # Example: add a new column
   class User(SQLModel, table=True):
      id: Optional[int] = Field(default=None, primary_key=True)
      name: str
      email: str
      # New column
      phone: Optional[str] = None  # Added column
   ```

2. Create a migration

   ```bash
   cd backend
   uv run migrate.py create "Add phone field to User table"
   ```

3. Inspect the generated migration

   Check the new file under `backend/alembic/versions/` to ensure the diff is correct.

4. Apply the migration

   ```bash
   uv run migrate.py upgrade

   docker compose down
   docker compose up -d
   ```

## Migration Management Commands

Read the repository [migration safety runbook](../docs/migration-safety.md)
before operating on an existing database. `migrate.py upgrade` performs a
read-only, fail-closed preflight and never stamps or repairs a ledger.

```bash
cd backend

# Create a new migration
uv run migrate.py create "Your migration message"

# Apply all pending migrations
uv run migrate.py preflight
uv run migrate.py upgrade

# Explicitly initialize local/test seed data after migration.
# Bootstrap is disabled by default and is never run during API startup.
ALLOW_DATABASE_BOOTSTRAP=true \
  uv run python -m app.scripts.seed_db --confirm-database-name <database_name>

# Read-only assessment for a non-empty database with a missing ledger
uv run migrate.py reconcile --check

# Show the current database revision
uv run migrate.py current

# Show migration history
uv run migrate.py history

# Downgrade to a specific revision (use with caution!)
uv run migrate.py downgrade <revision_id>
```

Migrations and bootstrap have separate responsibilities. Migrations create or
change schema, canonicalize the legacy category keys, and add a base category
only when no canonical or legacy row exists. They preserve administrator-owned
category display metadata and custom categories. `math-department` uses
`戳戳數學系` / `數學` only as its missing-row default.

The explicit dev/test bootstrap requires a migration-complete database. Its
first run accepts exactly the six migration-created canonical categories and
otherwise empty application tables, then writes
`database.explicit_bootstrap.v1`. Later runs may restore a missing canonical
key from default metadata, but never overwrite an existing row or delete a
custom category such as `web-development` / `網站架設`. A legacy key or a
default-name collision fails closed and must be resolved through a reviewed
migration.

`DEFAULT_ADMIN_PASSWORD` is used only when explicit bootstrap creates the
named default administrator or restores that same soft-deleted account. An
active account with `DEFAULT_ADMIN_NAME` keeps its current email and password.
If the named account is absent but `DEFAULT_ADMIN_EMAIL` belongs to a renamed
account, bootstrap fails before changing any user. If both name and email were
changed, a later explicit dev/test bootstrap may create another default
administrator.
