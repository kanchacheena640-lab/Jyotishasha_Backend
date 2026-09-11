"""P4.5 -- cancellation of a FROZEN-but-provably-unsent Campaign C
execution. Extends the existing N5.24 cancel() (previously pre-freeze
only: SCHEDULED/PAUSED) to ALSO accept a FROZEN execution, but ONLY
when zero transport attempts have ever occurred for any of its
targets -- see notifications/campaign_schedule_service.py::
_cancel_unsent_frozen() for the full, narrow contract this file proves.

No schema migration: NotificationCampaignExecution.state and
NotificationCampaign.state already allow 'CANCELLED' (added by the
pre-freeze cancel path); NotificationCampaignDelivery.status already
allows 'SUPPRESSED' with a free-text suppression_reason (no CHECK
constraint on that column) -- 'ADMIN_CANCELLED' is simply a new value
for it, not a new column/constraint.

LOCAL ONLY -- real local Postgres, real Flask test client, FakeTransport
(no network/FCM call anywhere in this file).
"""
import os
import unittest
from datetime import datetime, timedelta, timezone

from flask_jwt_extended import create_access_token

from app import app
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.models_saved_audience import SavedAudience
from notifications.notification_models import UserNotification
from notifications.campaign_models import NotificationCampaign
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery,
    NotificationCampaignAttempt, NotificationSendNowRequest,
)
from notifications.campaign_bell_models import NotificationCampaignBellItem
from notifications.campaign_service import CampaignError, get_campaign
from notifications.campaign_schedule_service import cancel
from notifications.campaign_bell_service import list_unified_bell
from notifications import campaign_worker as worker
from notifications.campaign_transport import FakeTransport, TransportResult, OUTCOME_ACCEPTED


def iso(dt):
    return dt.isoformat()


class FrozenCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 9989000
        cls.ids = list(range(cls.base, cls.base + 3))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in enumerate(cls.ids):
            uid = f'p45-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'p45-token-{offset}', lang='en'))
        db.session.commit()
        cls.audience = SavedAudience(name='P4.5 synthetic', criteria={'version': 1, 'filters': {'search': 'p45-'}}, is_active=True)
        db.session.add(cls.audience); db.session.commit()
        cls.audience_id = cls.audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.ids[0])
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[0]))}
        cls.target_app_user_id = cls.ids[0] + 100  # first recipient's AppUser.id

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
        SavedAudience.query.filter_by(id=cls.audience_id).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    # ---------------- fixtures ----------------

    def _frozen_execution(self, title='P4.5 test'):
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
        self.assertEqual(r.status_code, 202, r.get_json())
        execution_id = r.get_json()['id']
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'FROZEN')
        self.assertIsNone(execution.started_at)
        deliveries = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).all()
        self.assertEqual(len(deliveries), 3)
        self.assertTrue(all(d.status == 'PENDING' and d.attempt_count == 0 for d in deliveries))
        return campaign_id, execution_id

    # ---------------- 1. contract: success + every refusal condition ----------------

    def test_a_frozen_zero_attempts_cancel_succeeds(self):
        _campaign_id, execution_id = self._frozen_execution()
        body, status = cancel(execution_id)
        self.assertEqual(status, 200)
        self.assertEqual(body['state'], 'CANCELLED')
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'CANCELLED')
        self.assertIsNotNone(execution.completed_at)
        campaign = get_campaign(execution.campaign_id)
        self.assertEqual(campaign.state, 'CANCELLED')

    def test_b_frozen_with_any_attempt_is_refused(self):
        """Defensive check on attempt_count itself, isolated from the
        delivery.status check below (still PENDING, but attempted)."""
        _campaign_id, execution_id = self._frozen_execution()
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        delivery.attempt_count = 1
        db.session.add(NotificationCampaignAttempt(
            delivery_id=delivery.id, attempt_number=1, started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc), outcome='UNKNOWN', provider='fake'))
        db.session.commit()
        with self.assertRaises(CampaignError) as ctx:
            cancel(execution_id)
        self.assertEqual(ctx.exception.status, 409)
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'FROZEN', 'refusal must leave state untouched')

    def test_c_frozen_with_accepted_delivery_is_refused(self):
        _campaign_id, execution_id = self._frozen_execution()
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        delivery.status = 'ACCEPTED'
        db.session.commit()
        with self.assertRaises(CampaignError) as ctx:
            cancel(execution_id)
        self.assertEqual(ctx.exception.status, 409)

    def test_d_frozen_with_leased_delivery_is_refused(self):
        """Simulates a worker mid-claim -- the concurrency check must
        refuse independently of status/attempt_count (both still
        PENDING/0 here)."""
        _campaign_id, execution_id = self._frozen_execution()
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        delivery.lease_owner = 'worker-simulated'
        delivery.lease_until = datetime.now(timezone.utc) + timedelta(seconds=60)
        db.session.commit()
        with self.assertRaises(CampaignError) as ctx:
            cancel(execution_id)
        self.assertEqual(ctx.exception.status, 409)
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'FROZEN')

    def test_e_sending_is_refused(self):
        _campaign_id, execution_id = self._frozen_execution()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        execution.state = 'SENDING'
        execution.started_at = datetime.now(timezone.utc)
        db.session.commit()
        with self.assertRaises(CampaignError) as ctx:
            cancel(execution_id)
        self.assertEqual(ctx.exception.status, 409)

    def test_f_completed_is_refused(self):
        _campaign_id, execution_id = self._frozen_execution()
        transport = FakeTransport(default=TransportResult(outcome=OUTCOME_ACCEPTED, provider='fake'))
        summary = worker.process_execution(execution_id, transport)
        self.assertTrue(summary['finalized'])
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'COMPLETED')
        with self.assertRaises(CampaignError) as ctx:
            cancel(execution_id)
        self.assertEqual(ctx.exception.status, 409)

    def test_g_already_started_frozen_is_refused_even_if_state_somehow_still_frozen(self):
        """Belt-and-suspenders: started_at is checked independently of
        execution.state, since process_execution() sets both together
        in the same commit -- this proves the started_at guard alone,
        not merely relying on state having already moved to SENDING."""
        _campaign_id, execution_id = self._frozen_execution()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        execution.started_at = datetime.now(timezone.utc)  # state deliberately left FROZEN
        db.session.commit()
        with self.assertRaises(CampaignError) as ctx:
            cancel(execution_id)
        self.assertEqual(ctx.exception.status, 409)

    # ---------------- 2. terminal semantics ----------------

    def test_h_deliveries_terminalized_to_suppressed_admin_cancelled(self):
        _campaign_id, execution_id = self._frozen_execution()
        cancel(execution_id)
        deliveries = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).all()
        self.assertEqual(len(deliveries), 3)
        for delivery in deliveries:
            self.assertEqual(delivery.status, 'SUPPRESSED')
            self.assertEqual(delivery.suppression_reason, 'ADMIN_CANCELLED')
            self.assertIsNone(delivery.lease_owner)
            self.assertIsNone(delivery.lease_until)

    def test_i_nothing_is_ever_deleted(self):
        _campaign_id, execution_id = self._frozen_execution()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        campaign_id = execution.campaign_id
        delivery_count_before = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count()
        bell_count_before = NotificationCampaignBellItem.query.filter_by(execution_id=execution_id).count()
        cancel(execution_id)
        self.assertIsNotNone(db.session.get(NotificationCampaignExecution, execution_id), 'execution must still exist')
        self.assertIsNotNone(db.session.get(NotificationCampaign, campaign_id), 'campaign must still exist')
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), delivery_count_before)
        self.assertEqual(NotificationCampaignBellItem.query.filter_by(execution_id=execution_id).count(), bell_count_before)

    # ---------------- 3. Bell behavior ----------------

    def test_j_bell_items_hidden_but_not_deleted_after_cancellation(self):
        _campaign_id, execution_id = self._frozen_execution()
        bell_items = NotificationCampaignBellItem.query.filter_by(execution_id=execution_id).all()
        self.assertEqual(len(bell_items), 3)
        self.assertTrue(all(item.dismissed_at is None for item in bell_items))
        before = list_unified_bell(self.target_app_user_id, limit=50)
        self.assertTrue(any(item['execution_id'] == execution_id for item in before),
                         'Bell item must be visible before cancellation')

        cancel(execution_id)

        db.session.expire_all()
        bell_items_after = NotificationCampaignBellItem.query.filter_by(execution_id=execution_id).all()
        self.assertEqual(len(bell_items_after), 3, 'rows must still exist, never deleted')
        self.assertTrue(all(item.dismissed_at is not None for item in bell_items_after))
        after = list_unified_bell(self.target_app_user_id, limit=50)
        self.assertFalse(any(item['execution_id'] == execution_id for item in after),
                          'Bell item must no longer be visible after cancellation')

    # ---------------- worker safety ----------------

    def test_k_cancelled_execution_never_discovered_by_worker(self):
        _campaign_id, execution_id = self._frozen_execution()
        cancel(execution_id)
        discovered = worker.discover_processable_executions(limit=50)
        self.assertNotIn(execution_id, discovered)

    def test_l_cancelled_execution_never_sent_even_if_process_execution_called_directly(self):
        _campaign_id, execution_id = self._frozen_execution()
        cancel(execution_id)
        transport = FakeTransport(default=TransportResult(outcome=OUTCOME_ACCEPTED, provider='fake'))
        summary = worker.process_execution(execution_id, transport)
        self.assertEqual(summary['claimed'], 0)
        self.assertEqual(summary['attempted'], 0)
        self.assertEqual(len(transport.calls), 0, 'FCM/transport must never be invoked for a cancelled execution')
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'CANCELLED', 'process_execution() must never resurrect a CANCELLED execution')

    # ---------------- idempotency ----------------

    def test_m_repeated_cancellation_is_idempotent(self):
        _campaign_id, execution_id = self._frozen_execution()
        body1, status1 = cancel(execution_id)
        body2, status2 = cancel(execution_id)
        self.assertEqual((status1, status2), (200, 200))
        self.assertEqual(body1['state'], body2['state'], 'CANCELLED')
        deliveries = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).all()
        self.assertTrue(all(d.status == 'SUPPRESSED' and d.suppression_reason == 'ADMIN_CANCELLED' for d in deliveries),
                         'second call must not re-mutate or corrupt already-cancelled deliveries')

    # ---------------- history/monitoring preserved ----------------

    def test_n_execution_detail_api_still_returns_cancelled_execution_with_correct_counts(self):
        _campaign_id, execution_id = self._frozen_execution()
        cancel(execution_id)
        r = self.client.get(f'/admin/api/notifications/executions/{execution_id}', headers=self.admin)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body['state'], 'CANCELLED')
        self.assertEqual(body['target_count'], 3)
        self.assertEqual(body['delivery_counts']['SUPPRESSED'], 3)
        self.assertEqual(body['delivery_counts']['ACCEPTED'], 0)

    # ---------------- A/B isolation ----------------

    def test_o_ab_pipeline_untouched_by_cancellation(self):
        before = UserNotification.query.count()
        _campaign_id, execution_id = self._frozen_execution()
        cancel(execution_id)
        after = UserNotification.query.count()
        self.assertEqual(before, after, 'cancellation must never write/delete a UserNotification row')

    # ---------------- API route (existing route, extended service logic) ----------------

    def test_p_admin_cancel_route_accepts_frozen_and_returns_cancelled(self):
        _campaign_id, execution_id = self._frozen_execution()
        r = self.client.post(f'/admin/api/notifications/executions/{execution_id}/cancel', headers=self.admin)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['state'], 'CANCELLED')

    def test_q_admin_cancel_route_refuses_sending(self):
        _campaign_id, execution_id = self._frozen_execution()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        execution.state = 'SENDING'
        execution.started_at = datetime.now(timezone.utc)
        db.session.commit()
        r = self.client.post(f'/admin/api/notifications/executions/{execution_id}/cancel', headers=self.admin)
        self.assertEqual(r.status_code, 409)


if __name__ == '__main__':
    unittest.main()
