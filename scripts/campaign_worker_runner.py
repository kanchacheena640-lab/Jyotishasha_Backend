"""P3A -- production-quality, bounded, single-invocation Campaign C
worker runner. Triggered by
.github/workflows/campaign_notifications_worker.yml, now on BOTH a
periodic schedule AND workflow_dispatch (P4 -- Final Production
Activation; see that file's own comments for the exact cadence and the
kill-switch behavior of turning the schedule off).

This script contains NO worker business logic of its own -- it only:
  1. fails closed on any missing/conflicting safety gate, BEFORE ever
     importing the Flask app / touching the DB;
  2. P4: promotes any DUE SCHEDULED execution via
     notifications.campaign_scheduler.process_due_scheduled_campaigns()
     -- the existing, already-tested N5 module that was built but never
     wired to a trigger (see its own module docstring). This call sits
     BEHIND the exact same production gates as sending itself (below),
     so the kill switch (ADMIN_CAMPAIGN_SEND_ENABLED=false) stops
     schedule promotion too, not only delivery -- a due campaign simply
     waits, never silently freezes targets while sending is disabled.
     Never calls Transport.send() itself (N5's own frozen contract) --
     it only ever decides EXPIRED/BLOCKED/PAUSED/FROZEN for a due row;
     a newly-FROZEN execution is then picked up by step 3 below, in
     this SAME invocation, exactly like a Send Now-frozen one already
     was.
  3. discovers eligible execution ids via
     notifications.campaign_worker.discover_processable_executions()
     (the one small, reusable, read-only helper P3A added there);
  4. calls notifications.campaign_worker.process_execution() for each,
     unchanged, exactly as every existing caller (tests, the P1/P2
     controlled-test script) already does.

Bounded by design -- never an unbounded while-true daemon:
  --max-executions   (default 20): at most this many executions claimed
                      in this one invocation; a larger backlog is left
                      for the NEXT invocation, never drained in one go.
  --batch-limit       (default 100, matches the existing frozen
                      TRANSPORT_BATCH_LIMIT/process_execution() default):
                      at most this many deliveries attempted per
                      execution per invocation.
  --max-runtime-seconds (default 240): once this wall-clock budget is
                      exhausted, the runner finishes the execution
                      currently in progress and then stops claiming
                      NEW executions -- remaining backlog is deferred to
                      the next invocation, never abandoned mid-delivery.

Exit code contract: 0 only for a clean bounded run (including a run
where individual deliveries ended FAILED_RETRYABLE/FAILED_PERMANENT/
UNKNOWN -- those are normal, expected transport outcomes, not runner
failures). Non-zero for any configuration/safety-gate failure, BEFORE
any execution is claimed -- GitHub Actions surfaces this as a failed run.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _env_true(name):
    return os.environ.get(name, '').strip().lower() == 'true'


def _fail(message):
    print(f'BLOCKED -- {message}', file=sys.stderr)
    sys.exit(1)


def _preflight_gate_check():
    """Runs BEFORE `from app import app` -- a config-only decision, no
    DB, no Firebase, no risk of claiming anything. Mirrors
    scripts/p1_run_controlled_test_send.py's own established pattern of
    checking loudly before touching anything, extended here with the
    P3A-required "controlled-test mode must be OFF" assertion."""
    # P3A Section 5 -- explicit, hard requirement: a production run must
    # NEVER also have controlled-test mode enabled. Conflicting
    # configuration is never silently ignored/prioritized -- it fails
    # the whole run closed before a single execution is touched.
    test_mode_vars = ('ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED', 'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID')
    present = [name for name in test_mode_vars if os.environ.get(name)]
    if present:
        _fail(
            'controlled-test mode variable(s) are set in a production worker invocation: '
            + ', '.join(present) + '. A production run and a controlled-test run must never '
            'overlap in the same process. Unset them before running this script for production.'
        )

    if os.environ.get('DEPLOYMENT_ENVIRONMENT', '').strip().lower() != 'production':
        _fail("DEPLOYMENT_ENVIRONMENT must be exactly 'production' for this runner.")
    if not _env_true('ADMIN_CAMPAIGN_SEND_ENABLED'):
        _fail("ADMIN_CAMPAIGN_SEND_ENABLED must be exactly 'true'.")
    if not _env_true('ADMIN_CAMPAIGN_WORKER_AUTHORIZED'):
        _fail("ADMIN_CAMPAIGN_WORKER_AUTHORIZED must be exactly 'true'.")
    if not os.environ.get('FCM_SERVICE_ACCOUNT_JSON'):
        _fail('FCM_SERVICE_ACCOUNT_JSON is not set.')
    if not os.environ.get('DATABASE_URL'):
        _fail('DATABASE_URL is not set.')


def _verify_production_transport(select_transport, FirebaseTransport):
    """Section 6 -- proves the resolved transport is EXACTLY
    FirebaseTransport (not NoSendTransport, not ControlledTestTransport,
    not FakeTransport, not any future subclass masquerading as one) --
    `type(...) is ...`, not isinstance(), so a wrapper that happens to
    hold a real FirebaseTransport inside it (ControlledTestTransport)
    still correctly fails this check. Never weakens select_transport()
    itself -- this only inspects what it already, independently decided."""
    transport = select_transport()
    if type(transport) is not FirebaseTransport:
        _fail(
            f'select_transport() resolved to {type(transport).__name__}, not FirebaseTransport. '
            'This almost certainly means a required production gate is missing or misconfigured. '
            'Refusing to claim any execution.'
        )
    return transport


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='P3A bounded Campaign C worker runner (workflow_dispatch only).')
    parser.add_argument('--max-executions', type=int, default=20,
                         help='Maximum number of executions claimed in this invocation (default 20).')
    parser.add_argument('--batch-limit', type=int, default=100,
                         help='Maximum deliveries attempted per execution per invocation (default 100, matches TRANSPORT_BATCH_LIMIT).')
    parser.add_argument('--max-runtime-seconds', type=int, default=240,
                         help='Wall-clock budget; once exhausted, no NEW execution is claimed (default 240s).')
    return parser.parse_args(argv)


def run(args):
    """The whole runnable body, factored out of main() so tests can call
    it directly (with env vars patched and firebase_admin.messaging.send
    mocked) without spawning a real subprocess. Identical behavior to
    running this script from the command line. Returns the process exit
    code; never itself calls sys.exit (only `_fail()` does, for the
    preflight/transport checks that must abort immediately)."""
    _preflight_gate_check()

    print('[worker] Preflight gates OK: DEPLOYMENT_ENVIRONMENT=production, '
          'ADMIN_CAMPAIGN_SEND_ENABLED=true, ADMIN_CAMPAIGN_WORKER_AUTHORIZED=true, '
          'FCM_SERVICE_ACCOUNT_JSON=<set>, DATABASE_URL=<set>, controlled-test mode=OFF')

    from app import app  # noqa: E402 -- triggers db_safety via factory.create_app()
    from extensions import db
    from notifications.campaign_transport import select_transport
    from notifications.firebase_transport import FirebaseTransport
    from notifications import campaign_worker as worker
    from notifications.campaign_scheduler import process_due_scheduled_campaigns
    from notifications.campaign_execution_models import NotificationCampaignExecution

    with app.app_context():
        # Re-verified AFTER app import too -- db_safety.py's own decision
        # (printed by create_app()) is the authoritative "is this really
        # production" signal; this transport check is this script's own,
        # independent, additional proof specifically that FirebaseTransport
        # -- not merely "some non-NoSend transport" -- is what will be used.
        _verify_production_transport(select_transport, FirebaseTransport)

        # P4 -- promote any DUE SCHEDULED execution to FROZEN/PAUSED/
        # BLOCKED/EXPIRED before discovering processable work, so a
        # newly-FROZEN one is processed in this SAME invocation. See the
        # module docstring above for why this sits behind the identical
        # gates as sending.
        schedule_summary = process_due_scheduled_campaigns(batch_limit=args.max_executions)
        if schedule_summary['claimed']:
            print(f"[worker] Scheduler: promoted {schedule_summary['claimed']} due SCHEDULED execution(s): "
                  f"{schedule_summary['results']}")
        else:
            print('[worker] Scheduler: no due SCHEDULED executions.')

        execution_ids = worker.discover_processable_executions(limit=args.max_executions)
        print(f'[worker] Discovered {len(execution_ids)} processable execution(s) '
              f'(states={worker.WORKER_PROCESSABLE_STATES}, limit={args.max_executions}).')

        started_at = time.monotonic()
        summary = []
        for execution_id in execution_ids:
            elapsed = time.monotonic() - started_at
            if elapsed >= args.max_runtime_seconds:
                print(f'[worker] Runtime budget ({args.max_runtime_seconds}s) exhausted -- '
                      f'{len(execution_ids) - len(summary)} remaining execution(s) deferred to the next invocation.')
                break

            # Section 7 -- re-validate the send-enabled flag AND the
            # resolved transport type immediately before EACH execution,
            # not just once at process start. An operator's config change
            # mid-run (e.g. flipping ADMIN_CAMPAIGN_SEND_ENABLED=false in
            # GitHub's secret store) cannot alter THIS already-running
            # process's own os.environ -- that is a real, documented
            # residual limit (see this script's own module docstring and
            # the P3A report's own "Kill-switch behavior" section) -- but
            # this re-check still closes any other way the same process
            # could end up in an unsafe state between executions, and
            # keeps the safety invariant explicit and re-asserted rather
            # than assumed from the top of the run.
            if not _env_true('ADMIN_CAMPAIGN_SEND_ENABLED'):
                print('[worker] ADMIN_CAMPAIGN_SEND_ENABLED no longer true -- stopping before claiming further work.')
                break
            transport = _verify_production_transport(select_transport, FirebaseTransport)

            execution = db.session.get(NotificationCampaignExecution, execution_id)
            campaign_id = execution.campaign_id if execution else None
            state_before = execution.state if execution else None
            print(f'[worker] Processing execution_id={execution_id} campaign_id={campaign_id} state={state_before}')

            result = worker.process_execution(execution_id, transport, batch_limit=args.batch_limit)
            print(f'[worker]   claimed={result["claimed"]} attempted={result["attempted"]} '
                  f'suppressed={result["suppressed"]} reaped={result["reaped"]} finalized={result["finalized"]}')
            summary.append({'execution_id': execution_id, **result})

        print(f'[worker] Completed. {len(summary)} execution(s) processed in this invocation.')

    print('[worker] Worker run finished normally.')
    return 0


def main():
    sys.exit(run(parse_args()))


if __name__ == '__main__':
    main()
