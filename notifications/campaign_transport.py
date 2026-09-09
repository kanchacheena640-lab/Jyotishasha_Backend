"""N4 Admin Campaign transport abstraction (N1 Section 12/13).

send(target, payload) -> TransportResult. One bounded attempt, no
business commits, no audience queries, no Bell writes -- exactly N1's
own transport contract. This module imports firebase_admin nowhere;
NO real production-sending class exists in N4 at all (see this
module's own bottom section) -- only the interface plus two safe,
non-network implementations.

select_transport() is the ONLY place allowed to decide which
implementation is used, and it always returns NoSendTransport unless
every one of N1 Section 13's gates is independently true. Since a real
production transport class does not exist in this codebase yet, that
"every gate true" branch currently raises rather than silently
returning something unsafe -- a missing gate fails closed, and there
is nothing beyond it that could accidentally send.
"""
import os
import random
import time
from dataclasses import dataclass
from typing import Optional

OUTCOME_ACCEPTED = 'ACCEPTED'
OUTCOME_FAILED_RETRYABLE = 'FAILED_RETRYABLE'
OUTCOME_FAILED_PERMANENT = 'FAILED_PERMANENT'
OUTCOME_UNKNOWN = 'UNKNOWN'

# N1 Section 12 technical defaults. connect_timeout/total_timeout are
# documented and enforced at the worker boundary (campaign_worker.py's
# own per-attempt deadline), not claimed as a raw socket-level knob no
# transport class here actually sets -- see WORKER_ENFORCED_TIMEOUTS.
CONNECT_TIMEOUT_SECONDS = 5
TOTAL_TIMEOUT_SECONDS = 20
MAX_CONCURRENCY = 10
MAX_REQUESTS_PER_SECOND = 20
TRANSPORT_BATCH_LIMIT = 100


@dataclass(frozen=True)
class Target:
    """Never a raw FCM token snapshot from durable storage -- see
    campaign_execution_service.py's own docstring. `fcm_token` is
    resolved fresh, in-memory, immediately before this one attempt."""
    user_id: int
    app_user_id: int
    fcm_token: str


@dataclass(frozen=True)
class RenderedMessage:
    title: str
    body: str
    data: dict


@dataclass(frozen=True)
class TransportResult:
    outcome: str
    provider: str
    provider_message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_class: Optional[str] = None
    retryable: bool = False
    invalid_token: bool = False
    retry_after: Optional[float] = None


class NoSendTransport:
    """The ONLY transport local/test construction may ever produce (N1
    Section 13). Performs no network call and labels its own result as
    simulated -- never mistakeable for a real provider acceptance."""
    provider = 'nosend'

    def send(self, target: Target, message: RenderedMessage) -> TransportResult:
        return TransportResult(outcome=OUTCOME_ACCEPTED, provider=self.provider,
                               provider_message_id=f'simulated-{target.app_user_id}')


class FakeTransport:
    """Test-only transport with per-token or default canned outcomes,
    so N4 tests can exercise every classification (ACCEPTED/
    FAILED_RETRYABLE/FAILED_PERMANENT/UNKNOWN) deterministically without
    any network access. `outcomes` maps fcm_token -> TransportResult (or
    a zero-arg callable raising, to simulate a transport-layer
    exception); `default` is used for any token not explicitly listed."""
    provider = 'fake'

    def __init__(self, outcomes: Optional[dict] = None, default: Optional[TransportResult] = None):
        self.outcomes = outcomes or {}
        self.default = default or TransportResult(outcome=OUTCOME_ACCEPTED, provider=self.provider)
        self.calls = []

    def send(self, target: Target, message: RenderedMessage) -> TransportResult:
        self.calls.append(target.fcm_token)
        result = self.outcomes.get(target.fcm_token, self.default)
        if callable(result):
            return result()
        return result


class RateLimiter:
    """P1 -- the smallest robust shared limiter that keeps
    MAX_REQUESTS_PER_SECOND a real, enforced ceiling rather than a merely
    documented one, regardless of how many recipients a single
    process_execution() batch attempts serially. A plain sliding window
    over a bounded deque of recent send timestamps -- no external
    dependency, no thread pool of its own (safe to share across attempts
    within one worker process since campaign_worker.py's own loop is
    already strictly serial, never concurrent, so there is no race on
    the deque to guard against here)."""

    def __init__(self, max_per_second: int = MAX_REQUESTS_PER_SECOND):
        from collections import deque
        self.max_per_second = max_per_second
        self._sent_at = deque()

    def acquire(self, *, sleep=time.sleep, now=time.monotonic) -> None:
        cutoff = now() - 1.0
        while self._sent_at and self._sent_at[0] <= cutoff:
            self._sent_at.popleft()
        if len(self._sent_at) >= self.max_per_second:
            wait = self._sent_at[0] + 1.0 - now()
            if wait > 0:
                sleep(wait)
            cutoff = now() - 1.0
            while self._sent_at and self._sent_at[0] <= cutoff:
                self._sent_at.popleft()
        self._sent_at.append(now())


def _env_true(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() == 'true'


def select_transport(*, environment: Optional[str] = None) -> object:
    """N1 Section 13 (unchanged gates, reused by name) + P1 additions:
    real sending requires environment=production AND an explicit
    send-enable flag AND configured provider credentials AND an
    authorized worker role AND an approved campaign (the last verified
    by the caller, not here -- this function only gates the transport
    CLASS itself). Any single missing/false/misconfigured gate fails
    closed to NoSendTransport.

    ADMIN_CAMPAIGN_WORKER_AUTHORIZED (P1, new): a 4th independent gate,
    the "explicit worker/send authorization" N1 Section 13 already named
    but N4 left unimplemented (no worker process existed to authorize).
    Intended to be set ONLY on the actual dedicated worker
    process/environment -- never on a web/admin dyno that merely shares
    the same DEPLOYMENT_ENVIRONMENT/ADMIN_CAMPAIGN_SEND_ENABLED values --
    so a correctly-configured production WEB process still cannot
    activate real sending merely by also calling this function.

    Controlled test mode (P1, new): a SEPARATE, narrower path,
    deliberately independent of `environment` (never requires
    'production' -- it exists specifically to exercise the real
    FirebaseTransport from an ordinary local/dev run against one real
    device), gated by its own explicit opt-in
    (ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED) plus the SAME worker-
    authorization flag plus real credentials plus exactly one
    allowlisted recipient (ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID).
    Returns a ControlledTestTransport wrapping the real FirebaseTransport
    -- the SAME send path production will eventually use, not a second
    fake sender -- but one that refuses (FAILED_PERMANENT, never sends)
    any target whose app_user_id is not that exact allowlisted id, no
    matter what a SavedAudience/campaign resolved. This is deliberately
    NOT gated on ADMIN_CAMPAIGN_SEND_ENABLED (the broad-production flag)
    -- the two are independent switches on purpose, so flipping one can
    never silently enable the other's blast radius.

    No branch here reads anything from a request, the Admin UI, or
    campaign content -- every gate is a server-side process environment
    variable only."""
    environment = environment or os.environ.get('DEPLOYMENT_ENVIRONMENT', 'local')
    send_enabled = _env_true('ADMIN_CAMPAIGN_SEND_ENABLED')
    has_credentials = bool(os.environ.get('FCM_SERVICE_ACCOUNT_JSON'))
    worker_authorized = _env_true('ADMIN_CAMPAIGN_WORKER_AUTHORIZED')

    if environment == 'production' and send_enabled and has_credentials and worker_authorized:
        from notifications.firebase_transport import FirebaseTransport
        return FirebaseTransport()

    if _env_true('ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED') and has_credentials and worker_authorized:
        raw_id = os.environ.get('ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID', '').strip()
        if not raw_id.isdigit():
            raise RuntimeError(
                'ADMIN_CAMPAIGN_TEST_TRANSPORT_ENABLED requires a valid positive integer '
                'ADMIN_CAMPAIGN_TEST_RECIPIENT_APP_USER_ID (the exact allowlisted test AppUser.id).'
            )
        from notifications.firebase_transport import FirebaseTransport, ControlledTestTransport
        return ControlledTestTransport(FirebaseTransport(), allowlisted_app_user_id=int(raw_id))

    return NoSendTransport()


def backoff_seconds(attempt_number: int) -> float:
    """N4 locked retry contract: initial attempt (1) is immediate; up to
    3 retries follow (attempts 2, 3, 4), for 4 transport attempts total.
    N1 Section 21 explicitly establishes only a 30s-then-120s schedule
    and does not authorize a new exponential interval for a third retry,
    so the final retry (before attempt 4) reuses the last established
    120s interval rather than inventing 240s/480s/etc:

        attempt 1 -> immediate (no backoff call)
        attempt 2 -> retry 1: 30s + jitter  (backoff_seconds(1))
        attempt 3 -> retry 2: 120s + jitter (backoff_seconds(2))
        attempt 4 -> retry 3: 120s + jitter (backoff_seconds(3))

    attempt_number here is the attempt that just failed retryably (1, 2
    or 3); this returns the delay before the NEXT attempt. Bounded
    positive jitter up to 20%, per the existing N4 convention."""
    base = {1: 30.0, 2: 120.0, 3: 120.0}.get(attempt_number)
    if base is None:
        raise ValueError('backoff only defined before attempt 4 (max 4 attempts total: 1 initial + 3 retries)')
    jitter = base * random.uniform(0, 0.20)
    return base + jitter
