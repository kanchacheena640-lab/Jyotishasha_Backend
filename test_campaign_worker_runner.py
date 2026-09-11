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
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
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
    def test_a_workflow_is_manually_dispatchable_schedule_temporarily_paused(self):
        """P4.2 -- controlled first-production-send pause: the `schedule`
        trigger is deliberately OFF right now (a real production backlog
        had 3 FROZEN executions, only 1 authorized to send; an automatic
        cron sweep would have attempted all 3). workflow_dispatch (incl.
        the --execution-id scoped mode) must remain fully available
        throughout the pause. Still never push/pull_request -- this
        remains a bounded, isolated job, not a CI trigger. See the
        workflow file's own P4.2 comment for the exact restore step."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.github', 'workflows', 'campaign_notifications_worker.yml')
        with open(path, encoding='utf-8') as fh:
            spec = yaml.safe_load(fh)
        # YAML parses the bare key `on` as the boolean True in PyYAML 1.1
        # semantics -- handle both spellings defensively.
        triggers = spec.get('on', spec.get(True))
        self.assertIsInstance(triggers, dict)
        self.assertEqual(set(triggers.keys()), {'workflow_dispatch'}, 'schedule must stay paused (P4.2)')
        self.assertNotIn('push', triggers)
        self.assertNotIn('pull_request', triggers)
        self.assertIn('execution_id', triggers['workflow_dispatch']['inputs'],
                       'scoped single-execution resume must remain available during the pause')

    def test_workflow_never_sets_test_mode_vars(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.github', 'workflows', 'campaign_notifications_worker.yml')
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        for forbidden in ('ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED:', 'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID:'):
            self.assertNotIn(forbidden, text)

    def test_n_scheduler_is_now_invoked_by_runner_and_workflow_behind_the_same_gates(self):
        """P4 -- the OPPOSITE of this test's own pre-P4 assertion:
        notifications.campaign_scheduler.process_due_scheduled_campaigns()
        is now called by the runner, so due SCHEDULED campaigns are
        promoted without a human dispatching anything. Still gated by
        the exact same preflight (DEPLOYMENT_ENVIRONMENT=production,
        ADMIN_CAMPAIGN_SEND_ENABLED, ADMIN_CAMPAIGN_WORKER_AUTHORIZED,
        FCM_SERVICE_ACCOUNT_JSON) BEFORE this call -- see
        PreflightGateTests below, which prove the whole run (including
        this promotion step) fails closed on any missing gate."""
        with open(runner.__file__, encoding='utf-8') as fh:
            runner_src = fh.read()
        self.assertIn('process_due_scheduled_campaigns', runner_src)
        self.assertIn('from notifications.campaign_scheduler import process_due_scheduled_campaigns', runner_src)
        # The call must sit AFTER the preflight gate check and the
        # production-transport verification, never before either.
        # Isolate run()'s own body so a prose mention of these same names
        # in the module docstring (explaining the change above) can never
        # be mistaken for the actual call sites.
        run_body = runner_src[runner_src.index('\ndef run('):]
        preflight_pos = run_body.index('_preflight_gate_check()')
        transport_pos = run_body.index('_verify_production_transport(select_transport, FirebaseTransport)')
        scheduler_pos = run_body.index('process_due_scheduled_campaigns(')
        self.assertLess(preflight_pos, scheduler_pos)
        self.assertLess(transport_pos, scheduler_pos)
        # Checks what the workflow actually EXECUTES (the `run:` step's
        # own shell command) never itself needs to name campaign_scheduler
        # -- that wiring lives inside campaign_worker_runner.py, called
        # unconditionally as part of this one script's own run().
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.github', 'workflows', 'campaign_notifications_worker.yml')
        with open(path, encoding='utf-8') as fh:
            spec = yaml.safe_load(fh)
        run_command = spec['jobs']['run-campaign-worker']['steps'][-1]['run']
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

    def _scheduled_execution(self, title='P4 scheduled runner test'):
        """P4 -- mirrors _frozen_execution() but via the Schedule path
        (SCHEDULED, not FROZEN): a real draft, a real
        POST .../schedule call at least MIN_SCHEDULE_LEAD (60s) in the
        future -- the minimum this route accepts -- so the resulting
        execution is genuinely SCHEDULED, not yet due, until a test
        explicitly advances "now" past scheduled_for."""
        payload = dict(title=title, body='Body', audience_mode='SAVED_AUDIENCE',
                        saved_audience_id=self.audience_id,
                        action={'type': 'NONE', 'target': None, 'parameters': {}})
        r = self.client.post('/admin/api/notifications', json=payload, headers=self.admin)
        self.assertEqual(r.status_code, 201)
        campaign_id = r.get_json()['id']
        self.campaigns.append(campaign_id)
        now = datetime.now(timezone.utc)
        scheduled_for = now + timedelta(seconds=90)
        r = self.client.post(f'/admin/api/notifications/{campaign_id}/schedule', json={
            'revision': 1, 'idempotency_key': 'sched-key-' + campaign_id,
            'scheduled_for': scheduled_for.isoformat(), 'preview_generated_at': now.isoformat(),
        }, headers=self.admin)
        self.assertEqual(r.status_code, 202, r.get_json())
        return r.get_json()['id'], scheduled_for

    def test_m_due_scheduled_execution_is_promoted_and_processed_in_one_invocation(self):
        """P4 -- Final Production Activation's own core requirement: a
        due SCHEDULED campaign is delivered WITHOUT any human manually
        dispatching anything -- one runner.run() call both promotes it
        (SCHEDULED -> FROZEN, via the existing, unmodified N5
        process_due_scheduled_campaigns()) and processes/sends it
        (FROZEN -> COMPLETED, via the existing, unmodified N4 worker) --
        exactly the "one worker engine" contract this task requires."""
        execution_id, scheduled_for = self._scheduled_execution()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'SCHEDULED')
        due_now = scheduled_for + timedelta(seconds=5)
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('notifications.campaign_scheduler._now', return_value=due_now), \
                 patch('firebase_admin.messaging.send', return_value='msg-scheduled'):
                code = runner.run(runner.parse_args(['--max-executions', '5']))
        self.assertEqual(code, 0)
        # The pre-run() fetch above cached this row in this session's
        # identity map; runner.run()'s own nested app_context commits are
        # real, but this OUTER session was never the one that committed
        # them, so its cached copy is never auto-expired -- force a fresh
        # read rather than trust a stale in-memory object.
        db.session.expire_all()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'COMPLETED')
        delivery = NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).first()
        self.assertEqual(delivery.status, 'ACCEPTED')

    def test_m2_not_yet_due_scheduled_execution_is_left_untouched(self):
        """The complementary case: a SCHEDULED campaign whose time has
        NOT yet arrived must remain SCHEDULED (never force-promoted,
        never sent early) -- runner.run() is a pure no-op for it."""
        execution_id, scheduled_for = self._scheduled_execution(title='P4 not yet due')
        not_due_yet = scheduled_for - timedelta(seconds=30)
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('notifications.campaign_scheduler._now', return_value=not_due_yet), \
                 patch('firebase_admin.messaging.send') as mock_send:
                code = runner.run(runner.parse_args(['--max-executions', '5']))
        self.assertEqual(code, 0)
        mock_send.assert_not_called()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'SCHEDULED')

    def test_n2_kill_switch_stops_schedule_promotion_too_not_only_delivery(self):
        """P4's own explicit safety requirement: ADMIN_CAMPAIGN_SEND_ENABLED
        is the kill switch for BOTH schedule promotion and delivery -- a
        due campaign must simply wait (stay SCHEDULED) when sending is
        disabled, never silently freeze targets while unable to send."""
        execution_id, scheduled_for = self._scheduled_execution(title='P4 kill switch due')
        due_now = scheduled_for + timedelta(seconds=5)
        with _GateSandbox() as sandbox:
            sandbox.prod(ADMIN_CAMPAIGN_SEND_ENABLED='false')
            with patch('notifications.campaign_scheduler._now', return_value=due_now), \
                 patch('firebase_admin.messaging.send') as mock_send:
                with self.assertRaises(SystemExit) as ctx:
                    runner.run(runner.parse_args(['--max-executions', '5']))
                self.assertEqual(ctx.exception.code, 1, 'preflight must fail closed, never silently no-op')
        mock_send.assert_not_called()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'SCHEDULED', 'kill switch stops promotion too, not only delivery')

    def test_o_execution_id_flag_processes_only_that_execution_and_leaves_others_untouched(self):
        """P4.1 incident-recovery mode: with a real production backlog of
        MULTIPLE FROZEN executions (proven live via the read-only
        diagnostic that found three simultaneously-FROZEN executions),
        --execution-id must resume exactly ONE of them without sending
        to any other campaign's targets."""
        target_execution_id = self._frozen_execution(title='P4.1 target execution')
        other_execution_id = self._frozen_execution(title='P4.1 bystander execution')
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send', return_value='msg-scoped') as mock_send:
                code = runner.run(runner.parse_args(['--max-executions', '5', '--execution-id', target_execution_id]))
        self.assertEqual(code, 0)
        self.assertEqual(mock_send.call_count, 1, 'must send to exactly the one scoped execution, never the bystander')
        db.session.expire_all()
        target = db.session.get(NotificationCampaignExecution, target_execution_id)
        other = db.session.get(NotificationCampaignExecution, other_execution_id)
        self.assertEqual(target.state, 'COMPLETED')
        self.assertEqual(other.state, 'FROZEN', 'bystander execution must be left completely untouched')
        target_delivery = NotificationCampaignDelivery.query.filter_by(execution_id=target_execution_id).first()
        other_delivery = NotificationCampaignDelivery.query.filter_by(execution_id=other_execution_id).first()
        self.assertEqual(target_delivery.status, 'ACCEPTED')
        self.assertEqual(other_delivery.status, 'PENDING', 'bystander delivery must never be attempted')

    def test_o2_execution_id_flag_rejects_unknown_id(self):
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send') as mock_send:
                with self.assertRaises(SystemExit) as ctx:
                    runner.run(runner.parse_args(['--execution-id', str(uuid.uuid4())]))
                self.assertEqual(ctx.exception.code, 1)
        mock_send.assert_not_called()

    def test_o3_execution_id_flag_rejects_non_frozen_state(self):
        """A SCHEDULED-but-not-due execution id must be refused, not
        silently force-processed -- --execution-id is scoped resumption
        of already-approved FROZEN/SENDING work, never a bypass of the
        FROZEN-state requirement itself."""
        execution_id, _scheduled_for = self._scheduled_execution(title='P4.1 not processable yet')
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('firebase_admin.messaging.send') as mock_send:
                with self.assertRaises(SystemExit) as ctx:
                    runner.run(runner.parse_args(['--execution-id', execution_id]))
                self.assertEqual(ctx.exception.code, 1)
        mock_send.assert_not_called()
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        self.assertEqual(execution.state, 'SCHEDULED')

    def test_o4_execution_id_flag_skips_scheduler_promotion_entirely(self):
        """A separate due SCHEDULED execution must NOT be promoted as a
        side effect of a scoped --execution-id run -- scoped mode
        touches only the one named execution, full stop."""
        target_execution_id = self._frozen_execution(title='P4.1 scoped target, scheduler bystander test')
        sched_execution_id, scheduled_for = self._scheduled_execution(title='P4.1 due but must stay untouched')
        due_now = scheduled_for + timedelta(seconds=5)
        with _GateSandbox() as sandbox:
            sandbox.prod()
            with patch('notifications.campaign_scheduler._now', return_value=due_now), \
                 patch('firebase_admin.messaging.send', return_value='msg-scoped2') as mock_send:
                code = runner.run(runner.parse_args(['--execution-id', target_execution_id]))
        self.assertEqual(code, 0)
        self.assertEqual(mock_send.call_count, 1)
        db.session.expire_all()
        sched_execution = db.session.get(NotificationCampaignExecution, sched_execution_id)
        self.assertEqual(sched_execution.state, 'SCHEDULED', 'due SCHEDULED execution must not be promoted in scoped mode')

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
