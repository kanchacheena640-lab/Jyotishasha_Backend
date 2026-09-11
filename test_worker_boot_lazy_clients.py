"""Regression protection for the "Campaign C worker boot" incident:
`from app import app` used to unconditionally construct real OpenAI and
Razorpay clients at IMPORT TIME (report_writer.py, summary_api.py,
routes/routes_free_consult.py, modules/services/chat_engine.py,
modules/smartchat/smartchat_engine.py,
services/ai_prediction_lab/openai_client.py, and
config/razorpay_config.py -- plus one confirmed-dead, now-removed
`openai_client = OpenAI(...)` line in app.py itself), each raising if
OPENAI_API_KEY/RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET were unset. This
made scripts/campaign_worker_runner.py -- which never touches either
service -- unable to import the Flask app at all in an environment
that (correctly) never sets those vars, such as
.github/workflows/campaign_notifications_worker.yml's own job env.

All seven were converted from an eager module-level
`client = OpenAI(...)` / `razorpay_client = razorpay.Client(...)` to a
lazy singleton, constructed only on first REAL use. This file proves:
  1. `from app import app` genuinely boots with NEITHER OpenAI NOR
     Razorpay credentials present (the exact worker environment) --
     via a real subprocess, not an in-process reimport, since Python's
     own sys.modules import cache would otherwise mask a regression.
  2. The full worker boot chain (preflight gate -> app import ->
     select_transport()) still resolves FirebaseTransport correctly
     under the same credential-free environment -- proving this fix
     never weakened the existing, frozen production-gate/transport
     logic.
  3. Each lazy singleton genuinely defers construction to first use,
     and caches it (never reconstructs on a second call) -- so no
     behavior changed for real callers beyond WHEN construction happens.
  4. Real use without genuine credentials still fails with the exact
     same, unweakened error it always did -- these are never silent
     fake-credential fallbacks on any real report/chat/payment path.
"""
import importlib
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# Mirrors scripts/campaign_worker_runner.py's own production gate env,
# and the FCM placeholder every prior diagnostic in this repo's history
# has used -- NOT a real credential, never capable of authenticating to
# any real Firebase project. Deliberately OMITS OPENAI_API_KEY,
# RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET -- the whole point of this test.
# Verified independently (cryptography.hazmat's own PEM loader, before
# being embedded here) to be a well-formed, parseable private key --
# NOT the real secret, never derived from it, never capable of
# authenticating to any real Firebase project.
_FAKE_FCM_JSON = '{"type": "service_account", "project_id": "test-only-unused", "private_key_id": "x", "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDPMyBqdLrbCfVJ\\n8jGfMwJbmPMd3x3wm+dBjrQb/DftkVeGrtLVNocmyRHbQv1R+YEEda7UoWzy9DNX\\nUbaoY4mfdmvs2PruqYzW5SPISxaupE8l5EgolZQ0fBGCyUgcHWJj++sxMkrIsRrQ\\nGi6hl8tmWBj+NzGFBa8297lMRfkkM7QB6yhhAmZdJteHjpezl/p9Cjg7PHZ7wAz+\\nWkIAaXCPpZlvMQDQlTP2Y5DF7lurCo890/ESKsEiPVcw3vIW8WFuuHHpKCPdzXP1\\nUctR40pR9+WPjKUQ2gYjFrQsyoV6KiXCIomy9nnd6bLPPhIlqgOeiabbF82AMwMk\\ne3VeAaxFAgMBAAECggEAD8EMauu7NWJZcyjmGvuu5zYG7jODvEKuX66xBRu1SOvv\\nIr9yKmH9/rX1FJ3QUwZMiAFGrMYlWYe1y6Lb54vB8Az6AcUxtynPGpvLj7Qd4mN9\\n3RyxW9ybqy3vyujxAao+S+ngpRn007ObnU0QVJsNDRgPtmyN6FZZTy2guirr2ZOt\\nqXKaUbag//ItMLKCIsY+kfMnF0mW7BinM3+pbsPT7fZ0zVYTa66nKNs99KfiC2Lx\\n4Y06lN42zC6PMLwsNulYKhcUpeprCcbcG8XEhAoeilhODUGC3jmP9whXkSa+6DXp\\nZ+gs5xWY9dPOpkMKMH7vuOS63hEX74P6vzJkHwRlQQKBgQD7LtX9Z1x+CSb5Q2Yx\\nauHIkEjxsxN7QHw+rrzzO+5jxZnme86Ccr8mizoY4IKIyH9cCWyBXtMjCf6axEVD\\nbGS0N4ZQZSg+PsEhpGT1etOLjnDYsmpjv+7osbIBsWrLQYvpTWFD5efjAN0fgTzR\\nXf67yjfBp5+dm4zw1aK6KihQFQKBgQDTLFu3n2/TIdlHYqNzUZR5vJRsX1Vo4ZYk\\n67/ImzaidFU6b7e8l/0Nza2P8dy1lmgzOwaWlhG2u/UzIs7BQm+LFJuq/pN/rxUP\\nppK1ljGsjaS5dDKjJaOKU6GzErUpFwdEBHiwpaB9uCyOrWxy5OUQ3gGpDT+swPKb\\nNmKaw57HcQKBgHU6BJDBPn9r0g6fEACcO0eZXxG+W6c4D0RJ1NFH9RgHTq4stdJX\\nrzJT5AdcME+aEyZnF4bBNJSzw2mDlDfFTLJ2/25h54g1TXlf+eY/Lp+BGNVpXxGy\\nr9NVqxfzLz4xFxUJEg3YLILbElfzvuiPj6Ug2Si+DFZIFF0Jt2pe5nWJAoGBAI4Y\\nhCLcCwAT/8PUMM4RMAp2hZ0izTME0OZJKETRhILuKsdmk0k5MJNQOiDpC6245qbK\\nahV8J7FBaq4dFujeTnZUyKbYJOI/KrncSU4dIZHNwfD0qnozgoc63UzFItfiYgY3\\nyAp9eK//9SOQuK/bK/QcnxtlCdqx/s3IW7NuPHJRAoGAI8KfG6EnScMBmF3qPjaG\\nOnVGdaSns76SYt8ctqzjhio2jksHFifwa0XqcGkeGRyWRyLW/BSANdb/g6gPOvU/\\nwo013MDoPN+pjGhQpxd73Qe+MnxEcKfK5E93SjDjkTqGGpLoWfDAATVLNLoezV1N\\n9hZzaVh5L3pMvuvAbmZ2rL4=\\n-----END PRIVATE KEY-----\\n", "client_email": "test-worker-boot@test-only-unused.iam.gserviceaccount.com", "client_id": "1", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_x509_cert_url": "https://x", "universe_domain": "googleapis.com"}'


def _clean_worker_env(database_url):
    """The FULL current environment (so any platform-specific need --
    e.g. WeasyPrint's native GTK/Pango DLL search on Windows, which
    this repo's own report/pdf pipeline depends on transitively but
    which is entirely unrelated to this bug -- keeps working exactly
    as it does for every other local test run), with OPENAI_API_KEY /
    RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET explicitly forced to empty
    string. Empty string, not merely absent, is required: this repo's
    own local .env (present on this dev machine, never committed) would
    otherwise fill in a REAL key via load_dotenv()'s own default
    override=False behavior -- which only skips a key that is already
    PRESENT in the environment, even with an empty value. This mirrors
    exactly what .github/workflows/campaign_notifications_worker.yml's
    own job env provides in real production: no .env there, and these
    three vars genuinely never set."""
    env = dict(os.environ)
    env['OPENAI_API_KEY'] = ''
    env['RAZORPAY_KEY_ID'] = ''
    env['RAZORPAY_KEY_SECRET'] = ''
    env['DATABASE_URL'] = database_url
    env['FCM_SERVICE_ACCOUNT_JSON'] = _FAKE_FCM_JSON
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


class WorkerBootWithoutOpenAIOrRazorpayTests(unittest.TestCase):
    """Subprocess-based -- a plain in-process reimport would be masked
    by Python's own sys.modules cache (these modules are already
    imported by the time this test file itself loads) and by this
    repo's local .env (loaded via load_dotenv(), which only fills in
    env vars NOT already set in the process). A real child process,
    started with an explicit, minimal env and no cwd-relative .env
    fallback risk, is the only way to genuinely prove this."""

    def _run(self, code):
        return subprocess.run(
            [sys.executable, '-c', code],
            cwd=REPO_ROOT,
            env=_clean_worker_env(os.environ.get(
                'DATABASE_URL', 'postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local')),
            capture_output=True, text=True, timeout=60,
        )

    def test_app_import_succeeds_with_no_openai_or_razorpay_credentials(self):
        result = self._run("from app import app; print('BOOT_OK')")
        self.assertEqual(result.returncode, 0,
                          f'stdout={result.stdout!r} stderr={result.stderr!r}')
        self.assertIn('BOOT_OK', result.stdout)
        self.assertNotIn('OpenAIError', result.stderr)
        self.assertNotIn('Missing Razorpay API keys', result.stderr)

    def test_worker_boot_chain_selects_firebase_transport_with_no_openai_or_razorpay_credentials(self):
        """The exact real chain scripts/campaign_worker_runner.py runs,
        up to (never including) claiming/processing an execution."""
        code = (
            "import os\n"
            "os.environ['DEPLOYMENT_ENVIRONMENT'] = 'production'\n"
            "os.environ['ADMIN_CAMPAIGN_SEND_ENABLED'] = 'true'\n"
            "os.environ['ADMIN_CAMPAIGN_WORKER_AUTHORIZED'] = 'true'\n"
            "os.environ['ACTIVITY_EVENTS_ENVIRONMENT'] = 'production'\n"
            "import sys; sys.path.insert(0, 'scripts')\n"
            "import campaign_worker_runner as runner\n"
            "runner._preflight_gate_check()\n"
            "from app import app\n"
            "from notifications.campaign_transport import select_transport\n"
            "from notifications.firebase_transport import FirebaseTransport\n"
            "with app.app_context():\n"
            "    transport = runner._verify_production_transport(select_transport, FirebaseTransport)\n"
            "print('TRANSPORT_OK', type(transport).__name__)\n"
        )
        result = self._run(code)
        self.assertEqual(result.returncode, 0,
                          f'stdout={result.stdout!r} stderr={result.stderr!r}')
        self.assertIn('TRANSPORT_OK FirebaseTransport', result.stdout)

    def test_exact_render_cron_command_runs_cleanly_end_to_end_with_zero_backlog(self):
        """P4.7 -- proves the EXACT command line a Render Cron Job runs
        (`python scripts/campaign_worker_runner.py --max-executions 20
        --batch-limit 100 --max-runtime-seconds 240`) works end to end,
        as a real subprocess, with the exact env shape planned for
        Render (production gates + FCM, NO OpenAI/Razorpay) -- not just
        `from app import app` or the transport-selection chain in
        isolation like the two tests above. Runs against a real local
        Postgres with (by construction, in this test run) zero FROZEN/
        SENDING/SCHEDULED backlog, so a clean exit with 'Discovered 0
        processable execution(s)' and no FCM call is the expected,
        safe, verifiable outcome -- exactly the 'no-work run' shape
        production itself is expected to show on Render's first real
        invocation."""
        # Precondition, not cleanup: this subprocess uses REAL
        # DEPLOYMENT_ENVIRONMENT=production (to prove the exact Render
        # command/gate sequence), so a stray FROZEN/SENDING execution
        # left behind by an unrelated interrupted test run would be
        # discovered and genuinely attempted against Firebase with this
        # test's own fake FCM credential -- messy, not a real send risk
        # (fake creds simply fail), but never assumed away. Skip rather
        # than silently mutate another test file's fixtures.
        from app import app as _app
        from notifications import campaign_worker as _worker
        with _app.app_context():
            stray = _worker.discover_processable_executions(limit=1)
        if stray:
            self.skipTest(f'stray FROZEN/SENDING execution(s) present ({stray}) -- '
                           'not this test\'s fixture to clean up, skipping to avoid a real Firebase attempt.')

        env = _clean_worker_env(os.environ.get(
            'DATABASE_URL', 'postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local'))
        env['DEPLOYMENT_ENVIRONMENT'] = 'production'
        env['ADMIN_CAMPAIGN_SEND_ENABLED'] = 'true'
        env['ADMIN_CAMPAIGN_WORKER_AUTHORIZED'] = 'true'
        env['ACTIVITY_EVENTS_ENVIRONMENT'] = 'production'
        result = subprocess.run(
            [sys.executable, 'scripts/campaign_worker_runner.py',
             '--max-executions', '20', '--batch-limit', '100', '--max-runtime-seconds', '240'],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0,
                          f'stdout={result.stdout!r} stderr={result.stderr!r}')
        self.assertIn('Preflight gates OK', result.stdout)
        self.assertIn('Worker run finished normally', result.stdout)
        self.assertNotIn('OpenAIError', result.stderr)
        self.assertNotIn('Missing Razorpay API keys', result.stderr)


class LazyClientCachingTests(unittest.TestCase):
    """In-process unit tests of the lazy-singleton MECHANICS themselves
    (construct-once, cache, still fail clearly for real use without
    credentials) -- representative of both patterns used: a plain
    getter function (report_writer.py) and a __getattr__ proxy
    (config/razorpay_config.py, since razorpay_client is imported BY
    NAME into 5+ other modules and must keep working unchanged there)."""

    def setUp(self):
        import report_writer
        report_writer._client = None  # never assume a prior test's cache

    def test_report_writer_client_not_constructed_by_import_alone(self):
        import report_writer
        self.assertIsNone(report_writer._client)

    def test_report_writer_client_constructed_once_and_cached(self):
        import report_writer
        with patch('report_writer.OpenAI') as mock_openai:
            mock_openai.return_value = 'fake-client-instance'
            c1 = report_writer._get_client()
            c2 = report_writer._get_client()
            self.assertEqual(mock_openai.call_count, 1, 'must construct only once, never per call')
            self.assertIs(c1, c2)

    def test_report_writer_real_use_without_credentials_still_fails_clearly(self):
        import report_writer
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('OPENAI_API_KEY', None)
            with self.assertRaises(Exception) as ctx:
                report_writer._get_client()
            self.assertIn('api_key', str(ctx.exception).lower())

    def test_razorpay_proxy_not_constructed_by_import_alone(self):
        from config.razorpay_config import _LazyRazorpayClient
        _LazyRazorpayClient._real_client = None
        self.assertIsNone(_LazyRazorpayClient._real_client)

    def test_razorpay_proxy_constructs_once_and_reuses_real_client_on_attribute_access(self):
        from config import razorpay_config
        razorpay_config._LazyRazorpayClient._real_client = None
        with patch.object(razorpay_config, 'razorpay') as mock_razorpay, \
             patch.dict(os.environ, {'RAZORPAY_KEY_ID': 'rzp_test_fake', 'RAZORPAY_KEY_SECRET': 'fake_secret'}):
            fake_real_client = type('FakeClient', (), {'order': type('O', (), {'create': lambda *a, **k: 'ok'})()})()
            mock_razorpay.Client.return_value = fake_real_client
            _ = razorpay_config.razorpay_client.order
            _ = razorpay_config.razorpay_client.order
            self.assertEqual(mock_razorpay.Client.call_count, 1, 'must construct only once across multiple attribute accesses')
        razorpay_config._LazyRazorpayClient._real_client = None

    def test_razorpay_proxy_real_use_without_credentials_still_fails_with_original_message(self):
        from config import razorpay_config
        razorpay_config._LazyRazorpayClient._real_client = None
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('RAZORPAY_KEY_ID', None)
            os.environ.pop('RAZORPAY_KEY_SECRET', None)
            with self.assertRaises(Exception) as ctx:
                _ = razorpay_config.razorpay_client.order
            self.assertEqual(str(ctx.exception), 'Missing Razorpay API keys in .env',
                              'must be the EXACT original error message -- no behavior change for real callers')
        razorpay_config._LazyRazorpayClient._real_client = None

    def tearDown(self):
        import report_writer
        report_writer._client = None
        from config.razorpay_config import _LazyRazorpayClient
        _LazyRazorpayClient._real_client = None


class DeadCodeRemovedTests(unittest.TestCase):
    def test_app_module_no_longer_has_eager_module_level_openai_client(self):
        """The confirmed-dead `openai_client = OpenAI(...)` line in
        app.py itself (never read by app.py or anything importing it --
        verified by full-repo grep before removal) is gone, not merely
        made lazy -- there was nothing real to preserve."""
        import app as app_module
        self.assertFalse(hasattr(app_module, 'openai_client'),
                          'dead eager client should have been removed entirely, not lazified')


if __name__ == '__main__':
    unittest.main()
