"""N7 -- Safety & Controls final gate. Adds ONLY the specific proofs not
already covered by test_notification_campaign_composer.py/
test_notification_campaign_execution.py/test_notification_campaign_scheduling.py/
test_notification_campaign_n6.py (which already exhaustively cover the
kill-switch, All Users/1000/50k gates, drift/reconfirm, idempotency,
retry/UNKNOWN/backoff ceiling, crash-lease-reap-to-UNKNOWN, no-PII
responses, and most state-transition guards). Run via
scripts/l3_local_verify.py so no Firebase/network/DDL slips in.

N7 discovery found N1-N6 already implement nearly every required control;
this file closes exactly three verified gaps:
  1. Every /admin/api/notifications/* endpoint (not just a sample) requires
     auth -- enumerated exhaustively here.
  2. Bell Mark All Read / Clear (not just Dismiss, already proven in N6's
     own suite) never mutate campaign/execution state.
  3. A SENDING (not just FROZEN/SCHEDULED) execution rejects
     cancel/reconfirm/reschedule -- the allowlist-based guards in
     campaign_schedule_service.py/campaign_execution_service.py make this
     true by construction, but no existing test drives an execution all
     the way to SENDING and proves it at the route layer.
"""
import os
import unittest
import uuid
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
from notifications import campaign_worker as worker
from notifications.campaign_transport import FakeTransport, TransportResult, OUTCOME_FAILED_RETRYABLE


def iso(dt):
    return dt.isoformat()


class N7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 9978000
        cls.ids = list(range(cls.base, cls.base + 2))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in enumerate(cls.ids):
            uid = f'n7-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'n7-token-{offset}',
                                    lang='en', moon_sign='Aries'))
        db.session.commit()
        cls.audience = SavedAudience(name='N7 synthetic', criteria={'version': 1, 'filters': {'search': 'n7-'}}, is_active=True)
        db.session.add(cls.audience)
        db.session.commit()
        cls.audience_id = cls.audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.ids[0])
        os.environ.setdefault('ACTIVITY_EVENTS_ENVIRONMENT', 'local')
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[0]))}
        cls.target_user_id = cls.ids[1] + 100

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

    def make_and_send(self, title='N7 campaign'):
        payload = dict(title=title, body='Body', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=self.audience_id,
                       action={'type': 'NONE', 'target': None, 'parameters': {}})
        r = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        self.assertEqual(r.status_code, 201)
        campaign_id = r.get_json()['id']
        self.campaigns.append(campaign_id)
        baseline = {'generated_at': iso(datetime.now(timezone.utc)), 'matched_user_count': 2, 'eligible_recipient_count': 2}
        r = self.client.post(f'/admin/api/notifications/{campaign_id}/send-now',
                              json={'revision': 1, 'idempotency_key': 'key-' + campaign_id, 'baseline': baseline},
                              headers=self.admin)
        self.assertEqual(r.status_code, 202)
        return campaign_id, r.get_json()

    # ---------------- 1. Admin auth on EVERY notification endpoint ----------------

    def test_every_admin_notification_endpoint_requires_auth(self):
        """Enumerates the full route table in routes/routes_admin_notifications.py
        (mutation AND monitoring/history) and proves each rejects a request
        with no credentials at all -- not a sample, the whole surface."""
        placeholder = str(uuid.uuid4())
        endpoints = [
            ('GET', '/admin/api/notifications'),
            ('POST', '/admin/api/notifications'),
            ('GET', f'/admin/api/notifications/{placeholder}'),
            ('PATCH', f'/admin/api/notifications/{placeholder}'),
            ('POST', '/admin/api/notifications/preview'),
            ('POST', f'/admin/api/notifications/{placeholder}/send-now'),
            ('POST', f'/admin/api/notifications/executions/{placeholder}/reconfirm'),
            ('GET', f'/admin/api/notifications/executions/{placeholder}'),
            ('POST', f'/admin/api/notifications/{placeholder}/schedule'),
            ('POST', f'/admin/api/notifications/executions/{placeholder}/reschedule'),
            ('POST', f'/admin/api/notifications/executions/{placeholder}/cancel'),
            ('GET', '/admin/api/notifications/history'),
            ('GET', f'/admin/api/notifications/{placeholder}/monitor'),
            ('GET', f'/admin/api/notifications/executions/{placeholder}/deliveries'),
            ('GET', f'/admin/api/notifications/deliveries/{placeholder}/attempts'),
        ]
        for method, path in endpoints:
            with self.subTest(method=method, path=path):
                resp = self.client.open(path, method=method, json={} if method in ('POST', 'PATCH') else None)
                self.assertEqual(resp.status_code, 401,
                                  f'{method} {path} must require auth (got {resp.status_code})')

    def test_wrong_bridge_key_and_wrong_jwt_identity_both_rejected(self):
        """The bridge-key path and the JWT path are both authoritative --
        a wrong value on either must not fall through to success."""
        r = self.client.get('/admin/api/notifications', headers={'X-Admin-Bridge-Key': 'not-the-real-secret'})
        self.assertIn(r.status_code, (401, 403))
        non_admin_token = {'Authorization': 'Bearer ' + create_access_token(identity=str(self.ids[1]))}
        r = self.client.get('/admin/api/notifications', headers=non_admin_token)
        self.assertEqual(r.status_code, 403)

    # ---------------- 2. Bell presentation-only: state untouched ----------------

    def test_mark_all_read_never_mutates_campaign_or_execution_state(self):
        campaign_id, execution = self.make_and_send()
        campaign_row = db.session.get(NotificationCampaign, campaign_id)
        execution_row = db.session.get(NotificationCampaignExecution, execution['id'])
        campaign_state_before, execution_state_before = campaign_row.state, execution_row.state
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution['id']).first()
        delivery_status_before = delivery.status

        campaign_bell_service.mark_all_read(self.target_user_id)

        db.session.refresh(campaign_row); db.session.refresh(execution_row); db.session.refresh(delivery)
        self.assertEqual(campaign_row.state, campaign_state_before)
        self.assertEqual(execution_row.state, execution_state_before)
        self.assertEqual(delivery.status, delivery_status_before)

    def test_clear_all_never_mutates_campaign_or_execution_state(self):
        campaign_id, execution = self.make_and_send()
        campaign_row = db.session.get(NotificationCampaign, campaign_id)
        execution_row = db.session.get(NotificationCampaignExecution, execution['id'])
        campaign_state_before, execution_state_before = campaign_row.state, execution_row.state
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution['id']).first()
        delivery_status_before = delivery.status

        campaign_bell_service.clear_all(self.target_user_id)

        db.session.refresh(campaign_row); db.session.refresh(execution_row); db.session.refresh(delivery)
        self.assertEqual(campaign_row.state, campaign_state_before)
        self.assertEqual(execution_row.state, execution_state_before)
        self.assertEqual(delivery.status, delivery_status_before)
        # Bell items are gone from the tray, but nothing was deleted.
        self.assertEqual(campaign_bell_service.list_unified_bell(self.target_user_id), [])
        self.assertEqual(NotificationCampaignBellItem.query.filter_by(execution_id=execution['id']).count(), 2)

    # ---------------- 3. SENDING execution rejects cancel/reconfirm/reschedule ----------------

    def test_sending_execution_rejects_cancel_reconfirm_and_reschedule(self):
        """Drives a real execution to SENDING (a FAILED_RETRYABLE outcome
        leaves it SENDING with a pending retry, not yet COMPLETED/PARTIAL/
        FAILED) and proves all three mutation routes reject it -- the
        allowlist design in campaign_schedule_service.py/
        campaign_execution_service.py makes this true by construction for
        any non-listed state, verified here for SENDING specifically."""
        campaign_id, execution = self.make_and_send()
        execution_id = execution['id']
        retryable = TransportResult(outcome=OUTCOME_FAILED_RETRYABLE, provider='fake', retryable=True)
        worker.process_execution(execution_id, FakeTransport(default=retryable))

        execution_row = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution_row.state, 'SENDING')

        cancel_resp = self.client.post(f'/admin/api/notifications/executions/{execution_id}/cancel',
                                        json={}, headers=self.admin)
        self.assertEqual(cancel_resp.status_code, 409)

        reconfirm_resp = self.client.post(f'/admin/api/notifications/executions/{execution_id}/reconfirm',
                                           json={'revision': 1}, headers=self.admin)
        self.assertEqual(reconfirm_resp.status_code, 409)

        reschedule_resp = self.client.post(f'/admin/api/notifications/executions/{execution_id}/reschedule',
                                            json={'scheduled_for': iso(datetime.now(timezone.utc))}, headers=self.admin)
        self.assertEqual(reschedule_resp.status_code, 409)

        db.session.refresh(execution_row)
        self.assertEqual(execution_row.state, 'SENDING', 'a rejected mutation must never partially apply')


if __name__ == '__main__':
    unittest.main()
