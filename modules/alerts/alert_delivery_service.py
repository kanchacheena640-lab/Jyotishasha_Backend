# modules/alerts/alert_delivery_service.py

"""
Alert Delivery Service (Phase 5).

Connects one persisted, detected personalized Alert to the EXISTING
notification infrastructure. Owns exactly the flow this phase
specifies:

    Detected Alert -> Subscription Entitlement -> Eligibility/Cooldown
        -> Content -> Existing FCM Sender -> Successful Send
        -> finalize_delivery() [Phase 5.1: last_delivered_at update +
           Bell insert, ONE atomic transaction -- see
           persistence_repository.py::finalize_delivery()'s own
           docstring for why this replaced Phase 5's original two
           separately-committing calls]

Sends nothing itself beyond calling the EXISTING, unmodified
services.notification_engine.send_push_notification(). Does not touch
run_daily_event_job(), AstroEvent, or NotificationLog -- NotificationLog
is deliberately NOT written to here: its (user_id, event_id, slot)
uniqueness is a dedup ledger for run_daily_event_job()'s own
morning/evening SLOT concept, which Alerts has no equivalent of (Alerts
dedup/cooldown is entirely owned by AlertMicroEvent.last_delivered_at +
delivery_eligibility_policy.py, an independent, already-complete
mechanism from Phase 4) -- writing a fabricated "slot" value into that
table would misuse its actual contract, not "reuse" it.

Does NOT implement a scheduler or batch loop -- see this phase's own
scope ("Do NOT create the scheduler yet"); deliver_alert() handles
exactly ONE (profile_id, event_id) delivery attempt per call. A future
Phase 6 is expected to call this function once per eligible alert,
across profiles, with its own batching/concurrency handling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.notification_engine import send_push_notification

from modules.entitlement.entitlement_service import EntitlementService

from modules.alerts.delivery_eligibility_policy import evaluate_delivery_eligibility
from modules.alerts.entitlement_gate import has_alerts_access
from modules.alerts.exceptions import AlertsEngineError
from modules.alerts.notification_content_adapter import AlertContentError, build_alert_notification_content
from modules.alerts.persistence_repository import AlertPersistenceError, AlertPersistenceRepository

# Phase 4D -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from modules.alerts.
from modules.activity_events.service import record_event

_activity_events_logger = logging.getLogger("activity_events")


def _emit_alert_notification_events(*, user_notification, emit_sent=True):
    """Phase 4D -- observational only, called ONLY after the caller's
    own authoritative commit has already succeeded: deliver_alert()
    below (via repository.finalize_delivery(), reached only after a
    CONFIRMED successful FCM send -- emit_sent defaults to True, its
    original behavior, unchanged for that call site) and, as of Phase
    4D.1, modules/alerts/alerts_scheduler.py (via
    repository.record_bell_only() -- no FCM interaction happens for
    that path at all, so it calls this with emit_sent=False; reused
    here rather than duplicated, since alerts_scheduler.py already
    imports this module for deliver_alert() -- no new dependency edge).
    Each event's own emission is independently wrapped so one failure
    never prevents the other, and neither can ever propagate back into
    the caller's own business result."""
    entity_id = str(user_notification.id)
    occurred_at = (
        user_notification.created_at.replace(tzinfo=timezone.utc)
        if user_notification.created_at is not None
        else datetime.now(timezone.utc)
    )
    notification_context = {"notification_id": entity_id}

    try:
        record_event(
            event_name="notification_created",
            occurred_at=occurred_at,
            platform="backend_internal",
            source="alert_delivery_service",
            firebase_uid=None,
            profile_id=user_notification.user_id,
            entity_type="notification",
            entity_id=entity_id,
            properties={"notification_type": "alert", "target_scope": "personal"},
            notification_context=notification_context,
            dedupe_key=f"notification_created:{entity_id}",
        )
    except Exception:
        _activity_events_logger.warning(
            "alert_delivery_service: unexpected error emitting notification_created "
            "for UserNotification.id=%s (swallowed -- the delivery result already "
            "decided is unaffected)",
            entity_id, exc_info=True,
        )

    if not emit_sent:
        # Bell-only: no FCM interaction happened at all -- never a
        # notification_sent.
        return

    try:
        record_event(
            event_name="notification_sent",
            occurred_at=datetime.now(timezone.utc),
            platform="backend_internal",
            source="alert_delivery_service",
            firebase_uid=None,
            profile_id=user_notification.user_id,
            entity_type="notification",
            entity_id=entity_id,
            properties={},
            notification_context=notification_context,
            dedupe_key=f"notification_sent:{entity_id}",
        )
    except Exception:
        _activity_events_logger.warning(
            "alert_delivery_service: unexpected error emitting notification_sent "
            "for UserNotification.id=%s (swallowed -- the delivery result already "
            "decided is unaffected)",
            entity_id, exc_info=True,
        )


@dataclass(frozen=True)
class AlertDeliveryResult:
    """Structured, JSON-serializable outcome of one deliver_alert()
    call -- `stage` names exactly where the flow stopped, so a caller
    (and tests) can assert precisely why a delivery was or wasn't
    sent, without inspecting logs."""

    sent: bool
    stage: str  # "entitlement" | "load" | "eligibility" | "content" | "send" | "finalization_failed" | "delivered"
    reason: str
    profile_id: int
    event_id: str
    severity: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "sent": self.sent, "stage": self.stage, "reason": self.reason,
            "profile_id": self.profile_id, "event_id": self.event_id, "severity": self.severity,
        }


def deliver_alert(
    *,
    profile_id: int,
    event_id: str,
    fcm_token: Optional[str],
    now: Optional[datetime] = None,
    entitlement_service: Optional[EntitlementService] = None,
    repository: Optional[AlertPersistenceRepository] = None,
) -> AlertDeliveryResult:
    """
    Attempts to deliver ONE persisted alert (profile_id, event_id).
    `fcm_token` is the caller's responsibility to supply (mirrors
    services/event_scheduler.py's own `token = getattr(user,
    "fcm_token", None)` pattern -- fetching it is a generic AppUser
    concern, not an Alerts-specific one, so this file does not query
    AppUser itself).

    `last_delivered_at` changes ONLY if this function reaches stage
    "delivered" -- every earlier return path (entitlement/load/
    eligibility/content/send failure) leaves persistence completely
    untouched. See modules/alerts/persistence_repository.py::mark_delivered()'s
    own docstring for the same guarantee at the repository layer.
    """
    now = now or datetime.utcnow()
    entitlement_service = entitlement_service or EntitlementService()
    repository = repository or AlertPersistenceRepository()

    # ---- 1. Subscription Entitlement ----
    entitlement = has_alerts_access(profile_id, entitlement_service=entitlement_service)
    if not entitlement.entitled:
        return AlertDeliveryResult(
            sent=False, stage="entitlement", reason=entitlement.reason,
            profile_id=profile_id, event_id=event_id,
        )

    # ---- 2. Load persisted alert ----
    row = repository.read(profile_id=profile_id, event_id=event_id)
    if row is None:
        return AlertDeliveryResult(
            sent=False, stage="load", reason="no persisted AlertMicroEvent row found",
            profile_id=profile_id, event_id=event_id,
        )

    # ---- 3. Eligibility / Cooldown (Phase 4, unmodified) ----
    try:
        eligibility = evaluate_delivery_eligibility(
            event_id=event_id, state=row.state, confidence=row.confidence,
            last_delivered_at=row.last_delivered_at, now=now,
        )
    except AlertsEngineError as exc:
        return AlertDeliveryResult(
            sent=False, stage="eligibility", reason=str(exc),
            profile_id=profile_id, event_id=event_id,
        )

    if not eligibility.eligible:
        return AlertDeliveryResult(
            sent=False, stage="eligibility", reason=eligibility.reason,
            profile_id=profile_id, event_id=event_id, severity=eligibility.severity,
        )

    # ---- 4. Content (deterministic, catalog-driven) ----
    try:
        content = build_alert_notification_content(
            event_id=event_id, category=row.category, severity=eligibility.severity,
            ai_insight=row.ai_insight, ai_action=row.ai_action,
        )
    except AlertContentError as exc:
        return AlertDeliveryResult(
            sent=False, stage="content", reason=str(exc),
            profile_id=profile_id, event_id=event_id, severity=eligibility.severity,
        )

    # ---- 5. Existing FCM Sender (unmodified) ----
    if not fcm_token:
        return AlertDeliveryResult(
            sent=False, stage="send", reason="profile has no fcm_token",
            profile_id=profile_id, event_id=event_id, severity=eligibility.severity,
        )

    try:
        success = send_push_notification(
            token=fcm_token, title=content["title"], body=content["body"], data=content["data"],
        )
    except Exception as exc:
        return AlertDeliveryResult(
            sent=False, stage="send", reason=f"send_push_notification raised: {exc}",
            profile_id=profile_id, event_id=event_id, severity=eligibility.severity,
        )

    if not success:
        return AlertDeliveryResult(
            sent=False, stage="send", reason="send_push_notification returned False",
            profile_id=profile_id, event_id=event_id, severity=eligibility.severity,
        )

    # ---- 6. Successful Send -> atomic finalization (Phase 5.1) ----
    # Reached ONLY after a CONFIRMED successful FCM send -- everything
    # above this line returns before touching persistence at all.
    #
    # FCM cannot participate in this database transaction (it is a
    # third-party network call, already completed). If
    # finalize_delivery() itself fails, the push has already reached
    # the device -- this is surfaced as its own distinct
    # "finalization_failed" stage (sent=True, since the physical send
    # genuinely succeeded) rather than folded into "send", and this
    # function does NOT retry the FCM send here: a blind retry could
    # duplicate the push the user already received. A caller may only
    # retry finalization itself (calling repository.finalize_delivery()
    # again is safe/idempotent -- it re-reads the row and re-writes the
    # same last_delivered_at/content).
    try:
        user_notification = repository.finalize_delivery(
            profile_id=profile_id, event_id=event_id,
            notification_title=content["title"], notification_body=content["body"],
            notification_data=content["data"], delivered_at=now,
        )
    except AlertPersistenceError as exc:
        return AlertDeliveryResult(
            sent=True, stage="finalization_failed",
            reason=f"FCM send succeeded but DB finalization failed (last_delivered_at "
                   f"and Bell insert both rolled back, not partially applied): {exc}",
            profile_id=profile_id, event_id=event_id, severity=eligibility.severity,
        )

    # Phase 4D -- emitted only after finalize_delivery()'s own commit
    # above has already succeeded, so user_notification.id is real and
    # durable. Never allowed to alter this function's own return value
    # -- see _emit_alert_notification_events()'s own per-event isolation.
    _emit_alert_notification_events(user_notification=user_notification)

    return AlertDeliveryResult(
        sent=True, stage="delivered", reason="sent",
        profile_id=profile_id, event_id=event_id, severity=eligibility.severity,
    )
