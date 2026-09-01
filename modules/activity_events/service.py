# modules/activity_events/service.py

"""
The one shared write path for ActivityEvent -- Phase 2 Step 2's ledger
helper. NOT wired into any producer yet (no payment/Ask Now/report/
subscription/notification code calls this in this step); it exists so
Phase 3/4 producers all go through one place instead of hand-rolling
inserts, per the frozen contract's own Phase 2 prerequisite.

Non-regression guarantee (frozen contract, S6 permanent rule):
"Event Tracking is an additive observational layer. Instrumentation
must not alter existing product/business behavior." record_event()
enforces this two ways:

1. It writes through a SEPARATE SQLAlchemy Session bound to the same
   engine as the app's own `db.session`, not the shared scoped session
   itself. This is a real isolation guarantee, not just a documented
   calling convention -- a failure or rollback in this helper's session
   cannot touch, commit, or roll back whatever the caller's own
   business transaction is doing in `db.session`, regardless of call
   order. (Best practice is still to call this only after the caller's
   own business transaction has already committed, so `occurred_at`
   reflects a fact that has actually happened -- but that is a
   timing/correctness recommendation, not what makes this safe.)

2. Every exception raised while writing the ledger row is caught,
   logged, and NEVER re-raised. The only exceptions record_event()
   raises are argument-validation errors for a genuinely unknown
   event_name/event_version (a programming-error signal, meant to be
   caught in development, not a live-traffic failure mode) -- see the
   three-way failure policy below.

Three deliberately different failure policies (do not conflate them):
  - Unknown event_name/event_version -> raises ValueError. This is a
    caller bug (using a name outside the frozen vocabulary), not a
    transient condition -- it should fail loudly so it's caught before
    a producer ships, not silently miscounted forever.
  - An unknown/forbidden property (or campaign_context/
    notification_context) key -> silently DROPPED before the row is
    ever built, logged as schema drift. Never raises. Rule 11's
    enforcement mechanism -- see event_schemas.py.
  - Any failure actually writing the row (DB error, or a duplicate
    non-null dedupe_key hitting the partial unique index) -> caught,
    logged, swallowed. Never raises. This is the non-regression rule.

record_event() never fabricates an optional value. If a caller does not
pass firebase_uid / profile_id / anonymous_id / session_id /
correlation_id / entity_type / entity_id / dedupe_key, it is stored as
NULL -- never guessed, never defaulted to something plausible-looking.

environment resolution (Phase 4 prerequisite fix): this codebase has no
existing environment-detection convention of its own (no FLASK_ENV/
APP_ENV/etc. anywhere -- confirmed by search; render.yaml declares no
environment-indicating variable either), so ACTIVITY_EVENTS_ENVIRONMENT
remains a new, narrowly-scoped env var introduced by this file
specifically. It previously defaulted to "production" when unset --
flagged in the Phase 2 and Phase 4 Step 1 reports as a frozen-contract
violation ("no silent production default") and corrected here: missing
or not-one-of-the-allowed-canonical-values now raises
EnvironmentConfigurationError internally, which record_event() catches
and turns into a controlled write_failed outcome -- never a silent
"production" label, and never an exception reaching the business
caller. Deployment is responsible for setting this var explicitly
(e.g. on the Render service) -- that is an operational action outside
this file's/this task's scope, not something to work around here.
"""

import logging
import os

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from extensions import db
from modules.models_activity_events import ActivityEvent
from modules.activity_events.event_schemas import (
    is_known_event,
    is_ledger_eligible,
    sanitize_properties,
    sanitize_campaign_context,
    sanitize_notification_context,
)

logger = logging.getLogger("activity_events")

# Smallest set actually needed by this project today: this repo's own
# render.yaml declares a single web service, no staging service block,
# and no code anywhere references a staging/dev deployment concept --
# "staging"/"dev" are deliberately NOT included here as speculative
# environments. If a real staging deployment is added later, this is a
# plain string column (no native DB enum, matching this codebase's own
# convention elsewhere), so extending this set needs no migration.
ALLOWED_ENVIRONMENTS = frozenset({"production", "local"})


class EnvironmentConfigurationError(Exception):
    """Raised only by _resolve_environment(), and only ever caught
    inside record_event() itself -- never propagates into a business
    caller. Signals "ACTIVITY_EVENTS_ENVIRONMENT is missing or not one
    of ALLOWED_ENVIRONMENTS," which must fail the analytics write, not
    silently resolve to "production"."""


def _resolve_environment() -> str:
    raw = os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT")
    if raw not in ALLOWED_ENVIRONMENTS:
        raise EnvironmentConfigurationError(
            f"ACTIVITY_EVENTS_ENVIRONMENT is missing or invalid (got {raw!r}); "
            f"must be explicitly set to one of {sorted(ALLOWED_ENVIRONMENTS)}. "
            "Refusing to silently default to 'production'."
        )
    return raw


class LedgerWriteResult:
    """Returned by record_event() -- never raised for a write failure,
    just reported. `status` is one of: "written", "skipped_not_ledger_
    eligible", "skipped_duplicate_dedupe_key", "write_failed"."""

    __slots__ = ("status", "event", "dropped_property_keys", "dropped_campaign_keys", "dropped_notification_keys")

    def __init__(self, status, event=None, dropped_property_keys=None,
                 dropped_campaign_keys=None, dropped_notification_keys=None):
        self.status = status
        self.event = event
        self.dropped_property_keys = dropped_property_keys or []
        self.dropped_campaign_keys = dropped_campaign_keys or []
        self.dropped_notification_keys = dropped_notification_keys or []

    @property
    def ok(self) -> bool:
        return self.status == "written"


def record_event(
    *,
    event_name: str,
    occurred_at,
    platform: str,
    event_version: int = 1,
    firebase_uid: str = None,
    profile_id: int = None,
    anonymous_id: str = None,
    session_id: str = None,
    source: str = None,
    correlation_id: str = None,
    entity_type: str = None,
    entity_id: str = None,
    properties: dict = None,
    campaign_context: dict = None,
    notification_context: dict = None,
    dedupe_key: str = None,
) -> LedgerWriteResult:
    """Record one canonical event to activity_events. See module
    docstring for the non-regression guarantee and the three failure
    policies. `occurred_at` and `platform` are required -- every other
    identity/context field is optional and is stored exactly as given,
    NULL if not given, never fabricated. `recorded_at` is not, and can
    never be, a parameter here -- it is server-generated only."""

    if not is_known_event(event_name, event_version):
        raise ValueError(
            f"Unknown canonical event_name/event_version: "
            f"{event_name!r} v{event_version} is not in the frozen "
            f"event registry (modules/activity_events/event_schemas.py)."
        )

    if not is_ledger_eligible(event_name, event_version):
        # e.g. page_view -- deliberately excluded from the ledger, S3.I.
        logger.info("activity_events: %s is not ledger-eligible, skipped", event_name)
        return LedgerWriteResult(status="skipped_not_ledger_eligible")

    # Phase 4 prerequisite fix: resolved BEFORE building the ActivityEvent
    # or opening any DB session. A missing/invalid ACTIVITY_EVENTS_
    # ENVIRONMENT is a configuration failure, not a caller bug -- it is
    # logged and reported as a normal analytics write_failed outcome,
    # exactly like a DB error would be, and never raises out of this
    # function. Resolving it this early also means no ActivityEvent
    # object, session, or transaction is ever created for a write that
    # can't legally be labeled -- nothing to roll back.
    try:
        environment = _resolve_environment()
    except EnvironmentConfigurationError:
        logger.warning(
            "activity_events: ACTIVITY_EVENTS_ENVIRONMENT misconfigured -- "
            "ledger write for event_name=%s refused (swallowed, business "
            "transaction unaffected)",
            event_name, exc_info=True,
        )
        return LedgerWriteResult(status="write_failed")

    clean_properties, dropped_props = sanitize_properties(event_name, event_version, properties)
    clean_campaign, dropped_campaign = sanitize_campaign_context(campaign_context)
    clean_notification, dropped_notification = sanitize_notification_context(notification_context)

    for label, dropped in (
        ("properties", dropped_props),
        ("campaign_context", dropped_campaign),
        ("notification_context", dropped_notification),
    ):
        if dropped:
            logger.warning(
                "activity_events: dropped unknown/forbidden %s keys %r for event_name=%s",
                label, dropped, event_name,
            )

    event = ActivityEvent(
        event_name=event_name,
        event_version=event_version,
        occurred_at=occurred_at,
        firebase_uid=firebase_uid,
        profile_id=profile_id,
        anonymous_id=anonymous_id,
        session_id=session_id,
        platform=platform,
        source=source,
        environment=environment,
        correlation_id=correlation_id,
        entity_type=entity_type,
        entity_id=entity_id,
        properties=clean_properties,
        campaign_context=clean_campaign or None,
        notification_context=clean_notification or None,
        dedupe_key=dedupe_key,
    )

    # A separate Session bound to the same engine -- NOT db.session --
    # so this write's own transaction can never commit or roll back
    # whatever the caller's own business transaction is doing. See the
    # module docstring's non-regression guarantee.
    LedgerSession = sessionmaker(bind=db.session.get_bind())
    ledger_session = LedgerSession()
    try:
        ledger_session.add(event)
        ledger_session.commit()
        # SQLAlchemy expires every attribute on commit by default; refresh
        # while the session is still open so the returned `event` (read
        # by the caller AFTER this session closes) has real, already-
        # loaded values -- including recorded_at, the one server-
        # generated field -- instead of raising DetachedInstanceError on
        # first access.
        ledger_session.refresh(event)
        return LedgerWriteResult(
            status="written",
            event=event,
            dropped_property_keys=dropped_props,
            dropped_campaign_keys=dropped_campaign,
            dropped_notification_keys=dropped_notification,
        )
    except IntegrityError:
        # Expected, benign: a duplicate non-null dedupe_key hit the
        # partial unique index -- this IS the dedupe mechanism working,
        # not a failure. Logged at info level, never re-raised.
        ledger_session.rollback()
        logger.info(
            "activity_events: duplicate dedupe_key=%r for event_name=%s, skipped",
            dedupe_key, event_name,
        )
        return LedgerWriteResult(status="skipped_duplicate_dedupe_key")
    except Exception:
        # Any other DB failure -- caught, logged, swallowed. Never
        # propagated into the business caller. Non-regression rule.
        ledger_session.rollback()
        logger.warning(
            "activity_events: ledger write failed for event_name=%s (swallowed, business transaction unaffected)",
            event_name, exc_info=True,
        )
        return LedgerWriteResult(status="write_failed")
    finally:
        ledger_session.close()
