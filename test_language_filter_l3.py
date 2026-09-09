"""Run through scripts/l3_local_verify.py; synthetic fixtures, fake auth/transport."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from app import app
from extensions import db
from modules.models_user import AppUser
from modules.auth.models import User
from modules.services import language_preference_service as pref
from modules.services import admin_users_service as users
from modules.services.saved_audience_criteria import validate_criteria, CriteriaValidationError
from modules.services.saved_audience_service import create_audience, preview_audience, preview_criteria
from modules.models_saved_audience import SavedAudience
from flask_jwt_extended import create_access_token
import os


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.ids = list(range(998810, 998821))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.in_([x + 100 for x in cls.ids])).first()
        cls.values = ['en', 'hi', None, '', ' \t', '\tHI\n', ' En ', 'fr', None, 'en', 'hi']
        for i, value in zip(cls.ids, cls.values):
            uid = f'l3-language-{i}'
            bridge = None if i == cls.ids[9] else ' \t\n' if i == cls.ids[10] else uid
            db.session.add(User(id=i, firebase_uid=bridge, email=f'{uid}@example.invalid', provider='password', name=uid))
            if i != cls.ids[8]:
                db.session.add(AppUser(id=i+100, firebase_uid=bridge, lang=value, name='unchanged', dob='2000-01-01', moon_sign='Aries'))
        db.session.commit()
        os.environ['ADMIN_USER_IDS'] = str(cls.ids[0])
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.ids[0]))}
        cls.audiences = []

    @classmethod
    def tearDownClass(cls):
        db.session.rollback()
        SavedAudience.query.filter(SavedAudience.id.in_(cls.audiences)).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.in_([x+100 for x in cls.ids])).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def call(self, method='get', payload=None, uid=None):
        uid = uid or f'l3-language-{self.ids[0]}'
        with patch('routes.routes_user.firebase_auth.verify_id_token', return_value={'uid': uid}):
            return getattr(self.client, method)('/api/user/preferences/language', json=payload, headers={'Authorization': 'Bearer fake'})

    def test_auth(self):
        self.assertEqual(self.client.get('/api/user/preferences/language').status_code, 401)
        with patch('routes.routes_user.firebase_auth.verify_id_token', side_effect=ValueError()):
            self.assertEqual(self.client.patch('/api/user/preferences/language', json={'lang':'hi'}, headers={'Authorization':'Bearer bad'}).status_code,401)

    def test_preference_write_only_language(self):
        row = db.session.get(AppUser, self.ids[0]+100)
        before = {c.name:getattr(row,c.name) for c in AppUser.__table__.columns if c.name != 'lang'}
        try:
            for value, expected in [('hi','hi'), ('hi','hi'), (' EN\t','en')]:
                response = self.call('patch', {'lang':value})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json, {'lang':expected,'profile_ready':True})
                db.session.refresh(row)
                self.assertEqual(before,{c.name:getattr(row,c.name) for c in AppUser.__table__.columns if c.name != 'lang'})
        finally:
            row.lang='en'; db.session.commit()

    def test_invalid_requests(self):
        for value in [None,'',' ',True,1,[],{},'English','Hindi','en-IN','hi-IN','fr']:
            with self.subTest(value=value): self.assertEqual(self.call('patch',{'lang':value}).status_code,400)
        for payload in [{},[],{'lang':'hi','firebase_uid':'someone'},{'lang':'hi','id':1},{'language':'hi'}]:
            with self.subTest(payload=payload): self.assertEqual(self.call('patch',payload).status_code,400)

    def test_missing_and_ambiguous(self):
        self.assertEqual(self.call(uid='l3-no-profile').json,{'lang':None,'profile_ready':False})
        self.assertEqual(self.call('patch',{'lang':'en'},uid='l3-no-profile').status_code,409)
        with patch.object(pref,'language_profile',side_effect=RuntimeError('ambiguous_profile')):
            self.assertEqual(self.call().json['error'],'ambiguous_profile')
        fake = MagicMock(); fake.query.filter_by.return_value.limit.return_value.all.return_value=[object(),object()]
        with patch.object(pref,'AppUser',fake), self.assertRaises(RuntimeError): pref.language_profile('duplicate')

    def test_unknown_readback(self):
        for value in [None,'',' ','fr','hi-IN']:
            self.assertEqual(pref.preference_state(SimpleNamespace(lang=value)),{'lang':None,'profile_ready':True})

    def test_generic_profile_does_not_write_preference(self):
        from modules.user_service import register_or_update_user
        row = db.session.get(AppUser, self.ids[0]+100)
        for keys in [{'lang':'hi'}, {'language':'hi'}, {}]:
            result = register_or_update_user({'firebase_uid':row.firebase_uid, **keys})
            self.assertEqual(result.id, row.id)
            db.session.refresh(row)
            self.assertEqual(row.lang, 'en')

    def test_bootstrap_compatibility(self):
        for payload, expected in [({},'en'),({'lang':' HI '},'hi'),({'language':'hi'},'hi'),({'lang':'EN','language':' en '},'en')]:
            self.assertEqual(pref.content_language(payload),expected)
        for payload in [{'lang':'hi','language':'en'},{'lang':'en','language':None},{'lang':False},{'language':[]}]:
            with self.assertRaises(ValueError): pref.content_language(payload)

    def test_criteria_validation(self):
        for value in [[],None,'en',['fr'],[True],[{}],['en','HI']]:
            with self.subTest(value=value), self.assertRaises(CriteriaValidationError):
                validate_criteria({'version':1,'filters':{'language':value}},authoring=False)
        self.assertEqual(validate_criteria({'version':1,'filters':{'language':['hi','en','hi']}},authoring=False),{'language':['en','hi']})

    def test_four_way_language_membership(self):
        for langs, offsets in [(['en'],[0,6]),(['hi'],[1,5]),(['en','hi'],[0,1,5,6]),(None,list(range(11)))]:
            filters={'search':'l3-language-'}
            if langs is not None: filters['language']=langs
            criteria={'version':1,'filters':filters}
            query={k:','.join(v) if isinstance(v,list) else v for k,v in filters.items()}
            live=self.client.get('/admin/api/users',query_string=query,headers=self.admin)
            self.assertEqual(live.status_code,200)
            direct=preview_criteria(criteria,page_size=100)
            saved=create_audience(name='L3 synthetic',criteria=criteria); self.audiences.append(saved.id)
            preview=preview_audience(saved.id,page_size=100)
            expected={self.ids[x] for x in offsets}
            for result in [live.json,direct,preview]:
                self.assertEqual({u['id'] for u in result['users']},expected)
            self.assertEqual(set(users.resolve_user_ids(**filters)),expected)

    def test_query_fail_closed(self):
        for query in ['language=','language=en,','language=EN','language=fr','language=en&language=hi','language=%20en']:
            self.assertEqual(self.client.get('/admin/api/users?'+query,headers=self.admin).status_code,400)

    def test_language_has_no_n_plus_one(self):
        from sqlalchemy import event
        counts=[]
        for size in (1,20,100):
            statements=[]
            def capture(conn,cursor,statement,parameters,context,many): statements.append(statement)
            event.listen(db.engine,'before_cursor_execute',capture)
            try: users.list_users(language=['en','hi'],page_size=size)
            finally: event.remove(db.engine,'before_cursor_execute',capture)
            counts.append(len(statements))
        self.assertEqual(len(set(counts)),1)
        self.assertLessEqual(counts[0],4)

    def test_sender_uses_lang_with_fake_transport(self):
        import notifications.notification_service as service
        for lang, title in [('en','English'),('hi','Hindi'),(None,'English')]:
            job=SimpleNamespace(id=1,audience={},title='English',title_hi='Hindi',body='Body',body_hi='Hindi body',payload={},mark_sent=MagicMock())
            recipient=SimpleNamespace(id=1,lang=lang,language='wrong',fcm_token='fake-only')
            log=MagicMock(); log.query.filter_by.return_value.first.return_value=None
            # Fake transport reports failure: no notification/log rows or events created.
            sender=MagicMock(return_value=False)
            with patch.object(service,'get_recipients',return_value=[recipient]),patch.object(service,'NotificationLog',log),patch.object(service,'db'),patch.object(service,'_emit_notification_events'):
                self.assertEqual(service.send_job_now(job,sender),(0,1))
            self.assertEqual(sender.call_args.kwargs['title'],title)

if __name__ == '__main__': unittest.main(verbosity=2)
