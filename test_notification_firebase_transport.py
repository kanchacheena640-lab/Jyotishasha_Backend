"""P1 -- real FCM transport (notifications/firebase_transport.py) +
select_transport() gate additions (notifications/campaign_transport.py).

NO real Firebase call anywhere in this file -- every test either exercises
pure gate logic (no network at all) or patches firebase_admin.messaging.send
directly, using the REAL firebase_admin exception classes (already
installed) to simulate every provider outcome deterministically.

Run via scripts/l3_local_verify.py so no Firebase/network/DDL slips in.
"""
import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

from flask_jwt_extended import create_access_token

from app import app
from extensions import db
from modules.models_user import AppUser
from modules.auth.models import User

from notifications import campaign_transport as ct
from notifications.campaign_transport import (
    Target, RenderedMessage, NoSendTransport,
    OUTCOME_ACCEPTED, OUTCOME_FAILED_RETRYABLE, OUTCOME_FAILED_PERMANENT, OUTCOME_UNKNOWN,
)
from notifications import firebase_transport as ft
from notifications import campaign_worker as worker
from notifications.campaign_execution_models import NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt

GATE_VARS = (
    'DEPLOYMENT_ENVIRONMENT', 'ADMIN_CAMPAIGN_SEND_ENABLED', 'ADMIN_CAMPAIGN_WORKER_AUTHORIZED',
    'ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED', 'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID',
)


class _EnvSandbox:
    """Saves/restores every gate var around a test so tests never leak
    environment state into each other or into unrelated suites."""

    def __enter__(self):
        self._saved = {name: os.environ.get(name) for name in GATE_VARS}
        for name in GATE_VARS:
            os.environ.pop(name, None)
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def set(self, **kwargs):
        for k, v in kwargs.items():
            os.environ[k] = v


class SelectTransportGateTests(unittest.TestCase):
    """Items 1-4."""

    def setUp(self):
        self.context = app.app_context(); self.context.push()

    def tearDown(self):
        self.context.pop()

    def test_1_local_default_selects_nosend(self):
        with _EnvSandbox():
            self.assertIsInstance(ct.select_transport(), NoSendTransport)

    def test_2_every_partial_production_gate_combination_fails_closed(self):
        combos = [
            {},
            {'DEPLOYMENT_ENVIRONMENT': 'production'},
            {'DEPLOYMENT_ENVIRONMENT': 'production', 'ADMIN_CAMPAIGN_SEND_ENABLED': 'true'},
            {'DEPLOYMENT_ENVIRONMENT': 'production', 'ADMIN_CAMPAIGN_WORKER_AUTHORIZED': 'true'},
            {'ADMIN_CAMPAIGN_SEND_ENABLED': 'true', 'ADMIN_CAMPAIGN_WORKER_AUTHORIZED': 'true'},  # missing environment
            {'DEPLOYMENT_ENVIRONMENT': 'production', 'ADMIN_CAMPAIGN_SEND_ENABLED': 'true',
             'ADMIN_CAMPAIGN_WORKER_AUTHORIZED': 'true'},  # missing real credentials, patched below
        ]
        for combo in combos:
            with self.subTest(combo=combo), _EnvSandbox() as sandbox:
                sandbox.set(**combo)
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop('FCM_SERVICE_ACCOUNT_JSON', None)
                    self.assertIsInstance(ct.select_transport(), NoSendTransport)

    def test_3_all_required_gates_selects_firebase_transport(self):
        with _EnvSandbox() as sandbox, patch.dict(os.environ, {'FCM_SERVICE_ACCOUNT_JSON': '{"project_id":"x"}'}):
            sandbox.set(DEPLOYMENT_ENVIRONMENT='production', ADMIN_CAMPAIGN_SEND_ENABLED='true',
                        ADMIN_CAMPAIGN_WORKER_AUTHORIZED='true')
            transport = ct.select_transport()
            self.assertIsInstance(transport, ft.FirebaseTransport)

    def test_4_select_transport_reads_no_request_or_campaign_content(self):
        """Structural: the only parameter select_transport() accepts is an
        `environment` override for tests -- no campaign_id/title/action/
        audience/request object of any kind can reach it."""
        import inspect
        sig = inspect.signature(ct.select_transport)
        self.assertEqual(list(sig.parameters.keys()), ['environment'])
        # And the route module never imports it at all (existing N4
        # invariant, re-verified here for P1).
        import routes.routes_admin_notifications as routes_mod
        self.assertNotIn('select_transport', dir(routes_mod))
        self.assertNotIn('FirebaseTransport', dir(routes_mod))


class FirebaseTransportClassificationTests(unittest.TestCase):
    """Items 5-8, 13-15."""

    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.base = 981800
        assert not User.query.filter_by(id=cls.base).first()
        assert not AppUser.query.filter_by(id=cls.base + 100).first()
        db.session.add(User(id=cls.base, firebase_uid='p1-fb-0', name='p1-fb-0', email='p1-fb-0@example.invalid'))
        db.session.add(AppUser(id=cls.base + 100, firebase_uid='p1-fb-0', fcm_token='real-token-abc', lang='en'))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        AppUser.query.filter_by(id=cls.base + 100).delete(synchronize_session=False)
        User.query.filter_by(id=cls.base).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def setUp(self):
        app_user = db.session.get(AppUser, self.base + 100)
        app_user.fcm_token = 'real-token-abc'
        db.session.commit()
        self.target = Target(user_id=self.base, app_user_id=self.base + 100, fcm_token='real-token-abc')
        self.message = RenderedMessage(
            title='P1 Test', body='Body',
            data={'campaign_id': 'camp-1', 'execution_id': 'exec-1', 'action_registry_version': '1',
                  'action_type': 'APP_DEEP_LINK', 'action_target': 'ASK_NOW', 'action_parameters': {}},
        )
        self.transport = ft.FirebaseTransport()

    def test_5_successful_send_is_accepted(self):
        with patch('firebase_admin.messaging.send', return_value='projects/x/messages/1'):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_ACCEPTED)
        self.assertEqual(result.provider, 'firebase')
        self.assertEqual(result.provider_message_id, 'projects/x/messages/1')

    def test_6_unregistered_token_is_permanent_and_clears_token(self):
        from firebase_admin import messaging
        with patch('firebase_admin.messaging.send', side_effect=messaging.UnregisteredError('gone')):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_FAILED_PERMANENT)
        self.assertTrue(result.invalid_token)
        app_user = db.session.get(AppUser, self.base + 100)
        db.session.refresh(app_user)
        self.assertIsNone(app_user.fcm_token)

    def test_6b_sender_id_mismatch_is_permanent_and_clears_token(self):
        from firebase_admin import messaging
        with patch('firebase_admin.messaging.send', side_effect=messaging.SenderIdMismatchError('wrong project')):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_FAILED_PERMANENT)
        self.assertTrue(result.invalid_token)

    def test_7_transient_provider_failure_is_retryable(self):
        from firebase_admin import exceptions
        with patch('firebase_admin.messaging.send', side_effect=exceptions.UnavailableError('down')):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_FAILED_RETRYABLE)
        self.assertTrue(result.retryable)

    def test_7b_quota_exceeded_is_retryable(self):
        from firebase_admin import messaging
        with patch('firebase_admin.messaging.send', side_effect=messaging.QuotaExceededError('rate limited')):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_FAILED_RETRYABLE)

    def test_8_unrecognized_firebase_error_is_unknown(self):
        from firebase_admin import exceptions
        with patch('firebase_admin.messaging.send',
                    side_effect=exceptions.FirebaseError('SOME_NEW_CODE', 'unrecognized')):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_UNKNOWN)

    def test_8b_generic_exception_is_unknown_never_retryable_flag(self):
        with patch('firebase_admin.messaging.send', side_effect=RuntimeError('socket exploded')):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_UNKNOWN)
        self.assertFalse(result.retryable)
        self.assertFalse(result.invalid_token)

    def test_8c_credential_config_error_is_retryable_not_unknown(self):
        """A definitive synchronous auth rejection is NOT ambiguous --
        never blindly forced into UNKNOWN just because an exception fired."""
        from firebase_admin import exceptions
        with patch('firebase_admin.messaging.send', side_effect=exceptions.UnauthenticatedError('bad creds')):
            result = self.transport.send(self.target, self.message)
        self.assertEqual(result.outcome, OUTCOME_FAILED_RETRYABLE)

    def test_13_stale_invalid_token_result_cannot_clear_a_refreshed_token(self):
        """The target was resolved with 'real-token-abc' in-memory before
        this attempt; if the AppUser's live token has since changed to
        something else, an invalid-token result for the OLD value must
        never touch the NEW one."""
        app_user = db.session.get(AppUser, self.base + 100)
        app_user.fcm_token = 'brand-new-refreshed-token'
        db.session.commit()

        from firebase_admin import messaging
        stale_target = Target(user_id=self.base, app_user_id=self.base + 100, fcm_token='real-token-abc')
        with patch('firebase_admin.messaging.send', side_effect=messaging.UnregisteredError('gone')):
            self.transport.send(stale_target, self.message)

        db.session.refresh(app_user)
        self.assertEqual(app_user.fcm_token, 'brand-new-refreshed-token',
                          "an invalid-token result for a STALE token must never clear the current one")

    def test_14_payload_contains_flutter_required_keys(self):
        captured = {}

        def fake_send(msg):
            captured['data'] = msg.data
            captured['notification'] = msg.notification
            return 'ok'

        with patch('firebase_admin.messaging.send', side_effect=fake_send):
            self.transport.send(self.target, self.message)
        data = captured['data']
        # Exact keys lib/core/notifications/notification_dispatcher.dart's
        # parse() reads for a Campaign C push tap (N6, frozen).
        for key in ('source', 'campaign_id', 'execution_id', 'action_type', 'action_target'):
            self.assertIn(key, data)
        self.assertEqual(data['source'], 'ADMIN_CAMPAIGN')
        self.assertEqual(data['campaign_id'], 'camp-1')
        self.assertEqual(data['execution_id'], 'exec-1')
        self.assertEqual(data['action_type'], 'APP_DEEP_LINK')
        self.assertEqual(data['action_target'], 'ASK_NOW')
        self.assertEqual(captured['notification'].title, 'P1 Test')
        self.assertEqual(captured['notification'].body, 'Body')
        # Every FCM data value must be a string -- the real wire contract.
        for v in data.values():
            self.assertIsInstance(v, str)

    def test_15_payload_contains_no_recipient_pii_token_or_uid(self):
        captured = {}

        def fake_send(msg):
            captured['message'] = msg
            return 'ok'

        with patch('firebase_admin.messaging.send', side_effect=fake_send):
            self.transport.send(self.target, self.message)
        msg = captured['message']
        self.assertEqual(msg.token, 'real-token-abc')  # the ONE place the token legitimately appears -- the SDK message itself, never `data`
        forbidden_substrings = ('real-token-abc', 'p1-fb-0', '@example.invalid', str(self.base + 100), str(self.base))
        for key, value in msg.data.items():
            for forbidden in forbidden_substrings:
                self.assertNotIn(forbidden, value, f'data[{key!r}]={value!r} must never contain {forbidden!r}')


class ControlledTestTransportTests(unittest.TestCase):
    """Items 16-18."""

    def setUp(self):
        self.context = app.app_context(); self.context.push()
        self.inner = ft.FirebaseTransport()
        self.wrapped = ft.ControlledTestTransport(self.inner, allowlisted_app_user_id=999001)
        self.message = RenderedMessage(
            title='T', body='B',
            data={'campaign_id': 'c1', 'execution_id': 'e1', 'action_type': 'NONE', 'action_target': '', 'action_parameters': {}},
        )

    def tearDown(self):
        self.context.pop()

    def test_16_refuses_a_non_allowlisted_recipient_never_calls_firebase(self):
        other_target = Target(user_id=1, app_user_id=555555, fcm_token='irrelevant-token')
        with patch('firebase_admin.messaging.send') as mock_send:
            result = self.wrapped.send(other_target, self.message)
        mock_send.assert_not_called()
        self.assertEqual(result.outcome, OUTCOME_FAILED_PERMANENT)
        self.assertEqual(result.error_code, 'controlled_test_recipient_not_allowlisted')

    def test_17_refusal_holds_regardless_of_how_many_targets_are_attempted(self):
        """Simulates what an (impossible, but defense-in-depth-checked)
        All-Users-sized batch would do: every non-allowlisted target in
        the batch is refused, none reach Firebase."""
        targets = [Target(user_id=i, app_user_id=i + 100000, fcm_token=f'tok-{i}') for i in range(5)]
        with patch('firebase_admin.messaging.send') as mock_send:
            results = [self.wrapped.send(t, self.message) for t in targets]
        mock_send.assert_not_called()
        self.assertTrue(all(r.outcome == OUTCOME_FAILED_PERMANENT for r in results))

    def test_16b_allowlisted_recipient_is_forwarded_to_the_real_transport(self):
        allowlisted_target = Target(user_id=1, app_user_id=999001, fcm_token='tok')
        with patch('firebase_admin.messaging.send', return_value='ok-id') as mock_send:
            result = self.wrapped.send(allowlisted_target, self.message)
        mock_send.assert_called_once()
        self.assertEqual(result.outcome, OUTCOME_ACCEPTED)

    def test_18_logs_never_contain_the_token(self):
        buf = io.StringIO()
        allowlisted_target = Target(user_id=1, app_user_id=999001, fcm_token='super-secret-token-xyz')
        with patch('firebase_admin.messaging.send', return_value='ok-id'), redirect_stdout(buf):
            self.wrapped.send(allowlisted_target, self.message)
        output = buf.getvalue()
        self.assertIn('CONTROLLED TEST', output)
        self.assertNotIn('super-secret-token-xyz', output)


class WorkerIntegrationWithFirebaseTransportTests(unittest.TestCase):
    """Items 9-12: retry ceiling, UNKNOWN/permanent no-retry, still hold
    with the REAL FirebaseTransport class driving them, not just
    FakeTransport. Uses the SAME real HTTP draft->send-now flow every
    other N4 test uses (test_notification_campaign_execution.py's own
    `frozen_execution()` precedent) rather than hand-constructing ORM
    rows, so every NOT NULL/derived field is populated exactly as
    production would populate it."""

    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 981850
        db.session.add(User(id=cls.base, firebase_uid='p1-fb-worker', name='p1-fb-worker', email='p1-fb-worker@example.invalid'))
        db.session.add(AppUser(id=cls.base + 100, firebase_uid='p1-fb-worker', fcm_token='worker-token', lang='en'))
        db.session.commit()
        from modules.models_saved_audience import SavedAudience
        cls.audience = SavedAudience(name='P1 worker synthetic', criteria={'version': 1, 'filters': {'search': 'p1-fb-worker'}}, is_active=True)
        db.session.add(cls.audience); db.session.commit()
        cls.audience_id = cls.audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.base)
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.base))}

    @classmethod
    def tearDownClass(cls):
        from modules.models_saved_audience import SavedAudience
        from notifications.campaign_models import NotificationCampaign
        from notifications.campaign_bell_models import NotificationCampaignBellItem
        from notifications.campaign_execution_models import NotificationSendNowRequest
        db.session.rollback()
        execution_ids = [e.id for e in NotificationCampaignExecution.query.filter(NotificationCampaignExecution.campaign_id.in_(cls.campaigns)).all()]
        delivery_ids = [d.id for d in NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.execution_id.in_(execution_ids)).all()]
        NotificationCampaignAttempt.query.filter(NotificationCampaignAttempt.delivery_id.in_(delivery_ids)).delete(synchronize_session=False)
        NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.id.in_(delivery_ids)).delete(synchronize_session=False)
        NotificationCampaignBellItem.query.filter(NotificationCampaignBellItem.execution_id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationSendNowRequest.query.filter(NotificationSendNowRequest.campaign_id.in_(cls.campaigns)).delete(synchronize_session=False)
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationCampaign.query.filter(NotificationCampaign.id.in_(cls.campaigns)).delete(synchronize_session=False)
        SavedAudience.query.filter_by(id=cls.audience_id).delete(synchronize_session=False)
        AppUser.query.filter_by(id=cls.base + 100).delete(synchronize_session=False)
        User.query.filter_by(id=cls.base).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def _frozen_execution(self):
        payload = dict(title='P1 worker test', body='Body', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=self.audience_id,
                       action={'type': 'NONE', 'target': None, 'parameters': {}})
        r = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        self.assertEqual(r.status_code, 201)
        campaign_id = r.get_json()['id']
        self.campaigns.append(campaign_id)
        baseline = {'generated_at': datetime.now(timezone.utc).isoformat(), 'matched_user_count': 1, 'eligible_recipient_count': 1}
        r = self.client.post(f'/admin/api/notifications/{campaign_id}/send-now',
                              json={'revision': 1, 'idempotency_key': 'key-' + campaign_id, 'baseline': baseline},
                              headers=self.admin)
        self.assertEqual(r.status_code, 202)
        return r.get_json()['id']

    def test_9_10_11_12_retry_ceiling_holds_with_real_transport_class(self):
        from firebase_admin import exceptions
        execution_id = self._frozen_execution()
        transport = ft.FirebaseTransport()

        with patch('firebase_admin.messaging.send', side_effect=exceptions.UnavailableError('down')):
            for _ in range(4):
                delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
                delivery.next_attempt_at = None
                delivery.lease_until = None
                db.session.commit()
                worker.process_execution(execution_id, transport)

        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        self.assertEqual(delivery.attempt_count, 4, 'exactly 4 attempts total -- never a 5th')
        self.assertEqual(delivery.status, 'FAILED_PERMANENT', 'retry-exhausted, never left retryable forever')
        attempts = NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).order_by(
            NotificationCampaignAttempt.attempt_number).all()
        self.assertEqual([a.attempt_number for a in attempts], [1, 2, 3, 4])
        self.assertTrue(all(a.outcome == 'FAILED_RETRYABLE' for a in attempts))

        # A 5th call must be a structural no-op -- delivery is terminal,
        # never reclaimed, transport never invoked again.
        with patch('firebase_admin.messaging.send') as mock_send:
            worker.process_execution(execution_id, transport)
        mock_send.assert_not_called()
        self.assertEqual(
            NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count(), 4,
            'attempt 5 must be impossible')

    def test_unknown_outcome_never_auto_retries_with_real_transport(self):
        execution_id = self._frozen_execution()
        transport = ft.FirebaseTransport()
        with patch('firebase_admin.messaging.send', side_effect=RuntimeError('mystery failure')):
            worker.process_execution(execution_id, transport)
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        self.assertEqual(delivery.status, 'UNKNOWN')
        self.assertIsNone(delivery.next_attempt_at)
        with patch('firebase_admin.messaging.send') as mock_send:
            worker.process_execution(execution_id, transport)
        mock_send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
