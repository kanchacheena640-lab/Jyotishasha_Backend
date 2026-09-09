"""P3A -- scripts/campaign_worker_runner.py + notifications.campaign_worker
.discover_processable_executions() + .github/workflows/
campaign_notifications_worker.yml.

NO real Firebase call anywhere in this file -- firebase_admin.messaging.send
is always patched. Run via scripts/l3_local_verify.py so no Firebase/
network/DDL slips in.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

import yaml

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
from notifications import campaign_worker as worker

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import campaign_worker_runner as runner  # noqa: E402

from flask_jwt_extended import create_access_token

GATE_VARS = (
    'DEPLOYMENT_ENVIRONMENT', 'ADMIN_CAMPAIGN_SEND_ENABLED', 'ADMIN_CAMPAIGN_WORKER_AUTHORIZED',
    'ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED', 'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID',
)


def _sweep_stray_processable_executions():
    """discover_processable_executions() deliberately sees the WHOLE
    local DB (that is its entire point -- it is not test-fixture-scoped
    by design), so any stray FROZEN/SENDING execution left behind by an
    earlier, unrelated ad-hoc QA script, an interrupted test run, or (by
    design) a PRECEDING test in this same suite that deliberately leaves
    one execution still FROZEN (e.g. a bounded/deferred-work case) would
    otherwise silently compete with a later test's own bounded-count
    assertions -- it would be the oldest-frozen_at candidate discovery
    picks first. Neutralized by moving any such row to CANCELLED (a
    real, valid terminal state) -- never touches a row a currently-
    running test creates AFTER calling this, and never runs against
    anything but the local dev DB already verified by db_safety at
    `from app import app` above. Assumes an app context is already
    active (true both at module setup and inside each test's own setUp)."""
    stray_ids = [
        row.id for row in
        NotificationCampaignExecution.query.filter(
            NotificationCampaignExecution.state.in_(worker.WORKER_PROCESSABLE_STATES)
        ).all()
    ]
    if stray_ids:
        now = datetime.now(timezone.utc)
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(stray_ids)).update(
            {'state': 'CANCELLED', 'completed_at': now, 'updated_at': now}, synchronize_session=False)
        db.session.commit()


def setUpModule():
    with app.app_context():
        _sweep_stray_processable_executions()


class _GateSandbox:
    """Saves/restores every gate var (never DATABASE_URL/FCM_SERVICE_
    ACCOUNT_JSON, which the L3 runner already owns and which stay local/
    dummy throughout this whole file)."""

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

    def prod(self, **overrides):
        values = {'DEPLOYMENT_ENVIRONMENT': 'production', 'ADMIN_CAMPAIGN_SEND_ENABLED': 'true',
                  'ADMIN_CAMPAIGN_WORKER_AUTHORIZED': 'true'}
        values.update(overrides)
        for k, v in values.items():
            os.environ[k] = v


def iso(dt):
    return dt.isoformat()


# ---------------- A. workflow file itself ----------------

class WorkflowFileTests(unittest.TestCase):
    def test_a_workflow_is_workflow_dispatch_only(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.github', 'workflows', 'campaign_notifications_worker.yml')
        with open(path, encoding='utf-8') as fh:
            spec = yaml.safe_load(fh)
        # YAML parses the bare key `on` as the boolean True in PyYAML 1.1
        # semantics -- handle both spellings defensively.
        triggers = spec.get('on', spec.get(True))
        self.assertIsInstance(triggers, dict)
        self.assertEqual(set(triggers.keys()), {'workflow_dispatch'})
        self.assertNotIn('schedule', triggers)
        self.assertNotIn('push', triggers)
        self.assertNotIn('pull_request', triggers)

    def test_workflow_never_sets_test_mode_vars(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.github', 'workflows', 'campaign_notifications_worker.yml')
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        for forbidden in ('ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED:', 'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID:'):
            self.assertNotIn(forbidden, text)

    def test_n_scheduler_never_referenced_by_runner_or_workflow(self):
        with open(runner.__file__, encoding='utf-8') as fh:
            runner_src = fh.read()
        self.assertNotIn('campaign_scheduler', runner_src)
        # Checks what the workflow actually EXECUTES (the `run:` step's
        # own shell command), not its prose comments -- this file's own
        # comments legitimately explain that campaign_scheduler is NOT
        # invoked, which would otherwise trip a whole-file substring check.
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.github', 'workflows', 'campaign_notifications_worker.yml')
        with open(path, encoding='utf-8') as fh:
            spec = yaml.safe_load(fh)
        run_command = spec['jobs']['run-campaign-worker']['steps'][-1]['run']
        self.assertNotIn('campaign_scheduler', run_command)
        self.assertNotIn('process_due_scheduled_campaigns', run_command)
        self.assertIn('campaign_worker_runner.py', run_command)


# ---------------- B, C, D. gate/transport preflight (no DB fixtures needed) ----------------

class PreflightGateTests(unittest.TestCase):
    def setUp(self):
        self.context = app.app_context(); self.context.push()

    def tearDown(self):
        self.context.pop()

    def test_b_each_missing_production_gate_fails_closed(self):
        combos = [
            {},
            {'DEPLOYMENT_ENVIRONMENT': 'production'},
            {'DEPLOYMENT_ENVIRONMENT': 'production', 'ADMIN_CAMPAIGN_SEND_ENABLED': 'true'},
            {'DEPLOYMENT_ENVIRONMENT': 'production', 'ADMIN_CAMPAIGN_WORKER_AUTHORIZED': 'true'},
            {'ADMIN_CAMPAIGN_SEND_ENABLED': 'true', 'ADMIN_CAMPAIGN_WORKER_AUTHORIZED': 'true'},
        ]
        for combo in combos:
            with self.subTest(combo=combo), _GateSandbox() as sandbox:
                for k, v in combo.items():
                    os.environ[k] = v
                with self.assertRaises(SystemExit) as ctx:
                    runner.run(runner.parse_args(['--max-executions', '1']))
                self.assertEqual(ctx.exception.code, 1)

    def test_c_test_transport_var_enabled_fails_closed_even_with_all_prod_gates(self):
        with _GateSandbox() as sandbox:
            sandbox.prod(ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED='true')
            with self.assertRaises(SystemExit) as ctx:
                runner.run(runner.parse_args([]))
            self.assertEqual(ctx.exception.code, 1)

    def test_c2_test_recipient_var_alone_also_fails_closed(self):
        with _GateSandbox() as sandbox:
            sandbox.prod(ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID='3862')
            with self.assertRaises(SystemExit) as ctx:
                runner.run(runner.parse_args([]))
            self.assertEqual(ctx.exception.code, 1)

    def test_d_unexpected_transport_type_is_rejected(self):
        from notifications.campaign_transport import NoSendTransport, FakeTransport
        from notifications.firebase_transport import FirebaseTransport, ControlledTestTransport
        for bad_transport in (NoSendTransport(), FakeTransport(), ControlledTestTransport(FirebaseTransport(), allowlisted_app_user_id=1)):
            with self.subTest(transport=type(bad_transport).__name__):
                with self.assertRaises(SystemExit) as ctx:
                    runner._verify_production_transport(lambda: bad_transport, FirebaseTransport)
                self.assertEqual(ctx.exception.code, 1)

    def test_d2_real_firebase_transport_passes(self):
        from notifications.firebase_transport import FirebaseTransport
        real = FirebaseTransport()
        result = runner._verify_production_transport(lambda: real, FirebaseTransport)
        self.assertIs(result, real)


# ---------------- F, G. execution discovery ----------------

class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.base = 981870
        db.session.add(User(id=cls.base, firebase_uid='p3a-disc', name='p3a-disc', email='p3a-disc@example.invalid'))
        db.session.add(AppUser(id=cls.base + 100, firebase_uid='p3a-disc', fcm_token='disc-token', lang='en'))
        db.session.commit()
        cls.audience = SavedAudience(name='P3A discovery synthetic', criteria={'version': 1, 'filters': {'search': 'p3a-disc'}}, is_active=True)
        db.session.add(cls.audience); db.session.commit()
        cls.campaigns = []

    @classmethod
    def tearDownClass(cls):
        db.session.rollback()
        execution_ids = [e.id for e in NotificationCampaignExecution.query.filter(NotificationCampaignExecution.campaign_id.in_(cls.campaigns)).all()]
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationCampaign.query.filter(NotificationCampaign.id.in_(cls.campaigns)).delete(synchronize_session=False)
        SavedAudience.query.filter_by(id=cls.audience.id).delete(synchronize_session=False)
        AppUser.query.filter_by(id=cls.base + 100).delete(synchronize_session=False)
        User.query.filter_by(id=cls.base).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def _bare_execution(self, state, campaign_state='PROCESSING', **overrides):
        now = datetime.now(timezone.utc)
        campaign = NotificationCampaign(
            title=f'P3A discovery {state}', body='Body', saved_audience_id=self.audience.id,
            draft_criteria={'version': 1, 'filters': {'search': 'p3a-disc'}}, criteria_version=1, draft_criteria_hash='x',
            action={'type': 'NONE', 'target': None, 'parameters': {}}, state=campaign_state,
        )
        db.session.add(campaign); db.session.flush()
        self.campaigns.append(campaign.id)
        fields = dict(
            campaign_id=campaign.id, state=state,
            approved_saved_audience_id=self.audience.id, approved_criteria={'version': 1, 'filters': {}},
            approved_criteria_version=1, approved_criteria_hash='x',
            approved_title='t', approved_body='b', approved_action={'type': 'NONE', 'target': None, 'parameters': {}},
            baseline_generated_at=now, baseline_matched_user_count=1, baseline_eligible_recipient_count=1,
            baseline_recorded_at=now, resolved_matched_user_count=1, resolved_eligible_recipient_count=1,
            resolved_excluded_recipient_count=0, resolved_exclusion_counts={}, resolver_policy_version='x',
            created_at=now, updated_at=now,
        )
        fields.update(overrides)
        execution = NotificationCampaignExecution(**fields)
        db.session.add(execution); db.session.commit()
        return campaign.id, execution.id

    def test_f_g_only_frozen_and_sending_are_discovered(self):
        included_ids = set()
        excluded_ids = set()
        for state, extra in [
            ('FROZEN', {'frozen_at': datetime.now(timezone.utc)}),
            ('SENDING', {'frozen_at': datetime.now(timezone.utc), 'started_at': datetime.now(timezone.utc)}),
        ]:
            _, exec_id = self._bare_execution(state, **extra)
            included_ids.add(exec_id)
        for state, campaign_state, extra in [
            ('SCHEDULED', 'SCHEDULED', {'scheduled_for': datetime.now(timezone.utc)}),
            ('PAUSED', 'PROCESSING', {'hold_reason': 'DRIFT'}),
            ('COMPLETED', 'COMPLETED', {'completed_at': datetime.now(timezone.utc)}),
            ('PARTIAL', 'PARTIAL', {'completed_at': datetime.now(timezone.utc)}),
            ('FAILED', 'FAILED', {'completed_at': datetime.now(timezone.utc)}),
            ('EXPIRED', 'FAILED', {'completed_at': datetime.now(timezone.utc)}),
            ('BLOCKED', 'FAILED', {'completed_at': datetime.now(timezone.utc)}),
            ('CANCELLED', 'CANCELLED', {'completed_at': datetime.now(timezone.utc)}),
        ]:
            _, exec_id = self._bare_execution(state, campaign_state=campaign_state, **extra)
            excluded_ids.add(exec_id)

        discovered = set(worker.discover_processable_executions(limit=100))
        self.assertTrue(included_ids.issubset(discovered), "every FROZEN/SENDING execution must be discovered")
        self.assertEqual(discovered & excluded_ids, set(),
                          "no SCHEDULED/PAUSED/terminal execution may ever be discovered")


# ---------------- E, H, I, J, K, L, M. end-to-end via run() ----------------

class RunnerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        cls.client = app.test_client()
        cls.base = 981880
        db.session.add(User(id=cls.base, firebase_uid='p3a-run', name='p3a-run', email='p3a-run@example.invalid'))
        db.session.add(AppUser(id=cls.base + 100, firebase_uid='p3a-run', fcm_token='run-token', lang='en'))
        db.session.commit()
        cls.audience = SavedAudience(name='P3A runner synthetic', criteria={'version': 1, 'filters': {'search': 'p3a-run'}}, is_active=True)
        db.session.add(cls.audience); db.session.commit()
        cls.audience_id = cls.audience.id
        cls.campaigns = []
        os.environ['ADMIN_USER_IDS'] = str(cls.base)
        cls.admin = {'Authorization': 'Bearer ' + create_access_token(identity=str(cls.base))}

    @classmethod
    def tearDownClass(cls):
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

    def setUp(self):
        # Re-swept before EVERY test, not just once for the whole module
        # (setUpModule above): several tests in this class deliberately
        # leave one execution still FROZEN by design (e.g. test_h's own
        # "bounded, deferred to next run" case) -- without this, THAT
        # leftover row would be the oldest-frozen_at candidate the NEXT
        # test's own bounded discover_processable_executions() picks up
        # first, instead of that test's own fresh fixtures.
        _sweep_stray_processable_executions()

    def _frozen_execution(self, title='P3A runner test'):
        payload = dict(title=title, body='Body', audience_mode='SAVED_AUDIENCE',
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

    def test_e_eligible_execution_processes_with_all_gates_and_real_transport_class(self):
        execution_id = self._frozen_execution()
        buf = io.StringIO()
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send', return_value='msg-1'), redirect_stdout(buf):
                code = runner.run(runner.parse_args(['--max-executions', '5']))
        self.assertEqual(code, 0)
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        self.assertEqual(delivery.status, 'ACCEPTED')
        attempts = NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).all()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].provider, 'firebase')
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'COMPLETED')
        return buf.getvalue()

    def test_h_multiple_eligible_executions_bounded_by_max_executions(self):
        ids = [self._frozen_execution(title=f'P3A bound {i}') for i in range(3)]
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send', return_value='msg-bound'):
                code = runner.run(runner.parse_args(['--max-executions', '2']))
        self.assertEqual(code, 0)
        states = [db.session.get(NotificationCampaignExecution, eid).state for eid in ids]
        completed = sum(1 for s in states if s == 'COMPLETED')
        still_frozen = sum(1 for s in states if s == 'FROZEN')
        self.assertEqual(completed, 2, 'exactly max-executions worth of work processed this run')
        self.assertEqual(still_frozen, 1, 'the rest is left for the next invocation, never force-drained')

    def test_i_restart_resumes_deferred_work_safely(self):
        ids = [self._frozen_execution(title=f'P3A restart {i}') for i in range(2)]
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send', return_value='msg-restart'):
                # "Crash"/first invocation only gets to 1 of 2.
                runner.run(runner.parse_args(['--max-executions', '1']))
                first_states = [db.session.get(NotificationCampaignExecution, eid).state for eid in ids]
                self.assertEqual(sorted(first_states), ['COMPLETED', 'FROZEN'])
                # "Restart": a fresh invocation picks up exactly the leftover one.
                runner.run(runner.parse_args(['--max-executions', '5']))
        second_states = [db.session.get(NotificationCampaignExecution, eid).state for eid in ids]
        self.assertEqual(second_states, ['COMPLETED', 'COMPLETED'])

    def test_j_no_duplicate_delivery_or_attempt_across_two_runner_invocations(self):
        execution_id = self._frozen_execution()
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send', return_value='msg-once') as mock_send:
                runner.run(runner.parse_args(['--max-executions', '5']))
                # Second invocation: the execution is now COMPLETED, no
                # longer discoverable -- must be a pure no-op.
                runner.run(runner.parse_args(['--max-executions', '5']))
        self.assertEqual(mock_send.call_count, 1)
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        self.assertEqual(NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id).count(), 1)

    def test_k_l_unknown_and_attempt_ceiling_hold_through_the_runner(self):
        from firebase_admin import exceptions
        execution_id = self._frozen_execution(title='P3A ceiling test')
        with _GateSandbox() as sandbox:
            sandbox.prod()
            # 4 rounds of transient failure -> exhausts to FAILED_PERMANENT, never a 5th.
            with patch('firebase_admin.messaging.send', side_effect=exceptions.UnavailableError('down')):
                for _ in range(4):
                    delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
                    delivery.next_attempt_at = None
                    delivery.lease_until = None
                    db.session.commit()
                    runner.run(runner.parse_args(['--max-executions', '5']))
            delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
            self.assertEqual(delivery.attempt_count, 4)
            self.assertEqual(delivery.status, 'FAILED_PERMANENT')
            with patch('firebase_admin.messaging.send') as mock_send:
                runner.run(runner.parse_args(['--max-executions', '5']))
            mock_send.assert_not_called()

        # UNKNOWN, separately: never auto-retried.
        execution_id2 = self._frozen_execution(title='P3A unknown test')
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send', side_effect=RuntimeError('mystery')):
                runner.run(runner.parse_args(['--max-executions', '5']))
            delivery2 = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id2).first()
            self.assertEqual(delivery2.status, 'UNKNOWN')
            with patch('firebase_admin.messaging.send') as mock_send2:
                runner.run(runner.parse_args(['--max-executions', '5']))
            mock_send2.assert_not_called()

    def test_m_logs_contain_no_token_credential_or_pii(self):
        execution_id = self._frozen_execution(title='P3A log-safety test')
        buf = io.StringIO()
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send', return_value='msg-log'), redirect_stdout(buf):
                runner.run(runner.parse_args(['--max-executions', '5']))
        output = buf.getvalue()
        for forbidden in ('run-token', 'p3a-run@example.invalid', 'p3a-run'):
            self.assertNotIn(forbidden, output)
        self.assertIn('[worker]', output)


if __name__ == '__main__':
    unittest.main()
