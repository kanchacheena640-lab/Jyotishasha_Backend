"""N6 -- Bell isolation, unified read/write API, metrics contract,
Admin history. Run via scripts/l3_local_verify.py so no Firebase/
network/DDL slips in."""
import os
import unittest
from datetime import datetime, timedelta, timezone, time as dt_time

from flask_jwt_extended import create_access_token

from app import app
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.models_saved_audience import SavedAudience
from modules.models_activity_events import ActivityEvent
from notifications.notification_models import UserNotification
from notifications.campaign_models import NotificationCampaign
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
    NotificationSendNowRequest,
)
from notifications.campaign_bell_models import NotificationCampaignBellItem
from notifications import campaign_bell_service
from notifications import campaign_metrics_service as metrics_svc
from notifications import campaign_history_service as history_svc
from notifications.campaign_service import CampaignError, get_campaign
from services.attention_policy import count_pushes_sent_today
import services.event_scheduler as event_scheduler


def iso(dt):
    return dt.isoformat()


class N6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 9979000
        cls.ids = list(range(cls.base, cls.base + 4))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in enumerate(cls.ids):
            uid = f'n6-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'n6-token-{offset}',
                                    lang='en', moon_sign='Aries'))
        db.session.commit()
        cls.audience = SavedAudience(name='N6 synthetic', criteria={'version': 1, 'filters': {'search': 'n6-'}}, is_active=True)
        db.session.add(cls.audience)
        db.session.commit()
        cls.audience_id = cls.audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.ids[0])
        os.environ.setdefault('ACTIVITY_EVENTS_ENVIRONMENT', 'local')
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[0]))}
        cls.user_token = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[1]))}
        cls.target_user_id = cls.ids[1] + 100  # app_user_id of ids[1]

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
        UserNotification.query.filter(UserNotification.user_id.in_([i + 100 for i in cls.ids])).delete(synchronize_session=False)
        ActivityEvent.query.filter(ActivityEvent.firebase_uid.in_([f'n6-{o}' for o in range(4)])).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def setUp(self):
        # Clean per-test state for the shared target user's Bell rows.
        NotificationCampaignBellItem.query.filter_by(user_id=self.target_user_id).delete(synchronize_session=False)
        UserNotification.query.filter_by(user_id=self.target_user_id).delete(synchronize_session=False)
        db.session.commit()

    # ---------------- fixtures ----------------

    def make_and_send(self, title='N6 campaign'):
        payload = dict(title=title, body='Body', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=self.audience_id,
                       action={'type': 'NONE', 'target': None, 'parameters': {}})
        r = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        self.assertEqual(r.status_code, 201)
        campaign_id = r.get_json()['id']
        self.campaigns.append(campaign_id)
        baseline = {'generated_at': iso(datetime.now(timezone.utc)), 'matched_user_count': 4, 'eligible_recipient_count': 4}
        r = self.client.post(f'/admin/api/notifications/{campaign_id}/send-now',
                              json={'revision': 1, 'idempotency_key': 'key-' + campaign_id, 'baseline': baseline},
                              headers=self.admin)
        self.assertEqual(r.status_code, 202)
        return campaign_id, r.get_json()

    # ---------------- Bell lifecycle + isolation ----------------

    def test_bell_items_created_at_target_freeze(self):
        campaign_id, execution = self.make_and_send()
        self.assertEqual(execution['state'], 'FROZEN')
        items = NotificationCampaignBellItem.query.filter_by(execution_id=execution['id']).all()
        self.assertEqual(len(items), 4)
        self.assertTrue(all(i.is_read is False and i.dismissed_at is None for i in items))

    def test_campaign_c_never_writes_user_notifications_table(self):
        before = UserNotification.query.count()
        self.make_and_send()
        after = UserNotification.query.count()
        self.assertEqual(before, after, "Campaign C send-now must never insert a UserNotification row")

    def test_campaign_c_does_not_consume_ab_push_budget(self):
        before = count_pushes_sent_today(self.target_user_id, now=datetime.utcnow())
        self.make_and_send()
        self.make_and_send()  # multiple campaigns to the same audience
        after = count_pushes_sent_today(self.target_user_id, now=datetime.utcnow())
        self.assertEqual(before, after, "Campaign C bell items must never count toward A/B's daily push cap")

    def test_campaign_c_bell_items_not_touched_by_ab_keep_newest_10_trim(self):
        """The A pipeline's own 'keep newest 10' per-user trim
        (services/event_scheduler.py) queries UserNotification only --
        prove it neither deletes nor is influenced by
        NotificationCampaignBellItem rows for the same user."""
        campaign_id, execution = self.make_and_send()
        cc_count_before = NotificationCampaignBellItem.query.filter_by(user_id=self.target_user_id).count()
        self.assertGreater(cc_count_before, 0)

        # Simulate A's own trim for this user (exact query shape copied
        # from services/event_scheduler.py's own trim block).
        old_notifications = (
            UserNotification.query.filter_by(user_id=self.target_user_id)
            .order_by(UserNotification.created_at.desc(), UserNotification.id.desc())
            .offset(10).all()
        )
        for old in old_notifications:
            db.session.delete(old)
        db.session.commit()

        cc_count_after = NotificationCampaignBellItem.query.filter_by(user_id=self.target_user_id).count()
        self.assertEqual(cc_count_before, cc_count_after, "A's own trim must never touch Campaign C's isolated table")

    def test_ab_row_present_does_not_change_cc_bell_item_count(self):
        """Converse direction: A/B writing many UserNotification rows for
        a user must not cause Campaign C's own bell item count/visibility
        to change (proves no shared trim/limit is applied across tables)."""
        campaign_id, execution = self.make_and_send()
        cc_before = NotificationCampaignBellItem.query.filter_by(user_id=self.target_user_id).count()
        self.assertEqual(cc_before, 1)
        for i in range(15):
            db.session.add(UserNotification(user_id=self.target_user_id, title=f'AB {i}', body='x',
                                              data={}, is_read=False, created_at=datetime.now(timezone.utc)))
        db.session.commit()
        cc_after = NotificationCampaignBellItem.query.filter_by(user_id=self.target_user_id).count()
        self.assertEqual(cc_before, cc_after, "Campaign C row count must be unaffected by unrelated UserNotification inserts")

    # ---------------- unified read/write API ----------------

    def test_unified_list_merges_both_sources(self):
        campaign_id, execution = self.make_and_send()
        db.session.add(UserNotification(user_id=self.target_user_id, title='AB item', body='x',
                                          data={}, is_read=False, created_at=datetime.now(timezone.utc)))
        db.session.commit()
        items = campaign_bell_service.list_unified_bell(self.target_user_id)
        sources = {i['source'] for i in items}
        self.assertIn('AB', sources)
        self.assertIn('ADMIN_CAMPAIGN', sources)

    def test_cc_item_carries_campaign_and_execution_identity_for_client_correlation(self):
        """Flutter finalization: a Bell tap (unlike a push tap, which gets
        this from the FCM data payload) has no other way to learn which
        campaign/execution a Campaign C row belongs to -- required for a
        correctly-correlated notification_opened/destination_opened."""
        campaign_id, execution = self.make_and_send()
        items = campaign_bell_service.list_unified_bell(self.target_user_id)
        cc_item = next(i for i in items if i['source'] == 'ADMIN_CAMPAIGN')
        self.assertEqual(cc_item['campaign_id'], campaign_id)
        self.assertEqual(cc_item['execution_id'], execution['id'])

    def test_unread_count_sums_both_sources(self):
        campaign_id, execution = self.make_and_send()
        db.session.add(UserNotification(user_id=self.target_user_id, title='AB item', body='x',
                                          data={}, is_read=False, created_at=datetime.now(timezone.utc)))
        db.session.commit()
        count = campaign_bell_service.unread_count(self.target_user_id)
        self.assertEqual(count, 2)  # 1 Campaign C item for this user + 1 AB

    def test_mark_all_read_covers_both_sources(self):
        campaign_id, execution = self.make_and_send()
        db.session.add(UserNotification(user_id=self.target_user_id, title='AB item', body='x',
                                          data={}, is_read=False, created_at=datetime.now(timezone.utc)))
        db.session.commit()
        campaign_bell_service.mark_all_read(self.target_user_id)
        self.assertEqual(campaign_bell_service.unread_count(self.target_user_id), 0)

    def test_dismiss_one_is_presentation_only(self):
        campaign_id, execution = self.make_and_send()
        item = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution['id'], user_id=self.target_user_id).first()
        item_id = f'cc:{item.id}'
        delivery = NotificationCampaignDelivery.query.filter_by(
            execution_id=execution['id'], app_user_id=item.app_user_id).first()
        status_before = delivery.status
        ok = campaign_bell_service.dismiss_one(self.target_user_id, item_id)
        self.assertTrue(ok)
        db.session.refresh(delivery)
        self.assertEqual(delivery.status, status_before, "dismissal must never mutate delivery/operational history")
        self.assertNotIn(item_id, [i['id'] for i in campaign_bell_service.list_unified_bell(self.target_user_id)])

    # ---------------- N6 individual-dismiss defect regression ----------------
    # Physical-device QA found the × button never reached the backend at
    # all -- the root cause was entirely client-side (greeting_header_widget.dart
    # read the wrong composite-id field; see the Flutter test suite's own
    # N6 regression group). These prove the SERVER side of the same dismiss
    # contract the fixed client now actually calls: the composite cc:<uuid>
    # id works end to end through the real HTTP route (not just the service
    # function directly), only the targeted row is ever touched, A/B's own
    # composite dismiss is unaffected, a malformed/foreign id fails safely
    # (this investigation also found dismiss_one()/mark_read() crashing with
    # an unhandled 500 on a syntactically-invalid cc:<id> -- fixed in
    # campaign_bell_service.py alongside this), and no operational history
    # or activity-event side effect is ever produced.

    def test_dismiss_route_end_to_end_for_campaign_c_composite_id(self):
        campaign_id, execution = self.make_and_send()
        item = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution['id'], user_id=self.target_user_id).first()
        item_id = f'cc:{item.id}'

        events_before = ActivityEvent.query.count()
        r = self.client.post('/api/user-notifications/dismiss', json={'item_id': item_id}, headers=self.user_token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {'success': True})

        r = self.client.get('/api/user-notifications', headers=self.user_token)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(item_id, [i['id'] for i in r.get_json()],
                          "dismissed Campaign C item must disappear from the unified Bell response")
        self.assertEqual(ActivityEvent.query.count(), events_before,
                          "dismiss is a Bell-presentation action only -- it must never itself emit an activity event "
                          "(notification_opened/destination_opened are emitted only by a row TAP, never by dismiss)")

    def test_dismiss_only_affects_the_selected_item(self):
        """Two separate Campaign C sends to the same user -- dismissing one
        must leave the other's dismissed_at untouched."""
        campaign_id_1, execution_1 = self.make_and_send(title='N6 dismiss target')
        campaign_id_2, execution_2 = self.make_and_send(title='N6 dismiss bystander')
        item_1 = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution_1['id'], user_id=self.target_user_id).first()
        item_2 = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution_2['id'], user_id=self.target_user_id).first()

        ok = campaign_bell_service.dismiss_one(self.target_user_id, f'cc:{item_1.id}')
        self.assertTrue(ok)

        db.session.refresh(item_1)
        db.session.refresh(item_2)
        self.assertIsNotNone(item_1.dismissed_at)
        self.assertIsNone(item_2.dismissed_at, "dismissing one Campaign C item must never dismiss another")
        remaining_ids = [i['id'] for i in campaign_bell_service.list_unified_bell(self.target_user_id)]
        self.assertNotIn(f'cc:{item_1.id}', remaining_ids)
        self.assertIn(f'cc:{item_2.id}', remaining_ids)

    def test_dismiss_ab_composite_id_still_works_via_route(self):
        """A/B's own composite id ('ab:<int>') dismiss, through the same
        route the fixed Flutter client now calls -- unaffected by Campaign C."""
        row = UserNotification(user_id=self.target_user_id, title='AB dismiss test', body='x',
                                data={}, is_read=False, created_at=datetime.now(timezone.utc))
        db.session.add(row)
        db.session.commit()
        item_id = f'ab:{row.id}'

        r = self.client.post('/api/user-notifications/dismiss', json={'item_id': item_id}, headers=self.user_token)
        self.assertEqual(r.status_code, 200)

        db.session.refresh(row)
        self.assertIsNotNone(row.dismissed_at)
        self.assertFalse(row.is_read, "dismiss must never mutate an A/B row's is_read")
        self.assertNotIn(item_id, [i['id'] for i in campaign_bell_service.list_unified_bell(self.target_user_id)])

    def test_dismiss_malformed_id_fails_safely(self):
        """Regression: a syntactically-invalid cc:<id> (not a UUID) used to
        raise an unhandled psycopg2 DataError (500) instead of a clean
        'not found' -- fixed in campaign_bell_service.py's
        _is_syntactically_valid_uuid() guard."""
        for bad_id in ('cc:not-a-uuid', 'ab:not-an-int', 'totally-unknown-format'):
            r = self.client.post('/api/user-notifications/dismiss', json={'item_id': bad_id}, headers=self.user_token)
            self.assertEqual(r.status_code, 404, f"malformed id {bad_id!r} must fail safely, not crash")
        # An empty item_id never reaches the parser at all -- the route's
        # own "item_id required" guard rejects it first, safely, as 400.
        r = self.client.post('/api/user-notifications/dismiss', json={'item_id': ''}, headers=self.user_token)
        self.assertEqual(r.status_code, 400)

    def test_dismiss_foreign_id_fails_safely_and_leaves_owner_row_untouched(self):
        """Another user's real Campaign C item id, sent under THIS user's
        auth -- must be rejected (not found) and must never touch the
        actual owner's row."""
        campaign_id, execution = self.make_and_send()
        other_user_id = self.ids[2] + 100
        assert other_user_id != self.target_user_id
        foreign_item = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution['id'], user_id=other_user_id).first()
        self.assertIsNotNone(foreign_item)
        foreign_item_id = f'cc:{foreign_item.id}'

        r = self.client.post('/api/user-notifications/dismiss', json={'item_id': foreign_item_id}, headers=self.user_token)
        self.assertEqual(r.status_code, 404)

        db.session.refresh(foreign_item)
        self.assertIsNone(foreign_item.dismissed_at, "a foreign item_id must never dismiss another user's row")

    def test_dismiss_leaves_campaign_execution_delivery_and_history_untouched(self):
        campaign_id, execution = self.make_and_send()
        item = NotificationCampaignBellItem.query.filter_by(
            execution_id=execution['id'], user_id=self.target_user_id).first()
        delivery = NotificationCampaignDelivery.query.filter_by(
            execution_id=execution['id'], app_user_id=item.app_user_id).first()

        campaign_row = get_campaign(campaign_id)
        execution_row = db.session.get(NotificationCampaignExecution, execution['id'])
        campaign_state_before, execution_state_before = campaign_row.state, execution_row.state
        frozen_at_before, delivery_status_before = execution_row.frozen_at, delivery.status
        attempts_before = NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count()

        r = self.client.post('/api/user-notifications/dismiss', json={'item_id': f'cc:{item.id}'}, headers=self.user_token)
        self.assertEqual(r.status_code, 200)

        db.session.refresh(campaign_row)
        db.session.refresh(execution_row)
        db.session.refresh(delivery)
        self.assertEqual(campaign_row.state, campaign_state_before)
        self.assertEqual(execution_row.state, execution_state_before)
        self.assertEqual(execution_row.frozen_at, frozen_at_before)
        self.assertEqual(delivery.status, delivery_status_before)
        self.assertEqual(NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count(), attempts_before,
                          "dismiss must never create/mutate a delivery attempt row")

    def test_clear_all_dismisses_both_sources(self):
        campaign_id, execution = self.make_and_send()
        db.session.add(UserNotification(user_id=self.target_user_id, title='AB item', body='x',
                                          data={}, is_read=False, created_at=datetime.now(timezone.utc)))
        db.session.commit()
        campaign_bell_service.clear_all(self.target_user_id)
        self.assertEqual(campaign_bell_service.list_unified_bell(self.target_user_id), [])
        self.assertEqual(campaign_bell_service.unread_count(self.target_user_id), 0)

    def test_no_mark_unread_function_exists(self):
        self.assertFalse(hasattr(campaign_bell_service, 'mark_unread'))

    # ---------------- Panchang / expiry regression ----------------

    def test_expires_at_still_governs_ab_visibility_after_n6(self):
        """Regression: an already-expired A/B row must stay invisible in
        the unified list even though N6 added a new dismissed_at filter
        alongside the pre-existing expires_at filter."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        db.session.add(UserNotification(user_id=self.target_user_id, title='Expired Panchang-style', body='x',
                                          data={}, is_read=False, created_at=datetime.now(timezone.utc) - timedelta(hours=6),
                                          expires_at=past))
        db.session.commit()
        items = campaign_bell_service.list_unified_bell(self.target_user_id)
        self.assertFalse(any(i['title'] == 'Expired Panchang-style' for i in items))
        self.assertEqual(campaign_bell_service.unread_count(self.target_user_id), 0)

    def test_unexpired_ab_row_still_visible_and_undismissed_by_default(self):
        db.session.add(UserNotification(user_id=self.target_user_id, title='Still valid', body='x',
                                          data={}, is_read=False, created_at=datetime.now(timezone.utc)))
        db.session.commit()
        items = campaign_bell_service.list_unified_bell(self.target_user_id)
        self.assertTrue(any(i['title'] == 'Still valid' for i in items))

    def test_panchang_evening_disappear_boundary_unaffected_by_n6(self):
        """N6 final gate -- proves a same-day Panchang-shaped notification's
        real 5:00 PM IST evening-expiry INSTANT (services/event_scheduler.py's
        own PANCHANG_AUTO_DISMISS_HOUR_IST == 17, imported here, never a
        hand-copied literal) still governs unified-Bell visibility exactly
        as it did before N6, with a Campaign C item present in the SAME
        call to prove C's existence never alters A's expiry filtering.
        `now` is passed explicitly (LOCAL time-controlled, no real
        clock/sleep needed) so the test is deterministic regardless of
        when it actually runs.

        Stores expires_at as the tz-aware instant directly (this suite's
        own established convention -- see
        test_expires_at_still_governs_ab_visibility_after_n6 above), NOT
        via event_scheduler.py's own `.replace(tzinfo=None)` strip: this
        local Postgres role's default session TimeZone is Asia/Calcutta
        (not UTC), and a WHERE-clause comparison of that stripped naive
        value against a tz-aware `now` gets reinterpreted in the SESSION
        zone, not UTC, silently shifting the effective cutoff by the
        UTC/IST offset. That storage-convention question is a separate,
        PRE-EXISTING, N6-independent risk (identical before/after N6 --
        campaign_bell_service.py's own filter here is a byte-for-byte
        carry-over of user_notification_routes.py's pre-N6 query) --
        flagged separately, not fixed here per this task's own "do not
        change working code unless an actual N6 regression is found."
        This test's own job is narrower and still fully proven: GIVEN a
        correctly-stored 5 PM IST expires_at instant, unified-Bell
        visibility flips at exactly that instant, unchanged by N6."""
        target_date = datetime.now(timezone.utc).date()
        real_expiry_utc = datetime.combine(
            target_date, dt_time(hour=event_scheduler.PANCHANG_AUTO_DISMISS_HOUR_IST), tzinfo=event_scheduler.IST
        ).astimezone(timezone.utc)

        db.session.add(UserNotification(
            user_id=self.target_user_id, title='Today\'s Panchang', body='Best time, avoid time...',
            data={'type': 'panchang', 'auto_dismiss_at': real_expiry_utc.isoformat()},
            is_read=False, created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            expires_at=real_expiry_utc,
        ))
        db.session.commit()

        # A Campaign C item present in the same list call, to prove its
        # presence doesn't alter A's own expiry behavior either direction.
        campaign_id, execution = self.make_and_send(title='N6 alongside Panchang')

        before_boundary = real_expiry_utc - timedelta(minutes=1)   # 4:59 PM IST
        after_boundary = real_expiry_utc + timedelta(minutes=1)    # 5:01 PM IST

        visible_before = campaign_bell_service.list_unified_bell(self.target_user_id, now=before_boundary)
        self.assertTrue(any(i['title'] == "Today's Panchang" for i in visible_before),
                         "Panchang notification must be visible before its 5 PM IST evening expiry")
        self.assertTrue(any(i['source'] == 'ADMIN_CAMPAIGN' for i in visible_before),
                         "Campaign C item must also be visible in the same unified list")

        visible_after = campaign_bell_service.list_unified_bell(self.target_user_id, now=after_boundary)
        self.assertFalse(any(i['title'] == "Today's Panchang" for i in visible_after),
                          "Panchang notification must disappear once its 5 PM IST evening expiry passes")
        self.assertTrue(any(i['source'] == 'ADMIN_CAMPAIGN' for i in visible_after),
                         "Campaign C item's own visibility must be completely unaffected by Panchang's expiry")


class N6MetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        os.environ.setdefault('ACTIVITY_EVENTS_ENVIRONMENT', 'local')
        cls.uid = 'n6-metrics-user'
        cls.campaign_id = 'n6-metrics-campaign-11111111-1111-1111-1111-111111111111'
        cls.other_campaign_id = 'n6-metrics-campaign-22222222-2222-2222-2222-222222222222'

    @classmethod
    def tearDownClass(cls):
        ActivityEvent.query.filter(ActivityEvent.firebase_uid == cls.uid).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def tearDown(self):
        ActivityEvent.query.filter(ActivityEvent.firebase_uid == self.uid).delete(synchronize_session=False)
        db.session.commit()

    def _emit(self, event_name, occurred_at, campaign_id=None, properties=None):
        db.session.add(ActivityEvent(
            event_name=event_name, event_version=1, occurred_at=occurred_at,
            firebase_uid=self.uid, platform='app_android', environment='local',
            properties=properties or {},
            notification_context={'notification_id': 'n1', 'campaign_id': campaign_id, 'slot': 'general'} if campaign_id else None,
        ))
        db.session.commit()

    def test_rate_is_unknown_not_zero_when_denominator_is_zero(self):
        self.assertEqual(metrics_svc._rate(0, 0), 'UNKNOWN')
        self.assertEqual(metrics_svc._rate(5, 0), 'UNKNOWN')
        self.assertEqual(metrics_svc._rate(0, 5), 0.0)

    def test_open_and_destination_counts_scoped_to_exact_campaign_identity(self):
        now = datetime.now(timezone.utc)
        self._emit('notification_opened', now, campaign_id=self.campaign_id)
        self._emit('notification_opened', now, campaign_id=self.campaign_id)
        self._emit('destination_opened', now, campaign_id=self.campaign_id)
        self._emit('notification_opened', now, campaign_id=self.other_campaign_id)  # must NOT merge

        counts = metrics_svc.campaign_open_counts(self.campaign_id, environment='local')
        self.assertEqual(counts['notification_opened_count'], 2)
        self.assertEqual(counts['destination_opened_count'], 1)

        other_counts = metrics_svc.campaign_open_counts(self.other_campaign_id, environment='local')
        self.assertEqual(other_counts['notification_opened_count'], 1)

    def test_conversion_counts_qualifying_purchase_within_24h_after_click(self):
        click_at = datetime.now(timezone.utc) - timedelta(hours=1)
        purchase_at = click_at + timedelta(hours=23)
        self._emit('destination_opened', click_at, campaign_id=self.campaign_id)
        self._emit('payment_verified', purchase_at, properties={'purpose': 'REPORT_PURCHASE'})
        self.assertEqual(metrics_svc.campaign_conversion_count(self.campaign_id, environment='local'), 1)

    def test_conversion_excludes_purchase_after_24h_window(self):
        click_at = datetime.now(timezone.utc) - timedelta(hours=30)
        purchase_at = click_at + timedelta(hours=24, minutes=1)
        self._emit('destination_opened', click_at, campaign_id=self.campaign_id)
        self._emit('payment_verified', purchase_at, properties={'purpose': 'REPORT_PURCHASE'})
        self.assertEqual(metrics_svc.campaign_conversion_count(self.campaign_id, environment='local'), 0)

    def test_conversion_excludes_purchase_before_click(self):
        click_at = datetime.now(timezone.utc)
        purchase_at = click_at - timedelta(minutes=5)
        self._emit('destination_opened', click_at, campaign_id=self.campaign_id)
        self._emit('payment_verified', purchase_at, properties={'purpose': 'REPORT_PURCHASE'})
        self.assertEqual(metrics_svc.campaign_conversion_count(self.campaign_id, environment='local'), 0)

    def test_conversion_never_counts_payment_initiated(self):
        click_at = datetime.now(timezone.utc)
        purchase_at = click_at + timedelta(minutes=5)
        self._emit('destination_opened', click_at, campaign_id=self.campaign_id)
        self._emit('payment_initiated', purchase_at, properties={'purpose': 'REPORT_PURCHASE'})
        self.assertEqual(metrics_svc.campaign_conversion_count(self.campaign_id, environment='local'), 0)

    def test_conversion_ignores_non_qualifying_purpose(self):
        click_at = datetime.now(timezone.utc)
        purchase_at = click_at + timedelta(minutes=5)
        self._emit('destination_opened', click_at, campaign_id=self.campaign_id)
        self._emit('payment_verified', purchase_at, properties={'purpose': 'ASTROLOGER_CONSULT'})
        self.assertEqual(metrics_svc.campaign_conversion_count(self.campaign_id, environment='local'), 0)

    def test_conversion_counts_one_user_once_with_multiple_clicks_and_purchases(self):
        base = datetime.now(timezone.utc)
        self._emit('destination_opened', base, campaign_id=self.campaign_id)
        self._emit('destination_opened', base + timedelta(minutes=10), campaign_id=self.campaign_id)
        self._emit('payment_verified', base + timedelta(minutes=20), properties={'purpose': 'REPORT_PURCHASE'})
        self._emit('payment_verified', base + timedelta(minutes=30), properties={'purpose': 'SUBSCRIPTION'})
        self.assertEqual(metrics_svc.campaign_conversion_count(self.campaign_id, environment='local'), 1)


class N6HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 9979500
        cls.ids = list(range(cls.base, cls.base + 2))
        for offset, user_id in enumerate(cls.ids):
            uid = f'n6-hist-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'n6-hist-token-{offset}',
                                    lang='en', moon_sign='Aries'))
        db.session.commit()
        cls.audience = SavedAudience(name='N6 history synthetic', criteria={'version': 1, 'filters': {'search': 'n6-hist-'}}, is_active=True)
        db.session.add(cls.audience)
        db.session.commit()
        cls.audience_id = cls.audience.id
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
        NotificationCampaignBellItem.query.filter(NotificationCampaignBellItem.execution_id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationSendNowRequest.query.filter(NotificationSendNowRequest.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationCampaign.query.filter(NotificationCampaign.id.in_(campaign_ids)).delete(synchronize_session=False)
        SavedAudience.query.filter(SavedAudience.id == cls.audience_id).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def make_and_send(self, title='N6 history campaign'):
        payload = dict(title=title, body='Body', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=self.audience_id,
                       action={'type': 'NONE', 'target': None, 'parameters': {}})
        r = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        campaign_id = r.get_json()['id']
        self.campaigns.append(campaign_id)
        baseline = {'generated_at': iso(datetime.now(timezone.utc)), 'matched_user_count': 2, 'eligible_recipient_count': 2}
        r = self.client.post(f'/admin/api/notifications/{campaign_id}/send-now',
                              json={'revision': 1, 'idempotency_key': 'key-' + campaign_id, 'baseline': baseline},
                              headers=self.admin)
        return campaign_id, r.get_json()

    def test_list_history_includes_non_draft_states(self):
        campaign_id, execution = self.make_and_send()
        result = history_svc.list_history(page=1, page_size=50, search='N6 history campaign')
        ids = [c['id'] for c in result['campaigns']]
        self.assertIn(campaign_id, ids)
        row = next(c for c in result['campaigns'] if c['id'] == campaign_id)
        self.assertEqual(row['execution_state'], 'FROZEN')
        self.assertEqual(row['target_count'], 2)

    def test_list_history_filters_by_state(self):
        result = history_svc.list_history(page=1, page_size=50, state='DRAFT')
        for row in result['campaigns']:
            self.assertEqual(row['state'], 'DRAFT')

    def test_list_history_rejects_unknown_state(self):
        with self.assertRaises(CampaignError):
            history_svc.list_history(state='NOT_A_REAL_STATE')

    def test_get_campaign_execution_detail_includes_metrics_and_never_says_delivered(self):
        campaign_id, execution = self.make_and_send()
        detail = history_svc.get_campaign_execution_detail(campaign_id)
        self.assertIn('metrics', detail)
        self.assertIn('delivery_counts', detail['metrics'])
        self.assertIn('ACCEPTED', detail['metrics']['delivery_counts'])
        self.assertNotIn('Delivered', str(detail['metrics']))
        self.assertNotIn('delivered', [k.lower() for k in detail['metrics'].keys()])

    def test_get_campaign_execution_detail_404_for_draft(self):
        payload = dict(title='Draft only', body='Body', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=self.audience_id, action={'type': 'NONE', 'target': None, 'parameters': {}})
        r = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        campaign_id = r.get_json()['id']
        self.campaigns.append(campaign_id)
        with self.assertRaises(CampaignError) as ctx:
            history_svc.get_campaign_execution_detail(campaign_id)
        self.assertEqual(ctx.exception.status, 404)

    def test_list_deliveries_and_attempts(self):
        campaign_id, execution = self.make_and_send()
        result = history_svc.list_deliveries(execution['id'], page=1, page_size=50)
        self.assertEqual(len(result['deliveries']), 2)
        for d in result['deliveries']:
            self.assertIn('user_id', d)
            self.assertNotIn('fcm_token', d)
        first_delivery_id = result['deliveries'][0]['id']
        attempts = history_svc.list_attempts(first_delivery_id)
        self.assertIn('attempts', attempts)

    def test_admin_history_route_requires_auth(self):
        r = self.client.get('/admin/api/notifications/history')
        self.assertEqual(r.status_code, 401)

    def test_admin_history_route_smoke(self):
        campaign_id, execution = self.make_and_send()
        r = self.client.get('/admin/api/notifications/history', headers=self.admin)
        self.assertEqual(r.status_code, 200)
        r = self.client.get(f'/admin/api/notifications/{campaign_id}/monitor', headers=self.admin)
        self.assertEqual(r.status_code, 200)
        self.assertIn('metrics', r.get_json())
        r = self.client.get(f'/admin/api/notifications/executions/{execution["id"]}/deliveries', headers=self.admin)
        self.assertEqual(r.status_code, 200)


if __name__ == '__main__':
    unittest.main()
