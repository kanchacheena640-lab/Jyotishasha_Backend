"""P0 -- Campaign C account-deletion privacy fix.

Dedicated file (not folded into test_account_deletion_service.py) because
NotificationCampaignBellItem/Delivery/Attempt need a REAL campaign +
execution (FK-backed) to seed against -- unlike every row in that other
file's seed_personal_children(), which only needs a bare profile_id.
test_account_deletion_service.py itself is untouched by P0 and remains the
authority for every non-Campaign-C scenario; its own pre-existing "Test 3:
multiple AppUser rows sharing ONE firebase_uid" fixture independently fails
against this local DB's `unique_app_users_firebase_uid` partial unique
index (confirmed unrelated to P0 -- it fails at fixture INSERT time, before
delete_account_data() is ever reached; see the P0 report's own "Pre-existing
issues" section).

Run via scripts/l3_local_verify.py so no Firebase/network/DDL slips in.
"""
import os
import unittest
from datetime import datetime, timezone

from flask_jwt_extended import create_access_token

from app import app
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.models_saved_audience import SavedAudience
from notifications.campaign_models import NotificationCampaign
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
    NotificationSendNowRequest,
)
from notifications.campaign_bell_models import NotificationCampaignBellItem
from notifications import campaign_bell_service
from notifications import campaign_history_service
from notifications import campaign_metrics_service

from modules.auth.account_deletion_service import (
    resolve_firebase_identity, delete_account_data,
)


def iso(dt):
    return dt.isoformat()


class AccountDeletionCampaignCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 981900
        # Three synthetic recipients: [0] is the admin/creator, [1] is
        # deleted BY EVERY TEST (recreated fresh in setUp() below, since
        # several test methods each independently delete it), [2] is the
        # "other user in the same campaign" who must remain untouched
        # across the whole class.
        cls.ids = list(range(cls.base, cls.base + 3))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in ((0, cls.ids[0]), (2, cls.ids[2])):
            uid = f'p0-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'p0-token-{offset}',
                                    lang='en', moon_sign='Aries'))
        db.session.commit()
        cls.audience = SavedAudience(name='P0 synthetic', criteria={'version': 1, 'filters': {'search': 'p0-'}}, is_active=True)
        db.session.add(cls.audience)
        db.session.commit()
        cls.audience_id = cls.audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.ids[0])
        os.environ.setdefault('ACTIVITY_EVENTS_ENVIRONMENT', 'local')
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[0]))}
        # The identity actually deleted in these tests.
        cls.deleted_firebase_uid = 'p0-1'
        cls.deleted_user_id = cls.ids[1]
        cls.deleted_profile_id = cls.ids[1] + 100
        # A second, untouched recipient in the same campaigns.
        cls.other_user_id = cls.ids[2]
        cls.other_profile_id = cls.ids[2] + 100

    @classmethod
    def tearDownClass(cls):
        db.session.rollback()
        campaign_ids = list(cls.campaigns)
        execution_ids = [e.id for e in NotificationCampaignExecution.query.filter(NotificationCampaignExecution.campaign_id.in_(campaign_ids)).all()]
        delivery_ids = [d.id for d in NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.execution_id.in_(execution_ids)).all()]
        NotificationCampaignAttempt.query.filter(NotificationCampaignAttempt.delivery_id.in_(delivery_ids)).delete(synchronize_session=False)
        NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.id.in_(delivery_ids)).delete(synchronize_session=False)
        NotificationCampaignBellItem.query.filter(NotificationCampaignBellItem.execution_id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationSendNowRequest.query.filter(NotificationSendNowRequest.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationCampaign.query.filter(NotificationCampaign.id.in_(campaign_ids)).delete(synchronize_session=False)
        SavedAudience.query.filter(SavedAudience.id == cls.audience_id).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def setUp(self):
        # The deleted-user identity is recreated fresh before every test
        # method (several tests each independently delete it) -- defensive
        # cleanup first in case a prior test failed mid-way and left it
        # already gone or in an unexpected state.
        User.query.filter_by(id=self.deleted_user_id).delete(synchronize_session=False)
        AppUser.query.filter_by(id=self.deleted_profile_id).delete(synchronize_session=False)
        db.session.commit()
        db.session.add(User(id=self.deleted_user_id, firebase_uid=self.deleted_firebase_uid,
                             name='p0-1', email='p0-1@example.invalid'))
        db.session.add(AppUser(id=self.deleted_profile_id, firebase_uid=self.deleted_firebase_uid,
                                fcm_token='p0-token-1', lang='en', moon_sign='Aries'))
        db.session.commit()

    def make_and_send(self, title='P0 campaign'):
        payload = dict(title=title, body='Body', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=self.audience_id,
                       action={'type': 'NONE', 'target': None, 'parameters': {}})
        r = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        self.assertEqual(r.status_code, 201)
        campaign_id = r.get_json()['id']
        self.campaigns.append(campaign_id)
        baseline = {'generated_at': iso(datetime.now(timezone.utc)), 'matched_user_count': 3, 'eligible_recipient_count': 3}
        r = self.client.post(f'/admin/api/notifications/{campaign_id}/send-now',
                              json={'revision': 1, 'idempotency_key': 'key-' + campaign_id, 'baseline': baseline},
                              headers=self.admin)
        self.assertEqual(r.status_code, 202)
        return campaign_id, r.get_json()

    # ---------------- 1. no Campaign C history at all ----------------

    def test_deletion_with_no_campaign_c_history_still_succeeds(self):
        uid = User(id=self.base + 50, firebase_uid='p0-lonely', name='p0-lonely', email='p0-lonely@example.invalid')
        profile = AppUser(id=self.base + 150, firebase_uid='p0-lonely', lang='en')
        db.session.add(uid); db.session.add(profile); db.session.commit()
        try:
            identity = resolve_firebase_identity('p0-lonely')
            result = delete_account_data(identity)
            self.assertTrue(result.user_deleted)
            self.assertEqual(result.hard_deleted_profile_ids, [self.base + 150])
            self.assertIsNone(User.query.get(self.base + 50))
            self.assertIsNone(AppUser.query.get(self.base + 150))
        finally:
            db.session.rollback()

    # ---------------- 2-6: full scenario with real Bell + delivery + attempt ----------------

    def test_bell_delivery_attempt_privacy_and_isolation_and_history_integrity(self):
        campaign_id, execution = self.make_and_send()
        execution_id = execution['id']

        deleted_delivery = NotificationCampaignDelivery.query.filter_by(
            execution_id=execution_id, app_user_id=self.deleted_profile_id).first()
        other_delivery = NotificationCampaignDelivery.query.filter_by(
            execution_id=execution_id, app_user_id=self.other_profile_id).first()
        self.assertIsNotNone(deleted_delivery)
        self.assertIsNotNone(other_delivery)
        deleted_delivery_id = deleted_delivery.id
        other_delivery_id = other_delivery.id

        # Give the deleted user's delivery a real attempt row (so we prove
        # attempts, not just deliveries, are cleaned up).
        db.session.add(NotificationCampaignAttempt(
            delivery_id=deleted_delivery_id, attempt_number=1,
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
            outcome='FAILED_RETRYABLE', provider='fake', error_code='timeout', error_class='network',
        ))
        db.session.add(NotificationCampaignAttempt(
            delivery_id=other_delivery_id, attempt_number=1,
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
            outcome='ACCEPTED', provider='fake',
        ))
        db.session.commit()

        deleted_bell = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution_id, user_id=self.deleted_profile_id).first()
        other_bell = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution_id, user_id=self.other_profile_id).first()
        self.assertIsNotNone(deleted_bell)
        self.assertIsNotNone(other_bell)
        other_bell_id = other_bell.id

        target_count_before = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count()
        self.assertEqual(target_count_before, 3)

        # --- the actual privacy action ---
        identity = resolve_firebase_identity(self.deleted_firebase_uid)
        self.assertEqual(identity.profile_ids, [self.deleted_profile_id])
        result = delete_account_data(identity)
        self.assertTrue(result.user_deleted)
        self.assertEqual(result.hard_deleted_profile_ids, [self.deleted_profile_id])

        # 2. Bell identity removed.
        self.assertIsNone(NotificationCampaignBellItem.query.filter_by(
            execution_id=execution_id, user_id=self.deleted_profile_id).first())
        # 3. Delivery identity removed.
        self.assertIsNone(db.session.get(NotificationCampaignDelivery, deleted_delivery_id))
        # 4. The attempt cannot indirectly identify the deleted account --
        # it is gone too (its only link to identity was the delivery row).
        self.assertEqual(
            NotificationCampaignAttempt.query.filter_by(delivery_id=deleted_delivery_id).count(), 0)

        # 5. The OTHER recipient in the SAME campaign/execution is
        # completely untouched -- delivery, attempt, and Bell item all
        # survive byte-for-byte.
        still_there_delivery = db.session.get(NotificationCampaignDelivery, other_delivery_id)
        self.assertIsNotNone(still_there_delivery)
        self.assertEqual(still_there_delivery.app_user_id, self.other_profile_id)
        self.assertEqual(still_there_delivery.user_id, self.other_user_id)
        self.assertEqual(
            NotificationCampaignAttempt.query.filter_by(delivery_id=other_delivery_id).count(), 1)
        still_there_bell = db.session.get(NotificationCampaignBellItem, other_bell_id)
        self.assertIsNotNone(still_there_bell)
        self.assertEqual(still_there_bell.user_id, self.other_profile_id)
        remaining_unified = campaign_bell_service.list_unified_bell(self.other_profile_id)
        self.assertTrue(any(i['id'] == f'cc:{other_bell_id}' for i in remaining_unified))

        # 6. Campaign/execution operational history remains valid --
        # untouched rows, state unchanged, still resolvable.
        campaign_row = db.session.get(NotificationCampaign, campaign_id)
        execution_row = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertIsNotNone(campaign_row)
        self.assertIsNotNone(execution_row)
        self.assertEqual(execution_row.state, 'FROZEN')
        self.assertEqual(execution_row.approved_saved_audience_id, self.audience_id)
        # Documented, expected divergence (see account_deletion_service.py's
        # own docstring): target_count now reflects one fewer LIVE
        # recipient; the frozen baseline/resolved snapshot fields are
        # deliberately untouched, exactly as designed.
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 2)
        self.assertEqual(execution_row.resolved_eligible_recipient_count, 3)

    # ---------------- 7. Admin monitoring/history does not crash ----------------

    def test_admin_monitoring_and_history_survive_deletion(self):
        campaign_id, execution = self.make_and_send(title='P0 monitoring campaign')
        identity = resolve_firebase_identity(self.deleted_firebase_uid)
        delete_account_data(identity)

        detail = campaign_history_service.get_campaign_execution_detail(campaign_id)
        self.assertEqual(detail['id'], execution['id'])
        self.assertIn('metrics', detail)

        deliveries_page = campaign_history_service.list_deliveries(execution['id'])
        self.assertEqual(len(deliveries_page['deliveries']), 2)
        for row in deliveries_page['deliveries']:
            self.assertNotEqual(row['app_user_id'], self.deleted_profile_id)

        for delivery in NotificationCampaignDelivery.query.filter_by(execution_id=execution['id']).all():
            attempts = campaign_history_service.list_attempts(delivery.id)
            self.assertIsInstance(attempts['attempts'], list)  # never crashes, even with 0 attempts

    # ---------------- 8. Campaign metrics remain valid/privacy-safe ----------------

    def test_campaign_metrics_remain_valid_after_deletion(self):
        campaign_id, execution = self.make_and_send(title='P0 metrics campaign')
        identity = resolve_firebase_identity(self.deleted_firebase_uid)
        delete_account_data(identity)

        execution_row = db.session.get(NotificationCampaignExecution, execution['id'])
        metrics = campaign_metrics_service.execution_metrics(execution_row)
        self.assertEqual(metrics['target_count'], 2)
        self.assertEqual(sum(metrics['delivery_counts'].values()), 2)
        # Zero-denominator rates are the literal "UNKNOWN" string, never a
        # misleading 0% -- unaffected by this fix, re-verified here.
        self.assertEqual(metrics['open_rate'], 'UNKNOWN')
        self.assertEqual(metrics['conversion_rate'], 'UNKNOWN')
        # No key in this dict is capable of naming a specific recipient at
        # all (structural: execution_metrics() never selects a user/app_user
        # column) -- nothing to redact, nothing leaked.
        self.assertNotIn('user_id', metrics)
        self.assertNotIn('app_user_id', metrics)

    # ---------------- 9. idempotent / repeated deletion ----------------

    def test_repeated_deletion_is_idempotent_and_safe(self):
        campaign_id, execution = self.make_and_send(title='P0 idempotency campaign')
        identity = resolve_firebase_identity(self.deleted_firebase_uid)
        first = delete_account_data(identity)
        self.assertTrue(first.user_deleted)

        other_delivery = NotificationCampaignDelivery.query.filter_by(
            execution_id=execution['id'], app_user_id=self.other_profile_id).first()
        other_bell = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution['id'], user_id=self.other_profile_id).first()

        # Re-resolving now finds nothing (already gone) -- calling delete
        # again must be a safe, cheap no-op, never an error, and must never
        # touch the other recipient's rows.
        identity_again = resolve_firebase_identity(self.deleted_firebase_uid)
        self.assertFalse(identity_again.found)
        second = delete_account_data(identity_again)
        self.assertTrue(second.already_absent)

        self.assertIsNotNone(db.session.get(NotificationCampaignDelivery, other_delivery.id))
        self.assertIsNotNone(db.session.get(NotificationCampaignBellItem, other_bell.id))

    # ---------------- 10. no PII introduced into Campaign C storage ----------------

    def test_no_token_or_identity_column_exists_on_campaign_c_tables(self):
        """Structural proof, not a runtime one: this fix never had to (and
        did not) add any new column to store a token/firebase_uid/email/
        phone/birth-detail snapshot -- the erasure is row deletion, not a
        new pseudonym column. Re-verifies N4's original no-token-snapshot
        decision is still true after P0."""
        for model in (NotificationCampaignDelivery, NotificationCampaignAttempt, NotificationCampaignBellItem):
            columns = {c.name for c in model.__table__.columns}
            for forbidden in ('fcm_token', 'firebase_uid', 'email', 'phone', 'dob', 'tob', 'pob'):
                self.assertNotIn(forbidden, columns, f'{model.__name__} must never carry a {forbidden!r} column')


if __name__ == '__main__':
    unittest.main()
