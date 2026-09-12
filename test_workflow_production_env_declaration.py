"""N-FIX-1 -- regression guard for the P0 automatic-workflow boot failure.

Root cause (Notifications Final Audit, N-P0-1): db_safety.enforce_local_
database_safety() (called unconditionally at factory.py's own
create_app()) requires ACTIVITY_EVENTS_ENVIRONMENT to be explicitly
"production" to allow startup against a real production DATABASE_URL --
GitHub Actions runners have neither RENDER=true nor a local-allowlisted
database, so a job missing this var unconditionally raises
DatabaseSafetyError at the very first line of create_app(), before a
single query. notifications.yml's run-cron job, alerts.yml, and
subscription_state_sync.yml were never given this var when db_safety.py
was introduced (e98796a) and failed 100% of the time from that point on
-- proven via real GitHub Actions run history (identical
DatabaseSafetyError traceback in every post-e98796a run of all three).
campaign-c-worker (notifications.yml) and campaign_notifications_worker.yml
already had it correct from the start.

This file proves the fix purely by parsing the committed YAML -- no
GitHub Actions API call, no live dispatch -- mirroring
test_campaign_c_isolated_scheduler_job.py's own established pattern for
this exact repo.
"""
import os
import unittest

import yaml

WORKFLOWS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.github', 'workflows')
REQUIRED_VALUE = 'production'
ENV_VAR = 'ACTIVITY_EVENTS_ENVIRONMENT'


def _load(filename):
    with open(os.path.join(WORKFLOWS_DIR, filename), encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def _env_of(job, step_predicate=lambda s: 'env' in s):
    """The env dict of the first step in this job matching step_predicate
    -- every workflow here has exactly one Python-invoking step per job
    with a non-trivial env block, matching test_campaign_c_isolated_
    scheduler_job.py's own `next(s for s in steps if 'env' in s)` idiom."""
    return next(s for s in job['steps'] if step_predicate(s))['env']


class NotificationsYmlProductionEnvTests(unittest.TestCase):
    """notifications.yml has TWO jobs -- the fix must land specifically
    on run-cron's own env block, never merely "somewhere in the file"
    (campaign-c-worker already had this var before this fix, so a
    whole-file substring check would have given zero real regression
    protection)."""

    def test_run_cron_declares_production_environment(self):
        spec = _load('notifications.yml')
        env = _env_of(spec['jobs']['run-cron'])
        self.assertEqual(
            env.get(ENV_VAR), REQUIRED_VALUE,
            f"run-cron's own job env must declare {ENV_VAR}: {REQUIRED_VALUE} "
            "-- this is the exact N-P0-1 root cause (DatabaseSafetyError at boot)."
        )

    def test_campaign_c_worker_still_declares_production_environment(self):
        """Regression guard the other direction: this fix must not have
        touched campaign-c-worker's own (already-correct) env block."""
        spec = _load('notifications.yml')
        env = _env_of(spec['jobs']['campaign-c-worker'])
        self.assertEqual(env.get(ENV_VAR), REQUIRED_VALUE)

    def test_run_cron_business_logic_and_cron_schedules_unchanged(self):
        """N-FIX-1 must be an env-only change -- cron schedules and the
        A/B business-logic Python block are byte-identical to before."""
        spec = _load('notifications.yml')
        triggers = spec.get('on', spec.get(True))
        crons = [entry['cron'] for entry in triggers['schedule']]
        self.assertEqual(len(crons), 4)
        for original in ('30 0 * * *', '30 11 * * *', '30 12 * * *', '7,22,37,52 * * * *'):
            self.assertIn(original, crons)

        run_cron_env = _env_of(spec['jobs']['run-cron'])
        self.assertIn('NOTIFICATION_SLOT', run_cron_env)
        self.assertIn(
            "github.event.schedule == '30 0 * * *' && 'morning'",
            run_cron_env['NOTIFICATION_SLOT'],
        )
        run_step = next(s for s in spec['jobs']['run-cron']['steps'] if 'env' in s)
        self.assertIn('run_daily_event_job', run_step['run'])
        self.assertIn('run_panchang_dismiss_job', run_step['run'])


class AlertsYmlProductionEnvTests(unittest.TestCase):
    def test_run_alerts_cron_declares_production_environment(self):
        spec = _load('alerts.yml')
        env = _env_of(spec['jobs']['run-alerts-cron'])
        self.assertEqual(
            env.get(ENV_VAR), REQUIRED_VALUE,
            f"run-alerts-cron's own job env must declare {ENV_VAR}: {REQUIRED_VALUE} "
            "-- this is the exact N-P0-1 root cause (DatabaseSafetyError at boot)."
        )

    def test_alerts_cron_schedule_and_business_logic_unchanged(self):
        spec = _load('alerts.yml')
        triggers = spec.get('on', spec.get(True))
        crons = [entry['cron'] for entry in triggers['schedule']]
        self.assertEqual(crons, ['30 2 * * *'])
        run_step = next(s for s in spec['jobs']['run-alerts-cron']['steps'] if 'env' in s)
        self.assertIn('run_daily_alerts_job', run_step['run'])


class SubscriptionStateSyncYmlProductionEnvTests(unittest.TestCase):
    def test_sync_job_declares_production_environment(self):
        spec = _load('subscription_state_sync.yml')
        env = _env_of(spec['jobs']['sync-subscription-state'])
        self.assertEqual(
            env.get(ENV_VAR), REQUIRED_VALUE,
            f"sync-subscription-state's own job env must declare {ENV_VAR}: {REQUIRED_VALUE} "
            "-- this is the exact N-P0-1 root cause (DatabaseSafetyError at boot)."
        )

    def test_sync_schedule_and_business_logic_unchanged(self):
        spec = _load('subscription_state_sync.yml')
        triggers = spec.get('on', spec.get(True))
        crons = [entry['cron'] for entry in triggers['schedule']]
        self.assertEqual(crons, ['0 3 * * *'])
        run_step = next(s for s in spec['jobs']['sync-subscription-state']['steps'] if 'env' in s)
        self.assertIn('sync_all_profiles', run_step['run'])


class CampaignCAlreadyCorrectTests(unittest.TestCase):
    """N-FIX-1's own instruction: "Also verify Campaign C remains
    correctly configured." campaign_notifications_worker.yml (the
    manual/incident-recovery fallback) was already correct before this
    fix and must remain untouched."""

    def test_campaign_notifications_worker_declares_production_environment(self):
        spec = _load('campaign_notifications_worker.yml')
        jobs = spec['jobs']
        job = jobs[next(iter(jobs))]
        env = _env_of(job)
        self.assertEqual(env.get(ENV_VAR), REQUIRED_VALUE)


if __name__ == '__main__':
    unittest.main()
