"""N2 local synthetic fixtures; run via scripts/l3_local_verify.py."""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from sqlalchemy import event, text
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.models_saved_audience import SavedAudience
from notifications import saved_audience_recipient_resolver as resolver

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
db.init_app(app)


class N2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = app.app_context(); cls.ctx.push()
        assert db.session.execute(text('SELECT current_database()')).scalar() == 'jyotishasha_local'
        cls.base = 9989000
        cls.ids = list(range(cls.base, cls.base+13))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base+100,cls.base+199)).first()
        cls.audiences = []
        for offset, user_id in enumerate(cls.ids):
            uid = None if offset == 2 else ' \t ' if offset == 3 else f'n2-resolver-{offset}'
            db.session.add(User(id=user_id,firebase_uid=uid,name=f'n2-resolver-{offset}',email=f'n2-resolver-{offset}@example.invalid'))
            if offset in (2,3,4): continue
            token = None if offset == 5 else ' \t\n' if offset == 6 else 'n2-duplicate' if offset == 7 else '\tn2-duplicate\n' if offset == 8 else 'n2-outside' if offset == 10 else f'n2-token-{offset}'
            db.session.add(AppUser(id=user_id+100,firebase_uid=uid,fcm_token=token,
                                  lang='hi' if offset in (1,12) else 'en',moon_sign='Taurus' if offset == 12 else 'Aries'))
        # An orphan profile outside membership still owns a conflicting token.
        db.session.add(AppUser(id=cls.base+199,firebase_uid='n2-outside-owner',fcm_token='n2-outside'))
        audience=SavedAudience(name='N2 synthetic',criteria={'version':1,'filters':{'search':'n2-resolver-'}},is_active=True)
        db.session.add(audience);db.session.commit()
        cls.audience_id=audience.id;cls.audiences.append(audience.id)

    @classmethod
    def tearDownClass(cls):
        db.session.rollback()
        SavedAudience.query.filter(SavedAudience.id.in_(cls.audiences)).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base+100,cls.base+199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit();db.session.remove();cls.ctx.pop()

    def resolve(self): return resolver.resolve_saved_audience_recipients(self.audience_id)

    def test_real_bridge_exclusions_determinism_privacy(self):
        result=self.resolve()
        self.assertEqual(result,self.resolve())
        self.assertEqual(result.matched_user_count,13)
        self.assertEqual(result.eligible_recipient_count,5)
        self.assertEqual(dict(result.exclusion_counts),dict(missing_identity_bridge=2,missing_profile=1,missing_token=2,preference_suppressed=0,duplicate_target=3))
        self.assertEqual(result.matched_user_count,result.eligible_recipient_count+result.excluded_recipient_count)
        for target in result.recipients:
            self.assertEqual(target.app_user_id,target.user_id+100)
            self.assertNotIn(target.fcm_token,repr(result)+repr(target)+json.dumps(result.admin_safe()))
            self.assertNotIn(target.firebase_uid,json.dumps(result.admin_safe()))
        self.assertFalse(result.is_all_users)

    def test_language_delegation_and_composition(self):
        row=db.session.get(SavedAudience,self.audience_id)
        original=row.criteria
        try:
            for filters,expected in [({'language':['hi']},{1,12}),({'language':['en']},{0,9,11}),({'language':['hi'],'moon_sign':['Aries']},{1})]:
                row.criteria={'version':1,'filters':{'search':'n2-resolver-',**filters}};db.session.commit()
                result=self.resolve()
                self.assertEqual({t.user_id-self.base for t in result.recipients},expected)
        finally: row.criteria=original;db.session.commit()

    def test_missing_inactive_invalid(self):
        with self.assertRaises(resolver.RecipientResolutionError) as raised:
            resolver.resolve_saved_audience_recipients(2147483647)
        self.assertEqual(raised.exception.code,'AUDIENCE_NOT_FOUND')
        row=db.session.get(SavedAudience,self.audience_id);original=row.criteria
        try:
            row.is_active=False;db.session.commit()
            with self.assertRaises(resolver.RecipientResolutionError) as raised: self.resolve()
            self.assertEqual(raised.exception.code,'AUDIENCE_INACTIVE')
            row.is_active=True
            for criteria in [{'version':2,'filters':{}},{'version':True,'filters':{}},{'version':1.0,'filters':{}},{'version':1,'filters':{'language':[]}}, {'version':1}, {'version':1,'filters':{'bogus':True}}]:
                row.criteria=criteria;db.session.commit()
                with patch.object(resolver.admin_users_service,'resolve_user_ids') as shared:
                    with self.assertRaises(resolver.RecipientResolutionError) as raised:self.resolve()
                    self.assertEqual(raised.exception.code,'INVALID_AUDIENCE_CRITERIA');shared.assert_not_called()
        finally:row.is_active=True;row.criteria=original;db.session.commit()

    def test_shared_failure_is_sanitized_no_fallback(self):
        with patch.object(resolver.admin_users_service,'resolve_user_ids',side_effect=RuntimeError('secret-token')) as shared:
            with self.assertRaises(resolver.RecipientResolutionError) as raised:self.resolve()
            self.assertEqual(str(raised.exception),'RESOLUTION_UNAVAILABLE')
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertEqual(shared.call_count,1)

    def test_ambiguous_profile_blocks_entire_resolution(self):
        with patch.object(resolver,'_load_profiles',return_value=[('n2-resolver-0',2,1,'fake')]):
            with self.assertRaises(resolver.RecipientResolutionError) as raised:self.resolve()
            self.assertEqual(raised.exception.code,'AMBIGUOUS_APP_USER')

    def test_policy_absence_denial_and_failure(self):
        baseline=self.resolve()
        with patch.object(resolver,'_explicitly_disabled_user_ids',return_value={self.base}):
            denied=self.resolve()
            self.assertEqual(denied.eligible_recipient_count,baseline.eligible_recipient_count-1)
            self.assertEqual(dict(denied.exclusion_counts)['preference_suppressed'],1)
        with patch.object(resolver,'_explicitly_disabled_user_ids',side_effect=RuntimeError('policy offline')):
            with self.assertRaises(resolver.RecipientResolutionError) as raised:self.resolve()
            self.assertEqual(raised.exception.code,'RESOLUTION_UNAVAILABLE')

    def test_all_users_and_empty_membership(self):
        with patch.object(resolver.saved_audience_service,'get_audience',return_value=SimpleNamespace(is_active=True,criteria={'version':1,'filters':{}})):
            with patch.object(resolver.admin_users_service,'resolve_user_ids',return_value=[] ) as shared:
                result=self.resolve();shared.assert_called_once_with()
                self.assertTrue(result.is_all_users);self.assertEqual(result.matched_user_count,0)
            with patch.object(resolver.admin_users_service,'resolve_user_ids',return_value=self.ids):
                result=self.resolve();self.assertTrue(result.is_all_users)
                self.assertEqual(result.matched_user_count,13);self.assertEqual(result.eligible_recipient_count,5)

    def test_ceiling_no_truncation_or_bridge(self):
        with patch.object(resolver.admin_users_service,'resolve_user_ids',return_value=list(range(1,50002))),patch.object(resolver,'_load_users') as bridge:
            with self.assertRaises(resolver.RecipientResolutionError) as raised:self.resolve()
            self.assertEqual(raised.exception.code,'SAFETY_CEILING_EXCEEDED')
            self.assertEqual(raised.exception.matched_user_count,50001)
            self.assertIsNone(raised.exception.eligible_recipient_count);bridge.assert_not_called()

    def test_bounded_batches_and_global_duplicate_across_batches(self):
        ids=list(range(1,1002))
        def accounts(batch):
            self.assertLessEqual(len(batch),500)
            return [(i,f'uid-{i}') for i in batch]
        def profiles(uids):
            self.assertLessEqual(len(uids),500)
            return [(uid,1,int(uid[4:])+2000,'shared' if uid in ('uid-1','uid-1001') else 'token-'+uid) for uid in uids]
        def owners(tokens):
            self.assertLessEqual(len(tokens),500)
            return {token:2 if token=='shared' else 1 for token in tokens}
        with patch.object(resolver.admin_users_service,'resolve_user_ids',return_value=ids),patch.object(resolver,'_load_users',side_effect=accounts) as a,patch.object(resolver,'_load_profiles',side_effect=profiles) as p,patch.object(resolver,'_token_owners',side_effect=owners) as t:
            result=self.resolve()
            self.assertEqual((a.call_count,p.call_count,t.call_count),(3,3,3))
            self.assertEqual(result.eligible_recipient_count,999)
            self.assertEqual(dict(result.exclusion_counts)['duplicate_target'],2)

    def test_read_only_snapshot_and_no_n_plus_one(self):
        statements=[]
        def capture(conn,cursor,sql,params,context,many):statements.append(sql)
        event.listen(db.engine,'before_cursor_execute',capture)
        try:self.resolve()
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        self.assertEqual(len(statements),6) # SET, audience, membership, accounts, profiles, ownership
        self.assertTrue(all(not s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for s in statements))
        with patch.object(resolver,'_explicitly_disabled_user_ids',side_effect=lambda ids: self.verify_transaction()):self.resolve()
        self.assertNotIn('notifications.notification_service',sys.modules)
        self.assertNotIn('notifications.notification_fcm',sys.modules)

    def test_exact_ceiling_and_canonical_deduplication(self):
        ids=list(range(1,50001))
        def accounts(batch): return [(i,f'uid-{i}') for i in batch]
        def profiles(uids): return [(uid,1,int(uid[4:])+100000,uid+'-token') for uid in uids]
        with patch.object(resolver.admin_users_service,'resolve_user_ids',return_value=ids+ids[:1]),patch.object(resolver,'_load_users',side_effect=accounts) as a,patch.object(resolver,'_load_profiles',side_effect=profiles),patch.object(resolver,'_token_owners',side_effect=lambda tokens:{t:1 for t in tokens}):
            result=self.resolve()
            self.assertEqual(result.matched_user_count,50000)
            self.assertEqual(result.eligible_recipient_count,50000)
            self.assertEqual(result.excluded_recipient_count,0)
            self.assertEqual(a.call_count,100)

    def test_resolver_does_not_commit_caller_work(self):
        row=db.session.get(AppUser,self.base+100)
        before=row.name
        row.name='uncommitted caller edit'
        self.resolve()
        self.assertIn(row,db.session.dirty)
        db.session.rollback()
        self.assertEqual(db.session.get(AppUser,self.base+100).name,before)

    def test_no_filter_duplication_or_token_logging(self):
        import ast
        import inspect
        import logging
        source=ast.parse(inspect.getsource(resolver))
        attrs={node.attr for node in ast.walk(source) if isinstance(node,ast.Attribute)}
        self.assertFalse({'lang','moon_sign','mahadasha','lagna','_apply_admin_users_filters'} & attrs)
        records=[]
        class Capture(logging.Handler):
            def emit(self,record):records.append(record.getMessage())
        handler=Capture();logging.getLogger().addHandler(handler)
        try:result=self.resolve()
        finally:logging.getLogger().removeHandler(handler)
        for recipient in result.recipients:
            self.assertNotIn(recipient.fcm_token,'\n'.join(records))

    def verify_transaction(self):
        self.assertEqual(db.session.execute(text('SHOW transaction_isolation')).scalar(),'repeatable read')
        self.assertEqual(db.session.execute(text('SHOW transaction_read_only')).scalar(),'on')
        return frozenset()

if __name__=='__main__':unittest.main(verbosity=2)
