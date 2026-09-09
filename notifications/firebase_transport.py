"""P1 -- real Firebase Cloud Messaging transport for Campaign C.

Deliberately its OWN module, separate from campaign_transport.py: that
module's own docstring states "imports firebase_admin nowhere" as an
explicit invariant (so importing it -- which campaign_worker.py and every
test in this codebase already does unconditionally -- can never itself
require Firebase to be configured). This file is imported lazily, ONLY
from inside campaign_transport.py::select_transport()'s two gated
branches, never at any other module's top level.

REUSES the existing, already-proven Firebase infrastructure rather than
building a second one:
  - The SAME firebase_admin App extensions.py::init_firebase() already
    initializes once at app startup (idempotent via `if not
    firebase_admin._apps`) from the SAME FCM_SERVICE_ACCOUNT_JSON this
    module's own select_transport() gate already checks for. This file
    never calls firebase_admin.initialize_app() itself.
  - The SAME messaging.send() surface notifications/notification_fcm.py
    (A/B's own legacy HTTP-v1 sender) reaches by hand-rolled HTTP call --
    here reached instead through firebase_admin's own official Python
    SDK, which exposes it directly (Admin SDK 7.1.0 confirmed installed).
  - The SAME invalid-token-clears-AppUser.fcm_token policy
    notification_fcm.py already established for A/B, reused here for
    Campaign C -- see _handle_invalid_token()'s own docstring for why
    the scoping is even tighter here (id AND token match, not token
    alone).

Token snapshot policy (unchanged from N4): this module NEVER reads a
token from anywhere but the `Target` the worker already resolved
in-memory immediately before this one call. No query against
User/AppUser for resolution happens here -- SavedAudience membership and
token lookup are exclusively the worker's job (campaign_worker.py's own
`tokens = dict(db.session.query(AppUser.id, AppUser.fcm_token)...)`
call, unchanged). This file only ever WRITES a token field (nulling an
invalidated one), never resolves one to send to.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from notifications.campaign_transport import (
    RateLimiter, Target, RenderedMessage, TransportResult,
    OUTCOME_ACCEPTED, OUTCOME_FAILED_RETRYABLE, OUTCOME_FAILED_PERMANENT, OUTCOME_UNKNOWN,
    TOTAL_TIMEOUT_SECONDS,
)

# One shared limiter per process -- campaign_worker.py's own loop is
# strictly serial (never concurrent, see that module's own _claim_batch()/
# process_execution() -- one delivery attempted at a time), so a single
# module-level instance is safe with no locking of its own.
_rate_limiter = RateLimiter()

# One shared single-thread pool used ONLY to enforce a wall-clock
# deadline the firebase_admin SDK's own public API does not expose (see
# module docstring "TIMEOUT ENFORCEMENT" below) -- never used for
# concurrency (max_workers=1 keeps this transport's own calls exactly as
# serial as the worker that calls it; concurrency, if ever raised above
# 1, remains campaign_worker.py's decision to make, bounded there by
# MAX_CONCURRENCY, never by this transport silently parallelizing on its
# own).
_send_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fcm-send')


def _build_fcm_data(message: RenderedMessage) -> dict:
    """FCM's own wire contract requires every `data` value to be a
    string (unlike this codebase's internal RenderedMessage.data, whose
    `action_parameters` is a real dict) -- flattened here, at the
    transport boundary, exactly once. Every KEY NAME is reused verbatim
    from campaign_worker.py::_build_message() (contract_version, source,
    campaign_id, execution_id, action_registry_version, action_type,
    action_target, action_parameters) -- never renamed, since
    lib/core/notifications/notification_dispatcher.dart's `parse()`
    (N6, frozen) already reads exactly those key names for a real push
    tap: `source=='ADMIN_CAMPAIGN'` gates Campaign C parsing, then
    `campaign_id`/`execution_id`/`action_type`/`action_target` are read
    as flat strings -- APP_DEEP_LINK and NONE campaigns are fully
    compatible with this flattening as-is (their target/routing needs
    no nested structure). WEB_URL is not: its url lives inside
    action_parameters, which Dart's `parse()` only ever treats as a Map
    (real FCM data can never actually deliver one -- see this module's
    own P1 report, "Flutter compatibility" section, for the verified gap
    and why it is intentionally NOT patched here). action_parameters is
    still sent, JSON-encoded, so a future minimal `jsonDecode` addition
    on the Dart side is all a WEB_URL push tap would need."""
    return {
        'contract_version': '1',
        'source': 'ADMIN_CAMPAIGN',
        'campaign_id': str(message.data.get('campaign_id', '')),
        'execution_id': str(message.data.get('execution_id', '')),
        'action_registry_version': str(message.data.get('action_registry_version', '1')),
        'action_type': str(message.data.get('action_type') or ''),
        'action_target': str(message.data.get('action_target') or ''),
        'action_parameters': json.dumps(message.data.get('action_parameters') or {}, separators=(',', ':')),
    }


def _handle_invalid_token(target: Target) -> None:
    """Reuses notification_fcm.py's own proven policy (clear
    AppUser.fcm_token on a definitively invalid/unregistered token) --
    scoped TIGHTER than that legacy code's own `fcm_token=token` match:
    here by (AppUser.id == target.app_user_id) AND
    (AppUser.fcm_token == target.fcm_token) together, so a token this
    exact recipient has since REFRESHED (their row's fcm_token no longer
    equals target.fcm_token, the value resolved in-memory before THIS
    attempt) can never be cleared by a stale result -- the row simply
    fails to match and nothing is touched."""
    from extensions import db
    from modules.models_user import AppUser
    updated = (
        AppUser.query.filter(AppUser.id == target.app_user_id, AppUser.fcm_token == target.fcm_token)
        .update({'fcm_token': None}, synchronize_session=False)
    )
    if updated:
        db.session.commit()
    else:
        db.session.rollback()


class FirebaseTransport:
    """The one production-capable Transport implementation. Accepts only
    the already-resolved single `Target`/`RenderedMessage` the worker
    hands it -- performs no SavedAudience resolution, no User/AppUser
    query for recipient discovery, no token persistence beyond the one
    narrow invalidation case above."""
    provider = 'firebase'

    def send(self, target: Target, message: RenderedMessage) -> TransportResult:
        # Lazy import -- see module docstring: this file (and therefore
        # firebase_admin) is only ever reached once select_transport()'s
        # gates have already all passed.
        from firebase_admin import messaging, exceptions

        _rate_limiter.acquire()

        fcm_message = messaging.Message(
            token=target.fcm_token,
            notification=messaging.Notification(title=message.title, body=message.body),
            data=_build_fcm_data(message),
            android=messaging.AndroidConfig(priority='high'),
        )

        # TIMEOUT ENFORCEMENT: firebase_admin 7.1.0's public
        # messaging.send(message, dry_run=False, app=None) signature
        # exposes no connect/total timeout parameter at all (verified
        # directly via inspect.signature -- not assumed). Faking
        # CONNECT_TIMEOUT_SECONDS specifically is therefore not possible
        # from this layer; TOTAL_TIMEOUT_SECONDS is enforced the safest
        # way actually available -- a caller-side wall-clock deadline via
        # a single-worker thread pool's own .result(timeout=...), which
        # cannot know whether the underlying HTTP call actually completed
        # server-side. A timeout here is therefore classified UNKNOWN
        # (uncertain submission), never assumed safe to retry.
        try:
            future = _send_pool.submit(messaging.send, fcm_message)
            message_id = future.result(timeout=TOTAL_TIMEOUT_SECONDS)
            return TransportResult(outcome=OUTCOME_ACCEPTED, provider=self.provider, provider_message_id=message_id)

        except FutureTimeoutError:
            return TransportResult(
                outcome=OUTCOME_UNKNOWN, provider=self.provider,
                error_code='timeout', error_class='unknown',
            )

        except messaging.UnregisteredError as exc:
            _handle_invalid_token(target)
            return TransportResult(
                outcome=OUTCOME_FAILED_PERMANENT, provider=self.provider,
                error_code='unregistered_token', error_class='invalid_token', invalid_token=True,
            )

        except messaging.SenderIdMismatchError as exc:
            _handle_invalid_token(target)
            return TransportResult(
                outcome=OUTCOME_FAILED_PERMANENT, provider=self.provider,
                error_code='sender_id_mismatch', error_class='invalid_token', invalid_token=True,
            )

        except messaging.ThirdPartyAuthError as exc:
            # Not proof this recipient's own token is garbage (an APNs/
            # third-party auth concept) -- permanent for this attempt,
            # but the token itself is never cleared on this classification.
            return TransportResult(
                outcome=OUTCOME_FAILED_PERMANENT, provider=self.provider,
                error_code='third_party_auth_error', error_class='provider_config',
            )

        except (messaging.QuotaExceededError, exceptions.ResourceExhaustedError) as exc:
            return TransportResult(
                outcome=OUTCOME_FAILED_RETRYABLE, provider=self.provider,
                error_code='quota_exceeded', error_class='rate_limit', retryable=True,
            )

        except (exceptions.UnavailableError, exceptions.InternalError,
                exceptions.AbortedError, exceptions.DeadlineExceededError,
                exceptions.ConflictError) as exc:
            return TransportResult(
                outcome=OUTCOME_FAILED_RETRYABLE, provider=self.provider,
                error_code=type(exc).__name__, error_class='transient_provider', retryable=True,
            )

        except (exceptions.UnauthenticatedError, exceptions.PermissionDeniedError) as exc:
            # A definitive synchronous rejection (never sent to FCM's own
            # per-token logic at all) caused by OUR OWN credential/project
            # configuration, not this recipient -- recoverable once fixed,
            # so retryable, never UNKNOWN (there is no ambiguity about
            # whether this attempt reached the device: it did not).
            return TransportResult(
                outcome=OUTCOME_FAILED_RETRYABLE, provider=self.provider,
                error_code='credential_or_config_error', error_class='provider_config', retryable=True,
            )

        except exceptions.InvalidArgumentError as exc:
            # Malformed token/request shape -- permanent for this attempt,
            # but NOT auto-classified as an invalid token: this can also
            # mean OUR OWN payload was malformed, which is never proof the
            # recipient's token itself is bad.
            return TransportResult(
                outcome=OUTCOME_FAILED_PERMANENT, provider=self.provider,
                error_code='invalid_argument', error_class='request_error',
            )

        except exceptions.FirebaseError as exc:
            # Any other, unrecognized FirebaseError subtype fails closed
            # to UNKNOWN -- never guessed as safe to retry.
            return TransportResult(
                outcome=OUTCOME_UNKNOWN, provider=self.provider,
                error_code=type(exc).__name__, error_class='unknown',
            )

        except Exception:
            # Anything else (network-level exception below the SDK's own
            # exception hierarchy, etc.) -- an unexpected exception after
            # an uncertain submission. Never assumed safe to retry.
            return TransportResult(
                outcome=OUTCOME_UNKNOWN, provider=self.provider,
                error_code='transport_exception', error_class='unknown',
            )


class ControlledTestTransport:
    """P1 controlled-test wrapper (see campaign_transport.py::
    select_transport()'s own docstring for the gate contract). Wraps a
    real FirebaseTransport -- the SAME send path production will
    eventually use -- and refuses (never sends, never touches Firebase)
    any target outside the one explicitly allowlisted app_user_id. This
    is the ONLY logic this class adds; it invents no second sender."""
    provider = 'firebase_controlled_test'

    def __init__(self, inner: FirebaseTransport, *, allowlisted_app_user_id: int):
        self._inner = inner
        self._allowlisted_app_user_id = allowlisted_app_user_id

    def send(self, target: Target, message: RenderedMessage) -> TransportResult:
        campaign_id = message.data.get('campaign_id')
        execution_id = message.data.get('execution_id')
        if target.app_user_id != self._allowlisted_app_user_id:
            print(
                f'[CONTROLLED TEST] REFUSED -- target app_user_id={target.app_user_id} is not the '
                f'allowlisted test recipient ({self._allowlisted_app_user_id}); campaign_id={campaign_id} '
                f'execution_id={execution_id}. No Firebase call made.'
            )
            return TransportResult(
                outcome=OUTCOME_FAILED_PERMANENT, provider=self.provider,
                error_code='controlled_test_recipient_not_allowlisted', error_class='safety_guard',
            )
        print(
            f'[CONTROLLED TEST] Sending real FCM push -- campaign_id={campaign_id} '
            f'execution_id={execution_id} app_user_id={target.app_user_id} (token withheld from logs).'
        )
        result = self._inner.send(target, message)
        print(f'[CONTROLLED TEST] Result -- outcome={result.outcome} error_code={result.error_code}')
        return result
