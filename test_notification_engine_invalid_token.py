"""N-FIX-2B -- services/notification_engine.py::send_push_notification()
invalid-FCM-token handling for Pipeline A/B + Personalized Alerts.

Reuses (never reimplements) the exact classification/clearing already
proven for Campaign C in notifications/firebase_transport.py
(is_invalid_token_error()/clear_invalid_fcm_token(), extracted there
from the pre-existing _handle_invalid_token()) -- this file proves the
NEW A/B/Alerts-facing caller of that shared logic behaves correctly,
never re-derives the classification itself.

NO real Firebase call anywhere -- every test patches
firebase_admin.messaging.send directly, using the REAL firebase_admin
exception classes, exactly mirroring test_notification_firebase_
transport.py's own established convention for this repo.

Run via scripts/l3_local_verify.py so no Firebase/network/DDL slips in.
"""
import unittest
from unittest.mock import patch

from app import app
from extensions import db
from modules.models_user import AppUser
from modules.auth.models import User

from services.notification_engine import send_push_notification


class SendPushNotificationInvalidTokenTests(unittest.TestCase):
    """Items A-D."""

    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.base = 981900
        for offset in (0, 1):
            assert not User.query.filter_by(id=cls.base + offset).first()
            assert not AppUser.query.filter_by(id=cls.base + 100 + offset).first()
        db.session.add(User(id=cls.base, firebase_uid='n2b-fb-0', name='n2b-fb-0', email='n2b-fb-0@example.invalid'))
        db.session.add(User(id=cls.base + 1, firebase_uid='n2b-fb-1', name='n2b-fb-1', email='n2b-fb-1@example.invalid'))
        db.session.add(AppUser(id=cls.base + 100, firebase_uid='n2b-fb-0', fcm_token='token-user-a', lang='en'))
        db.session.add(AppUser(id=cls.base + 101, firebase_uid='n2b-fb-1', fcm_token='token-user-b', lang='en'))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        AppUser.query.filter(AppUser.id.in_([cls.base + 100, cls.base + 101])).delete(synchronize_session=False)
        User.query.filter(User.id.in_([cls.base, cls.base + 1])).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def setUp(self):
        # Reset both fixture users' tokens to their known-good starting
        # values before every test, regardless of what a previous test
        # in this class mutated them to.
        user_a = db.session.get(AppUser, self.base + 100)
        user_a.fcm_token = 'token-user-a'
        user_b = db.session.get(AppUser, self.base + 101)
        user_b.fcm_token = 'token-user-b'
        db.session.commit()

    # ------------------------------------------------------------
    # A: UnregisteredError -> return False, failed token cleared
    # ------------------------------------------------------------
    def test_a_unregistered_error_returns_false_and_clears_the_failed_token(self):
        from firebase_admin import messaging
        with patch('firebase_admin.messaging.send', side_effect=messaging.UnregisteredError('gone')):
            result = send_push_notification(
                token='token-user-a', title='t', body='b',
                app_user_id=self.base + 100,
            )
        self.assertFalse(result, "public bool contract must be preserved -- False on failure")

        user_a = db.session.get(AppUser, self.base + 100)
        db.session.refresh(user_a)
        self.assertIsNone(user_a.fcm_token, "a definitively-invalid token must be cleared")

    def test_a2_sender_id_mismatch_also_clears(self):
        from firebase_admin import messaging
        with patch('firebase_admin.messaging.send', side_effect=messaging.SenderIdMismatchError('wrong project')):
            result = send_push_notification(
                token='token-user-a', title='t', body='b',
                app_user_id=self.base + 100,
            )
        self.assertFalse(result)
        user_a = db.session.get(AppUser, self.base + 100)
        db.session.refresh(user_a)
        self.assertIsNone(user_a.fcm_token)

    # ------------------------------------------------------------
    # B: another user's token is untouched
    # ------------------------------------------------------------
    def test_b_another_users_token_is_never_touched(self):
        from firebase_admin import messaging
        with patch('firebase_admin.messaging.send', side_effect=messaging.UnregisteredError('gone')):
            send_push_notification(
                token='token-user-a', title='t', body='b',
                app_user_id=self.base + 100,
            )
        user_b = db.session.get(AppUser, self.base + 101)
        db.session.refresh(user_b)
        self.assertEqual(user_b.fcm_token, 'token-user-b',
                          "clearing user A's dead token must never affect user B's row")

    # ------------------------------------------------------------
    # C: token refreshed between the failed attempt and cleanup
    # ------------------------------------------------------------
    def test_c_token_refreshed_mid_attempt_is_never_cleared(self):
        """The exact race N-FIX-2B must close: by the time the retry loop
        exhausts and classification runs, the recipient may have already
        refreshed their token to something new. The clear is scoped by
        (AppUser.id == app_user_id AND AppUser.fcm_token == token) --
        since the live row no longer equals the OLD token that actually
        failed, the UPDATE must match zero rows and touch nothing."""
        from firebase_admin import messaging

        original_send = messaging.send
        call_count = {'n': 0}

        def flaky_then_refreshed(message):
            # Simulate the token being refreshed by the client in the
            # gap between this function's two internal retry attempts.
            call_count['n'] += 1
            if call_count['n'] == 1:
                user_a = db.session.get(AppUser, self.base + 100)
                user_a.fcm_token = 'brand-new-refreshed-token'
                db.session.commit()
            raise messaging.UnregisteredError('gone')

        with patch('firebase_admin.messaging.send', side_effect=flaky_then_refreshed):
            result = send_push_notification(
                token='token-user-a', title='t', body='b',
                app_user_id=self.base + 100,
            )
        self.assertFalse(result)

        user_a = db.session.get(AppUser, self.base + 100)
        db.session.refresh(user_a)
        self.assertEqual(
            user_a.fcm_token, 'brand-new-refreshed-token',
            "an invalid-token result for a STALE token value must never clear the CURRENT one",
        )

    # ------------------------------------------------------------
    # D: UnavailableError -> token untouched, retry count preserved
    # ------------------------------------------------------------
    def test_d_transient_error_never_clears_token_and_still_retries_twice(self):
        from firebase_admin import exceptions
        with patch('firebase_admin.messaging.send',
                   side_effect=exceptions.UnavailableError('down')) as mock_send:
            result = send_push_notification(
                token='token-user-a', title='t', body='b',
                app_user_id=self.base + 100,
            )
        self.assertFalse(result)
        self.assertEqual(mock_send.call_count, 2,
                          "the existing two-attempt retry structure must be completely unchanged")

        user_a = db.session.get(AppUser, self.base + 100)
        db.session.refresh(user_a)
        self.assertEqual(user_a.fcm_token, 'token-user-a',
                          "a transient/retryable error must never clear the token")

    def test_d2_unknown_error_never_clears_token(self):
        with patch('firebase_admin.messaging.send', side_effect=RuntimeError('socket exploded')):
            result = send_push_notification(
                token='token-user-a', title='t', body='b',
                app_user_id=self.base + 100,
            )
        self.assertFalse(result)
        user_a = db.session.get(AppUser, self.base + 100)
        db.session.refresh(user_a)
        self.assertEqual(user_a.fcm_token, 'token-user-a')

    # ------------------------------------------------------------
    # Backward-compatibility: app_user_id is optional
    # ------------------------------------------------------------
    def test_no_app_user_id_never_clears_anything_and_behaves_exactly_as_before(self):
        """Every existing caller that predates N-FIX-2B (or any future
        caller that genuinely doesn't know who this is for) must see
        byte-identical behavior: still retries twice, still returns
        False, never attempts a clear without an id to scope it by."""
        from firebase_admin import messaging
        with patch('firebase_admin.messaging.send',
                   side_effect=messaging.UnregisteredError('gone')) as mock_send:
            result = send_push_notification(token='token-user-a', title='t', body='b')
        self.assertFalse(result)
        self.assertEqual(mock_send.call_count, 2)

        user_a = db.session.get(AppUser, self.base + 100)
        db.session.refresh(user_a)
        self.assertEqual(user_a.fcm_token, 'token-user-a',
                          "omitting app_user_id must never guess/clear by token alone")

    def test_successful_send_returns_true_unchanged(self):
        with patch('firebase_admin.messaging.send', return_value='projects/x/messages/1'):
            result = send_push_notification(
                token='token-user-a', title='t', body='b',
                app_user_id=self.base + 100,
            )
        self.assertTrue(result)
        user_a = db.session.get(AppUser, self.base + 100)
        db.session.refresh(user_a)
        self.assertEqual(user_a.fcm_token, 'token-user-a')


if __name__ == '__main__':
    unittest.main()
