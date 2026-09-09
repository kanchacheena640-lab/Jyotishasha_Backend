"""add user_dasha_timeline constraints and index

U4A.1 -- Dasha Foundation Safety + Persistence.

Adds the two structures the U4A architecture decision (and U4A.0's
empirical row-count/uniqueness proof) determined are necessary and
sufficient for user_dasha_timeline, which has had ZERO constraints or
indexes beyond its primary key since it was created
(15517af13390_add_user_dasha_timeline.py):

1. UNIQUE (user_id, mahadasha, antardasha) -- not the wider
   (user_id, mahadasha, antardasha, start_date, end_date) a first guess
   might reach for. Within one profile's single generated Vimshottari
   cycle, each (mahadasha_lord, antardasha_lord) pair occurs EXACTLY
   ONCE (proven empirically across 8 representative Moon degrees in
   U4A.0, and true by construction: both the outer Mahadasha loop and
   each Mahadasha's own inner Antardasha loop are permutations of the
   same 9 lords). Including start_date/end_date in the key would let a
   real corruption case slip through undetected -- the same
   (user_id, mahadasha, antardasha) pair inserted twice with two
   DIFFERENT computed date ranges (e.g. an old timeline not fully
   deleted before a birth-data-triggered recompute) -- so the tighter
   3-column key is deliberately used instead. Its own backing index
   also serves per-profile lookups (user_id is the leading column), so
   no separate single-column user_id index is added -- the same
   reasoning modules/alerts/persistence_models.py::AlertMicroEvent's
   own composite unique constraint already documents for itself.

2. INDEX (start_date, end_date) -- serves both existing bulk readers'
   actual query shapes (services/personalization_engine.py):
     get_current_dasha_users(): WHERE start_date <= :today
                                       AND end_date > :today
     get_users_for_dasha_change(): WHERE start_date == :target_date
   Neither of these filters by user_id, so this index (not the
   UNIQUE constraint's own) is what keeps them from a full-table scan.

LOCAL VERIFICATION BEFORE WRITING THIS MIGRATION (U4A.1 Section 4):
    SELECT count(*) FROM user_dasha_timeline;                  -> 0
    SELECT user_id, mahadasha, antardasha, count(*)
      FROM user_dasha_timeline
      GROUP BY user_id, mahadasha, antardasha HAVING count(*) > 1;
                                                                 -> 0 rows
The local table is currently completely empty (nothing has ever
populated it outside of test runs, which each clean up after
themselves) -- there is no duplicate/corrupt data for this UNIQUE
constraint to conflict with, and nothing was cleaned up or destroyed to
make this migration apply. This migration has not been run against
production and this task does not run it there.

Revision ID: 37fd90bfdfd5
Revises: 6816ff4a7cf5
Create Date: 2026-09-07
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '37fd90bfdfd5'
down_revision = '6816ff4a7cf5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        'uq_user_dasha_timeline_user_mahadasha_antardasha',
        'user_dasha_timeline',
        ['user_id', 'mahadasha', 'antardasha'],
    )
    op.create_index(
        'ix_user_dasha_timeline_start_end',
        'user_dasha_timeline',
        ['start_date', 'end_date'],
    )


def downgrade():
    op.drop_index('ix_user_dasha_timeline_start_end', table_name='user_dasha_timeline')
    op.drop_constraint(
        'uq_user_dasha_timeline_user_mahadasha_antardasha',
        'user_dasha_timeline',
        type_='unique',
    )
