"""Add missing firebase_uid unique constraint (Trust Foundation Phase 0)

Revision ID: b3f8e6a2c9d4
Revises: d7e1b4c9f2a5
Create Date: 2026-08-28 00:00:00.000000

Trust Foundation Audit (Section Q) found the two identity tables in
OPPOSITE, undocumented constraint states across environments:

    users.firebase_uid      -- model declares unique=True, but NO
                                constraint actually exists in production
                                (confirmed via pg_indexes/pg_constraint,
                                not the model). Local dev DBs created via
                                db.create_all() DO already have it
                                (ix_users_firebase_uid), since db.create_all()
                                honors the model -- only Alembic-managed
                                environments (production) are missing it,
                                because no migration ever added it.

    app_users.firebase_uid  -- model declares NO uniqueness at all, but a
                                real UNIQUE constraint (unique_firebase_uid)
                                already exists in production -- added
                                directly to the database, outside any
                                migration, at some point in the past. Local
                                dev DBs created via db.create_all() do NOT
                                have it, since the model never declared it.

Preflight (re-run immediately before writing this migration, read-only,
against production): zero duplicate firebase_uid values in either table,
0/442 NULL in users, 177/581 NULL in app_users (expected -- many profiles
have never been linked to a Firebase login). Safe to add a constraint on
non-null values in both tables.

This migration is deliberately environment-agnostic rather than assuming
either "constraint already exists" or "constraint is missing" -- each
table's own upgrade() step queries pg_indexes for ANY existing unique
index already covering (firebase_uid) before creating a new one, so it
never issues CREATE INDEX CONCURRENTLY for a constraint some environment
already has under a different name (specifically: production's own
pre-existing `unique_firebase_uid` on app_users must never be duplicated
by a second, redundantly-named index here).

CONCURRENTLY is required on both sides: users has 442 live rows with
active logins in production; creating a blocking index there would lock
out authentication traffic for the build duration. CONCURRENTLY cannot
run inside a transaction block, so both CREATE INDEX statements run
inside op.get_context().autocommit_block() -- the standard Alembic
pattern for exactly this Postgres restriction.

Partial index (WHERE firebase_uid IS NOT NULL) rather than a plain
UNIQUE constraint: matches Postgres's own multiple-NULLs-allowed
semantics explicitly, and keeps the intent readable without depending on
that default being remembered correctly later.

Reversible: downgrade() drops ONLY the specifically-named indexes this
migration might have created (unique_users_firebase_uid /
unique_app_users_firebase_uid) -- it never touches app_users' pre-existing
unique_firebase_uid, which this migration did not create and must not
remove on rollback.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3f8e6a2c9d4'
down_revision = 'd7e1b4c9f2a5'
branch_labels = None
depends_on = None


_NEW_INDEX_NAMES = {
    "users": "unique_users_firebase_uid",
    "app_users": "unique_app_users_firebase_uid",
}


def _has_existing_unique_firebase_uid_index(bind, table_name: str) -> bool:
    """
    True if ANY unique index already covers (firebase_uid) on this table,
    under any name -- e.g. production's app_users.unique_firebase_uid, or
    a local dev DB's users.ix_users_firebase_uid. Queried by name-agnostic
    definition match, not a fixed index name, so this migration correctly
    recognizes a constraint it did not itself create.
    """
    result = bind.execute(
        sa.text(
            """
            SELECT 1 FROM pg_indexes
            WHERE tablename = :table_name
              AND indexdef ILIKE '%UNIQUE%'
              AND indexdef ILIKE '%(firebase_uid)%'
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).fetchone()
    return result is not None


def upgrade():
    """Add a unique index on firebase_uid for whichever of users/app_users
    doesn't already have one -- never both blindly, never redundantly."""
    bind = op.get_bind()

    for table_name, new_index_name in _NEW_INDEX_NAMES.items():
        if _has_existing_unique_firebase_uid_index(bind, table_name):
            # Already constrained under some name (production's app_users,
            # or a local dev DB's users) -- nothing to do for this table.
            continue

        with op.get_context().autocommit_block():
            op.execute(
                sa.text(
                    f"""
                    CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {new_index_name}
                    ON {table_name} (firebase_uid)
                    WHERE firebase_uid IS NOT NULL
                    """
                )
            )


def downgrade():
    """Drop ONLY the indexes this migration might have created, by their
    specific fixed names. Never touches app_users.unique_firebase_uid --
    this migration did not create it and must not remove it."""
    for new_index_name in _NEW_INDEX_NAMES.values():
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {new_index_name}")
