"""N3 Admin Campaign Composer: draft CRUD, action registry, live N2
preview, safety thresholds. Run via scripts/l3_local_verify.py so no
Firebase/network/DDL slips in. Local synthetic fixtures only."""
import os
import unittest
from unittest.mock import patch

from flask_jwt_extended import create_access_token

from app import app
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.models_saved_audience import SavedAudience
from notifications import campaign_service as svc
from notifications.campaign_models import NotificationCampaign
from notifications.saved_audience_recipient_resolver import RecipientResolution, RecipientResolutionError


class N3ComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 9979000
        cls.ids = list(range(cls.base, cls.base + 4))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in enumerate(cls.ids):
            uid = f'n3-composer-{offset}'
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f'{uid}@example.invalid'))
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=f'n3-token-{offset}',
                                    lang='en', moon_sign='Aries'))
        db.session.commit()
        cls.audience = SavedAudience(name='N3 synthetic', criteria={'version': 1, 'filters': {'search': 'n3-composer-'}}, is_active=True)
        cls.inactive_audience = SavedAudience(name='N3 inactive', criteria={'version': 1, 'filters': {'search': 'nobody-matches-this'}}, is_active=False)
        cls.all_users_audience = SavedAudience(name='N3 all users', criteria={'version': 1, 'filters': {}}, is_active=True)
        db.session.add_all([cls.audience, cls.inactive_audience, cls.all_users_audience])
        db.session.commit()
        cls.audience_id = cls.audience.id
        cls.inactive_audience_id = cls.inactive_audience.id
        cls.all_users_audience_id = cls.all_users_audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.ids[0])
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[0]))}

    @classmethod
    def tearDownClass(cls):
        db.session.rollback()
        NotificationCampaign.query.filter(NotificationCampaign.id.in_(cls.campaigns)).delete(synchronize_session=False)
        SavedAudience.query.filter(SavedAudience.id.in_([cls.audience_id, cls.inactive_audience_id, cls.all_users_audience_id])).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def _track(self, body):
        self.campaigns.append(body['id'])
        return body

    def create(self, **overrides):
        payload = dict(title='Hello', body='Body text', audience_mode='SAVED_AUDIENCE',
                       saved_audience_id=self.audience_id, action={'type': 'NONE', 'target': None, 'parameters': {}})
        payload.update(overrides)
        response = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        return response

    # ---------------- Draft CRUD lifecycle ----------------

    def test_create_read_list_update_lifecycle(self):
        create_resp = self.create()
        self.assertEqual(create_resp.status_code, 201)
        body = self._track(create_resp.get_json())
        self.assertEqual(body['state'], 'DRAFT')
        self.assertEqual(body['revision'], 1)
        self.assertEqual(body['audience_name'], 'N3 synthetic')
        self.assertEqual(body['audience_status'], 'active')
        self.assertFalse(body['audience_definition_changed'])
        self.assertEqual(body['action'], {'type': 'NONE', 'target': None, 'parameters': {}})

        get_resp = self.client.get(f"/admin/api/notifications/{body['id']}", headers=self.admin)
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.get_json()['title'], 'Hello')

        list_resp = self.client.get('/admin/api/notifications?search=Hello', headers=self.admin)
        self.assertEqual(list_resp.status_code, 200)
        listed_ids = {row['id'] for row in list_resp.get_json()['campaigns']}
        self.assertIn(body['id'], listed_ids)

        patch_resp = self.client.patch(f"/admin/api/notifications/{body['id']}", json={
            'title': 'Updated title', 'body': 'Body text', 'audience_mode': 'SAVED_AUDIENCE',
            'saved_audience_id': self.audience_id, 'action': {'type': 'NONE', 'target': None, 'parameters': {}},
            'revision': body['revision'],
        }, headers=self.admin)
        self.assertEqual(patch_resp.status_code, 200)
        updated = patch_resp.get_json()
        self.assertEqual(updated['title'], 'Updated title')
        self.assertEqual(updated['revision'], 2)

        # Stale revision (still 1) is rejected once the row is at revision 2.
        stale_resp = self.client.patch(f"/admin/api/notifications/{body['id']}", json={
            'title': 'Should fail', 'body': 'Body text', 'audience_mode': 'SAVED_AUDIENCE',
            'saved_audience_id': self.audience_id, 'action': {'type': 'NONE', 'target': None, 'parameters': {}},
            'revision': 1,
        }, headers=self.admin)
        self.assertEqual(stale_resp.status_code, 409)
        self.assertEqual(stale_resp.get_json()['error'], 'stale_revision')

    def test_unauthenticated_and_not_found(self):
        self.assertEqual(self.client.get('/admin/api/notifications').status_code, 401)
        self.assertEqual(self.client.post('/admin/api/notifications', json={}).status_code, 401)
        self.assertEqual(self.client.get('/admin/api/notifications/00000000-0000-0000-0000-000000000000', headers=self.admin).status_code, 404)
        self.assertEqual(self.client.get('/admin/api/notifications/not-a-uuid', headers=self.admin).status_code, 404)

    def test_unknown_fields_and_invalid_content_rejected(self):
        self.assertEqual(self.create(extra_field=1).status_code, 400)
        self.assertEqual(self.create(title='').status_code, 400)
        self.assertEqual(self.create(title=' ').status_code, 400)
        self.assertEqual(self.create(title='x' * 201).status_code, 400)
        self.assertEqual(self.create(body='x' * 501).status_code, 400)
        self.assertEqual(self.create(audience_mode='ALL_USERS').status_code, 400)
        self.assertEqual(self.create(saved_audience_id=-1).status_code, 400)
        self.assertEqual(self.create(saved_audience_id='1').status_code, 400)

    def test_audience_missing_inactive_invalid(self):
        self.assertEqual(self.create(saved_audience_id=2147483647).status_code, 422)
        self.assertEqual(self.create(saved_audience_id=self.inactive_audience_id).status_code, 422)

    def test_audience_definition_changed_detected(self):
        create_resp = self.create()
        body = self._track(create_resp.get_json())
        row = db.session.get(SavedAudience, self.audience_id)
        original = row.criteria
        try:
            row.criteria = {'version': 1, 'filters': {'search': 'n3-composer-', 'moon_sign': ['Taurus']}}
            db.session.commit()
            get_resp = self.client.get(f"/admin/api/notifications/{body['id']}", headers=self.admin)
            self.assertTrue(get_resp.get_json()['audience_definition_changed'])
        finally:
            row.criteria = original
            db.session.commit()

    def test_refresh_audience_resnapshots_hash(self):
        create_resp = self.create()
        body = self._track(create_resp.get_json())
        row = db.session.get(SavedAudience, self.audience_id)
        original = row.criteria
        try:
            row.criteria = {'version': 1, 'filters': {'search': 'n3-composer-', 'moon_sign': ['Taurus']}}
            db.session.commit()
            patch_resp = self.client.patch(f"/admin/api/notifications/{body['id']}", json={
                'title': body['title'], 'body': body['body'], 'audience_mode': 'SAVED_AUDIENCE',
                'saved_audience_id': self.audience_id, 'action': body['action'],
                'revision': body['revision'], 'refresh_audience': True,
            }, headers=self.admin)
            self.assertEqual(patch_resp.status_code, 200)
            self.assertFalse(patch_resp.get_json()['audience_definition_changed'])
            self.assertNotEqual(patch_resp.get_json()['draft_criteria_hash'], body['draft_criteria_hash'])
        finally:
            row.criteria = original
            db.session.commit()

    # ---------------- Action registry ----------------

    def test_action_none_and_app_deep_links(self):
        none_resp = self.create(action={'type': 'NONE', 'target': None, 'parameters': {}})
        self.assertEqual(none_resp.status_code, 201)
        self._track(none_resp.get_json())
        for target in ('ASK_NOW', 'KUNDALI', 'REPORTS', 'SUBSCRIPTION', 'PROFILE', 'DASHBOARD'):
            response = self.create(action={'type': 'APP_DEEP_LINK', 'target': target, 'parameters': {}})
            self.assertEqual(response.status_code, 201, target)
            self._track(response.get_json())
        self.assertEqual(self.create(action={'type': 'APP_DEEP_LINK', 'target': 'EVENT', 'parameters': {}}).status_code, 400)
        self.assertEqual(self.create(action={'type': 'APP_DEEP_LINK', 'target': 'KUNDALI', 'parameters': {'house': 1}}).status_code, 400)
        self.assertEqual(self.create(action={'type': 'NONE', 'target': 'KUNDALI', 'parameters': {}}).status_code, 400)
        self.assertEqual(self.create(action={'type': 'BOGUS', 'target': None, 'parameters': {}}).status_code, 400)
        self.assertEqual(self.create(action={'type': 'NONE', 'target': None}).status_code, 400)

    def test_action_web_url_website_and_youtube(self):
        for url in ('https://jyotishasha.com/reports', 'https://www.jyotishasha.com/'):
            response = self.create(action={'type': 'WEB_URL', 'target': 'HTTPS_URL', 'parameters': {'url': url}})
            self.assertEqual(response.status_code, 201, url)
            body = self._track(response.get_json())
            saved_url = body['action']['parameters']['url']
            self.assertTrue(saved_url.startswith('https://'))
            # UTM is campaign-level delivery-time attribution (N1 Section 16),
            # generated separately -- never baked into the stored action URL
            # itself, and never accepted verbatim from Admin input.
            self.assertNotIn('utm_source', saved_url)
            self.assertEqual(body['attribution']['utm_source'], 'jyotishasha_app')
            self.assertEqual(body['attribution']['utm_medium'], 'push')
            self.assertTrue(body['attribution']['utm_campaign'].startswith('nc_'))
        youtube = self.create(action={'type': 'WEB_URL', 'target': 'HTTPS_URL', 'parameters': {'url': 'https://www.youtube.com/@jyotishasha'}})
        self.assertEqual(youtube.status_code, 201)
        self.assertEqual(self._track(youtube.get_json())['action']['parameters']['url'], 'https://www.youtube.com/@jyotishasha')

    def test_action_web_url_rejects_unapproved_and_malformed(self):
        bad_urls = [
            'http://jyotishasha.com',  # not https
            'https://evil.com',  # unapproved host
            'https://jyotishasha.com.evil.com',  # lookalike/suffix attack
            'https://eviljyotishasha.com',  # lookalike
            'https://admin@jyotishasha.com',  # userinfo
            'https://jyotishasha.com:8443',  # non-default port
            'https://192.168.0.1/reports',  # IP literal
            'https://jyotishasha.com/%zz',  # malformed percent-encoding
            'https://www.youtube.com/watch?v=someOtherVideo',  # unapproved YouTube destination
            'not-a-url-at-all',
            '',
        ]
        for url in bad_urls:
            response = self.create(action={'type': 'WEB_URL', 'target': 'HTTPS_URL', 'parameters': {'url': url}})
            self.assertEqual(response.status_code, 400, url)

    def test_action_web_url_strips_and_rejects_duplicate_utm(self):
        response = self.create(action={'type': 'WEB_URL', 'target': 'HTTPS_URL', 'parameters': {
            'url': 'https://jyotishasha.com/reports?utm_source=old&keep=me'}})
        self.assertEqual(response.status_code, 201)
        url = self._track(response.get_json())['action']['parameters']['url']
        self.assertIn('keep=me', url)
        self.assertNotIn('utm_source=old', url)
        duplicate = self.create(action={'type': 'WEB_URL', 'target': 'HTTPS_URL', 'parameters': {
            'url': 'https://jyotishasha.com/reports?utm_source=a&utm_source=b'}})
        self.assertEqual(duplicate.status_code, 400)

    # ---------------- Live N2 preview ----------------

    def test_preview_ready_normal_audience(self):
        response = self.client.post('/admin/api/notifications/preview', json={'saved_audience_id': self.audience_id}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['status'], 'READY')
        self.assertEqual(body['matched_user_count'], 4)
        self.assertEqual(body['eligible_recipient_count'], 4)
        self.assertFalse(body['is_all_users'])
        self.assertFalse(body['large_audience'])
        self.assertNotIn('recipients', body)

    def test_preview_all_users_flag(self):
        response = self.client.post('/admin/api/notifications/preview', json={'saved_audience_id': self.all_users_audience_id}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['is_all_users'])

    def test_preview_against_saved_draft_revision(self):
        create_resp = self.create()
        body = self._track(create_resp.get_json())
        response = self.client.post('/admin/api/notifications/preview', json={'campaign_id': body['id'], 'revision': body['revision']}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['saved_audience_id'], self.audience_id)
        stale = self.client.post('/admin/api/notifications/preview', json={'campaign_id': body['id'], 'revision': body['revision'] + 1}, headers=self.admin)
        self.assertEqual(stale.status_code, 409)

    def test_preview_large_audience_warning(self):
        # 1000 eligible synthetic recipients without materializing real rows.
        fake = RecipientResolution(self.audience_id, 1000, tuple(object() for _ in range(1000)),
                                    (('missing_identity_bridge', 0), ('missing_profile', 0), ('missing_token', 0), ('preference_suppressed', 0), ('duplicate_target', 0)), False)
        with patch.object(svc, 'resolve_saved_audience_recipients', return_value=fake):
            response = self.client.post('/admin/api/notifications/preview', json={'saved_audience_id': self.audience_id}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['large_audience'])
        self.assertEqual(body['eligible_recipient_count'], 1000)

    def test_preview_blocked_over_ceiling(self):
        with patch.object(svc, 'resolve_saved_audience_recipients', side_effect=RecipientResolutionError('SAFETY_CEILING_EXCEEDED', matched_user_count=50001)):
            response = self.client.post('/admin/api/notifications/preview', json={'saved_audience_id': self.audience_id}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['status'], 'BLOCKED')
        self.assertTrue(body['safety_ceiling_exceeded'])
        self.assertEqual(body['matched_user_count'], 50001)
        self.assertIsNone(body['eligible_recipient_count'])

    def test_preview_dependency_failure_surfaces_as_error_not_zero(self):
        with patch.object(svc, 'resolve_saved_audience_recipients', side_effect=RecipientResolutionError('RESOLUTION_UNAVAILABLE')):
            response = self.client.post('/admin/api/notifications/preview', json={'saved_audience_id': self.audience_id}, headers=self.admin)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('matched_user_count', response.get_json())

    # ---------------- Safety/privacy invariants ----------------

    def test_no_recipient_pii_in_any_response(self):
        create_resp = self.create()
        body = self._track(create_resp.get_json())
        preview_resp = self.client.post('/admin/api/notifications/preview', json={'campaign_id': body['id'], 'revision': body['revision']}, headers=self.admin)
        payload = str(preview_resp.get_json())
        for offset in range(4):
            self.assertNotIn(f'n3-token-{offset}', payload)
            self.assertNotIn(f'n3-composer-{offset}', payload)

    def test_no_send_transport_or_execution_imports(self):
        """N3 must never import a sender/transport/execution module -- the
        service module's own import list is the proof, same style N2's own
        test asserts no sender import happened."""
        import notifications.campaign_service as module
        source = open(module.__file__, encoding='utf-8').read()
        for forbidden in ('firebase_admin', 'notification_service', 'send_job_now', 'FCM', 'NotificationExecution', 'NotificationDelivery'):
            self.assertNotIn(forbidden, source)

    def test_campaign_row_state_is_always_draft(self):
        create_resp = self.create()
        body = self._track(create_resp.get_json())
        row = db.session.get(NotificationCampaign, body['id'])
        self.assertEqual(row.state, 'DRAFT')


if __name__ == '__main__':
    unittest.main(verbosity=2)
