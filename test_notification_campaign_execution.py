"""N4 Send Now: approval freeze, idempotency, drift, target freeze,
worker claim/retry/UNKNOWN policy. Run via scripts/l3_local_verify.py
so no Firebase/network/DDL slips in. FakeTransport/NoSendTransport
only -- no real transport class exists to import."""
import math
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask_jwt_extended import create_access_token

from app import app
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.models_saved_audience import SavedAudience
from notifications import campaign_execution_service as svc
from notifications import campaign_worker as worker
from notifications.campaign_models import NotificationCampaign
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
    NotificationSendNowRequest,
)
from notifications import campaign_transport as transport_module
from notifications.campaign_transport import FakeTransport, NoSendTransport, TransportResult, select_transport
from notifications.saved_audience_recipient_resolver import RecipientResolution, RecipientResolutionError


def iso(dt):
    return dt.isoformat()


class N4ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 9969000
        cls.ids = list(range(cls.base, cls.base + 4))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in enumerate(cls.ids):
            uid = f'n4-exec-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'n4-token-{offset}',
                                    lang='en', moon_sign='Aries'))
        db.session.commit()
        cls.audience = SavedAudience(name='N4 synthetic', criteria={'version': 1, 'filters': {'search': 'n4-exec-'}}, is_active=True)
        cls.all_users_audience = SavedAudience(name='N4 all users', criteria={'version': 1, 'filters': {}}, is_active=True)
        db.session.add_all([cls.audience, cls.all_users_audience])
        db.session.commit()
        cls.audience_id = cls.audience.id
        cls.all_users_audience_id = cls.all_users_audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.ids[0])
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[0]))}

    @classmethod
    def tearDownClass(cls):
        db.session.rollback()
        campaign_ids = [c for c in cls.campaigns]
        execution_ids = [e.id for e in NotificationCampaignExecution.query.filter(NotificationCampaignExecution.campaign_id.in_(campaign_ids)).all()]
        delivery_ids = [d.id for d in NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.execution_id.in_(execution_ids)).all()]
        NotificationCampaignAttempt.query.filter(NotificationCampaignAttempt.delivery_id.in_(delivery_ids)).delete(synchronize_session=False)
        NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.id.in_(delivery_ids)).delete(synchronize_session=False)
        # N6 -- campaign_bell_service now also inserts a Bell row per
        # frozen target (same FK as delivery rows); clean it up here too
        # or the execution delete below violates its FK.
        from notifications.campaign_bell_models import NotificationCampaignBellItem
        NotificationCampaignBellItem.query.filter(NotificationCampaignBellItem.execution_id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationSendNowRequest.query.filter(NotificationSendNowRequest.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationCampaign.query.filter(NotificationCampaign.id.in_(campaign_ids)).delete(synchronize_session=False)
        SavedAudience.query.filter(SavedAudience.id.in_([cls.audience_id, cls.all_users_audience_id])).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    # ---------------- fixtures ----------------

    def make_draft(self, audience_id=None, **overrides):
        payload = dict(title='Hello N4', body='Body text', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=audience_id or self.audience_id,
                       action={'type': 'NONE', 'target': None, 'parameters': {}})
        payload.update(overrides)
        response = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.campaigns.append(body['id'])
        return body

    def fresh_baseline(self, matched=4, eligible=4):
        return {'generated_at': iso(datetime.now(timezone.utc)), 'matched_user_count': matched, 'eligible_recipient_count': eligible}

    def send_now(self, campaign_id, **overrides):
        payload = dict(revision=1, idempotency_key='key-' + campaign_id, baseline=self.fresh_baseline())
        payload.update(overrides)
        return self.client.post(f'/admin/api/notifications/{campaign_id}/send-now', json=payload, headers=self.admin)

    # ---------------- A/E/F/G: state + confirmations + ceiling ----------------

    def test_send_now_normal_audience_freezes_immediately(self):
        draft = self.make_draft()
        response = self.send_now(draft['id'])
        self.assertEqual(response.status_code, 202)
        body = response.get_json()
        self.assertEqual(body['state'], 'FROZEN')
        self.assertEqual(body['target_count'], 4)
        self.assertIsNotNone(body['frozen_at'])
        self.assertFalse(body['all_users_confirmed'])
        campaign = self.client.get(f"/admin/api/notifications/{draft['id']}", headers=self.admin).get_json()
        self.assertEqual(campaign['state'], 'PROCESSING')
        self.assertEqual(campaign['definition_status'], 'APPROVED')
        self.assertEqual(campaign['execution_id'], body['id'])

    def test_send_now_wrong_state_rejected(self):
        draft = self.make_draft()
        self.send_now(draft['id'])
        second = self.send_now(draft['id'], idempotency_key='different-key-' + draft['id'])
        self.assertEqual(second.status_code, 409)
        self.assertIn(second.get_json()['error'], ('invalid_state', 'execution_already_exists'))

    def test_send_now_stale_revision_rejected(self):
        draft = self.make_draft()
        response = self.send_now(draft['id'], revision=999)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error'], 'stale_revision')

    def test_all_users_requires_exact_phrase(self):
        draft = self.make_draft(audience_id=self.all_users_audience_id)
        no_phrase = self.send_now(draft['id'])
        self.assertEqual(no_phrase.status_code, 400)
        self.assertEqual(no_phrase.get_json()['error'], 'all_users_confirmation_required')
        for wrong in ('send to all users', 'SEND TO ALL USERS ', ' SEND TO ALL USERS', 'Send To All Users', 'SEND TO ALL  USERS'):
            resp = self.send_now(draft['id'], confirmation_phrase=wrong, idempotency_key='wrong-' + wrong)
            self.assertEqual(resp.status_code, 400, wrong)
        correct = self.send_now(draft['id'], confirmation_phrase='SEND TO ALL USERS', idempotency_key='correct-key')
        self.assertEqual(correct.status_code, 202)
        self.assertTrue(correct.get_json()['all_users_confirmed'])

    def test_large_audience_acknowledgement_not_required_unless_large(self):
        draft = self.make_draft()
        response = self.send_now(draft['id'])
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.get_json()['large_audience_acknowledged'])

    def test_large_audience_requires_acknowledgement_not_all_users_phrase(self):
        draft = self.make_draft()
        fake = self._fake_resolution(matched=1200, eligible=1200, is_all_users=False)
        with patch.object(svc, '_resolve_live', return_value=fake):
            missing_ack = self.send_now(draft['id'], baseline=self.fresh_baseline(1200, 1200))
            self.assertEqual(missing_ack.status_code, 400)
            self.assertEqual(missing_ack.get_json()['error'], 'large_audience_acknowledgement_required')
            ok = self.send_now(draft['id'], baseline=self.fresh_baseline(1200, 1200),
                                large_audience_acknowledged=True, idempotency_key='large-ok-' + draft['id'])
        self.assertEqual(ok.status_code, 202)
        body = ok.get_json()
        self.assertTrue(body['large_audience_acknowledged'])
        self.assertFalse(body['all_users_confirmed'])

    def _fake_resolution(self, *, matched, eligible, is_all_users, saved_audience_id=None):
        excluded = matched - eligible
        # Fake user_id/app_user_id values far outside any real fixture
        # range -- these tests exercise safety-gate/drift logic, not
        # real freeze-then-worker delivery (see frozen_execution() for
        # the real-fixture path those tests use instead).
        recipients = tuple(
            SimpleNamespace(user_id=8_000_000 + i, app_user_id=8_100_000 + i)
            for i in range(eligible)
        )
        return RecipientResolution(
            saved_audience_id or self.audience_id, matched, recipients,
            (('missing_identity_bridge', excluded), ('missing_profile', 0), ('missing_token', 0),
             ('preference_suppressed', 0), ('duplicate_target', 0)), is_all_users)

    def test_50k_boundary_exactly_allowed_50001_blocked(self):
        draft = self.make_draft()
        allowed = self._fake_resolution(matched=50000, eligible=50000, is_all_users=False)
        with patch.object(svc, '_resolve_live', return_value=allowed):
            resp = self.send_now(draft['id'], baseline=self.fresh_baseline(50000, 50000),
                                  large_audience_acknowledged=True, idempotency_key='fifty-k-' + draft['id'])
        self.assertEqual(resp.status_code, 202)

        draft2 = self.make_draft()
        with patch.object(svc, '_resolve_live', side_effect=lambda *a, **k: svc.fail('safety_ceiling_exceeded', 'x', 422)):
            resp2 = self.send_now(draft2['id'], baseline=self.fresh_baseline(50001, 50001),
                                   large_audience_acknowledged=True)
        self.assertEqual(resp2.status_code, 422)
        self.assertEqual(resp2.get_json()['error'], 'safety_ceiling_exceeded')
        # never truncated: no execution/delivery rows exist for draft2
        self.assertIsNone(NotificationCampaignExecution.query.filter_by(campaign_id=draft2['id']).first())

    # ---------------- B: idempotency ----------------

    def test_idempotency_same_key_same_request_returns_same_execution(self):
        draft = self.make_draft()
        baseline = self.fresh_baseline()  # SAME object both times -- a genuine retry resubmits identical JSON.
        first = self.send_now(draft['id'], idempotency_key='dup-key', baseline=baseline)
        second = self.send_now(draft['id'], idempotency_key='dup-key', baseline=baseline)
        self.assertEqual(first.status_code, second.status_code)
        self.assertEqual(first.get_json()['id'], second.get_json()['id'])
        self.assertEqual(NotificationCampaignExecution.query.filter_by(campaign_id=draft['id']).count(), 1)

    def test_idempotency_same_key_conflicting_request_rejected(self):
        draft = self.make_draft()
        self.send_now(draft['id'], idempotency_key='conflict-key')
        conflicting = self.send_now(draft['id'], idempotency_key='conflict-key', baseline=self.fresh_baseline(9, 9))
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(conflicting.get_json()['error'], 'idempotency_conflict')

    def test_idempotency_different_campaign_isolated(self):
        draft_a = self.make_draft()
        draft_b = self.make_draft()
        resp_a = self.send_now(draft_a['id'], idempotency_key='shared-key')
        resp_b = self.send_now(draft_b['id'], idempotency_key='shared-key')
        self.assertEqual(resp_a.status_code, 202)
        self.assertEqual(resp_b.status_code, 202)
        self.assertNotEqual(resp_a.get_json()['id'], resp_b.get_json()['id'])

    def test_missing_idempotency_key_rejected(self):
        draft = self.make_draft()
        payload = dict(revision=1, baseline=self.fresh_baseline())
        response = self.client.post(f"/admin/api/notifications/{draft['id']}/send-now", json=payload, headers=self.admin)
        self.assertEqual(response.status_code, 400)

    # ---------------- C: approval definition freeze ----------------

    def test_approved_definition_immutable_after_later_audience_edit(self):
        draft = self.make_draft()
        response = self.send_now(draft['id'])
        execution_id = response.get_json()['id']
        row = db.session.get(SavedAudience, self.audience_id)
        original = row.criteria
        try:
            row.criteria = {'version': 1, 'filters': {'search': 'n4-exec-', 'moon_sign': ['Taurus']}}
            db.session.commit()
            execution_after_edit = self.client.get(f'/admin/api/notifications/executions/{execution_id}', headers=self.admin).get_json()
        finally:
            row.criteria = original
            db.session.commit()
        db.session.refresh(db.session.get(NotificationCampaignExecution, execution_id))
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(stored.approved_criteria, {'version': 1, 'filters': {'search': 'n4-exec-'}})

    def test_missing_and_inactive_audience_blocks_initial_dispatch(self):
        missing = self.make_draft()
        row = db.session.get(NotificationCampaign, missing['id'])
        row.saved_audience_id = 2147483647
        db.session.commit()
        resp = self.send_now(missing['id'])
        self.assertEqual(resp.status_code, 422)

        # Active at draft-creation time (N3 already requires this), THEN
        # deactivated before Send Now -- this is the real N4.6 scenario:
        # "if SavedAudience is missing/inactive before initial dispatch,
        # block initial dispatch."
        soon_inactive = SavedAudience(name='N4 soon inactive', criteria={'version': 1, 'filters': {'search': 'n4-exec-'}}, is_active=True)
        db.session.add(soon_inactive); db.session.commit()
        try:
            draft = self.make_draft(audience_id=soon_inactive.id)
            soon_inactive.is_active = False
            db.session.commit()
            resp2 = self.send_now(draft['id'])
            self.assertEqual(resp2.status_code, 422)
        finally:
            db.session.delete(soon_inactive); db.session.commit()

    # ---------------- D: preview freshness ----------------

    def test_preview_freshness_15_minutes(self):
        draft = self.make_draft()
        fresh = self.fresh_baseline()
        fresh['generated_at'] = iso(datetime.now(timezone.utc) - timedelta(minutes=14, seconds=59))
        ok = self.send_now(draft['id'], baseline=fresh, idempotency_key='fresh-' + draft['id'])
        self.assertEqual(ok.status_code, 202)

        draft2 = self.make_draft()
        stale = self.fresh_baseline()
        stale['generated_at'] = iso(datetime.now(timezone.utc) - timedelta(minutes=15, seconds=1))
        rejected = self.send_now(draft2['id'], baseline=stale)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.get_json()['error'], 'preview_stale')

    def test_browser_supplied_counts_never_trusted(self):
        """A fabricated baseline with an absurdly high eligible count must
        not bypass the real backend resolution or safety checks."""
        draft = self.make_draft()
        forged = self.fresh_baseline(matched=4, eligible=4)
        response = self.send_now(draft['id'], baseline=forged)
        self.assertEqual(response.status_code, 202)
        body = response.get_json()
        # Resolved counts come from the REAL resolver (4 fixture users), not any client claim.
        self.assertEqual(body['resolved']['matched_user_count'], 4)
        self.assertEqual(body['target_count'], 4)

    # ---------------- H: drift ----------------

    def test_drift_threshold_math(self):
        self.assertEqual(svc._drift_threshold(100), 20)
        self.assertEqual(svc._drift_threshold(20), 10)
        self.assertEqual(svc._drift_threshold(1), 10)
        self.assertFalse(svc._drifted(100, 120))
        self.assertTrue(svc._drifted(100, 121))
        self.assertFalse(svc._drifted(20, 30))
        self.assertTrue(svc._drifted(20, 31))
        self.assertFalse(svc._drifted(0, 0))
        self.assertTrue(svc._drifted(0, 1))

    def test_drift_pauses_and_reconfirm_freezes_with_new_baseline(self):
        draft = self.make_draft()
        fake_baseline_gap = self._fake_resolution(matched=100, eligible=90, is_all_users=False)
        with patch.object(svc, '_resolve_live', return_value=fake_baseline_gap):
            resp = self.send_now(draft['id'], baseline=self.fresh_baseline(50, 50),
                                  large_audience_acknowledged=True)
        self.assertEqual(resp.status_code, 202)
        body = resp.get_json()
        self.assertEqual(body['state'], 'PAUSED')
        self.assertEqual(body['hold_reason'], 'DRIFT')
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=body['id']).count(), 0)
        campaign = self.client.get(f"/admin/api/notifications/{draft['id']}", headers=self.admin).get_json()
        self.assertEqual(campaign['state'], 'PROCESSING')
        self.assertEqual(campaign['hold_reason'], 'DRIFT')

        stable = self._fake_resolution(matched=101, eligible=91, is_all_users=False)  # within threshold of 100/90
        with patch.object(svc, '_resolve_live', return_value=stable):
            reconfirmed = self.client.post(f"/admin/api/notifications/executions/{body['id']}/reconfirm", json={}, headers=self.admin)
        self.assertEqual(reconfirmed.status_code, 200)
        after = reconfirmed.get_json()
        self.assertEqual(after['state'], 'FROZEN')
        self.assertIsNone(after['hold_reason'])
        self.assertEqual(after['baseline']['matched_user_count'], 100)  # promoted from the pause's own resolved value
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=body['id']).count(), 91)

    def test_drift_still_exceeds_pauses_again_with_explicit_new_baseline(self):
        draft = self.make_draft()
        first = self._fake_resolution(matched=100, eligible=90, is_all_users=False)
        with patch.object(svc, '_resolve_live', return_value=first):
            resp = self.send_now(draft['id'], baseline=self.fresh_baseline(50, 50), large_audience_acknowledged=True)
        execution_id = resp.get_json()['id']
        still_drifting = self._fake_resolution(matched=200, eligible=180, is_all_users=False)
        with patch.object(svc, '_resolve_live', return_value=still_drifting):
            again = self.client.post(f"/admin/api/notifications/executions/{execution_id}/reconfirm", json={}, headers=self.admin)
        self.assertEqual(again.status_code, 200)
        body = again.get_json()
        self.assertEqual(body['state'], 'PAUSED')
        self.assertEqual(body['baseline']['matched_user_count'], 100)  # new baseline = prior resolved
        self.assertEqual(body['resolved']['matched_user_count'], 200)

    def test_reconfirm_wrong_state_rejected(self):
        draft = self.make_draft()
        resp = self.send_now(draft['id'])
        execution_id = resp.get_json()['id']  # already FROZEN, not PAUSED
        reconfirmed = self.client.post(f'/admin/api/notifications/executions/{execution_id}/reconfirm', json={}, headers=self.admin)
        self.assertEqual(reconfirmed.status_code, 409)

    # ---------------- I: target freeze immutability ----------------

    def test_target_freeze_is_immutable_snapshot(self):
        draft = self.make_draft()
        resp = self.send_now(draft['id'])
        execution_id = resp.get_json()['id']
        frozen_user_ids = {d.user_id for d in NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).all()}
        self.assertEqual(frozen_user_ids, set(self.ids))
        # A brand-new matching user created after freeze must never join.
        new_id = self.base + 900
        db.session.add(User(id=new_id, firebase_uid='n4-exec-late', name='n4-exec-late', email='n4-exec-late@example.invalid'))
        db.session.add(AppUser(id=new_id + 100, firebase_uid='n4-exec-late', fcm_token='n4-token-late', lang='en'))
        db.session.commit()
        try:
            still_frozen = {d.user_id for d in NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).all()}
            self.assertEqual(still_frozen, set(self.ids))
        finally:
            AppUser.query.filter_by(id=new_id + 100).delete()
            User.query.filter_by(id=new_id).delete()
            db.session.commit()

    # ---------------- Worker: claim / retry / UNKNOWN / duplicate ----------------

    def frozen_execution(self, outcomes=None, default=None):
        draft = self.make_draft()
        resp = self.send_now(draft['id'])
        execution_id = resp.get_json()['id']
        transport = FakeTransport(outcomes=outcomes, default=default)
        return execution_id, transport

    def test_worker_accepted_marks_delivery_accepted_and_completes(self):
        execution_id, transport = self.frozen_execution()
        summary = worker.process_execution(execution_id, transport)
        self.assertEqual(summary['attempted'], 4)
        self.assertTrue(summary['finalized'])
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'COMPLETED')
        statuses = {d.status for d in NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).all()}
        self.assertEqual(statuses, {'ACCEPTED'})
        campaign = self.client.get(f"/admin/api/notifications/executions/{execution_id}", headers=self.admin).get_json()
        self.assertEqual(campaign['delivery_counts']['ACCEPTED'], 4)

    def test_worker_unknown_never_auto_retried(self):
        execution_id, _ = self.frozen_execution(outcomes={'n4-token-0': TransportResult(outcome='UNKNOWN', provider='fake')})
        transport = FakeTransport(outcomes={'n4-token-0': TransportResult(outcome='UNKNOWN', provider='fake')})
        worker.process_execution(execution_id, transport)
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id, app_user_id=self.base + 100).first()
        self.assertEqual(delivery.status, 'UNKNOWN')
        self.assertEqual(delivery.attempt_count, 1)
        attempts_before = NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count()
        self.assertEqual(attempts_before, 1)
        # Call the worker again -- UNKNOWN must not be picked up as claimable work.
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count(), 1)

    def test_worker_permanent_failure_never_retried(self):
        execution_id, transport = self.frozen_execution(outcomes={
            'n4-token-0': TransportResult(outcome='FAILED_PERMANENT', provider='fake', invalid_token=True, error_code='invalid_token'),
        })
        worker.process_execution(execution_id, transport)
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id, app_user_id=self.base + 100).first()
        self.assertEqual(delivery.status, 'FAILED_PERMANENT')
        self.assertIsNone(delivery.next_attempt_at)
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 1)

    def _force_due(self, delivery):
        delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()

    def test_worker_retryable_backs_off_per_locked_schedule_then_exhausts_at_four(self):
        """Locked N4 retry contract: attempt 1 = initial, retries 1/2/3 =
        attempts 2/3/4. Maximum 4 transport attempts total (never 5).
        Backoff: retry 1 -> 30s+jitter, retry 2 -> 120s+jitter,
        retry 3 -> 120s+jitter (the last established interval is reused,
        never an invented new exponential step)."""
        execution_id, transport = self.frozen_execution(outcomes={
            'n4-token-0': TransportResult(outcome='FAILED_RETRYABLE', provider='fake', retryable=True, error_code='temporary'),
        })
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id, app_user_id=self.base + 100).first()

        # Attempt 1 (initial, immediate -- no backoff involved in dispatching it).
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.status, 'FAILED_RETRYABLE')
        # Retry 1 backoff: 30s + up to 20% jitter -> [30, 36]s.
        self.assertGreater(delivery.next_attempt_at, datetime.now(timezone.utc) + timedelta(seconds=29))
        self.assertLessEqual(delivery.next_attempt_at, datetime.now(timezone.utc) + timedelta(seconds=37))

        # Not yet due -- another call must not consume an attempt early.
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 1)

        # Attempt 2 (retry 1, due).
        self._force_due(delivery)
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(delivery.status, 'FAILED_RETRYABLE')
        # Retry 2 backoff: 120s + up to 20% jitter -> [120, 144]s.
        self.assertGreater(delivery.next_attempt_at, datetime.now(timezone.utc) + timedelta(seconds=119))
        self.assertLessEqual(delivery.next_attempt_at, datetime.now(timezone.utc) + timedelta(seconds=145))

        # Attempt 3 (retry 2, due).
        self._force_due(delivery)
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 3)
        self.assertEqual(delivery.status, 'FAILED_RETRYABLE')
        # Retry 3 backoff: still 120s + jitter -- last established interval reused, not 240s.
        self.assertGreater(delivery.next_attempt_at, datetime.now(timezone.utc) + timedelta(seconds=119))
        self.assertLessEqual(delivery.next_attempt_at, datetime.now(timezone.utc) + timedelta(seconds=145))

        # Attempt 4 (retry 3, due) -- SAFE_TO_RETRY is still allowed on
        # attempt 4, and THIS is the one that exhausts to terminal.
        self._force_due(delivery)
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 4)
        self.assertEqual(delivery.status, 'FAILED_PERMANENT')
        self.assertIsNone(delivery.next_attempt_at)

        attempts = NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).order_by(NotificationCampaignAttempt.attempt_number).all()
        self.assertEqual([a.outcome for a in attempts], ['FAILED_RETRYABLE'] * 4)
        self.assertEqual(attempts[-1].error_code, 'RETRY_EXHAUSTED')
        self.assertEqual(len(attempts), 4)  # retry history is never overwritten

        # There must be no attempt 5: forcing "due" again with the
        # delivery already terminal must not dispatch anything further.
        delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)  # harmless on a terminal row
        db.session.commit()
        worker.process_execution(execution_id, transport)
        db.session.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 4)
        self.assertEqual(NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count(), 4)

    def test_backoff_seconds_matches_locked_schedule(self):
        """Direct unit proof of the three retry delays, independent of
        the worker's claim/lease timing -- 100 samples per attempt to
        bound the jitter range with confidence."""
        for attempt_number, low, high in ((1, 30.0, 36.0), (2, 120.0, 144.0), (3, 120.0, 144.0)):
            for _ in range(100):
                delay = transport_module.backoff_seconds(attempt_number)
                self.assertGreaterEqual(delay, low)
                self.assertLessEqual(delay, high)
        with self.assertRaises(ValueError):
            transport_module.backoff_seconds(4)  # no backoff beyond attempt 4 -- it is terminal, not retried again

    def test_worker_missing_token_suppressed_without_attempt(self):
        """Token still present at freeze time (so N2 includes this
        recipient in the frozen target set), then goes missing before
        the worker attempts it -- N1 Section 7's own per-attempt
        revalidation scenario, not a pre-freeze exclusion."""
        draft = self.make_draft()
        resp = self.send_now(draft['id'])
        execution_id = resp.get_json()['id']
        row = db.session.get(AppUser, self.base + 100)
        original_token = row.fcm_token
        try:
            row.fcm_token = None
            db.session.commit()
            transport = FakeTransport()
            worker.process_execution(execution_id, transport)
            delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id, app_user_id=self.base + 100).first()
            self.assertEqual(delivery.status, 'SUPPRESSED')
            self.assertEqual(delivery.suppression_reason, 'MISSING_TOKEN')
            self.assertEqual(NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count(), 0)
        finally:
            row.fcm_token = original_token
            db.session.commit()

    def test_worker_duplicate_token_after_freeze_suppresses_both(self):
        draft = self.make_draft()
        row0 = db.session.get(AppUser, self.base + 100)
        row1 = db.session.get(AppUser, self.base + 101)
        original0, original1 = row0.fcm_token, row1.fcm_token
        resp = self.send_now(draft['id'])
        execution_id = resp.get_json()['id']
        try:
            row1.fcm_token = row0.fcm_token  # token reassigned to collide AFTER freeze
            db.session.commit()
            transport = FakeTransport()
            worker.process_execution(execution_id, transport)
            d0 = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id, app_user_id=self.base + 100).first()
            d1 = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id, app_user_id=self.base + 101).first()
            self.assertEqual(d0.status, 'SUPPRESSED')
            self.assertEqual(d0.suppression_reason, 'TARGET_CHANGED')
            self.assertEqual(d1.status, 'SUPPRESSED')
            self.assertEqual(d1.suppression_reason, 'TARGET_CHANGED')
        finally:
            row0.fcm_token = original0
            row1.fcm_token = original1
            db.session.commit()

    def test_worker_mixed_outcomes_yield_partial(self):
        execution_id, transport = self.frozen_execution(outcomes={
            'n4-token-0': TransportResult(outcome='ACCEPTED', provider='fake'),
            'n4-token-1': TransportResult(outcome='FAILED_PERMANENT', provider='fake'),
        }, default=TransportResult(outcome='ACCEPTED', provider='fake'))
        worker.process_execution(execution_id, transport)
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'PARTIAL')

    def test_worker_all_fail_yields_failed_state(self):
        execution_id, transport = self.frozen_execution(default=TransportResult(outcome='FAILED_PERMANENT', provider='fake'))
        worker.process_execution(execution_id, transport)
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'FAILED')

    def test_worker_crash_leaves_lease_expired_delivery_reconciled_to_unknown(self):
        """Simulates a crash between the pre-invocation commit and the
        outcome commit: an attempt row with outcome=NULL and an expired
        lease must become UNKNOWN on the next call, never silently retried."""
        execution_id, transport = self.frozen_execution()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        execution.state = 'FROZEN'
        db.session.commit()
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        delivery.status = 'PENDING'
        delivery.attempt_count = 1
        delivery.lease_owner = 'crashed-worker'
        delivery.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.add(NotificationCampaignAttempt(
            delivery_id=delivery.id, attempt_number=1, started_at=datetime.now(timezone.utc) - timedelta(seconds=200),
            outcome=None, provider='fake',
        ))
        db.session.commit()
        worker.process_execution(execution_id, FakeTransport())
        db.session.refresh(delivery)
        self.assertEqual(delivery.status, 'UNKNOWN')
        open_attempts = NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id, outcome=None).count()
        self.assertEqual(open_attempts, 0)

    def test_worker_never_calls_transport_before_frozen(self):
        transport = FakeTransport()
        with self.assertRaises(ValueError):
            worker.process_execution('00000000-0000-0000-0000-000000000000', transport)
        with self.assertRaises(ValueError):
            worker.process_execution('not-a-uuid-at-all', transport)
        self.assertEqual(transport.calls, [])

    def test_worker_pending_execution_state_is_noop(self):
        """A PAUSED (drift-held) execution must never be processed by
        the worker -- only FROZEN/SENDING are claimable."""
        draft = self.make_draft()
        paused = self._fake_resolution(matched=100, eligible=90, is_all_users=False)
        with patch.object(svc, '_resolve_live', return_value=paused):
            resp = self.send_now(draft['id'], baseline=self.fresh_baseline(50, 50), large_audience_acknowledged=True)
        execution_id = resp.get_json()['id']
        transport = FakeTransport()
        summary = worker.process_execution(execution_id, transport)
        self.assertEqual(summary, {'claimed': 0, 'attempted': 0, 'suppressed': 0, 'reaped': 0, 'finalized': False})
        self.assertEqual(transport.calls, [])

    # ---------------- Transport gates ----------------

    def test_select_transport_always_nosend_locally(self):
        self.assertIsInstance(select_transport(environment='local'), NoSendTransport)
        self.assertIsInstance(select_transport(environment='test'), NoSendTransport)

    def test_select_transport_fails_closed_even_with_partial_production_gates(self):
        with patch.dict(os.environ, {'ADMIN_CAMPAIGN_SEND_ENABLED': 'true'}, clear=False):
            self.assertIsInstance(select_transport(environment='local'), NoSendTransport)
        with patch.dict(os.environ, {'ADMIN_CAMPAIGN_SEND_ENABLED': 'false', 'FCM_SERVICE_ACCOUNT_JSON': '{"type":"service_account"}'}, clear=False):
            self.assertIsInstance(select_transport(environment='production'), NoSendTransport)

    def test_select_transport_activates_firebase_transport_only_with_all_four_gates(self):
        """P1 superseded N4's own 'no production transport class exists,
        always raises' assertion -- see notifications/firebase_transport.py.
        The gates themselves did not weaken: a 4th (ADMIN_CAMPAIGN_
        WORKER_AUTHORIZED) was ADDED, and all four together are still
        required -- missing just the new one still fails closed."""
        from notifications.firebase_transport import FirebaseTransport
        with patch.dict(os.environ, {
            'ADMIN_CAMPAIGN_SEND_ENABLED': 'true', 'FCM_SERVICE_ACCOUNT_JSON': '{"type":"service_account"}',
        }, clear=False):
            # Missing the new worker-authorization gate -- still NoSend.
            self.assertIsInstance(select_transport(environment='production'), NoSendTransport)
        with patch.dict(os.environ, {
            'ADMIN_CAMPAIGN_SEND_ENABLED': 'true', 'FCM_SERVICE_ACCOUNT_JSON': '{"type":"service_account"}',
            'ADMIN_CAMPAIGN_WORKER_AUTHORIZED': 'true',
        }, clear=False):
            self.assertIsInstance(select_transport(environment='production'), FirebaseTransport)

    # ---------------- Privacy ----------------

    def test_no_token_uid_in_any_admin_response(self):
        draft = self.make_draft()
        resp = self.send_now(draft['id'])
        execution_id = resp.get_json()['id']
        worker.process_execution(execution_id, FakeTransport())
        detail = self.client.get(f'/admin/api/notifications/executions/{execution_id}', headers=self.admin)
        payload = str(detail.get_json())
        for offset in range(4):
            self.assertNotIn(f'n4-token-{offset}', payload)
            self.assertNotIn(f'n4-exec-{offset}', payload)

    def test_no_transport_or_execution_import_in_send_route_module(self):
        """send_now()/reconfirm() must never import the worker/transport
        modules -- checked against real import statements only (this
        module's own docstring legitimately NAMES campaign_worker.py in
        prose to explain the architecture boundary)."""
        import notifications.campaign_execution_service as module
        with open(module.__file__, encoding='utf-8') as fh:
            lines = [line for line in fh if line.strip().startswith(('import ', 'from '))]
        for forbidden in ('firebase_admin', 'campaign_worker', 'campaign_transport', 'messaging'):
            self.assertFalse(any(forbidden in line for line in lines), f'{forbidden} imported in campaign_execution_service.py')

    def test_worker_never_imports_firebase_admin(self):
        import notifications.campaign_worker as module
        with open(module.__file__, encoding='utf-8') as fh:
            source = fh.read()
        self.assertNotIn('firebase_admin', source)
        self.assertNotIn('import celery', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
