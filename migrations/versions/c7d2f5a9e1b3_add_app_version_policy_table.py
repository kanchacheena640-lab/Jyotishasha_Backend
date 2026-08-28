"""Add app_version_policy table (Force Update system)

Revision ID: c7d2f5a9e1b3
Revises: b3f8e6a2c9d4
Create Date: 2026-08-28 00:00:00.000000

Creates modules/models_app_version_policy.py::AppVersionPolicy and seeds
exactly ONE row, for "android" -- the only platform this app ships.

SAFE INITIAL STATE (Ask Now Security + Force Update task, Part F):
seeded to the CURRENT, already-live production build, with force_update
False. This is deliberate and load-bearing -- seeding minimum_supported_
build any HIGHER than the live build would block the app for every user
already on it the instant this migration runs, before any client build
carrying the force-update checker itself has ever reached a single
device. (force_update itself is descriptive/UI-severity metadata only,
per the Safe Deployment Split's own correction -- see
modules/models_app_version_policy.py's own field docstring -- so it is
seeded False here purely for a sane, honest starting value, not because
True would itself have blocked anyone.) The exact value (48) was
confirmed against Play Console by the project owner, not guessed from
source (pubspec.yaml's working-tree version alone cannot prove what is
actually live).

Raising minimum_supported_build later is an operator action via
PATCH /admin/api/app-version-policy (routes/routes_app_version.py) --
never another migration -- once (and only once) the new build carrying
Ask Now's JWT header is confirmed publicly available on Google Play.

Environment-agnostic, same posture as migrations/versions/
b3f8e6a2c9d4_...py: this codebase's factory.py calls db.create_all() on
every app startup, which means a local/dev environment can already have
this exact table (empty, no seed row) the moment this model file exists
-- BEFORE this migration ever runs. upgrade() checks for the table's
existence (and separately, the seed row's) rather than assuming either
"nothing exists yet," so it behaves correctly whether this is a fresh
Alembic-only environment (production) or one where db.create_all() got
here first (local dev) -- confirmed by hitting exactly this state while
testing this migration.
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c7d2f5a9e1b3'
down_revision = 'b3f8e6a2c9d4'
branch_labels = None
depends_on = None

# Confirmed live production build at the time this migration was
# written -- see module docstring. NOT a guess.
_CURRENT_LIVE_ANDROID_BUILD = 48
_PACKAGE_ID = "com.jyotishasha.app"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'app_version_policy' not in inspector.get_table_names():
        op.create_table(
            'app_version_policy',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('platform', sa.String(length=20), nullable=False),
            sa.Column('minimum_supported_build', sa.Integer(), nullable=False),
            sa.Column('latest_build', sa.Integer(), nullable=False),
            sa.Column('force_update', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('store_url', sa.String(length=500), nullable=False),
            sa.Column('message', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('platform', name='uq_app_version_policy_platform'),
        )

    app_version_policy = sa.table(
        'app_version_policy',
        sa.column('platform', sa.String),
        sa.column('minimum_supported_build', sa.Integer),
        sa.column('latest_build', sa.Integer),
        sa.column('force_update', sa.Boolean),
        sa.column('store_url', sa.String),
        sa.column('message', sa.String),
        sa.column('created_at', sa.DateTime),
        sa.column('updated_at', sa.DateTime),
    )

    # Idempotent seed: only insert the "android" row if one doesn't
    # already exist (e.g. a re-run, or a db.create_all()'d table that
    # happens to already have been seeded some other way) -- never a
    # second row, never overwriting an operator's own already-applied
    # PATCH.
    existing = bind.execute(
        sa.text("SELECT 1 FROM app_version_policy WHERE platform = 'android'")
    ).fetchone()

    if existing is None:
        now = datetime.utcnow()
        op.bulk_insert(app_version_policy, [{
            'platform': 'android',
            # SAFE INITIAL STATE -- see module docstring. Both values
            # equal the current live build: nothing is blocked by this
            # migration.
            'minimum_supported_build': _CURRENT_LIVE_ANDROID_BUILD,
            'latest_build': _CURRENT_LIVE_ANDROID_BUILD,
            'force_update': False,
            'store_url': f'https://play.google.com/store/apps/details?id={_PACKAGE_ID}',
            'message': None,
            'created_at': now,
            'updated_at': now,
        }])


def downgrade():
    op.drop_table('app_version_policy')
