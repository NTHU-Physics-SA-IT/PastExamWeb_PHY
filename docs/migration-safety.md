# Alembic migration safety

`alembic_version` is a migration ledger, not a description of the live
schema. If a non-empty database loses that ledger, a direct
`alembic upgrade head` may replay the chain from `base` and collide with
existing objects. Stamping `head` based on table names is also unsafe because
columns, constraints, indexes, enum values, defaults, or data migrations may
still be missing.

## Safe commands

Run from `backend/`:

```bash
uv run python migrate.py preflight
uv run python migrate.py preflight --json
uv run python migrate.py upgrade
uv run python migrate.py reconcile --check
uv run python migrate.py reconcile --check --json
uv run python audit.py run \
  --audit archive-submission-self-delete-eligibility \
  --mode isolated-test
uv run python audit.py run \
  --audit archive-report-active-pending-uniqueness \
  --mode persistent-local --expected-ledger f3a7c1e9d5b2
```

All preflight and reconciliation checks are read-only. Production-style
upgrades must use this CLI rather than invoking Alembic directly. The CLI
holds a PostgreSQL advisory lock across preflight, upgrade, and postflight,
and verifies that every phase targets the same database. A concurrent
migration fails without entering Alembic. This repository provides no stamp
or repair command.

`upgrade` is allowed only when:

- the database is truly empty and has no ledger revision;
- the repository has exactly one head, the database ledger contains exactly
  that head, and the complete head-schema comparison passes; or
- the database is at an explicitly reviewed forward-migration source revision
  and its complete revision-specific schema manifest passes.

Known ancestors without a reviewed manifest, unknown revisions, multiple
ledger rows, multiple repository heads, a non-empty database without a
ledger, source drift, and head drift all fail closed. A migration or
postflight error exits non-zero.

Reviewed manifests currently cover:

- `c4d8e2f1a6b9`: a reviewed legacy schema captured from an isolated,
  read-only restore;
- `a4c7e9d2f6b1`: the reviewed pre-canonicalization test baseline;
- `c9e4f1a7b2d6`: the canonical-category schema before metadata alignment;
- `e3b7c1d9f5a2`: the reviewed schema before the archive-report workflow;
- `a7c3e9f1b5d2`: the reviewed schema before persisted ArchiveSubmission
  owner-self-delete eligibility;
- `f5e1d8c3a7b2`: the reviewed schema before typed ArchiveSubmission previous
  status;
- `d8f2a6c1b4e7`: the reviewed schema before the ArchiveSubmission/Archive
  one-to-one constraint; and
- `6f3a9c2d8e41`: the reviewed schema before NTHU OAuth provider-identity
  uniqueness;
- `9f1c2a7e4b63`: the reviewed schema before persisted NTHU student ID; and
- `b7e3d9a1c5f2`: the reviewed schema before bilingual course catalog fields;
  and
- `c2a8e4f6b9d1`: the reviewed schema before bilingual ArchiveSubmission
  presentation snapshots; and
- `d4b7e2a9c6f1`: the reviewed schema before About Us entries; and
- `e6a1b3c5d7f9`: the reviewed schema before both known sibling branches;
- `e8a4c1d7b2f6`: the reviewed Category-state sibling source before
  CourseSubmission lifecycle independence;
- `a9c2e5f7b1d4`: the reviewed Stage 5D sibling head;
- `a9c4e7b2d6f1`: the reviewed bilingual managed-content and Wish Pool sibling
  head; and
- `b4d6f8a2c1e3`: the merged schema before optional Wish academic year; and
- `f3a7c1e9d5b2`: the reviewed schema before persisted About Us ordering; and
- `c7e4a9b2d6f1`: the schema before active-pending ArchiveReport uniqueness
  excludes trashed rows; and
- `c8e4a1f7b2d9`: the current repository head and SQLModel metadata contract.

These are not claims about a live production revision. An unrecognized
production revision must remain blocked until a separately authorized,
read-only inspection produces a reviewed manifest.

## What is compared

The head assessment compares:

- tables and columns;
- PostgreSQL data types and nullability;
- primary keys and foreign keys, including delete behavior;
- unique and check constraints;
- indexes, including uniqueness and partial-index predicates;
- server defaults;
- PostgreSQL enum types and values;
- the database ledger revision and repository heads.

Any missing, unexpected, ambiguous, or unsupported structure fails closed.
Errors and JSON reports omit database URLs and redact configured passwords.

## Missing ledger

For a non-empty database without `alembic_version`,
`reconcile --check` may report a structural head candidate only when every
schema check matches. The command still exits non-zero because schema equality
cannot prove that historical data migrations ran. It never creates a ledger,
stamps a revision, changes data, or upgrades the schema.

Recovery requires a separately reviewed procedure and verified backup outside
this automation. Do not add `stamp`, repair logic, or reconciliation to a
container startup command.

## Startup, bootstrap, and Compose boundaries

Normal backend startup calls only the read-only readiness check. It never
runs Alembic, `create_all`, seed synchronization, bootstrap, or stamp. Missing
or drifting schema makes the process fail fast.

Fresh isolated development/test databases may be seeded only with the
explicit bootstrap command:

```bash
ALLOW_DATABASE_BOOTSTRAP=true \
uv run python -m app.scripts.seed_db \
  --confirm-database-name archive_db_dev_example
```

The database name must use an approved dev/test prefix. The canonical local
Compose exception is the exact `pastexam-dev` project using `archive_db`, the
internal `db` host, and a loopback frontend URL; production Compose does not
provide that local-project attestation. Migration and postflight must already
pass, and the first run permits only the six
migration-created canonical categories with otherwise empty application
tables. A durable marker makes later explicit runs idempotent.

The six canonical category keys are identity anchors, not immutable display
content. Category `name`, `label`, `icon`, `badge_color`, ordering, active
state, and trash/restore metadata remain database-managed. Custom rows are
also database-managed and do not need to be added to application constants.
The missing-row default for `math-department` is `戳戳數學系` with label
`數學`.

Category migrations only convert the documented legacy keys and their key
references. They preserve administrator metadata and submission snapshot
fields. Ambiguous canonical/legacy rows or normalized-name collisions abort
the transaction; migrations never choose a row by ID or delete a conflicting
row automatically.

The ArchiveSubmission owner-self-delete eligibility migration classifies the
reviewed source rows before adding its non-null boolean. Historical owner
self-deletes, active restored rows with cleared deletion provenance, and
currently identifiable administrator-deleted rows are conservatively
backfilled as consumed. Metadata-consistent historical system/cascade rows
using the tracked linked-Archive permanent-deletion format are also
conservatively backfilled as consumed; future system/cascade deletion preserves
the existing value and remains application-milestone work. Clean active rows
are not consumed. Unknown actor/reason combinations, mismatched system
metadata, ownership or lifecycle contradictions, overlapping buckets,
unclassified rows, and conservation failures abort the PostgreSQL transaction.
The migration does not infer one submission's value from a shared Archive and
does not modify Archive, ownership, review, delete, or restore metadata.

The ArchiveSubmission/Archive one-to-one migration adds the named standard
nullable unique constraint
`uq_archive_submissions_created_archive_id`. Before DDL it locks the source
table and performs bounded aggregate checks for duplicate non-null links and
dangling Archive references. Any anomaly aborts the transaction with counts
only; the migration never exposes relationship IDs, chooses a canonical
submission, clears or reassigns a link, duplicates an Archive, or rewrites
application rows. Multiple null links remain valid. Downgrade removes only
the named unique constraint and preserves the existing foreign key, rows,
links, primary keys, and sequences.

The NTHU OAuth identity migration adds the named standard nullable unique
constraint `uq_users_oauth_provider_sub` on
`users(oauth_provider, oauth_sub)`. Before DDL it verifies the exact reviewed
source revision and column shape, locks `users` in
`SHARE ROW EXCLUSIVE` mode, and performs one aggregate-only duplicate check
over non-null provider/sub pairs. Any duplicate aborts with counts only; the
migration does not expose identity values, select a winner, link accounts, or
rewrite rows. Multiple local `(NULL, NULL)` identities remain valid. Downgrade
removes only the named constraint and preserves every User row and identity
value.

The NTHU student-ID migration adds only nullable `users.student_id` as
`VARCHAR(255)`, with no default, index, uniqueness rule, or backfill. Existing
and local User rows therefore remain null, and NTHU UUID provider identity is
unchanged. Upgrade verifies the exact reviewed source revision and source
columns before DDL, then validates the new type and nullability. Downgrade
removes only this attribute column and preserves all User rows and provider
identity values.

The bilingual course-catalog migration adds only nullable `courses.name_en`
and nullable `course_category_configs.name_en` / `label_en`. It preserves the
canonical Chinese fields, category keys, course identities, ordering, archive
relationships, and custom rows. The reviewed upgrade backfills exactly the 71
canonical course mappings when the source Course table is non-empty, and
always backfills the six canonical category mappings. A non-empty Course table
with a missing canonical source row, or a missing canonical category row,
aborts without partial application. A fresh database with an empty Course
table remains migration-safe because course creation belongs to the explicit
bootstrap boundary. Downgrade drops only the three additive English display
columns.

The bilingual ArchiveSubmission snapshot migration adds only nullable
`requested_course_name_en`, `requested_category_name_en`, and
`requested_category_label_en` columns. Existing rows remain null and retain
their existing Chinese snapshots. New submissions copy English metadata only
from the canonical Course and CourseCategory records selected at submission
time; missing English metadata remains null.

The About Us migration adds only the dedicated `about_us_entries` table and
its update-order/editor indexes. It backfills or rewrites no existing rows,
keeps its editor reference nullable with `ON DELETE SET NULL`, and downgrade
removes only that new table and its indexes.

The About Us ordering migration adds one non-null integer `order_index` and its
non-unique lookup index. It preserves the previously configured presentation
order by backfilling `updated_at DESC, id DESC` to contiguous zero-based
indexes while the table is locked. Newer entries subsequently start at index
zero and administrator reorder operations persist the complete sequence.
Downgrade removes only the ordering index and column; legacy title/body data is
unchanged.

The optional Wish-semester migration changes only
`archive_wishes.academic_year` from non-null to nullable. It adds no sentinel,
default, or backfill, so every existing value and target meaning is preserved.
Downgrade fails closed while Any Semester rows exist instead of deleting or
rewriting them.

The Category state-preservation migration follows the About Us revision. It
adds nullable `course_category_configs.pre_delete_is_active`, leaves live rows
unchanged, snapshots the prior active state of deleted rows, and makes every
deleted Category inactive. Upgrade and downgrade reject malformed lifecycle
rows rather than guessing. Downgrade returns only to the About Us revision:
it restores deleted rows' representable pre-D1 active state, removes only the
snapshot column, and preserves the About Us table and its contents.
The ArchiveReport active-pending uniqueness migration replaces only the named
partial index predicate, from `status = 'pending'` to
`status = 'pending' AND deleted_at IS NULL`. It locks the table for the
bounded index transition, fails closed on source-schema drift or active
duplicate scopes, and never deletes or rewrites report history. Downgrade
restores the older predicate only when every active and trashed pending row can
satisfy it; otherwise the PostgreSQL transaction aborts unchanged. The sealed
`archive-report-active-pending-uniqueness` audit reports aggregate duplicate,
trashed, mixed-scope, restore-conflict, detached-identity, and index-contract
counts without returning identifiers or report content.


On the first bootstrap, one missing canonical key or any extra custom category
is evidence that the database is not the expected clean initialized target,
so bootstrap fails without creating an administrator or marker. After the
marker exists, missing canonical keys are recreated from defaults, while
existing and custom rows are left unchanged. Legacy keys and same-name
different-key conflicts still fail closed.

The default administrator password is applied only while creating the named
default account or restoring it from soft deletion. Restoration intentionally
resets the password and is therefore a sensitive dev/test operation. A normal
account retains its password and email. A renamed account still holding the
configured default email causes an explicit conflict error; if both configured
identity fields were changed, bootstrap can create a separate default account.

Development and production Compose definitions use a
one-shot `migrate` service running `python migrate.py upgrade`. Backend
startup depends on `service_completed_successfully`; the migrate service has
no seed command, fixed container name, or restart loop.

Destructive tests additionally require an explicit `TEST_DATABASE_URL`, an
isolation marker, approved host/database/role prefixes, a database owned by
the connected non-superuser test role, and a target distinct from runtime
configuration. They never fall back to `DATABASE_URL` or `archive_db`.

## Bounded read-only aggregate audits

`backend/audit.py` is the sealed audit entry point. It accepts only registered
audit IDs and versions; callers cannot provide SQL, table names, output fields,
retry behavior, or free-form predicates. A versioned adapter owns historical
constants and aggregate predicates independently of application services, and
focused parity tests keep a migration-specific adapter aligned with its
reviewed migration classifier. Adding a classifier requires a new registered
version and synthetic PostgreSQL evidence.

Adapter version 4 supports the reviewed bilingual revisions
`c2a8e4f6b9d1`, `d4b7e2a9c6f1`, `e6a1b3c5d7f9`, and `e8a4c1d7b2f6`. It
preserves the version 3 ArchiveSubmission lifecycle classifier and aggregate
fingerprints, while its continuity gate additionally requires the
revision-appropriate nullable English catalog and submission-snapshot columns.
The e8 revision also requires the nullable Category lifecycle snapshot; e6 and
all older revisions require that column to be absent. Versions 1 through 3
retain their historical revision bounds.

Every execution sends one complete input stream to non-interactive `psql` and
uses `ON_ERROR_STOP`, `REPEATABLE READ READ ONLY`, statement/lock/idle
timeouts, environment identity checks, a one-row ledger check, targeted schema
and enum continuity (including `pg_enum.enumlabel::text`), aggregate-only
classification, mutual-exclusivity and conservation checks, explicit
`ROLLBACK`, and a final completion sentinel. It creates no server file,
temporary object, lock, function, or persistent state and never emits row IDs,
PII, raw free-text reasons, or timestamps.

The strict machine-readable result distinguishes `complete`, `data_blocked`,
`audit_error`, and `incomplete_transport`. Human output is derived from the
same validated object and does not query again. Unknown fields, more than the
bounded combination count, an unexpected revision/environment/enum, a write
token, a timeout, a psql error, missing rollback, or truncated transport fails
closed. There is no implicit retry or repair operation.

Modes remain separate:

- isolated test mode reuses the destructive-test identity guard;
- persistent-local mode requires the exact healthy `pastexam-dev` PostgreSQL
  container and never migrates or repairs it; and
- production aggregate-only mode requires both task-level authorization and
  the explicit CLI production gate, plus the exact production container
  identity. Merely selecting the mode is not production authority.

This runner is not a SQL shell, migration wrapper, schema reconciliation
replacement, data remediation tool, production repair tool, or generic
database console.

For the persistent local stack, invoke the same sealed adapter through
`scripts/dev-compose.sh schema-status`. `backend-resume` runs that compatibility
gate before starting an existing paused backend; it never creates a container
or performs an upgrade. `backend-pause` and `backend-resume` are deliberate
schema-branch controls, not general restart shortcuts.

For isolated validation on a schema-changing branch only,
`schema-status --expected-ledger <revision>` exposes the audit runner's existing
read-only ledger selection. The isolated test runner first requires that the
revision have a reviewed manifest, be a legal Alembic ancestor of the single
repository head, and be supported by the sealed audit. The selected value is
the canonical persistent pre/post baseline only; callers cannot override the
ephemeral migration target, which remains the repository head. Unknown,
unreviewed, non-ancestor, schema-drifting, or checksum-changing baselines fail
before or during the guarded run. Persistent migration remains a later,
separately authorized operation after isolated branch evidence is Green.

## Migration-chain rule

Published or deployed revision files are immutable. Add a new revision for
future schema changes and update the models in the same change. An unpublished
revision isolated to an unmerged development branch may be corrected before
release only after history and tag checks prove it has not shipped. Extend the
focused migration safety scenarios whenever a new PostgreSQL enum, persistent
server default, partial index, or other schema feature changes the head
manifest.

### ADR-0008 exact sibling-convergence exception

[ADR-0008](decisions/0008-narrow-sibling-migration-convergence-exception.md)
is the sole accepted exception to the immutability rule above. It applies only
to the pre-DDL source-compatibility guard behavior of these exact revisions:

- `e8a4c1d7b2f6`;
- `a9c2e5f7b1d4`; and
- `a9c4e7b2d6f1`.

Revision IDs, `down_revision` identities and order, `branch_labels`,
`depends_on`, schema DDL, data backfill or transformation intent, named
constraint and index intent, locking intent, post-upgrade target-schema
intent, and downgrade schema and data intent remain immutable.

An implementation may recognize only finite, mechanically enumerated sibling
states for which it proves both the exact expected migration-ledger or
transition identity and the exact sibling-specific schema continuity. Ledger
identity alone is insufficient. Unknown, partial, malformed,
unexpected-multiple, unreviewed, or schema-inconsistent states fail closed.

The implemented finite compatibility states are:

- `e8a4c1d7b2f6` accepts its normal exact `e6a1b3c5d7f9` source or the exact
  `a9c4e7b2d6f1` sibling ledger with complete Wish Pool/bilingual continuity;
- `a9c2e5f7b1d4` accepts its normal exact `e8a4c1d7b2f6` source or the exact
  two-row `e8a4c1d7b2f6` plus `a9c4e7b2d6f1` Alembic transition with complete
  Category and Wish Pool continuity; and
- `a9c4e7b2d6f1` accepts its normal exact `e6a1b3c5d7f9` source or the exact
  `a9c2e5f7b1d4` sibling ledger with complete Category and CourseSubmission
  lifecycle continuity.

The no-op topology revision `b4d6f8a2c1e3` joins the two sibling heads. Tests
prove that databases starting at `e6a1b3c5d7f9`, `a9c2e5f7b1d4`, or
`a9c4e7b2d6f1` converge to that single head without `alembic stamp`, manual
`alembic_version` repair, skipped or fictitious DDL, or reparenting or deletion
of accepted revisions. Unknown, partial, malformed, or schema-inconsistent
states still fail closed.

This exception does not permit arbitrary future sibling branches and does not
authorize production or canonical-local migration or deployment.
