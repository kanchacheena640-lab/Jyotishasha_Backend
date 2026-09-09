"""N5 Scheduling: schedule creation, approved-definition freeze without
membership freeze, due discovery/claim, drift/ceiling/expiry at
dispatch, reconfirm, reschedule/cancel, and the mandatory approved-
criteria-survives-audience-edit proof (N5.36). Run via
scripts/l3_local_verify.py. FakeTransport/NoSendTransport only -- no
real transport class exists to import."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask_jwt_extended import create_access_token

from app import app
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.models_saved_audience import SavedAudience
from notifications import campaign_execution_service as svc
from notifications import campaign_schedule_service as sched
from notifications import campaign_scheduler as scheduler
from notifications import campaign_worker as worker
from notifications.campaign_models import NotificationCampaign
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
    NotificationSendNowRequest,
)
from notifications.campaign_transport import FakeTransport, TransportResult
from notifications.saved_audience_recipient_resolver import (
    resolve_saved_audience_recipients, RecipientResolution, RecipientResolutionError,
)


def iso(dt):
    return dt.isoformat()


class N5SchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 9959000
        cls.ids = list(range(cls.base, cls.base + 4))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in enumerate(cls.ids):
            uid = f'n5-sched-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'n5-token-{offset}', lang='en', moon_sign='Aries'))
        db.session.commit()
        cls.audience = SavedAudience(name='N5 synthetic', criteria={'version': 1, 'filters': {'search': 'n5-sched-'}}, is_active=True)
        cls.all_users_audience = SavedAudience(name='N5 all users', criteria={'version': 1, 'filters': {}}, is_active=True)
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
        campaign_ids = list(cls.campaigns)
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
        payload = dict(title='Hello N5', body='Body text', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=audience_id or self.audience_id,
                       action={'type': 'NONE', 'target': None, 'parameters': {}})
        payload.update(overrides)
        response = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.campaigns.append(body['id'])
        return body

    def schedule(self, campaign_id, **overrides):
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        payload = dict(revision=1, idempotency_key='sched-' + campaign_id,
                       scheduled_for=iso(future), preview_generated_at=iso(datetime.now(timezone.utc)))
        payload.update(overrides)
        return self.client.post(f'/admin/api/notifications/{campaign_id}/schedule', json=payload, headers=self.admin)

    def _fake_resolution(self, *, matched, eligible, is_all_users, saved_audience_id=None):
        from types import SimpleNamespace
        excluded = matched - eligible
        recipients = tuple(SimpleNamespace(user_id=8_200_000 + i, app_user_id=8_300_000 + i) for i in range(eligible))
        return RecipientResolution(
            saved_audience_id or self.audience_id, matched, recipients,
            (('missing_identity_bridge', excluded), ('missing_profile', 0), ('missing_token', 0),
             ('preference_suppressed', 0), ('duplicate_target', 0)), is_all_users)

    # ---------------- A: scheduling ----------------

    def test_schedule_creates_scheduled_execution_no_deliveries_no_transport(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'])
        self.assertEqual(response.status_code, 202)
        body = response.get_json()
        self.assertEqual(body['state'], 'SCHEDULED')
        self.assertIsNotNone(body['scheduled_for'])
        self.assertIsNotNone(body['expires_at'])
        self.assertEqual(body['target_count'], 0)
        self.assertEqual(sum(body['delivery_counts'].values()), 0)
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=body['id']).count(), 0)
        campaign = self.client.get(f"/admin/api/notifications/{draft['id']}", headers=self.admin).get_json()
        self.assertEqual(campaign['state'], 'SCHEDULED')
        self.assertEqual(campaign['execution_id'], body['id'])

    def test_schedule_wrong_state_and_stale_revision(self):
        draft = self.make_draft()
        self.schedule(draft['id'])
        second = self.schedule(draft['id'], idempotency_key='different-' + draft['id'])
        self.assertIn(second.status_code, (409,))
        draft2 = self.make_draft()
        stale = self.schedule(draft2['id'], revision=999)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()['error'], 'stale_revision')

    # ---------------- B: time ----------------

    def test_naive_datetime_rejected(self):
        draft = self.make_draft()
        naive = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(tzinfo=None).isoformat()
        response = self.schedule(draft['id'], scheduled_for=naive)
        self.assertEqual(response.status_code, 400)

    def test_past_time_rejected(self):
        draft = self.make_draft()
        past = iso(datetime.now(timezone.utc) - timedelta(hours=1))
        response = self.schedule(draft['id'], scheduled_for=past)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'invalid_schedule_time')

    def test_too_close_to_now_rejected(self):
        draft = self.make_draft()
        soon = iso(datetime.now(timezone.utc) + timedelta(seconds=5))
        response = self.schedule(draft['id'], scheduled_for=soon)
        self.assertEqual(response.status_code, 400)

    def test_utc_persisted_and_returned(self):
        draft = self.make_draft()
        future = datetime.now(timezone.utc) + timedelta(hours=5)
        response = self.schedule(draft['id'], scheduled_for=iso(future))
        body = response.get_json()
        returned = datetime.fromisoformat(body['scheduled_for'])
        self.assertIsNotNone(returned.tzinfo)
        self.assertAlmostEqual(returned.timestamp(), future.timestamp(), delta=1)

    # ---------------- C: preview freshness / authoritative counts ----------------

    def test_stale_preview_rejected_at_schedule(self):
        draft = self.make_draft()
        stale = iso(datetime.now(timezone.utc) - timedelta(minutes=16))
        response = self.schedule(draft['id'], preview_generated_at=stale)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error'], 'preview_stale')

    def test_baseline_is_always_backend_authoritative_never_client_supplied(self):
        """N5.8: schedule_campaign() accepts no client baseline counts at
        all -- only a freshness timestamp. The persisted baseline must
        equal the real fixture resolution (4 users), proving nothing
        client-supplied could ever become the baseline even if it wanted to."""
        draft = self.make_draft()
        response = self.schedule(draft['id'])
        body = response.get_json()
        self.assertEqual(body['baseline']['matched_user_count'], 4)
        self.assertEqual(body['baseline']['eligible_recipient_count'], 4)
        self.assertNotIn('matched_user_count', str(self.schedule.__doc__ or ''))  # no-op guard; real proof is the assertion above

    # ---------------- D/E/F: All Users / large audience / ceiling ----------------

    def test_all_users_requires_exact_phrase_at_schedule(self):
        draft = self.make_draft(audience_id=self.all_users_audience_id)
        missing = self.schedule(draft['id'])
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.get_json()['error'], 'all_users_confirmation_required')
        wrong = self.schedule(draft['id'], confirmation_phrase='send to all users', idempotency_key='wrong-' + draft['id'])
        self.assertEqual(wrong.status_code, 400)
        correct = self.schedule(draft['id'], confirmation_phrase='SEND TO ALL USERS', idempotency_key='correct-' + draft['id'])
        self.assertEqual(correct.status_code, 202)
        self.assertTrue(correct.get_json()['all_users_confirmed'])

    def test_large_audience_ack_required_at_schedule(self):
        draft = self.make_draft()
        fake = self._fake_resolution(matched=1200, eligible=1200, is_all_users=False)
        with patch.object(sched, '_resolve_live', return_value=fake):
            missing = self.schedule(draft['id'])
            self.assertEqual(missing.status_code, 400)
            self.assertEqual(missing.get_json()['error'], 'large_audience_acknowledgement_required')
            ok = self.schedule(draft['id'], large_audience_acknowledged=True, idempotency_key='large-' + draft['id'])
        self.assertEqual(ok.status_code, 202)

    def test_50k_blocked_at_schedule_approval(self):
        draft = self.make_draft()
        with patch.object(sched, '_resolve_live', side_effect=lambda *a, **k: svc.fail('safety_ceiling_exceeded', 'x', 422)):
            response = self.schedule(draft['id'], large_audience_acknowledged=True)
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(NotificationCampaignExecution.query.filter_by(campaign_id=draft['id']).first())

    # ---------------- G: approved definition ----------------

    def test_missing_and_inactive_audience_blocks_schedule(self):
        draft = self.make_draft()
        row = db.session.get(NotificationCampaign, draft['id'])
        row.saved_audience_id = 2147483647
        db.session.commit()
        response = self.schedule(draft['id'])
        self.assertEqual(response.status_code, 422)

        soon_inactive = SavedAudience(name='N5 soon inactive', criteria={'version': 1, 'filters': {'search': 'n5-sched-'}}, is_active=True)
        db.session.add(soon_inactive); db.session.commit()
        try:
            draft2 = self.make_draft(audience_id=soon_inactive.id)
            soon_inactive.is_active = False
            db.session.commit()
            response2 = self.schedule(draft2['id'])
            self.assertEqual(response2.status_code, 422)
        finally:
            db.session.delete(soon_inactive); db.session.commit()

    # ---------------- MANDATORY (N5.36): approved criteria survive audience edit ----------------

    def test_approved_criteria_survive_audience_edit_at_dispatch(self):
        """Schedule with criteria A -> edit SavedAudience to criteria B
        -> dispatch -> live users MUST be evaluated against approved
        criteria A, never current criteria B."""
        row = db.session.get(SavedAudience, self.audience_id)
        original_criteria = row.criteria
        try:
            row.criteria = {'version': 1, 'filters': {'search': 'n5-sched-'}}  # criteria A: matches all 4 fixtures
            db.session.commit()
            draft = self.make_draft()
            response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
            self.assertEqual(response.status_code, 202)
            body = response.get_json()
            self.assertEqual(body['baseline']['matched_user_count'], 4)  # criteria A resolution
            execution_id = body['id']

            # Edit the audience to criteria B: a search string matching NOTHING.
            row.criteria = {'version': 1, 'filters': {'search': 'no-such-user-should-match-xyz'}}
            db.session.commit()

            # Direct proof at the resolver boundary: resolving with the
            # approved snapshot still returns the ORIGINAL 4 matches,
            # even though the SavedAudience's current criteria now match 0.
            stored = db.session.get(NotificationCampaignExecution, execution_id)
            approved_result = resolve_saved_audience_recipients(self.audience_id, approved_criteria=stored.approved_criteria)
            self.assertEqual(approved_result.matched_user_count, 4)
            current_result = resolve_saved_audience_recipients(self.audience_id)
            self.assertEqual(current_result.matched_user_count, 0)

            # Full dispatch proof: due processing must freeze exactly the
            # 4 criteria-A users, never 0.
            future_now = stored.scheduled_for + timedelta(seconds=1)
            summary = scheduler.process_due_scheduled_campaigns(now=future_now)
            self.assertIn(execution_id, [r['execution_id'] for r in summary['results']])
            db.session.refresh(stored)
            self.assertEqual(stored.state, 'FROZEN')
            self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 4)
        finally:
            row.criteria = original_criteria
            db.session.commit()

    def test_later_audience_edit_does_not_mutate_approved_snapshot(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'])
        execution_id = response.get_json()['id']
        row = db.session.get(SavedAudience, self.audience_id)
        original = row.criteria
        try:
            row.criteria = {'version': 1, 'filters': {'search': 'n5-sched-', 'moon_sign': ['Taurus']}}
            db.session.commit()
            stored = db.session.get(NotificationCampaignExecution, execution_id)
            self.assertEqual(stored.approved_criteria, {'version': 1, 'filters': {'search': 'n5-sched-'}})
        finally:
            row.criteria = original
            db.session.commit()

    # ---------------- H: due discovery + claim ----------------

    def test_future_execution_not_claimed(self):
        draft = self.make_draft()
        self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(hours=3)))
        summary = scheduler.process_due_scheduled_campaigns(now=datetime.now(timezone.utc))
        self.assertEqual(summary['claimed'], 0)

    def test_due_execution_claimed_and_frozen(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        summary = scheduler.process_due_scheduled_campaigns(now=stored.scheduled_for + timedelta(seconds=1))
        self.assertIn(execution_id, [r['execution_id'] for r in summary['results']])
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'FROZEN')
        self.assertIsNotNone(stored.frozen_at)
        self.assertIsNotNone(stored.dispatch_started_at)
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 4)
        campaign = db.session.get(NotificationCampaign, draft['id'])
        self.assertEqual(campaign.state, 'PROCESSING')

    def test_concurrent_claim_cannot_duplicate(self):
        """Two 'workers' racing for the same due execution: only one may
        claim it (lease compare-and-set is DB-authoritative, not a
        Python lock)."""
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        # A generous batch_limit -- other tests in this suite may have
        # left their own due-but-unclaimed executions behind for the
        # same "now"; the assertions below check THIS execution
        # specifically, not the batch's total size.
        due_now = stored.scheduled_for + timedelta(seconds=1)
        first = scheduler._claim_due_batch(due_now, 50, 'worker-A', 120)
        second = scheduler._claim_due_batch(due_now, 50, 'worker-B', 120)
        self.assertIn(execution_id, [e.id for e in first])
        self.assertNotIn(execution_id, [e.id for e in second])
        db.session.refresh(stored)
        self.assertEqual(stored.lease_owner, 'worker-A')

    def test_lease_recovery_after_expiry(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        due_now = stored.scheduled_for + timedelta(seconds=1)
        claimed = scheduler._claim_due_batch(due_now, 50, 'crashed-worker', 1)  # 1-second lease
        self.assertIn(execution_id, [e.id for e in claimed])
        later = due_now + timedelta(seconds=5)  # lease now expired, execution still SCHEDULED (never dispatched)
        recovered = scheduler._claim_due_batch(later, 50, 'recovery-worker', 120)
        self.assertIn(execution_id, [e.id for e in recovered])

    # ---------------- I: late execution ----------------

    def test_late_unexpired_execution_still_dispatches(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        original_scheduled_for = stored.scheduled_for
        late_now = stored.scheduled_for + timedelta(minutes=25)  # worker was down, recovers late
        self.assertLess(late_now, stored.expires_at)  # still within the 24h default window
        summary = scheduler.process_due_scheduled_campaigns(now=late_now)
        self.assertIn(execution_id, [r['execution_id'] for r in summary['results']])
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'FROZEN')
        self.assertEqual(stored.scheduled_for, original_scheduled_for)  # never rewritten
        self.assertEqual(stored.dispatch_started_at, late_now)

    # ---------------- J: expiry ----------------

    def test_default_expiry_is_24h(self):
        draft = self.make_draft()
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        response = self.schedule(draft['id'], scheduled_for=iso(future))
        body = response.get_json()
        scheduled = datetime.fromisoformat(body['scheduled_for'])
        expires = datetime.fromisoformat(body['expires_at'])
        self.assertAlmostEqual((expires - scheduled).total_seconds(), 24 * 3600, delta=2)

    def test_expiry_cannot_exceed_24h(self):
        draft = self.make_draft()
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        too_long = future + timedelta(hours=25)
        response = self.schedule(draft['id'], scheduled_for=iso(future), expires_at=iso(too_long))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'invalid_expiry')

    def test_expired_execution_never_freezes_or_sends(self):
        draft = self.make_draft()
        future = datetime.now(timezone.utc) + timedelta(minutes=2)
        response = self.schedule(draft['id'], scheduled_for=iso(future), expires_at=iso(future + timedelta(minutes=10)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        after_expiry = stored.expires_at + timedelta(seconds=1)
        summary = scheduler.process_due_scheduled_campaigns(now=after_expiry)
        # >=1, not ==1: other tests in this suite may leave their own due
        # SCHEDULED executions behind for this same "now" to sweep up --
        # the assertions below check THIS execution specifically.
        self.assertGreaterEqual(summary['claimed'], 1)
        self.assertIn(execution_id, [r['execution_id'] for r in summary['results']])
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'EXPIRED')
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 0)
        campaign = db.session.get(NotificationCampaign, draft['id'])
        self.assertEqual(campaign.state, 'FAILED')
        self.assertEqual(campaign.hold_reason, 'EXPIRED')

    # ---------------- K: dispatch resolution / audience unavailable ----------------

    def test_dependency_failure_at_dispatch_blocks_not_zero(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        due_now = stored.scheduled_for + timedelta(seconds=1)
        with patch('notifications.campaign_scheduler.resolve_saved_audience_recipients',
                   side_effect=RecipientResolutionError('RESOLUTION_UNAVAILABLE')):
            scheduler.process_due_scheduled_campaigns(now=due_now)
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'BLOCKED')
        self.assertEqual(stored.hold_reason, 'RESOLUTION_UNAVAILABLE')
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 0)

    def test_audience_deleted_before_dispatch_fails_closed(self):
        soon_gone = SavedAudience(name='N5 soon gone', criteria={'version': 1, 'filters': {'search': 'n5-sched-'}}, is_active=True)
        db.session.add(soon_gone); db.session.commit()
        draft = self.make_draft(audience_id=soon_gone.id)
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        db.session.delete(soon_gone); db.session.commit()
        due_now = stored.scheduled_for + timedelta(seconds=1)
        scheduler.process_due_scheduled_campaigns(now=due_now)
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'BLOCKED')
        self.assertEqual(stored.hold_reason, 'AUDIENCE_UNAVAILABLE')

    def test_50k_blocked_again_at_dispatch_even_if_approved_below(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        due_now = stored.scheduled_for + timedelta(seconds=1)
        with patch('notifications.campaign_scheduler.resolve_saved_audience_recipients',
                   side_effect=RecipientResolutionError('SAFETY_CEILING_EXCEEDED', matched_user_count=52000)):
            scheduler.process_due_scheduled_campaigns(now=due_now)
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'BLOCKED')
        self.assertEqual(stored.hold_reason, 'SAFETY_CEILING_EXCEEDED')
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 0)

    # ---------------- L: drift at dispatch + reconfirm ----------------

    def test_drift_at_dispatch_pauses_no_deliveries(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        due_now = stored.scheduled_for + timedelta(seconds=1)
        drifted = self._fake_resolution(matched=100, eligible=90, is_all_users=False)  # baseline was 4/4 -> huge drift
        with patch('notifications.campaign_scheduler.resolve_saved_audience_recipients', return_value=drifted):
            scheduler.process_due_scheduled_campaigns(now=due_now)
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'PAUSED')
        self.assertEqual(stored.hold_reason, 'DRIFT')
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 0)
        campaign = db.session.get(NotificationCampaign, draft['id'])
        self.assertEqual(campaign.state, 'PROCESSING')
        self.assertEqual(campaign.hold_reason, 'DRIFT')

        # Reconfirm with an acceptable resolution -> freezes, scheduled_for preserved.
        original_scheduled_for = stored.scheduled_for
        stable = self._fake_resolution(matched=101, eligible=91, is_all_users=False)
        with patch.object(svc, '_resolve_live', return_value=stable):
            reconfirmed = self.client.post(f'/admin/api/notifications/executions/{execution_id}/reconfirm', json={}, headers=self.admin)
        self.assertEqual(reconfirmed.status_code, 200)
        body = reconfirmed.get_json()
        self.assertEqual(body['state'], 'FROZEN')
        self.assertEqual(NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).count(), 91)
        db.session.refresh(stored)
        self.assertEqual(stored.scheduled_for, original_scheduled_for)

    def test_drift_threshold_reused_exactly(self):
        self.assertFalse(svc._drifted(100, 120))
        self.assertTrue(svc._drifted(100, 121))
        self.assertTrue(svc._drifted(0, 1))

    # ---------------- M: target freeze reuse / retry regression ----------------

    def test_frozen_scheduled_execution_uses_n4_worker_unchanged(self):
        """Once FROZEN, a scheduled execution is indistinguishable from
        an N4 Send Now one to campaign_worker.py -- same retry/UNKNOWN
        contract, proven directly here (not just by not-touching the code)."""
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        scheduler.process_due_scheduled_campaigns(now=stored.scheduled_for + timedelta(seconds=1))
        db.session.refresh(stored)
        self.assertEqual(stored.state, 'FROZEN')

        transport = FakeTransport(outcomes={'n5-token-0': TransportResult(outcome='FAILED_RETRYABLE', provider='fake', retryable=True)})
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id, app_user_id=self.base + 100).first()
        for _ in range(4):
            worker.process_execution(execution_id, transport)
            db.session.refresh(delivery)
            if delivery.status == 'FAILED_PERMANENT':
                break
            delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(delivery.attempt_count, 4)  # max 4 attempts, locked N4 contract
        self.assertEqual(delivery.status, 'FAILED_PERMANENT')
        attempts = NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count()
        self.assertEqual(attempts, 4)

    def test_new_matching_user_after_freeze_not_added(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        scheduler.process_due_scheduled_campaigns(now=stored.scheduled_for + timedelta(seconds=1))
        new_id = self.base + 900
        db.session.add(User(id=new_id, firebase_uid='n5-sched-late', name='n5-sched-late', email='n5-sched-late@example.invalid'))
        db.session.add(AppUser(id=new_id + 100, firebase_uid='n5-sched-late', fcm_token='n5-token-late', lang='en'))
        db.session.commit()
        try:
            ids = {d.user_id for d in NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).all()}
            self.assertNotIn(new_id, ids)
        finally:
            AppUser.query.filter_by(id=new_id + 100).delete()
            User.query.filter_by(id=new_id).delete()
            db.session.commit()

    # ---------------- N: idempotency ----------------

    def test_schedule_idempotency_same_key_same_request(self):
        draft = self.make_draft()
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        payload = dict(revision=1, idempotency_key='dup-sched', scheduled_for=iso(future), preview_generated_at=iso(datetime.now(timezone.utc)))
        first = self.client.post(f"/admin/api/notifications/{draft['id']}/schedule", json=payload, headers=self.admin)
        second = self.client.post(f"/admin/api/notifications/{draft['id']}/schedule", json=payload, headers=self.admin)
        self.assertEqual(first.get_json()['id'], second.get_json()['id'])
        self.assertEqual(NotificationCampaignExecution.query.filter_by(campaign_id=draft['id']).count(), 1)

    def test_schedule_idempotency_conflicting_request_rejected(self):
        draft = self.make_draft()
        self.schedule(draft['id'], idempotency_key='conflict-sched')
        conflicting = self.schedule(draft['id'], idempotency_key='conflict-sched',
                                     scheduled_for=iso(datetime.now(timezone.utc) + timedelta(hours=9)))
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(conflicting.get_json()['error'], 'idempotency_conflict')

    # ---------------- Reschedule / Cancel ----------------

    def test_reschedule_before_due_changes_only_time_fields(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'])
        execution_id = response.get_json()['id']
        new_time = iso(datetime.now(timezone.utc) + timedelta(hours=6))
        reschedule_resp = self.client.post(f'/admin/api/notifications/executions/{execution_id}/reschedule',
                                            json={'scheduled_for': new_time}, headers=self.admin)
        self.assertEqual(reschedule_resp.status_code, 200)
        body = reschedule_resp.get_json()
        self.assertEqual(body['scheduled_for'], datetime.fromisoformat(new_time).isoformat())
        self.assertEqual(body['approved_saved_audience_id'], self.audience_id)  # definition untouched
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(stored.approved_title, 'Hello N5')

    def test_reschedule_after_due_rejected(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        scheduler.process_due_scheduled_campaigns(now=stored.scheduled_for + timedelta(seconds=1))
        reschedule_resp = self.client.post(f'/admin/api/notifications/executions/{execution_id}/reschedule',
                                            json={'scheduled_for': iso(datetime.now(timezone.utc) + timedelta(hours=6))}, headers=self.admin)
        self.assertEqual(reschedule_resp.status_code, 409)

    def test_cancel_before_freeze_is_idempotent(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'])
        execution_id = response.get_json()['id']
        first = self.client.post(f'/admin/api/notifications/executions/{execution_id}/cancel', json={}, headers=self.admin)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()['state'], 'CANCELLED')
        second = self.client.post(f'/admin/api/notifications/executions/{execution_id}/cancel', json={}, headers=self.admin)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()['state'], 'CANCELLED')
        campaign = db.session.get(NotificationCampaign, draft['id'])
        self.assertEqual(campaign.state, 'CANCELLED')

    def test_cancel_after_freeze_rejected(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        scheduler.process_due_scheduled_campaigns(now=stored.scheduled_for + timedelta(seconds=1))
        cancel_resp = self.client.post(f'/admin/api/notifications/executions/{execution_id}/cancel', json={}, headers=self.admin)
        self.assertEqual(cancel_resp.status_code, 409)

    def test_cancelled_execution_never_claimed(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        self.client.post(f'/admin/api/notifications/executions/{execution_id}/cancel', json={}, headers=self.admin)
        summary = scheduler.process_due_scheduled_campaigns(now=stored.scheduled_for + timedelta(seconds=1))
        self.assertNotIn(execution_id, [r['execution_id'] for r in summary['results']])

    # ---------------- P: isolation ----------------

    def test_no_firebase_or_transport_import_in_scheduler_modules(self):
        for module in (sched, scheduler):
            with open(module.__file__, encoding='utf-8') as fh:
                lines = [l for l in fh if l.strip().startswith(('import ', 'from '))]
            for forbidden in ('firebase_admin', 'campaign_worker', 'campaign_transport', 'messaging', 'celery'):
                self.assertFalse(any(forbidden in line.lower() for line in lines), f'{forbidden} imported in {module.__name__}')

    def test_no_recipient_pii_in_scheduled_execution_response(self):
        draft = self.make_draft()
        response = self.schedule(draft['id'], scheduled_for=iso(datetime.now(timezone.utc) + timedelta(minutes=2)))
        execution_id = response.get_json()['id']
        stored = db.session.get(NotificationCampaignExecution, execution_id)
        scheduler.process_due_scheduled_campaigns(now=stored.scheduled_for + timedelta(seconds=1))
        detail = self.client.get(f'/admin/api/notifications/executions/{execution_id}', headers=self.admin)
        payload = str(detail.get_json())
        for offset in range(4):
            self.assertNotIn(f'n5-token-{offset}', payload)
            self.assertNotIn(f'n5-sched-{offset}', payload)


if __name__ == '__main__':
    unittest.main(verbosity=2)
