"""P1 -- manual, operator-run controlled-test dispatch helper.

NOT auto-executed by anything in this codebase (no route, no cron, no
import side effect triggers this). The operator runs it BY HAND, after
already creating and Send-Now-ing a DRAFT campaign through the normal
Admin flow (which itself never calls transport -- see
campaign_execution_service.py). This script performs exactly the ONE
step that currently has no wired caller anywhere in this codebase: handing
a FROZEN execution to campaign_worker.process_execution() with whatever
transport notifications.campaign_transport.select_transport() decides is
safe for the CURRENT process environment.

It does not create a campaign, does not resolve an audience, does not
choose a recipient -- all of that stays the existing, unmodified N3/N4
Admin flow. This script's only job is the dispatch step.

Usage (see the P1 report's own "Exact ONE-device test procedure" section
for the full walkthrough, including which environment variables must be
set BEFORE running this):

    python scripts/p1_run_controlled_test_send.py <execution_id>

Refuses to run (loudly, before touching the DB) unless every controlled-
test gate is already satisfied in the CURRENT process environment --
never guesses, never relaxes a gate on the caller's behalf.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    if len(sys.argv) != 2:
        print('Usage: python scripts/p1_run_controlled_test_send.py <execution_id>')
        sys.exit(2)
    execution_id = sys.argv[1]

    # Fail loudly BEFORE importing the app/DB layer at all if the
    # controlled-test gates aren't visibly set -- this script must never
    # silently fall through to NoSendTransport and report a false
    # "nothing happened" success for what the operator believes is a
    # real test.
    required = [
        'ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED',
        'ADMIN_CAMPAIGN_WORKER_AUTHORIZED',
        'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID',
        'FCM_SERVICE_ACCOUNT_JSON',
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print('BLOCKED -- required controlled-test environment variable(s) not set:')
        for name in missing:
            print(f'  - {name}')
        print('Set all of them in THIS process before running this script. See the P1 report.')
        sys.exit(1)
    if os.environ.get('ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED', '').strip().lower() != 'true':
        print("BLOCKED -- ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED must be exactly 'true'.")
        sys.exit(1)

    from app import app  # noqa: E402 -- triggers db_safety via factory.create_app()
    from notifications.campaign_transport import select_transport
    from notifications import campaign_worker as worker
    from notifications.campaign_execution_models import NotificationCampaignExecution
    from extensions import db

    with app.app_context():
        execution = db.session.get(NotificationCampaignExecution, execution_id)
        if execution is None:
            print(f'BLOCKED -- no execution found for id={execution_id!r}.')
            sys.exit(1)
        if execution.state not in ('FROZEN', 'SENDING'):
            print(f'BLOCKED -- execution.state={execution.state!r}; only FROZEN/SENDING can be dispatched. '
                  'Send Now the campaign through the normal Admin flow first.')
            sys.exit(1)

        transport = select_transport()
        print(f'[CONTROLLED TEST] Using transport: {type(transport).__name__} (provider={getattr(transport, "provider", "?")})')
        if type(transport).__name__ != 'ControlledTestTransport':
            print('BLOCKED -- select_transport() did not return ControlledTestTransport for the '
                  'current environment; refusing to dispatch (this should be structurally '
                  'impossible if the gate check above passed -- stop and investigate).')
            sys.exit(1)

        result = worker.process_execution(execution_id, transport)
        print(f'[CONTROLLED TEST] process_execution result: {result}')


if __name__ == '__main__':
    main()
