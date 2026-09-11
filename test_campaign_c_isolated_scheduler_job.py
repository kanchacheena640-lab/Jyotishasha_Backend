"""P4.9 -- Campaign C automatic processing, Option 2 fallback.

Root cause of campaign_notifications_worker.yml's own `schedule:`
trigger repeatedly failing to fire (P4.7/P4.8: 11 due ticks missed
across 3 separate activation attempts and 2 different cron
expressions) was never fully proven from outside GitHub's own
scheduler -- but it was clearly specific to THAT workflow file/id
(created 2026-09-10), since notifications.yml (registered since
2026-04-02) has never missed a tick in the same repo, same account,
same time windows.

Rather than keep guessing at that one workflow's own registration,
Campaign C's automatic processing now rides on notifications.yml's own
proven-reliable registration, as a completely separate, isolated job
(campaign-c-worker) -- NEVER merged into that file's own A/B business
logic (run-cron), no shared state, no `needs:` dependency either way.

This file proves the isolation contract itself, purely by parsing the
committed YAML -- no GitHub Actions API call, no live dispatch. See
test_campaign_worker_runner.py's own WorkflowFileTests for
campaign_notifications_worker.yml's own (now workflow_dispatch-only)
shape.
"""
import os
import unittest

import yaml

NOTIFICATIONS_YML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  '.github', 'workflows', 'notifications.yml')
CAMPAIGN_C_SLOT_CRON = '7,22,37,52 * * * *'


def _load():
    with open(NOTIFICATIONS_YML, encoding='utf-8') as fh:
        return yaml.safe_load(fh)


class NotificationsYmlCampaignCIsolationTests(unittest.TestCase):
    def test_a_four_schedule_entries_present_campaign_c_slot_is_new_and_offset(self):
        spec = _load()
        # YAML parses the bare key `on` as the boolean True in PyYAML
        # 1.1 semantics -- handle both spellings defensively.
        triggers = spec.get('on', spec.get(True))
        crons = [entry['cron'] for entry in triggers['schedule']]
        self.assertEqual(len(crons), 4, 'exactly the 3 original A/B slots plus 1 new Campaign C slot')
        self.assertIn(CAMPAIGN_C_SLOT_CRON, crons)
        # Every 15 minutes, offset from the popular :00/:15/:30/:45
        # boundaries (same P4.8 reasoning that motivated this cron).
        minute_field = CAMPAIGN_C_SLOT_CRON.split()[0]
        listed_minutes = {part.split('/')[0] for part in minute_field.split(',')}
        self.assertFalse(listed_minutes & {'0', '00', '15', '30', '45'})

    def test_b_original_ab_slots_are_byte_identical_never_altered(self):
        """Hard requirement: 'Do NOT alter Panchang/Event business
        timing just to accommodate Campaign C.'"""
        spec = _load()
        triggers = spec.get('on', spec.get(True))
        crons = [entry['cron'] for entry in triggers['schedule']]
        for original in ('30 0 * * *', '30 11 * * *', '30 12 * * *'):
            self.assertIn(original, crons, f'original A/B cron {original!r} must be untouched')

    def test_c_workflow_dispatch_slot_input_unchanged(self):
        """The existing manual-trigger `slot` choice input (morning/
        evening/dismiss_panchang) for run-cron must be untouched --
        Campaign C's manual dispatch lives exclusively in
        campaign_notifications_worker.yml, never duplicated here."""
        spec = _load()
        triggers = spec.get('on', spec.get(True))
        wd = triggers['workflow_dispatch']
        self.assertEqual(set(wd['inputs'].keys()), {'slot'})
        self.assertEqual(set(wd['inputs']['slot']['options']), {'morning', 'evening', 'dismiss_panchang'})

    def test_d_two_jobs_present_and_fully_independent(self):
        spec = _load()
        jobs = spec['jobs']
        self.assertEqual(set(jobs.keys()), {'run-cron', 'campaign-c-worker'})
        self.assertNotIn('needs', jobs['run-cron'], 'run-cron must never depend on campaign-c-worker')
        self.assertNotIn('needs', jobs['campaign-c-worker'], 'campaign-c-worker must never depend on run-cron')

    def test_e_run_cron_if_excludes_the_campaign_c_slot(self):
        spec = _load()
        condition = spec['jobs']['run-cron']['if']
        self.assertIn(f"github.event.schedule != '{CAMPAIGN_C_SLOT_CRON}'", condition)
        self.assertIn("github.event_name == 'workflow_dispatch'", condition)

    def test_f_campaign_c_worker_if_matches_only_its_own_slot(self):
        spec = _load()
        condition = spec['jobs']['campaign-c-worker']['if']
        self.assertIn(f"github.event.schedule == '{CAMPAIGN_C_SLOT_CRON}'", condition)
        self.assertIn("github.event_name == 'schedule'", condition,
                       'must never also fire on this workflow\'s own workflow_dispatch -- '
                       'manual Campaign C dispatch stays exclusively in campaign_notifications_worker.yml')

    def test_g_campaign_c_worker_reuses_exact_production_gates(self):
        spec = _load()
        steps = spec['jobs']['campaign-c-worker']['steps']
        run_step = next(s for s in steps if 'env' in s)
        env = run_step['env']
        self.assertEqual(env['DEPLOYMENT_ENVIRONMENT'], 'production')
        self.assertEqual(env['ADMIN_CAMPAIGN_WORKER_AUTHORIZED'], 'true')
        self.assertEqual(env['ADMIN_CAMPAIGN_SEND_ENABLED'].strip(),
                          '${{ vars.ADMIN_CAMPAIGN_SEND_ENABLED }}',
                          'kill switch must be the same P4.4 repo variable, not a hardcoded literal')
        for forbidden in ('ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED', 'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID'):
            self.assertNotIn(forbidden, env)

    def test_h_campaign_c_worker_runs_the_exact_unscoped_bounded_command(self):
        spec = _load()
        steps = spec['jobs']['campaign-c-worker']['steps']
        run_step = next(s for s in steps if 'env' in s)
        command = run_step['run']
        self.assertIn('scripts/campaign_worker_runner.py', command)
        self.assertIn('--max-executions 20', command)
        self.assertIn('--batch-limit 100', command)
        self.assertIn('--max-runtime-seconds 240', command)
        self.assertNotIn('--execution-id', command,
                          'automatic runs must sweep the whole backlog, never scoped to one execution')

    def test_i_run_cron_python_logic_untouched(self):
        """Static regression guard: the A/B business-logic Python block
        (NOTIFICATION_SLOT resolution + run_daily_event_job/
        run_panchang_dismiss_job dispatch) must be byte-identical to
        before this task -- Campaign C must never touch A/B logic."""
        spec = _load()
        steps = spec['jobs']['run-cron']['steps']
        run_step = next(s for s in steps if 'env' in s)
        self.assertIn('NOTIFICATION_SLOT', run_step['env'])
        self.assertIn("github.event.schedule == '30 0 * * *' && 'morning'", run_step['env']['NOTIFICATION_SLOT'])
        self.assertIn('run_daily_event_job', run_step['run'])
        self.assertIn('run_panchang_dismiss_job', run_step['run'])


if __name__ == '__main__':
    unittest.main()
