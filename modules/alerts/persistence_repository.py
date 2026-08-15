# modules/alerts/persistence_repository.py

"""
Persistence adapter for the Micro Event Engine (Alerts) -- Phase 1.

Thin data-access layer around AlertMicroEvent. This is the ONLY module
that touches the database for Alerts -- the Rule Engine, Confidence
Engine, Event Registry, and Planning Window Engine
(rule_interface.py, rule_evaluator.py, confidence_engine.py,
event_registry.py, micro_event_engine.py, planning_window_engine.py,
event_state.py) are NOT modified by this phase and know nothing about
this file. This repository is a pure consumer of their existing output
shapes (DetectedMicroEvent / PlannedMicroEvent) -- it takes plain
values, not those dataclasses themselves, so it has no import
dependency on the detection layer at all, matching modules/alerts/'s
own "each layer independent" discipline already used between
event_state.py and planning_window_engine.py.

Phase 5.1 exception: finalize_delivery() below is the ONE place this
file touches a table outside AlertMicroEvent (notifications.
notification_models.UserNotification, the existing Bell/in-app inbox)
-- justified because finalizing a confirmed-successful delivery is
inherently a two-table operation that must be atomic (see that
method's own docstring for why the original Phase 5 design, two
separately-committing calls, left a real gap between them). No other
method here is affected by this exception.

Calling this repository (a future Phase 2 detection service) is
explicitly OUT OF SCOPE for this phase -- Phase 1 is persistence only.

==================================================
IDEMPOTENCY KEY: WHY (profile_id, event_id), NOT (..., active_from)
==================================================

The task's own conceptual suggestion was
(profile + event_id + active_from). Verified directly against
modules/alerts/event_state.py::summarize() before choosing the actual
key, and that suggestion is NOT safe:

    active_days.sort(key=lambda d: d.day_offset)
    first = active_days[0]
    ...
    active_from=first.date

`active_from` is the first ACTIVE day within THAT RUN's own simulated
window (today + N days, see planning_window_engine.py's
`_ist_midnight_today()` / `_build_daily_contexts()`) -- it is
recomputed fresh on every run and has no memory of any PREVIOUS run's
result. A continuously-active event evaluated on three consecutive
days would report a DIFFERENT active_from each day (always "today" of
that run), because the Planning Window Engine only ever simulates
FORWARD from "today". Keying uniqueness on
(profile_id, event_id, active_from) would insert a brand-new row every
single day for one ongoing occurrence -- the opposite of idempotent,
and a direct violation of this phase's own "safe under
concurrent/retried jobs" requirement.

(profile_id, event_id) is the only value in the engine's actual output
that is genuinely stable across repeated runs of the same ongoing
occurrence, so it is the database's UNIQUE constraint (see the
migration and persistence_models.py::AlertMicroEvent.__table_args__).

Consequence (disclosed, not hidden): this table holds at most ONE row
per (profile_id, event_id) -- the CURRENT/most recent known window for
that event, upserted in place, mirroring
modules/models_ai_reports.py's own "generate once, read many,
overwrite only when regeneration required" cache-row discipline. It is
NOT an append-only log of every distinct past occurrence. Deciding
when a gap between two appearances of the same event_id is long enough
to count as a genuinely NEW occurrence (vs. a continuation) is a
detection-service POLICY decision, explicitly out of scope for
persistence-only Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from notifications.notification_models import UserNotification

from modules.alerts.persistence_models import AlertMicroEvent
from services.notification_lifecycle import expiry_for_alert_notification


class AlertPersistenceError(Exception):
    """Raised when a persistence operation fails for a reason other
    than the expected unique-constraint race handled inside
    save_detection() -- never silently swallowed."""


@dataclass(frozen=True)
class SyncCounts:
    """Return shape of synchronize_profile_events() (Phase 2 addition)
    -- instrumentation counters, nothing else."""

    created: int
    updated: int
    reactivated: int
    expired: int


class AlertPersistenceRepository:
    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    def read(self, *, profile_id: int, event_id: str) -> Optional[AlertMicroEvent]:
        """The one existing row for this (profile_id, event_id), if
        any -- the UNIQUE constraint on AlertMicroEvent guarantees
        there is at most one."""
        return AlertMicroEvent.query.filter_by(
            profile_id=profile_id, event_id=event_id,
        ).first()

    def fetch_active_for_profile(self, *, profile_id: int) -> List[AlertMicroEvent]:
        """Rows currently NEW or ACTIVE for one profile, most confident
        first. EXPIRED rows (only ever written by a future
        detection-service phase -- Phase 1 never writes that state)
        are excluded. Ordered by confidence rather than the `priority`
        string column -- "high"/"medium"/"low" does not sort correctly
        as plain text, and confidence is the exact numeric signal
        `priority` was itself derived from
        (confidence_engine.derive_priority())."""
        return (
            AlertMicroEvent.query
            .filter(
                AlertMicroEvent.profile_id == profile_id,
                AlertMicroEvent.state.in_(("NEW", "ACTIVE")),
            )
            .order_by(AlertMicroEvent.confidence.desc())
            .all()
        )

    def fetch_history_for_profile(self, *, profile_id: int) -> List[AlertMicroEvent]:
        """Every row for one profile regardless of state -- "event
        history for one profile", most recently evaluated first."""
        return (
            AlertMicroEvent.query
            .filter(AlertMicroEvent.profile_id == profile_id)
            .order_by(AlertMicroEvent.last_evaluated_at.desc())
            .all()
        )

    # ------------------------------------------------------------
    # Write
    # ------------------------------------------------------------
    def save_detection(
        self,
        *,
        profile_id: int,
        event_id: str,
        category: str,
        state: str,
        confidence: float,
        priority: str,
        active_from: date,
        active_until: date,
        evaluated_at: Optional[datetime] = None,
    ) -> AlertMicroEvent:
        """
        Persists one detection result for (profile_id, event_id):
        - No row yet -> INSERT (first_detected_at = evaluated_at).
        - Row already exists -> UPDATE in place (state/confidence/
          priority/active_from/active_until/last_evaluated_at);
          first_detected_at is never touched again once set.

        Race-safe: two concurrent callers detecting the SAME
        (profile_id, event_id) for the first time at the same moment
        will both attempt an INSERT; the database's own UNIQUE
        constraint rejects the loser's INSERT with an IntegrityError,
        which is recovered here by rolling back this session and
        retrying as an UPDATE against the winner's now-committed row.
        The database constraint is the actual concurrency guarantee --
        this read-then-write Python logic only optimizes the common,
        non-racing case (mirrors
        modules/ai_report_engine/cache_repository.py::save_cache()'s
        identical, already-proven IntegrityError-recovery pattern).
        """
        evaluated_at = evaluated_at or datetime.utcnow()

        existing = self.read(profile_id=profile_id, event_id=event_id)
        if existing is not None:
            return self._update(
                existing,
                state=state, confidence=confidence, priority=priority,
                active_from=active_from, active_until=active_until,
                evaluated_at=evaluated_at,
            )

        row = AlertMicroEvent(
            profile_id=profile_id,
            event_id=event_id,
            category=category,
            state=state,
            confidence=confidence,
            priority=priority,
            active_from=active_from,
            active_until=active_until,
            first_detected_at=evaluated_at,
            last_evaluated_at=evaluated_at,
        )
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            winner = self.read(profile_id=profile_id, event_id=event_id)
            if winner is None:
                # Not the race we expected -- a genuinely different
                # integrity problem (e.g. an invalid profile_id with no
                # matching app_users row). Never swallow it.
                raise AlertPersistenceError(
                    f"Failed to persist AlertMicroEvent(profile_id={profile_id}, "
                    f"event_id={event_id!r}): {exc}"
                ) from exc
            return self._update(
                winner,
                state=state, confidence=confidence, priority=priority,
                active_from=active_from, active_until=active_until,
                evaluated_at=evaluated_at,
            )
        return row

    def _update(
        self,
        row: AlertMicroEvent,
        *,
        state: str,
        confidence: float,
        priority: str,
        active_from: date,
        active_until: date,
        evaluated_at: datetime,
    ) -> AlertMicroEvent:
        row.state = state
        row.confidence = confidence
        row.priority = priority
        row.active_from = active_from
        row.active_until = active_until
        row.last_evaluated_at = evaluated_at
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise AlertPersistenceError(
                f"Failed to update AlertMicroEvent id={row.id}: {exc}"
            ) from exc
        return row

    # ------------------------------------------------------------
    # Phase 2 addition -- whole-profile lifecycle synchronization.
    # save_detection()/_update() above are UNCHANGED by this addition
    # and remain available for a single-event upsert; this method is
    # what ProfileDetectionService (modules/alerts/profile_detection_service.py)
    # actually calls, once per profile evaluation, with the COMPLETE
    # result of one PlanningWindowEngine.plan() run.
    # ------------------------------------------------------------
    def synchronize_profile_events(
        self,
        *,
        profile_id: int,
        detected_events: List[Dict[str, Any]],
        evaluated_at: Optional[datetime] = None,
    ) -> SyncCounts:
        """
        ONE atomic transaction that reconciles a profile's FULL
        detection result against this table's existing rows for that
        profile only:

        - event_id in `detected_events`, no existing row -> INSERT
          (created).
        - event_id in `detected_events`, existing NEW/ACTIVE row ->
          UPDATE in place (updated). first_detected_at untouched.
        - event_id in `detected_events`, existing EXPIRED row ->
          REACTIVATED: state/confidence/priority/window updated,
          first_detected_at is STILL never reset -- see "REAPPEARANCE
          POLICY" below.
        - Existing NEW/ACTIVE row whose event_id is NOT in
          `detected_events` -> marked EXPIRED. confidence/priority/
          active_from/active_until are preserved as the last-known
          values (NOT overwritten with anything) -- they describe the
          window as it was when the event was last actually detected.
        - Existing EXPIRED row whose event_id is NOT in
          `detected_events` -> left completely untouched (already
          correctly reflects "not currently happening"; re-writing it
          every run would only grow write volume for a permanently
          dormant event with no change in meaning).

        Every row read/written is scoped to `profile_id` via the query
        itself -- no other profile's rows can be touched by this call.

        `detected_events` is a list of plain dicts (event_id, category,
        state, confidence, priority, active_from, active_until,
        severity [Phase 4, optional -- see below]) -- deliberately NOT
        PlannedMicroEvent objects, so this file keeps zero import
        dependency on the detection layer
        (modules/alerts/planning_models.py etc.), the same
        independence Phase 1's save_detection() already established.

        Phase 4 addition: each dict MAY carry a `severity` key
        (LOW/MEDIUM/HIGH/CRITICAL, from
        modules/alerts/severity_cooldown_registry.py, resolved by the
        CALLER -- this repository stays a plain-values consumer and
        never imports that registry). When present, it is written to
        the row on both insert and update. `last_delivered_at` is
        NEVER touched anywhere in this method, on any path -- it is
        set ONLY by a future Phase 5 delivery adapter after a
        CONFIRMED successful send; detection/lifecycle synchronization
        must never advance or reset it (a failed/nonexistent send must
        not consume cooldown, and reconciling NEW/ACTIVE/EXPIRED state
        has nothing to do with whether a notification was ever sent).

        ==================================================
        REAPPEARANCE POLICY (profile_id, event_id) uniqueness)
        ==================================================
        Because this table's identity is (profile_id, event_id) --
        see persistence_models.py's own docstring for why
        (profile_id, event_id, active_from) is unsafe -- a reappearance
        after EXPIRED reuses the SAME row rather than inserting a
        second historical row. `first_detected_at` keeps its ORIGINAL
        value (the first time this profile ever had this event_id
        detected, across all time), never reset on reactivation. This
        is a deliberate Phase 2 choice, per this phase's own
        instruction to prefer reactivating the existing row over a
        schema redesign unless proven unsafe -- nothing about
        PlanningWindowEngine's or EventRegistry's actual output makes
        reuse unsafe. A future phase wanting "first_detected_at per
        distinct occurrence" (e.g. to notify "this is happening again
        after N months") would need a schema change (e.g. a separate
        occurrences table) -- out of scope here.

        ==================================================
        ATOMICITY
        ==================================================
        Every mutation below is staged on the SAME db.session and
        committed EXACTLY ONCE, at the end. If anything fails partway
        through (including a duplicate-key race from a genuinely
        concurrent evaluation of the SAME profile), the ENTIRE batch is
        rolled back and AlertPersistenceError is raised -- a profile
        evaluation can never leave a partially-synchronized state (some
        events updated, others not) as a side effect of this method.
        This trades Phase 1's per-row IntegrityError-and-retry
        graceful-recovery (still exactly as-is in save_detection()
        above) for whole-batch atomicity, which this phase's own
        transaction-safety requirement explicitly prioritizes;
        concurrent evaluation of the SAME profile is a scheduler-level
        concern explicitly deferred to a later phase.

        This method does NOT protect against a PlanningWindowEngine.plan()
        failure -- that must simply never reach this method at all; see
        ProfileDetectionService.evaluate_profile(), which only calls
        this after `.plan()` has already returned successfully.
        """
        evaluated_at = evaluated_at or datetime.utcnow()

        existing_by_event_id: Dict[str, AlertMicroEvent] = {
            row.event_id: row
            for row in AlertMicroEvent.query.filter_by(profile_id=profile_id).all()
        }

        created = updated = reactivated = expired = 0
        detected_ids = set()

        for detected in detected_events:
            event_id = detected["event_id"]
            detected_ids.add(event_id)
            existing = existing_by_event_id.get(event_id)

            if existing is None:
                db.session.add(AlertMicroEvent(
                    profile_id=profile_id,
                    event_id=event_id,
                    category=detected["category"],
                    state=detected["state"],
                    confidence=detected["confidence"],
                    priority=detected["priority"],
                    severity=detected.get("severity"),  # Phase 4, optional; None if caller omits it
                    active_from=detected["active_from"],
                    active_until=detected["active_until"],
                    first_detected_at=evaluated_at,
                    last_evaluated_at=evaluated_at,
                    # last_delivered_at intentionally omitted -- defaults to
                    # NULL (column default); never set here, see docstring.
                ))
                created += 1
            else:
                was_expired = existing.state == "EXPIRED"
                existing.state = detected["state"]
                existing.confidence = detected["confidence"]
                existing.priority = detected["priority"]
                if "severity" in detected:
                    existing.severity = detected["severity"]  # Phase 4; only touched when supplied
                existing.active_from = detected["active_from"]
                existing.active_until = detected["active_until"]
                existing.last_evaluated_at = evaluated_at
                # first_detected_at AND last_delivered_at intentionally
                # untouched -- see "REAPPEARANCE POLICY" above and this
                # method's own docstring on last_delivered_at.
                if was_expired:
                    reactivated += 1
                else:
                    updated += 1

        for event_id, row in existing_by_event_id.items():
            if event_id in detected_ids:
                continue
            if row.state == "EXPIRED":
                continue  # already correct, no-op
            row.state = "EXPIRED"
            row.last_evaluated_at = evaluated_at
            expired += 1

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise AlertPersistenceError(
                f"Failed to synchronize AlertMicroEvent rows for "
                f"profile_id={profile_id}: {exc}"
            ) from exc

        return SyncCounts(created=created, updated=updated, reactivated=reactivated, expired=expired)

    # ------------------------------------------------------------
    # Alerts Product Hardening addition -- read-only, scoped PURELY to
    # AlertMicroEvent.last_delivered_at. Used by
    # modules/alerts/user_alert_selection.py's orchestration (in
    # alerts_scheduler.py) to enforce the max-2-per-alert-day cap
    # independent of any single event's own cooldown clock -- a rerun
    # must not bypass the daily cap just because some OTHER event's
    # cooldown happened to elapse. Does not change any existing method.
    # ------------------------------------------------------------
    def count_delivered_since(self, *, profile_id: int, since: datetime) -> int:
        """Count of this profile's AlertMicroEvent rows whose
        last_delivered_at falls on/after `since` -- i.e. how many
        distinct alerts have already been delivered within the caller-
        supplied window (typically the current alert day's start)."""
        return (
            AlertMicroEvent.query
            .filter(
                AlertMicroEvent.profile_id == profile_id,
                AlertMicroEvent.last_delivered_at.isnot(None),
                AlertMicroEvent.last_delivered_at >= since,
            )
            .count()
        )

    # ------------------------------------------------------------
    # Phase 5 addition -- scoped PURELY to AlertMicroEvent.last_delivered_at,
    # matching this file's own single-table discipline (every other
    # method here only ever touches AlertMicroEvent too). The
    # accompanying Bell/UserNotification insert is a DIFFERENT table
    # belonging to a different subsystem -- deliberately kept in
    # modules/alerts/alert_delivery_service.py instead, not here.
    # ------------------------------------------------------------
    def mark_delivered(
        self,
        *,
        profile_id: int,
        event_id: str,
        delivered_at: Optional[datetime] = None,
    ) -> Optional[AlertMicroEvent]:
        """
        Sets ONLY `last_delivered_at` on an existing (profile_id,
        event_id) row -- touches AlertMicroEvent alone, no Bell insert.

        Phase 5.1 note: alert_delivery_service.deliver_alert() no
        longer calls this method for its own success path -- it calls
        finalize_delivery() below instead, which performs this same
        `last_delivered_at` update AND the Bell/UserNotification insert
        in ONE atomic transaction (closing the gap between two
        separately-committing calls that Phase 5 originally had). This
        method is kept, unmodified, as a standalone primitive for any
        future caller that needs to mark a delivery without also
        writing a Bell notification -- never by detection/lifecycle
        synchronization (synchronize_profile_events() above never
        touches this field, by design; see its own docstring).

        Returns None (a no-op, not an error) if no row exists for this
        key.
        """
        delivered_at = delivered_at or datetime.utcnow()
        row = self.read(profile_id=profile_id, event_id=event_id)
        if row is None:
            return None

        row.last_delivered_at = delivered_at
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise AlertPersistenceError(
                f"Failed to mark AlertMicroEvent id={row.id} delivered: {exc}"
            ) from exc
        return row

    # ------------------------------------------------------------
    # Phase 5.1 -- THE atomic finalization step. Replaces Phase 5's
    # original sequence (mark_delivered() then a separate
    # alert_delivery_service._persist_bell_notification() commit),
    # which left a disclosed gap: a Bell-insert failure occurring after
    # last_delivered_at had already been durably committed.
    # ------------------------------------------------------------
    def finalize_delivery(
        self,
        *,
        profile_id: int,
        event_id: str,
        notification_title: str,
        notification_body: str,
        notification_data: dict,
        delivered_at: Optional[datetime] = None,
    ) -> AlertMicroEvent:
        """
        Called EXCLUSIVELY by
        modules/alerts/alert_delivery_service.py::deliver_alert(), and
        ONLY after a CONFIRMED successful FCM send. In ONE transaction:
        (a) sets AlertMicroEvent.last_delivered_at, and (b) inserts a
        UserNotification row (the SAME Bell/in-app inbox
        services/event_scheduler.py::run_daily_event_job() already
        writes to -- reused, not duplicated; `user_id` is populated
        with `profile_id`, matching that existing code's own
        convention of using AppUser.id despite the column's generic
        name). Either both writes land, or neither does.

        N2 (lifecycle/expiry): the inserted UserNotification row's
        `expires_at` is derived from THIS row's own `active_until`
        (never NULL -- see persistence_models.py) via
        services/notification_lifecycle.py::expiry_for_alert_notification()
        -- not the previous hardcoded `None`. Touches only the Bell
        row's visibility; `active_until`/`active_from`/`state`/
        `confidence`/`severity`/`priority` themselves, and every other
        Alerts detection/selection/cooldown/scheduler file, are
        untouched by this change.

        Raises AlertPersistenceError -- never silently swallowed -- if
        either write fails, OR if no AlertMicroEvent row exists for
        this key. The caller MUST treat this as a distinct,
        structured "finalization failed" outcome, not a generic send
        failure: by this point FCM has ALREADY reported success, so
        the caller must NOT retry the FCM send itself (that could
        duplicate the push already delivered to the device) -- only
        finalization (this method) may be retried. This is the
        documented, unavoidable edge case: FCM cannot participate in
        this database transaction, so a successful push followed by a
        failed DB commit is a real possible outcome, not a bug this
        method can eliminate -- only isolate and surface clearly.

        No other AlertMicroEvent field (state/confidence/priority/
        severity/active_from/active_until/first_detected_at/
        last_evaluated_at) is touched.
        """
        delivered_at = delivered_at or datetime.utcnow()
        row = self.read(profile_id=profile_id, event_id=event_id)
        if row is None:
            raise AlertPersistenceError(
                f"Cannot finalize delivery -- no AlertMicroEvent row found "
                f"for profile_id={profile_id}, event_id={event_id!r}"
            )

        row.last_delivered_at = delivered_at
        db.session.add(UserNotification(
            user_id=profile_id,
            title=notification_title,
            body=notification_body,
            data=notification_data,
            is_read=False,
            expires_at=expiry_for_alert_notification(active_until=row.active_until),
        ))
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise AlertPersistenceError(
                f"Failed to finalize delivery for profile_id={profile_id}, "
                f"event_id={event_id!r} (last_delivered_at update and Bell "
                f"insert both rolled back): {exc}"
            ) from exc
        return row

    def record_bell_only(
        self,
        *,
        profile_id: int,
        event_id: str,
        notification_title: str,
        notification_body: str,
        notification_data: dict,
        active_until: date,
        now: Optional[datetime] = None,
    ) -> Optional[UserNotification]:
        """
        N5 -- Bell-only fallback for an alert that ALREADY passed
        Alerts' own hardened eligibility + selection
        (delivery_eligibility_policy.py / user_alert_selection.py, both
        unmodified) but was not attempted this run because the user's
        GLOBAL push budget (N4, services/attention_policy.py) was
        already spent elsewhere. Deliberately separate from
        finalize_delivery() above: inserts ONLY the UserNotification
        (Bell) row and explicitly does NOT touch
        AlertMicroEvent.last_delivered_at -- a Bell-only insert must
        never start, extend, or otherwise affect this event's cooldown,
        and must never be mistaken for a real delivery by
        evaluate_delivery_eligibility() (which reads last_delivered_at
        exclusively) or count_delivered_since() (the daily-cap counter,
        which reads it too). Never called for a raw/unselected
        detection -- the caller (alerts_scheduler.py) only reaches this
        for rows already present in that run's own selected set.

        Idempotent per (profile_id, event_id): if a still-active
        (unexpired) bell-only row already exists for this exact pair,
        this is a no-op and returns None -- a rerun, or the same
        globally-suppressed alert surviving into a later run the same
        day, can never insert a duplicate Bell row.

        expires_at reuses the EXACT same N2 policy
        (expiry_for_alert_notification(), unmodified) a normally-pushed
        alert's Bell row already gets, from this row's own
        `active_until` -- N2 lifecycle remains the sole authority on
        when it disappears, whether it arrived via push or Bell-only.
        """
        now = now or datetime.utcnow()

        existing = (
            UserNotification.query
            .filter(UserNotification.user_id == profile_id)
            .filter(UserNotification.data["type"].astext == "alert")
            .filter(UserNotification.data["event_id"].astext == event_id)
            .filter(UserNotification.data["delivery_channel"].astext == "bell_only")
            .filter(db.or_(
                UserNotification.expires_at.is_(None),
                UserNotification.expires_at > now,
            ))
            .first()
        )
        if existing is not None:
            return None

        bell_only_data = dict(notification_data)
        bell_only_data["delivery_channel"] = "bell_only"

        row = UserNotification(
            user_id=profile_id,
            title=notification_title,
            body=notification_body,
            data=bell_only_data,
            is_read=False,
            expires_at=expiry_for_alert_notification(active_until=active_until),
        )
        db.session.add(row)
        db.session.commit()
        return row
